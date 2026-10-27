
import json
import logging
import uuid
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from orders.models import Order, OrderItem
from products.models import Product

from .gateway import (
    PaystackAPIError,
    PaystackError,
    PaystackTransportError,
    initialize_transaction,
    initiate_full_refund,
    verify_transaction,
)
from .models import PaymentAttempt


logger = logging.getLogger(__name__)


class PaymentIntegrityError(Exception):
    """Gateway details do not match the order/payment we expect."""


class PaymentConflict(APIException):
    status_code = 409
    default_detail = "This payment operation conflicts with the current order state."
    default_code = "payment_conflict"


def initialize_order_payment(user, order_id):
    """Create or reuse one valid Paystack checkout link for an order."""

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .filter(pk=order_id, user=user)
            .first()
        )

        if order is None:
            raise Order.DoesNotExist

        if order.payment_status == Order.PaymentStatus.PAID:
            raise PaymentConflict("This order has already been paid.")

        if order.status in {
            Order.Status.CANCELLED,
            Order.Status.REFUNDED,
        } or order.stock_restored:
            raise ValidationError(
                {"order": "Payment cannot be initialized for this order."}
            )

        if order.total <= 0:
            raise ValidationError(
                {"order": "A zero-total order cannot be sent to Paystack."}
            )

        latest = order.payment_attempts.order_by("-created_at").first()

        if (
            latest
            and latest.status == PaymentAttempt.Status.PENDING
            and latest.authorization_url
        ):
            return latest, False

        if latest and latest.status == PaymentAttempt.Status.INITIALIZING:
            recent_cutoff = timezone.now() - timedelta(minutes=2)

            if latest.created_at >= recent_cutoff:
                raise PaymentConflict(
                    "Payment initialization is already in progress. "
                    "Please retry shortly."
                )

            # A stale initialization needs reconciliation before a new attempt.
            # Do not assume that an earlier request definitely failed.
            raise PaymentConflict(
                "The previous payment initialization is unresolved. "
                "Verify its status before creating another payment."
            )

        reference = f"VH-{uuid.uuid4().hex.upper()}"

        payment = PaymentAttempt.objects.create(
            order=order,
            reference=reference,
            amount=order.total,
            currency="NGN",
            status=PaymentAttempt.Status.INITIALIZING,
        )

        order.paystack_reference = reference
        order.payment_status = Order.PaymentStatus.PENDING
        order.save(
            update_fields=[
                "paystack_reference",
                "payment_status",
                "updated_at",
            ]
        )

    # The external HTTP request happens outside the database transaction.
    try:
        gateway_data = initialize_transaction(
            email=user.email,
            amount=payment.amount,
            reference=payment.reference,
            callback_url=settings.PAYSTACK_CALLBACK_URL,
            metadata=json.dumps(
                {
                    "order_id": str(payment.order.order_number),
                    "payment_attempt_id": payment.pk,
                }
            ),
        )

        authorization_url = gateway_data.get("authorization_url")
        access_code = gateway_data.get("access_code")

        if not authorization_url or not access_code:
            raise PaystackAPIError(
                "Paystack did not return a valid checkout URL."
            )

        with transaction.atomic():
            payment = PaymentAttempt.objects.select_for_update().get(
                pk=payment.pk
            )

            # A webhook/manual reconciliation could have completed while
            # initialization was returning. Never overwrite a successful state.
            if payment.status == PaymentAttempt.Status.INITIALIZING:
                payment.status = PaymentAttempt.Status.PENDING
                payment.authorization_url = authorization_url
                payment.access_code = access_code
                payment.gateway_response = {
                    "message": "Authorization URL created",
                }
                payment.save(
                    update_fields=[
                        "status",
                        "authorization_url",
                        "access_code",
                        "gateway_response",
                        "updated_at",
                    ]
                )

        return payment, True

    except PaystackError:
        logger.exception(
            "Paystack initialization failed for order %s.",
            order.order_number,
        )

        PaymentAttempt.objects.filter(
            pk=payment.pk,
            status=PaymentAttempt.Status.INITIALIZING,
        ).update(status=PaymentAttempt.Status.FAILED)

        Order.objects.filter(
            pk=order.pk,
            paystack_reference=payment.reference,
            payment_status=Order.PaymentStatus.PENDING,
        ).update(payment_status=Order.PaymentStatus.FAILED)

        raise


