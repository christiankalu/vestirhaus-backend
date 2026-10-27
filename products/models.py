
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models, transaction
from django.db.models import Q
from django.utils.text import slugify


def generate_unique_slug(instance, source, fallback):
    """Generate a unique slug without overwriting an existing slug."""
    model = instance.__class__
    base_slug = slugify(source) or fallback
    candidate = base_slug
    suffix = 2

    queryset = model._default_manager.all()
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    while queryset.filter(slug=candidate).exists():
        candidate = f"{base_slug}-{suffix}"
        suffix += 1

    return candidate


class Category(models.Model):
    """Hierarchical category such as Men > Agbada."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=150, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="categories/",
        blank=True,
        null=True,
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="children",
        blank=True,
        null=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"
        indexes = [
            models.Index(fields=["parent", "is_active"]),
        ]

    def clean(self):
        """Prevent a category from becoming its own ancestor."""
        super().clean()

        ancestor = self.parent
        while ancestor is not None:
            if self.pk and ancestor.pk == self.pk:
                raise ValidationError(
                    {"parent": "A category cannot be its own ancestor."}
                )
            ancestor = ancestor.parent

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(
                self, self.name, "category"
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    """A Vestirhaus fashion product."""

    class Audience(models.TextChoices):
        MEN = "men", "Men"
        WOMEN = "women", "Women"
        KIDS = "kids", "Kids"
        UNISEX = "unisex", "Unisex"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(
        blank=True,
        help_text="Product description. Treat stored text as plain text.",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )
    audience = models.CharField(
        max_length=10,
        choices=Audience.choices,
        default=Audience.UNISEX,
        db_index=True,
    )
    brand = models.CharField(max_length=120, default="Vestirhaus")
    base_price = models.PositiveBigIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Price in kobo. ₦1,000.00 = 100000 kobo.",
    )
    discount_price = models.PositiveBigIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1)],
        help_text="Optional discounted price in kobo.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="A JSON list of tags, e.g. ['ankara', 'occasion'].",
    )

    # Updated by the orders workflow after a qualifying sale.
    sales_count = models.PositiveBigIntegerField(
        default=0,
        editable=False,
        db_index=True,
        help_text="Internal popularity counter maintained by the order workflow.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "-created_at"]),
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["audience", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(discount_price__isnull=True)
                    | Q(discount_price__lt=models.F("base_price"))
                ),
                name="product_discount_below_base_price",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(
                self, self.name, "product"
            )
        super().save(*args, **kwargs)

    @property
    def current_price(self):
        return (
            self.discount_price
            if self.discount_price is not None
            else self.base_price
        )

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    """A purchasable combination of size and colour."""

    LOW_STOCK_THRESHOLD = 5

    class Size(models.TextChoices):
        XS = "XS", "XS"
        S = "S", "S"
        M = "M", "M"
        L = "L", "L"
        XL = "XL", "XL"
        XXL = "XXL", "XXL"
        CUSTOM = "Custom", "Custom"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    size = models.CharField(
        max_length=10,
        choices=Size.choices,
        default=Size.M,
    )
    color = models.CharField(max_length=60)
    color_hex_code = models.CharField(
        max_length=7,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^#[0-9a-fA-F]{6}$",
                message="Use a six-digit hex colour such as #1A2B3C.",
            )
        ],
    )
    stock_quantity = models.PositiveIntegerField(default=0)
    sku = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
    )
    additional_price = models.PositiveBigIntegerField(
        default=0,
        help_text="Additional price in kobo above the product price.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__name", "size", "color"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "size", "color"],
                name="unique_product_size_color",
            ),
        ]
        indexes = [
            models.Index(fields=["size", "color"]),
            models.Index(fields=["stock_quantity"]),
        ]

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = f"VH-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)

    @property
    def is_low_stock(self):
        return self.stock_quantity < self.LOW_STOCK_THRESHOLD

    @property
    def current_price(self):
        return self.product.current_price + self.additional_price

    def __str__(self):
        return f"{self.product.name} — {self.size} / {self.color}"


class ProductImage(models.Model):
    """A product image stored using the configured Cloudinary storage."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to="products/")
    alt_text = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-is_primary", "order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_primary=True),
                name="unique_primary_image_per_product",
            ),
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_primary:
                ProductImage.objects.filter(
                    product=self.product,
                    is_primary=True,
                ).exclude(pk=self.pk).update(is_primary=False)

            super().save(*args, **kwargs)

    def __str__(self):
        return f"Image for {self.product.name}"


class Review(models.Model):
    """A customer's rating and review of a purchased product."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    title = models.CharField(max_length=150)
    body = models.TextField()
    is_verified_purchase = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "user"],
                name="one_review_per_user_per_product",
            ),
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5),
                name="review_rating_between_1_and_5",
            ),
        ]
        indexes = [
            models.Index(fields=["product", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.product.name} — {self.rating}/5"
