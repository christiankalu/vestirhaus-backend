
from django.contrib import admin

from .models import PaymentAttempt, PaystackWebhookEvent


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "order",
        "amount",
        "currency",
        "status",
        "refund_status",
        "paid_at",
        "created_at",
    )
    list_filter = ("status", "refund_status", "currency", "created_at")
    search_fields = (
        "reference",
        "order__order_number",
        "order__user__email",
    )
    readonly_fields = (
        "order",
        "reference",
        "amount",
        "currency",
        "status",
        "authorization_url",
        "access_code",
        "gateway_transaction_id",
        "refund_status",
        "refund_reference",
        "refund_amount",
        "gateway_response",
        "fulfillment_processed",
        "confirmation_email_sent",
        "paid_at",
        "created_at",
        "updated_at",
    )


@admin.register(PaystackWebhookEvent)
class PaystackWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "reference",
        "processed",
        "received_at",
        "processed_at",
    )
    list_filter = ("event_type", "processed", "received_at")
    search_fields = ("reference", "event_hash", "last_error")
    readonly_fields = (
        "event_hash",
        "event_type",
        "reference",
        "processed",
        "last_error",
        "received_at",
        "processed_at",
    )