def validate_gateway_transaction(payment, data):
    """Check gateway status, reference, amount, currency, and customer."""

    order = payment.order

    if data.get("status") != "success":
        return False

    if data.get("reference") != payment.reference:
        raise PaymentIntegrityError("Paystack reference mismatch.")

    if int(data.get("amount", -1)) != payment.amount:
        raise PaymentIntegrityError("Paystack amount does not match the payment.")

    if payment.amount != order.total:
        raise PaymentIntegrityError("Payment amount does not match the order total.")

    if data.get("currency") != payment.currency or payment.currency != "NGN":
        raise PaymentIntegrityError("Payment currency does not match NGN.")

    customer = data.get("customer") or {}
    gateway_email = customer.get("email")

    if gateway_email and gateway_email.strip().casefold() != order.user.email.casefold():
        raise PaymentIntegrityError("Paystack customer email does not match the order.")

    return True


def verify_and_process_payment(reference, user=None):
    """
    Verify a reference directly with Paystack and update local records.

    If user is supplied, the payment must belong to that authenticated user.
    """
    queryset = PaymentAttempt.objects.select_related(
        "order",
        "order__user",
    ).filter(reference=reference)

    if user is not None:
        queryset = queryset.filter(order__user=user)

    payment = queryset.first()

    if payment is None:
        raise PaymentAttempt.DoesNotExist

    gateway_data = verify_transaction(reference)
    gateway_status = gateway_data.get("status")

    if gateway_status != "success":
        if gateway_status in {"failed", "abandoned"}:
            with transaction.atomic():
                locked_payment = PaymentAttempt.objects.select_for_update().get(
                    pk=payment.pk
                )
                order = Order.objects.select_for_update().get(
                    pk=locked_payment.order_id
                )

                # Do not overwrite a previously successful payment.
                if locked_payment.status != PaymentAttempt.Status.SUCCESS:
                    locked_payment.status = PaymentAttempt.Status.FAILED
                    locked_payment.gateway_response = {
                        "status": gateway_status,
                        "gateway_response": gateway_data.get(
                            "gateway_response", ""
                        ),
                    }
                    locked_payment.save(
                        update_fields=[
                            "status",
                            "gateway_response",
                            "updated_at",
                        ]
                    )

                    if (
                        order.paystack_reference == reference
                        and order.payment_status != Order.PaymentStatus.PAID
                    ):
                        order.payment_status = Order.PaymentStatus.FAILED
                        order.save(
                            update_fields=["payment_status", "updated_at"]
                        )

        return payment, gateway_data

    if not validate_gateway_transaction(payment, gateway_data):
        return payment, gateway_data

    apply_verified_success(payment.pk, gateway_data)

    payment.refresh_from_db()
    return payment, gateway_data


