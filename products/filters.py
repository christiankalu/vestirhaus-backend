
from django.db.models import Exists, OuterRef
from django_filters import rest_framework as filters
from rest_framework.filters import BaseFilterBackend

from .models import Product, ProductVariant


class ProductFilter(filters.FilterSet):
    """Query filters for the public product catalogue."""

    category = filters.CharFilter(
        field_name="category__slug",
        lookup_expr="iexact",
    )
    min_price = filters.NumberFilter(
        field_name="effective_price",
        lookup_expr="gte",
        help_text="Minimum effective price in kobo.",
    )
    max_price = filters.NumberFilter(
        field_name="effective_price",
        lookup_expr="lte",
        help_text="Maximum effective price in kobo.",
    )
    audience = filters.ChoiceFilter(
        choices=Product.Audience.choices,
    )
    size = filters.CharFilter(method="filter_size")
    color = filters.CharFilter(method="filter_color")
    in_stock = filters.BooleanFilter(method="filter_in_stock")

    class Meta:
        model = Product
        fields = []

    def filter_size(self, queryset, name, value):
        return queryset.filter(
            variants__size__iexact=value
        ).distinct()

    def filter_color(self, queryset, name, value):
        return queryset.filter(
            variants__color__icontains=value
        ).distinct()

    def filter_in_stock(self, queryset, name, value):
        """
        Filter based on stock for the requested size/colour, when supplied.
        """
        variants = ProductVariant.objects.filter(
            product=OuterRef("pk"),
            stock_quantity__gt=0,
        )

        size = self.data.get("size")
        color = self.data.get("color")

        if size:
            variants = variants.filter(size__iexact=size)

        if color:
            variants = variants.filter(color__icontains=color)

        queryset = queryset.annotate(
            _has_matching_stock=Exists(variants)
        )

        return queryset.filter(_has_matching_stock=value)


class ProductSortFilter(BaseFilterBackend):
    """Restrict product sorting to explicit, supported options."""

    SORT_OPTIONS = {
        "newest": ("-created_at", "-pk"),
        "price_asc": ("effective_price", "pk"),
        "price_desc": ("-effective_price", "pk"),
        "popularity": ("-sales_count", "-created_at", "-pk"),
    }

    def filter_queryset(self, request, queryset, view):
        sort = request.query_params.get("sort", "newest")

        # Use the documented default when the supplied option is invalid.
        ordering = self.SORT_OPTIONS.get(
            sort,
            self.SORT_OPTIONS["newest"],
        )

        return queryset.order_by(*ordering)

    def get_schema_operation_parameters(self, view):
        return [
            {
                "name": "sort",
                "required": False,
                "in": "query",
                "description": (
                    "Sort order: newest, price_asc, price_desc, popularity."
                ),
                "schema": {
                    "type": "string",
                    "enum": list(self.SORT_OPTIONS.keys()),
                    "default": "newest",
                },
            }
        ]
