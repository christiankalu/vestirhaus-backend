from django.conf import settings
from django.db import models


class RefundRecord(models.Model):
    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="admin_refund",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="admin_refund_requests",
    )

    paystack_refund_id = models.CharField(
        max_length=100,
        blank=True,
    )

    amount = models.PositiveBigIntegerField(
        help_text="Refund amount in kobo.",
    )

    status = models.CharField(
        max_length=30,
        default="pending",
    )

    reason = models.TextField(blank=True)

    gateway_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Refund for order {self.order_id} - {self.status}"