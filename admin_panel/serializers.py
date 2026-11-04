import json

from django.db import transaction
from rest_framework import serializers

from products.models import (
    Category,
    Product,
    ProductImage,
    ProductVariant,
)
from orders.models import Coupon, Order
from orders.serializers import CouponSerializer, OrderSerializer


class AdminProductSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.all(),
    )

    current_price = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()

    image_file = serializers.ImageField(
        write_only=True,
        required=False,
    )

    variants = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "category",
            "audience",
            "brand",
            "description",
            "tags",
            "base_price",
            "discount_price",
            "current_price",
            "primary_image",
            "image_file",
            "is_featured",
            "is_active",
            "variants",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "current_price",
            "primary_image",
            "created_at",
            "updated_at",
        )

    def to_internal_value(self, data):
        data = data.copy()

        raw_variants = data.get("variants")

        if isinstance(raw_variants, str):
            try:
                data["variants"] = json.loads(raw_variants)
            except json.JSONDecodeError:
                raise serializers.ValidationError({
                    "variants": "Invalid variant JSON."
                })

        return super().to_internal_value(data)

    def get_current_price(self, obj):
        return getattr(
            obj,
            "current_price",
            obj.discount_price
            if obj.discount_price
            else obj.base_price,
        )

    def get_primary_image(self, obj):
        image = (
            obj.images.filter(is_primary=True).first()
            or obj.images.order_by("order").first()
        )

        if not image or not image.image:
            return ""

        try:
            return image.image.url
        except ValueError:
            return ""

    def to_representation(self, instance):
        data = super().to_representation(instance)

        data["variants"] = list(
            instance.variants.values(
                "id",
                "size",
                "color",
                "color_hex_code",
                "stock_quantity",
                "sku",
                "additional_price",
            )
        )

        return data

    def save_image(self, product, image_file):
        if not image_file:
            return

        ProductImage.objects.filter(
            product=product,
            is_primary=True,
        ).update(is_primary=False)

        ProductImage.objects.create(
            product=product,
            image=image_file,
            alt_text=product.name,
            is_primary=True,
            order=0,
        )

    def save_variants(self, product, variants):
        allowed = {
            "size",
            "color",
            "color_hex_code",
            "stock_quantity",
            "additional_price",
        }

        for data in variants:
            variant_id = data.pop("id", None)

            values = {
                key: value
                for key, value in data.items()
                if key in allowed
            }

            if variant_id:
                variant = ProductVariant.objects.filter(
                    pk=variant_id,
                    product=product,
                ).first()

                if not variant:
                    raise serializers.ValidationError({
                        "variants": (
                            f"Variant {variant_id} does not belong "
                            "to this product."
                        )
                    })

                for key, value in values.items():
                    setattr(variant, key, value)

                variant.save()

            else:
                ProductVariant.objects.create(
                    product=product,
                    **values,
                )

    @transaction.atomic
    def create(self, validated_data):
        variants = validated_data.pop("variants", [])
        image_file = validated_data.pop("image_file", None)

        product = Product.objects.create(**validated_data)

        self.save_image(product, image_file)
        self.save_variants(product, variants)

        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        variants = validated_data.pop("variants", None)
        image_file = validated_data.pop("image_file", None)

        product = super().update(instance, validated_data)

        self.save_image(product, image_file)

        if variants is not None:
            self.save_variants(product, variants)

        return product


class AdminOrderSerializer(OrderSerializer):
    customer_email = serializers.EmailField(
        source="user.email",
        read_only=True,
    )

    customer_name = serializers.SerializerMethodField()

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + (
            "customer_email",
            "customer_name",
        )

    def get_customer_name(self, obj):
        return obj.user.get_full_name()


class AdminCouponSerializer(CouponSerializer):
    class Meta(CouponSerializer.Meta):
        fields = CouponSerializer.Meta.fields