from rest_framework import serializers

from products.models import Product
from .models import WishlistItem


class WishlistProductSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()

    # All monetary values below remain in kobo, matching Product API.
    price = serializers.SerializerMethodField()
    current_price = serializers.SerializerMethodField()
    base_price = serializers.SerializerMethodField()
    discount_price = serializers.SerializerMethodField()
    sale_price = serializers.SerializerMethodField()

    image_url = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "price",
            "current_price",
            "base_price",
            "discount_price",
            "sale_price",
            "image_url",
            "primary_image",
            "category_name",
        ]

    def get_name(self, obj):
        return getattr(obj, "name", None) or getattr(obj, "title", "")

    def get_slug(self, obj):
        return getattr(obj, "slug", "")

    def get_current_price(self, obj):
        current = getattr(obj, "current_price", None)

        if current is not None:
            return current

        discount = getattr(obj, "discount_price", None)

        if discount not in (None, 0):
            return discount

        return getattr(obj, "base_price", 0) or 0

    def get_price(self, obj):
        # Backwards-compatible alias for existing frontend components.
        return self.get_current_price(obj)

    def get_base_price(self, obj):
        return getattr(obj, "base_price", 0) or 0

    def get_discount_price(self, obj):
        return getattr(obj, "discount_price", None)

    def get_sale_price(self, obj):
        discount = getattr(obj, "discount_price", None)

        if discount in (None, 0):
            return None

        base = getattr(obj, "base_price", None)

        if base is not None and discount >= base:
            return None

        return discount

    def _resolve_image_url(self, image):
        if not image:
            return ""

        try:
            url = image.url
        except (AttributeError, ValueError):
            url = str(image)

        if not url:
            return ""

        request = self.context.get("request")

        if request and url.startswith("/"):
            return request.build_absolute_uri(url)

        return url

    def get_image_url(self, obj):
        # Your Product API exposes primary_image as a Cloudinary URL.
        primary = getattr(obj, "primary_image", None)
        url = self._resolve_image_url(primary)

        if url:
            return url

        # Fall back to the related product images.
        images = getattr(obj, "images", None)

        if images is not None:
            try:
                image_record = (
                    images.filter(is_primary=True).first()
                    or images.order_by("order").first()
                )

                if image_record:
                    return self._resolve_image_url(
                        image_record.image
                    )
            except (AttributeError, TypeError):
                pass

        return ""

    def get_primary_image(self, obj):
        return self.get_image_url(obj)

    def get_category_name(self, obj):
        category = getattr(obj, "category", None)

        if category:
            return getattr(category, "name", None) or str(category)

        return getattr(obj, "category_name", "")


class WishlistItemSerializer(serializers.ModelSerializer):
    product = WishlistProductSerializer(read_only=True)

    class Meta:
        model = WishlistItem
        fields = [
            "id",
            "product",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]