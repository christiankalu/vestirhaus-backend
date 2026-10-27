from django.db.models import Avg, Count, Prefetch
from django.db.models.functions import Coalesce
from django.db.models import BigIntegerField
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from django_filters.rest_framework import DjangoFilterBackend

from users.permissions import IsPlatformAdmin, IsVerifiedUser

from .filters import ProductFilter, ProductSortFilter
from .models import Category, Product, ProductImage, ProductVariant, Review
from .serializers import (
    CategoryTreeSerializer,
    CategoryWriteSerializer,
    ProductDetailSerializer,
    ProductImageSerializer,
    ProductListSerializer,
    ProductVariantSerializer,
    ProductWriteSerializer,
    ReviewCreateSerializer,
    ReviewReadSerializer,
)
from core.pagination import StandardResultsSetPagination


def is_catalog_admin(user):
    """Recognize a Vestirhaus admin or Django superuser."""
    return bool(
        user
        and user.is_authenticated
        and (
            getattr(user, "role", None) == "admin"
            or user.is_superuser
        )
    )


class CategoryViewSet(viewsets.ModelViewSet):
    """Public category tree with admin-only catalogue management."""

    lookup_field = "slug"
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = Category.objects.all().order_by("name").prefetch_related(
            "children",
            "children__children",
            "children__children__children",
            "children__children__children__children",
        )

        if not is_catalog_admin(self.request.user):
            queryset = queryset.filter(is_active=True)

        return queryset

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsPlatformAdmin()]

    def get_serializer_class(self):
        if self.action in ("list", "retrieve"):
            return CategoryTreeSerializer
        return CategoryWriteSerializer

    def list(self, request, *args, **kwargs):
        # The public list endpoint returns roots with nested children.
        queryset = self.filter_queryset(
            self.get_queryset().filter(parent__isnull=True)
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class ProductViewSet(viewsets.ModelViewSet):
    """Public read-only catalogue; admin-only product mutations."""

    lookup_field = "slug"
    pagination_class = StandardResultsSetPagination
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        ProductSortFilter,
    ]
    filterset_class = ProductFilter
    search_fields = [
        "name",
        "description",
        "brand",
        "category__name",
    ]

    def get_queryset(self):
        queryset = Product.objects.select_related(
            "category"
        ).prefetch_related(
            Prefetch(
                "images",
                queryset=ProductImage.objects.order_by(
                    "-is_primary", "order", "id"
                ),
            ),
            Prefetch(
                "variants",
                queryset=ProductVariant.objects.order_by(
                    "size", "color"
                ),
            ),
        ).annotate(
            effective_price=Coalesce(
                "discount_price",
                "base_price",
                output_field=BigIntegerField(),
            ),
            reviews_count=Count("reviews", distinct=True),
            average_rating=Avg("reviews__rating"),
        )

        if not is_catalog_admin(self.request.user):
            queryset = queryset.filter(
                is_active=True,
                category__is_active=True,
            )

        return queryset

    def get_permissions(self):
        if self.action in ("list", "retrieve", "featured"):
            return [AllowAny()]

        if self.action == "reviews":
            if self.request.method == "POST":
                return [IsAuthenticated(), IsVerifiedUser()]
            return [AllowAny()]

        return [IsPlatformAdmin()]

    def get_serializer_class(self):
        if self.action == "list" or self.action == "featured":
            return ProductListSerializer

        if self.action == "retrieve":
            return ProductDetailSerializer

        if self.action == "reviews":
            if self.request.method == "POST":
                return ReviewCreateSerializer
            return ReviewReadSerializer

        return ProductWriteSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="sort",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=[
                    "newest",
                    "price_asc",
                    "price_desc",
                    "popularity",
                ],
                description="Catalogue sort option.",
            )
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="featured")
    def featured(self, request):
        queryset = self.filter_queryset(
            self.get_queryset().filter(is_featured=True)
        )
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"], url_path="reviews")
    def reviews(self, request, slug=None):
        product = self.get_object()

        if request.method == "GET":
            queryset = (
                Review.objects.filter(product=product)
                .select_related("user")
                .order_by("-created_at")
            )
            page = self.paginate_queryset(queryset)

            if page is not None:
                serializer = ReviewReadSerializer(
                    page,
                    many=True,
                    context=self.get_serializer_context(),
                )
                return self.get_paginated_response(serializer.data)

            serializer = ReviewReadSerializer(
                queryset,
                many=True,
                context=self.get_serializer_context(),
            )
            return Response(serializer.data)

        serializer = ReviewCreateSerializer(
            data=request.data,
            context={
                **self.get_serializer_context(),
                "product": product,
            },
        )
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        output = ReviewReadSerializer(
            review,
            context=self.get_serializer_context(),
        )
        return Response(output.data, status=status.HTTP_201_CREATED)


class ProductVariantViewSet(viewsets.ModelViewSet):
    """Administrative variant CRUD."""

    queryset = ProductVariant.objects.select_related("product").all()
    serializer_class = ProductVariantSerializer
    permission_classes = [IsPlatformAdmin]
    parser_classes = [JSONParser, MultiPartParser, FormParser]


class ProductImageViewSet(viewsets.ModelViewSet):
    """Administrative product-image CRUD."""

    queryset = ProductImage.objects.select_related("product").all()
    serializer_class = ProductImageSerializer
    permission_classes = [IsPlatformAdmin]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
