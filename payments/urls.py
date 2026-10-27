
from django.urls import path

from .views import (
    InitializePaymentView,
    PaystackWebhookView,
    RefundPaymentView,
    VerifyPaymentView,
)


urlpatterns = [
    path(
        "initialize/",
        InitializePaymentView.as_view(),
        name="payment-initialize",
    ),
    path(
        "verify/<str:reference>/",
        VerifyPaymentView.as_view(),
        name="payment-verify",
    ),
    path(
        "webhook/",
        PaystackWebhookView.as_view(),
        name="paystack-webhook",
    ),
    path(
        "refund/<int:order_id>/",
        RefundPaymentView.as_view(),
        name="payment-refund",
    ),
]
