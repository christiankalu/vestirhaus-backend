
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import ProductVariant


logger = logging.getLogger(__name__)


@receiver(pre_save, sender=ProductVariant)
def remember_previous_stock(sender, instance, **kwargs):
    """Capture the previous stock quantity before an update."""
    if not instance.pk:
        instance._previous_stock_quantity = None
        return

    instance._previous_stock_quantity = (
        sender.objects.filter(pk=instance.pk)
        .values_list("stock_quantity", flat=True)
        .first()
    )


@receiver(post_save, sender=ProductVariant)
def notify_low_stock(sender, instance, created, **kwargs):
    """Alert administrators when a variant enters low-stock status."""
    threshold = ProductVariant.LOW_STOCK_THRESHOLD
    previous = getattr(instance, "_previous_stock_quantity", None)

    crossed_threshold = (
        instance.stock_quantity < threshold
        and (
            created
            or previous is None
            or previous >= threshold
        )
    )

    if not crossed_threshold:
        return

    product_name = instance.product.name
    sku = instance.sku
    quantity = instance.stock_quantity

    def send_alert():
        logger.warning(
            "Vestirhaus low stock: product=%s sku=%s quantity=%s",
            product_name,
            sku,
            quantity,
        )

        recipients = getattr(
            settings,
            "LOW_STOCK_NOTIFICATION_EMAILS",
            [],
        )

        if not recipients:
            logger.warning(
                "No low-stock email recipients configured."
            )
            return

        try:
            send_mail(
                subject=f"Vestirhaus low stock alert: {product_name}",
                message=(
                    f"Product: {product_name}\n"
                    f"SKU: {sku}\n"
                    f"Remaining units: {quantity}\n"
                    f"Threshold: fewer than {threshold} units."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=False,
            )
        except Exception:
            logger.exception("Unable to send low-stock notification.")

    # Send after the transaction succeeds, not before the save commits.
    transaction.on_commit(send_alert)
