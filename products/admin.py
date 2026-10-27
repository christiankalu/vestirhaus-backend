
from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Product, ProductImage, ProductVariant, Review


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = (
        "size",
        "color",
        "color_hex_code",
        "stock_quantity",
        "sku",
        "additional_price",
        "low_stock_status",
    )
    readonly_fields = ("low_stock_status",)

    @admin.display(description="Stock status")
    def low_stock_status(self, obj):
        if not obj.pk:
            return "Save variant to generate status"

        if obj.is_low_stock:
            return format_html(
                '<strong style="color: #b91c1c;">Low stock: {}</strong>',
                obj.stock_quantity,
            )

        return f"In stock: {obj.stock_quantity}"


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ("image", "alt_text", "is_primary", "order")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "updated_at")
    list_filter = ("is_active", "parent")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "audience",
        "base_price",
        "discount_price",
        "is_active",
        "is_featured",
        "sales_count",
    )
    list_filter = (
        "audience",
        "category",
        "is_active",
        "is_featured",
    )
    search_fields = ("name", "slug", "brand", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("sales_count", "created_at", "updated_at")
    inlines = [ProductVariantInline, ProductImageInline]
    ordering = ("-created_at",)


class LowStockFilter(admin.SimpleListFilter):
    title = "stock level"
    parameter_name = "low_stock"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Low stock (below 5)"),
            ("no", "Stock of 5 or more"),
        )

    def queryset(self, request, queryset):
        threshold = ProductVariant.LOW_STOCK_THRESHOLD

        if self.value() == "yes":
            return queryset.filter(stock_quantity__lt=threshold)

        if self.value() == "no":
            return queryset.filter(stock_quantity__gte=threshold)

        return queryset


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "size",
        "color",
        "sku",
        "stock_quantity",
        "low_stock_status",
    )
    list_filter = ("size", LowStockFilter)
    search_fields = ("product__name", "sku", "color")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Stock status")
    def low_stock_status(self, obj):
        if obj.is_low_stock:
            return format_html(
                '<strong style="color: #b91c1c;">LOW: {}</strong>',
                obj.stock_quantity,
            )
        return f"OK: {obj.stock_quantity}"


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("product", "alt_text", "is_primary", "order")
    list_filter = ("is_primary",)
    search_fields = ("product__name", "alt_text")
    ordering = ("product", "order")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "user",
        "rating",
        "is_verified_purchase",
        "created_at",
    )
    list_filter = ("rating", "is_verified_purchase", "created_at")
    search_fields = ("product__name", "user__email", "title", "body")
    readonly_fields = ("is_verified_purchase", "created_at")
    ordering = ("-created_at",)
