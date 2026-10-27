
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    ProductImageViewSet,
    ProductVariantViewSet,
    ProductViewSet,
)


router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")
router.register(
    "variants",
    ProductVariantViewSet,
    basename="product-variant",
)
router.register(
    "product-images",
    ProductImageViewSet,
    basename="product-image",
)

urlpatterns = [
    path("", include(router.urls)),
]
