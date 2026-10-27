
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from orders.models import Order


class PaymentAttempt(models.Model):
    """One attempt to pay for an order using Paystack."""

    class Status(models.TextChoices):
        INITIALIZING = "initializing", "Initializing"
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Successful"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    class RefundStatus(models.TextChoices):
        NONE = "none", "No refund"
        REQUESTING = "requesting", "Submitting refund"
        PENDING = "pending", "Refund pending"
        PROCESSING = "processing", "Refund processing"
        NEEDS_ATTENTION = "needs-attention", "Needs attention"
        FAILED = "failed", "Refund failed"
        PROCESSED = "processed", "Refund processed"

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="payment_attempts",
    )

    reference = models.CharField(max_length=100, unique=True)
    amount = models.PositiveBigIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Amount charged, in kobo.",
    )
    currency = models.CharField(max_length=3, default="NGN")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INITIALIZING,
        db_index=True,
    )

    authorization_url = models.URLField(max_length=1000, blank=True)
    access_code = models.CharField(max_length=255, blank=True)
    gateway_transaction_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
    )

    refund_status = models.CharField(
        max_length=20,
        choices=RefundStatus.choices,
        default=RefundStatus.NONE,
    )
    refund_reference = models.CharField(max_length=100, blank=True)
    refund_amount = models.PositiveBigIntegerField(null=True, blank=True)

    # Store only a curated subset of gateway response information.
    gateway_response = models.JSONField(default=dict, blank=True)

    # Idempotency markers.
    fulfillment_processed = models.BooleanField(default=False)
    confirmation_email_sent = models.BooleanField(default=False)

    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=1),
                name="payment_attempt_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.reference} — {self.status}"


class PaystackWebhookEvent(models.Model):
    """Minimal audit record for idempotent webhook processing."""

    event_hash = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=80)
    reference = models.CharField(max_length=100, blank=True)

    processed = models.BooleanField(default=False, db_index=True)
    last_error = models.CharField(max_length=500, blank=True)

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["event_type", "-received_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} — {self.reference or self.event_hash[:12]}"
