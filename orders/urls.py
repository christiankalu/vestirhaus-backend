from django.urls import include, path

from .views import (
    AdminOrderViewSet,
    ApplyCouponView,
    CancelOrderView,
    CartCSRFView,
    CartItemDetailView,
    CartView,
    CheckoutView,
    OrderDetailView,
    OrderListView,
)


urlpatterns = [
    # Guest and customer cart
    path("cart/csrf/", CartCSRFView.as_view(), name="cart-csrf"),
    path("cart/apply-coupon/", ApplyCouponView.as_view(), name="cart-apply-coupon"),
    path("cart/<str:item_id>/", CartItemDetailView.as_view(), name="cart-item-detail"),
    path("cart/", CartView.as_view(), name="cart"),

    # Checkout and customer order history
    path("orders/checkout/", CheckoutView.as_view(), name="order-checkout"),
    path("orders/<int:order_id>/cancel/", CancelOrderView.as_view(), name="order-cancel"),
    path("orders/<int:order_id>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/", OrderListView.as_view(), name="order-list"),

]