def apply_verified_success(payment_id, gateway_data):
    """Apply a confirmed successful payment exactly once."""

    with transaction.atomic():
        payment = PaymentAttempt.objects.select_for_update().get(
            pk=payment_id
        )
        order = Order.objects.select_for_update().get(pk=payment.order_id)

        # Repeated verification of the same successful reference is safe.
        if payment.status == PaymentAttempt.Status.SUCCESS:
            is_primary = order.paystack_reference == payment.reference
            if is_primary and not payment.confirmation_email_sent:
                transaction.on_commit(
                    lambda pk=payment.pk: send_order_confirmation_email_once(pk)
                )
            return

        payment.status = PaymentAttempt.Status.SUCCESS
        payment.gateway_transaction_id = str(gateway_data.get("id", ""))
        payment.paid_at = timezone.now()
        payment.gateway_response = {
            "status": gateway_data.get("status"),
            "channel": gateway_data.get("channel"),
            "gateway_response": gateway_data.get("gateway_response", ""),
            "paid_at": gateway_data.get("paid_at"),
        }
        payment.save(
            update_fields=[
                "status",
                "gateway_transaction_id",
                "paid_at",
                "gateway_response",
                "updated_at",
            ]
        )

        if order.payment_status == Order.PaymentStatus.PAID:
            # A different successful attempt indicates a possible double charge.
            if order.paystack_reference != payment.reference:
                logger.critical(
                    "Possible duplicate successful payment: "
                    "order=%s reference=%s",
                    order.order_number,
                    payment.reference,
                )
            return

        order.payment_status = Order.PaymentStatus.PAID
        order.paystack_reference = payment.reference

        if (
            order.status not in {
                Order.Status.CANCELLED,
                Order.Status.REFUNDED,
            }
            and not order.stock_restored
        ):
            if order.status == Order.Status.PENDING:
                order.status = Order.Status.CONFIRMED

            # Record sales once, only after payment has been confirmed.
            if not payment.fulfillment_processed:
                quantities_by_product = defaultdict(int)

                order_items = (
                    OrderItem.objects.filter(order=order)
                    .select_related("product_variant__product")
                )

                for item in order_items:
                    product_id = item.product_variant.product_id
                    quantities_by_product[product_id] += item.quantity

                for product_id, quantity in quantities_by_product.items():
                    Product.objects.filter(pk=product_id).update(
                        sales_count=F("sales_count") + quantity
                    )

                payment.fulfillment_processed = True
                payment.save(
                    update_fields=["fulfillment_processed", "updated_at"]
                )
        else:
            # A delayed successful charge after cancellation must be flagged
            # for review/refund; do not silently reopen a cancelled order.
            logger.critical(
                "Payment succeeded for a cancelled/restored order: order=%s ref=%s",
                order.order_number,
                payment.reference,
            )

        order.save(
            update_fields=[
                "payment_status",
                "paystack_reference",
                "status",
                "updated_at",
            ]
        )

        if not order.stock_restored:
            transaction.on_commit(
                lambda pk=payment.pk: send_order_confirmation_email_once(pk)
            )


