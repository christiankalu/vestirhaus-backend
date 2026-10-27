
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Avg, Count
from rest_framework import serializers

from .models import Category, Product, ProductImage, ProductVariant, Review


class CategoryWriteSerializer(serializers.ModelSerializer):
    parent = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.all(),
        required=False,
        allow_null=True,
    )
    slug = serializers.SlugField(
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = Category
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "image",
            "parent",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_slug(self, value):
        if not value:
            return value

        queryset = Category.objects.filter(slug=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "This category slug is already in use."
            )

        return value

    def validate(self, attrs):
        parent = attrs.get(
            "parent",
            self.instance.parent if self.instance else None,
        )

        node = parent
        while node is not None:
            if self.instance and node.pk == self.instance.pk:
                raise serializers.ValidationError(
                    {"parent": "A category cannot be its own ancestor."}
                )
            node = node.parent

        return attrs


class CategoryTreeSerializer(serializers.ModelSerializer):
    parent = serializers.SlugRelatedField(
        slug_field="slug",
        read_only=True,
    )
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "image",
            "parent",
            "children",
        )

    def get_children(self, obj) -> list:
        # Use prefetched relations and filter inactive children in Python.
        children = [
            child
            for child in obj.children.all()
            if child.is_active
        ]
        return CategoryTreeSerializer(
            children,
            many=True,
            context=self.context,
        ).data


class ProductVariantSerializer(serializers.ModelSerializer):
    product = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Product.objects.all(),
    )
    is_low_stock = serializers.BooleanField(read_only=True)
    current_price = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProductVariant
        fields = (
            "id",
            "product",
            "size",
            "color",
            "color_hex_code",
            "stock_quantity",
            "sku",
            "additional_price",
            "current_price",
            "is_low_stock",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        product = attrs.get(
            "product",
            self.instance.product if self.instance else None,
        )
        size = attrs.get(
            "size",
            self.instance.size if self.instance else None,
        )
        color = attrs.get(
            "color",
            self.instance.color if self.instance else None,
        )

        if product and size and color:
            queryset = ProductVariant.objects.filter(
                product=product,
                size=size,
                color=color,
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise serializers.ValidationError(
                    "This size and colour combination already exists."
                )

        return attrs


class ProductImageSerializer(serializers.ModelSerializer):
    product = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Product.objects.all(),
    )

    class Meta:
        model = ProductImage
        fields = (
            "id",
            "product",
            "image",
            "alt_text",
            "is_primary",
            "order",
        )
        read_only_fields = ("id",)


class ProductWriteSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.all(),
    )
    slug = serializers.SlugField(
        required=False,
        allow_blank=True,
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        allow_empty=True,
        max_length=30,
    )

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "category",
            "audience",
            "brand",
            "base_price",
            "discount_price",
            "is_active",
            "is_featured",
            "tags",
            "sales_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "sales_count",
            "created_at",
            "updated_at",
        )

    def validate_slug(self, value):
        if not value:
            return value

        queryset = Product.objects.filter(slug=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "This product slug is already in use."
            )

        return value

    def validate(self, attrs):
        base_price = attrs.get(
            "base_price",
            self.instance.base_price if self.instance else None,
        )
        discount_price = attrs.get(
            "discount_price",
            self.instance.discount_price if self.instance else None,
        )

        if (
            base_price is not None
            and discount_price is not None
            and discount_price >= base_price
        ):
            raise serializers.ValidationError(
                {
                    "discount_price": (
                        "Discount price must be less than base price."
                    )
                }
            )

        return attrs


class ProductListSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(
        slug_field="slug",
        read_only=True,
    )
    current_price = serializers.IntegerField(read_only=True)
    average_rating = serializers.FloatField(read_only=True, allow_null=True)
    review_count = serializers.IntegerField(
        source="reviews_count",
        read_only=True,
    )
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "category",
            "audience",
            "brand",
            "base_price",
            "discount_price",
            "current_price",
            "is_featured",
            "tags",
            "created_at",
            "primary_image",
            "average_rating",
            "review_count",
        )

    def get_primary_image(self, obj) -> str | None:
        image = next(
            (item for item in obj.images.all() if item.is_primary),
            None,
        )
        if image is None:
            image = next(iter(obj.images.all()), None)

        if image is None or not image.image:
            return None

        request = self.context.get("request")
        url = image.image.url
        return request.build_absolute_uri(url) if request else url


class ProductDetailSerializer(ProductListSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    description = serializers.CharField(read_only=True)

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + (
            "description",
            "images",
            "variants",
            "updated_at",
        )


class ReviewReadSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = (
            "id",
            "reviewer_name",
            "rating",
            "title",
            "body",
            "is_verified_purchase",
            "created_at",
        )
        read_only_fields = fields

    def get_reviewer_name(self, obj) -> str:
        full_name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return full_name or "Verified customer"


class ReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ("rating", "title", "body")

    def validate(self, attrs):
        request = self.context["request"]
        product = self.context["product"]

        if Review.objects.filter(
            product=product,
            user=request.user,
        ).exists():
            raise serializers.ValidationError(
                "You have already reviewed this product."
            )

        from .services import has_verified_purchase

        if not has_verified_purchase(request.user, product):
            raise serializers.ValidationError(
                "A verified purchase is required to review this product."
            )

        return attrs

    def create(self, validated_data):
        return Review.objects.create(
            product=self.context["product"],
            user=self.context["request"].user,
            is_verified_purchase=True,
            **validated_data,
        )
