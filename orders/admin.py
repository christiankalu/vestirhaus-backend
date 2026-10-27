from django.contrib import admin, messages
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from .models import Cart, CartItem, Coupon, Order, OrderItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ("product_variant", "quantity", "created_at", "updated_at")
    can_delete = False


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "coupon", "created_at", "updated_at")
    search_fields = ("user__email",)
    readonly_fields = ("user", "created_at", "updated_at")
    inlines = [CartItemInline]


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("cart", "product_variant", "quantity", "updated_at")
    search_fields = (
        "cart__user__email",
        "product_variant__sku",
        "product_variant__product__name",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_type",
        "value",
        "min_order_value",
        "used_count",
        "max_uses",
        "expiry_date",
        "is_active",
    )
    list_filter = ("discount_type", "is_active", "expiry_date")
    search_fields = ("code",)
    readonly_fields = ("used_count", "created_at")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "product_variant",
        "product_name",
        "variant_sku",
        "size",
        "color",
        "quantity",
        "unit_price",
        "total_price",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "user",
        "status",
        "payment_status",
        "total",
        "created_at",
    )
    list_filter = ("status", "payment_status", "created_at")
    search_fields = ("order_number", "user__email")
    readonly_fields = (
        "order_number",
        "user",
        "status",
        "payment_status",
        "subtotal",
        "shipping_fee",
        "discount",
        "total",
        "shipping_address",
        "coupon",
        "coupon_code_snapshot",
        "coupon_use_reserved",
        "paystack_reference",
        "stock_restored",
        "created_at",
        "updated_at",
    )
    inlines = [OrderItemInline]
    actions = ["cancel_selected_unpaid_orders"]

    @admin.action(description="Cancel selected eligible unpaid orders")
    def cancel_selected_unpaid_orders(self, request, queryset):
        from .services import cancel_order

        succeeded = 0
        failed = 0

        for order in queryset:
            try:
                cancel_order(order.user, order.pk)
                succeeded += 1
            except (DRFValidationError, DjangoValidationError):
                failed += 1

        if succeeded:
            self.message_user(
                request,
                f"Cancelled {succeeded} order(s) and restored stock.",
                level=messages.SUCCESS,
            )

        if failed:
            self.message_user(
                request,
                (
                    f"{failed} order(s) could not be cancelled. "
                    "Check payment and order status."
                ),
                level=messages.WARNING,
            )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "product_name",
        "variant_sku",
        "quantity",
        "unit_price",
        "total_price",
    )
    search_fields = (
        "order__order_number",
        "order__user__email",
        "product_name",
        "variant_sku",
    )
    readonly_fields = (
        "order",
        "product_variant",
        "quantity",
        "unit_price",
        "total_price",
        "product_name",
        "variant_sku",
        "size",
        "color",
    )