import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Coupon(models.Model):
    """Promotional code with usage, expiry and value restrictions."""

    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage"
        FIXED = "fixed", "Fixed amount"

    code = models.CharField(max_length=50, unique=True, db_index=True)
    discount_type = models.CharField(
        max_length=12,
        choices=DiscountType.choices,
    )
    # Percentage values are 1–100; fixed values are in kobo.
    value = models.PositiveBigIntegerField(
        validators=[MinValueValidator(1)]
    )
    min_order_value = models.PositiveBigIntegerField(default=0)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0, editable=False)
    expiry_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(discount_type="percentage")
                    | Q(value__gte=1, value__lte=100)
                ),
                name="coupon_percentage_between_1_and_100",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.discount_type == self.DiscountType.PERCENTAGE
            and not 1 <= self.value <= 100
        ):
            raise ValidationError(
                {"value": "Percentage discounts must be between 1 and 100."}
            )

        if (
            self.max_uses is not None
            and self.used_count > self.max_uses
        ):
            raise ValidationError(
                {"max_uses": "Maximum uses cannot be below uses already reserved."}
            )

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def is_available(self, subtotal, now=None):
        """Check whether this coupon may be applied to the given subtotal."""
        now = now or timezone.now()

        if not self.is_active:
            return False

        if self.expiry_date and self.expiry_date <= now:
            return False

        if self.max_uses is not None and self.used_count >= self.max_uses:
            return False

        return subtotal >= self.min_order_value

    def calculate_discount(self, subtotal):
        if subtotal <= 0:
            return 0

        if self.discount_type == self.DiscountType.PERCENTAGE:
            discount = subtotal * self.value // 100
        else:
            discount = self.value

        return min(discount, subtotal)

    def __str__(self):
        return self.code


class Cart(models.Model):
    """One persistent cart per authenticated customer."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shopping_cart",
    )
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="carts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for {self.user.email}"


class CartItem(models.Model):
    """A variant and quantity in a customer's persistent cart."""

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product_variant = models.ForeignKey(
        "products.ProductVariant",
        on_delete=models.PROTECT,
        related_name="cart_items",
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(99)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product_variant"],
                name="unique_variant_per_cart",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="cart_item_quantity_at_least_one",
            ),
        ]

    def __str__(self):
        return f"{self.product_variant.sku} × {self.quantity}"


class Order(models.Model):
    """A checkout snapshot with inventory and payment lifecycle tracking."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    order_number = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    payment_status = models.CharField(
        max_length=12,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )

    subtotal = models.PositiveBigIntegerField()
    shipping_fee = models.PositiveBigIntegerField(default=0)
    discount = models.PositiveBigIntegerField(default=0)
    total = models.PositiveBigIntegerField()

    # Snapshot of the delivery destination at checkout.
    shipping_address = models.JSONField(default=dict)

    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    coupon_code_snapshot = models.CharField(max_length=50, blank=True)
    coupon_use_reserved = models.BooleanField(default=False)

    paystack_reference = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
    )

    # These flags make cancellation/stock restoration idempotent.
    stock_restored = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["payment_status", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total__gte=0),
                name="order_total_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(discount__lte=models.F("subtotal")),
                name="order_discount_not_over_subtotal",
            ),
        ]

    def __str__(self):
        return f"Order {self.order_number} — {self.user.email}"


class OrderItem(models.Model):
    """Immutable-at-checkout pricing snapshot for one order line."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product_variant = models.ForeignKey(
        "products.ProductVariant",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )
    unit_price = models.PositiveBigIntegerField(
        help_text="Snapshot of the unit price in kobo.",
    )
    total_price = models.PositiveBigIntegerField(
        help_text="Snapshot of quantity × unit price in kobo.",
    )

    # Preserve order details even if the catalogue label changes later.
    product_name = models.CharField(max_length=200)
    variant_sku = models.CharField(max_length=64)
    size = models.CharField(max_length=10)
    color = models.CharField(max_length=60)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="order_item_quantity_at_least_one",
            ),
            models.CheckConstraint(
                condition=Q(
                    total_price=models.F("unit_price") * models.F("quantity")
                ),
                name="order_item_total_matches_unit_price",
            ),
        ]

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"