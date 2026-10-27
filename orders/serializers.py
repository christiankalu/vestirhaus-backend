from rest_framework import serializers

from products.models import ProductVariant

from .models import CartItem, Coupon, Order, OrderItem, Cart


class CartAddSerializer(serializers.Serializer):
    """Add quantity of a selected product variant to the cart."""

    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=99)

    def validate_variant_id(self, value):
        if not ProductVariant.objects.filter(pk=value).exists():
            raise serializers.ValidationError(
                "The selected product variant does not exist."
            )
        return value


class CartQuantitySerializer(serializers.Serializer):
    """Replace a cart line's quantity."""

    quantity = serializers.IntegerField(min_value=1, max_value=99)


class ApplyCouponSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50, trim_whitespace=True)


class CartLineSerializer(serializers.Serializer):
    """Normalized output for both guest and authenticated cart lines."""

    id = serializers.CharField()
    product_variant = serializers.DictField()
    product_name = serializers.CharField()
    product_slug = serializers.CharField()
    image_url = serializers.CharField(allow_null=True)
    quantity = serializers.IntegerField()
    unit_price = serializers.IntegerField()
    total_price = serializers.IntegerField()
    stock_quantity = serializers.IntegerField()
    available = serializers.BooleanField()


class CartSummarySerializer(serializers.Serializer):
    items = CartLineSerializer(many=True)
    subtotal = serializers.IntegerField()
    discount = serializers.IntegerField()
    shipping_fee = serializers.IntegerField()
    total = serializers.IntegerField()
    coupon_code = serializers.CharField(allow_null=True)
    coupon_error = serializers.CharField(allow_null=True)


class ShippingAddressSerializer(serializers.Serializer):
    """Validate the delivery destination stored on the order."""

    recipient_name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(max_length=30)
    address_line_1 = serializers.CharField(max_length=255)
    address_line_2 = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100)
    postal_code = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        default="",
    )
    country = serializers.CharField(
        max_length=100,
        required=False,
        default="Nigeria",
    )


class CheckoutSerializer(serializers.Serializer):
    shipping_address = ShippingAddressSerializer()


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product_variant",
            "quantity",
            "unit_price",
            "total_price",
            "product_name",
            "variant_sku",
            "size",
            "color",
        )
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "order_number",
            "status",
            "payment_status",
            "subtotal",
            "shipping_fee",
            "discount",
            "total",
            "shipping_address",
            "coupon_code_snapshot",
            "paystack_reference",
            "created_at",
            "items",
        )
        read_only_fields = fields


class AdminOrderUpdateSerializer(serializers.ModelSerializer):
    """Administrative updates to fulfilment status only."""

    class Meta:
        model = Order
        fields = ("status",)
        
        
from .models import Cart, CartItem, Coupon


class CouponSerializer(serializers.ModelSerializer):
    """Administrative/internal coupon representation."""

    class Meta:
        model = Coupon
        fields = (
            "id",
            "code",
            "discount_type",
            "value",
            "min_order_value",
            "max_uses",
            "used_count",
            "expiry_date",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "used_count", "created_at")

    def validate(self, attrs):
        discount_type = attrs.get(
            "discount_type",
            self.instance.discount_type if self.instance else None,
        )
        value = attrs.get(
            "value",
            self.instance.value if self.instance else None,
        )

        if (
            discount_type == Coupon.DiscountType.PERCENTAGE
            and value is not None
            and not 1 <= value <= 100
        ):
            raise serializers.ValidationError(
                {"value": "Percentage discounts must be between 1 and 100."}
            )

        return attrs


class CartItemModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = CartItem
        fields = (
            "id",
            "product_variant",
            "quantity",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class CartModelSerializer(serializers.ModelSerializer):
    items = CartItemModelSerializer(many=True, read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    coupon_code = serializers.CharField(
        source="coupon.code",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Cart
        fields = (
            "id",
            "user_email",
            "coupon_code",
            "items",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields