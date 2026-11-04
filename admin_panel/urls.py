from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminHealthView,
    AdminDashboardView,
    AdminProductViewSet,
    AdminOrderViewSet,
    AdminCustomerListView,
    AdminCouponViewSet,
)


router = DefaultRouter()

router.register(
    "products",
    AdminProductViewSet,
    basename="admin-products",
)

router.register(
    "orders",
    AdminOrderViewSet,
    basename="admin-orders",
)

router.register(
    "coupons",
    AdminCouponViewSet,
    basename="admin-coupons",
)


urlpatterns = [
    path("health/", AdminHealthView.as_view(), name="health"),
    path("dashboard/", AdminDashboardView.as_view(), name="dashboard"),
    path("customers/", AdminCustomerListView.as_view(), name="customers"),
    path("", include(router.urls)),
]