def send_order_confirmation_email_once(payment_id):
    """Send one order confirmation after a successful payment."""

    with transaction.atomic():
        payment = (
            PaymentAttempt.objects.select_for_update()
            .select_related("order", "order__user")
            .get(pk=payment_id)
        )
        order = payment.order

        if payment.status != PaymentAttempt.Status.SUCCESS:
            return

        if order.payment_status != Order.PaymentStatus.PAID:
            return

        if order.paystack_reference != payment.reference:
            return

        if payment.confirmation_email_sent:
            return

        items = order.items.all()
        item_lines = [
            f"- {item.product_name} ({item.size}, {item.color}) "
            f"x {item.quantity}: NGN {item.total_price / 100:,.2f}"
            for item in items
        ]

        body = (
            f"Hello {order.user.first_name or 'there'},\n\n"
            f"Your Vestirhaus order {order.order_number} has been confirmed.\n\n"
            + "\n".join(item_lines)
            + "\n\n"
            f"Subtotal: NGN {order.subtotal / 100:,.2f}\n"
            f"Shipping: NGN {order.shipping_fee / 100:,.2f}\n"
            f"Discount: NGN {order.discount / 100:,.2f}\n"
            f"Total paid: NGN {order.total / 100:,.2f}\n\n"
            "Thank you for shopping with Vestirhaus."
        )

        try:
            sent = send_mail(
                subject=f"Vestirhaus order confirmed — {order.order_number}",
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[order.user.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception(
                "Unable to send confirmation email for order %s.",
                order.order_number,
            )
            return

        if sent:
            payment.confirmation_email_sent = True
            payment.save(
                update_fields=["confirmation_email_sent", "updated_at"]
            )


def update_refund_from_webhook(event_type, data):
    """Record Paystack refund lifecycle updates from signed webhooks."""

    reference = data.get("transaction_reference")
    if not reference:
        logger.error("Refund webhook did not include transaction_reference.")
        return

    with transaction.atomic():
        payment = (
            PaymentAttempt.objects.select_for_update()
            .filter(reference=reference)
            .first()
        )

        if payment is None:
            logger.error(
                "Refund event for unknown Vestirhaus reference: %s",
                reference,
            )
            return

        order = Order.objects.select_for_update().get(pk=payment.order_id)

        status_map = {
            "refund.pending": PaymentAttempt.RefundStatus.PENDING,
            "refund.processing": PaymentAttempt.RefundStatus.PROCESSING,
            "refund.needs-attention": PaymentAttempt.RefundStatus.NEEDS_ATTENTION,
            "refund.failed": PaymentAttempt.RefundStatus.FAILED,
            "refund.processed": PaymentAttempt.RefundStatus.PROCESSED,
        }

        refund_status = status_map.get(event_type)
        if refund_status is None:
            return

        if data.get("currency") and data["currency"] != payment.currency:
            logger.critical("Refund currency mismatch for %s.", reference)
            return

        if event_type == "refund.processed":
            try:
                refunded_amount = int(data.get("amount"))
            except (TypeError, ValueError):
                logger.critical("Invalid refunded amount for %s.", reference)
                return

            # This implementation supports full refunds only.
            if (
                payment.refund_amount != payment.amount
                or refunded_amount != payment.amount
            ):
                logger.critical(
                    "Refund amount mismatch for %s; manual reconciliation required.",
                    reference,
                )
                return

            payment.status = PaymentAttempt.Status.REFUNDED
            order.payment_status = Order.PaymentStatus.REFUNDED
            order.status = Order.Status.REFUNDED
            order.save(update_fields=["payment_status", "status", "updated_at"])

        payment.refund_status = refund_status
        payment.refund_reference = str(data.get("refund_reference") or "")
        payment.save(
            update_fields=[
                "status",
                "refund_status",
                "refund_reference",
                "updated_at",
            ]
        )


def request_order_refund(order_id, merchant_note="Vestirhaus order refund"):
    """Request a full Paystack refund, without assuming it has completed."""

    with transaction.atomic():
        order = Order.objects.select_for_update().filter(pk=order_id).first()

        if order is None:
            raise Order.DoesNotExist

        if order.payment_status != Order.PaymentStatus.PAID:
            raise ValidationError(
                {"order": "Only paid orders can be refunded."}
            )

        payment = (
            PaymentAttempt.objects.select_for_update()
            .filter(
                order=order,
                reference=order.paystack_reference,
                status=PaymentAttempt.Status.SUCCESS,
            )
            .first()
        )

        if payment is None:
            raise ValidationError(
                {"payment": "No successful Paystack payment was found."}
            )

        blocked_statuses = {
            PaymentAttempt.RefundStatus.REQUESTING,
            PaymentAttempt.RefundStatus.PENDING,
            PaymentAttempt.RefundStatus.PROCESSING,
            PaymentAttempt.RefundStatus.PROCESSED,
        }

        if payment.refund_status in blocked_statuses:
            raise PaymentConflict(
                "A refund has already been requested for this payment."
            )

        payment.refund_status = PaymentAttempt.RefundStatus.REQUESTING
        payment.refund_amount = payment.amount
        payment.save(
            update_fields=["refund_status", "refund_amount", "updated_at"]
        )

    try:
        gateway_data = initiate_full_refund(
            reference=payment.reference,
            merchant_note=merchant_note,
        )
    except PaystackTransportError:
        # The request may have reached Paystack. Do not automatically retry.
        logger.exception(
            "Refund result is ambiguous for payment %s.",
            payment.reference,
        )
        raise
    except PaystackAPIError:
        PaymentAttempt.objects.filter(
            pk=payment.pk,
            refund_status=PaymentAttempt.RefundStatus.REQUESTING,
        ).update(refund_status=PaymentAttempt.RefundStatus.FAILED)
        raise

    remote_status = str(gateway_data.get("status") or "pending").lower()

    status_map = {
        "pending": PaymentAttempt.RefundStatus.PENDING,
        "processing": PaymentAttempt.RefundStatus.PROCESSING,
        "needs-attention": PaymentAttempt.RefundStatus.NEEDS_ATTENTION,
        "processed": PaymentAttempt.RefundStatus.PROCESSED,
        "failed": PaymentAttempt.RefundStatus.FAILED,
    }

    PaymentAttempt.objects.filter(pk=payment.pk).update(
        refund_status=status_map.get(
            remote_status,
            PaymentAttempt.RefundStatus.PENDING,
        ),
        refund_reference=str(gateway_data.get("refund_reference") or ""),
        gateway_response={
            "refund_message": "Refund submitted to Paystack.",
        },
    )

    # Do not mark the order refunded merely because Paystack accepted the request.
    return PaymentAttempt.objects.get(pk=payment.pk)
