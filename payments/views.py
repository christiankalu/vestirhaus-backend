
import hashlib
import hmac
import json
import logging
from datetime import timezone as datetime_timezone

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.models import Order
from users.permissions import IsPlatformAdmin, IsVerifiedUser

from .gateway import (
    PaystackAPIError,
    PaystackError,
    PaystackTransportError,
)
from .models import PaymentAttempt, PaystackWebhookEvent
from .serializers import (
    InitializePaymentSerializer,
    RefundRequestSerializer,
)
from .services import (
    PaymentConflict,
    PaymentIntegrityError,
    initialize_order_payment,
    request_order_refund,
    update_refund_from_webhook,
    verify_and_process_payment,
)


logger = logging.getLogger(__name__)


class InitializePaymentView(APIView):
    """Initialize a Paystack transaction for an owned order."""

    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def post(self, request):
        serializer = InitializePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payment, created = initialize_order_payment(
                user=request.user,
                order_id=serializer.validated_data["order_id"],
            )
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PaymentConflict as exc:
            return Response(
                {"detail": str(exc.detail)},
                status=status.HTTP_409_CONFLICT,
            )
        except PaystackTransportError:
            return Response(
                {
                    "detail": (
                        "Could not confirm Paystack initialization. "
                        "Check payment status before retrying."
                    )
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except PaystackError:
            logger.exception("Paystack initialization error.")
            return Response(
                {"detail": "Paystack could not initialize this payment."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "authorization_url": payment.authorization_url,
                "reference": payment.reference,
                "amount": payment.amount,
                "currency": payment.currency,
                "status": payment.status,
                "reused_existing_attempt": not created,
            },
            status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED,
        )


class VerifyPaymentView(APIView):
    """Manually verify a transaction after the checkout redirect."""

    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def get(self, request, reference):
        try:
            payment, gateway_data = verify_and_process_payment(
                reference=reference,
                user=request.user,
            )
        except PaymentAttempt.DoesNotExist:
            return Response(
                {"detail": "Payment reference not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PaymentIntegrityError:
            logger.critical(
                "Payment verification integrity error for %s.",
                reference,
                exc_info=True,
            )
            return Response(
                {
                    "detail": (
                        "Payment details do not match this order. "
                        "Contact support before retrying."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        except PaystackTransportError:
            return Response(
                {
                    "detail": (
                        "Could not reach Paystack to verify this payment. "
                        "Retry verification later."
                    )
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except PaystackError:
            logger.exception("Paystack verification failed for %s.", reference)
            return Response(
                {"detail": "Unable to verify the payment at this time."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payment.refresh_from_db()
        payment.order.refresh_from_db()

        verified = (
            payment.status == PaymentAttempt.Status.SUCCESS
            and payment.order.payment_status == Order.PaymentStatus.PAID
            and payment.order.paystack_reference == payment.reference
        )

        return Response(
            {
                "reference": payment.reference,
                "verified": verified,
                "gateway_status": gateway_data.get("status"),
                "payment_status": payment.status,
                "order_status": payment.order.status,
                "order_payment_status": payment.order.payment_status,
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name="dispatch")
class PaystackWebhookView(APIView):
    """
    Receive signed Paystack events.

    This endpoint intentionally has no session/JWT authentication. Paystack
    authenticates events using the HMAC-SHA512 signature of the raw body.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        secret = settings.PAYSTACK_SECRET_KEY

        if not secret:
            logger.error("Paystack webhook received without a configured secret.")
            return Response(
                {"detail": "Webhook verification is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        raw_body = request._request.body
        received_signature = request.headers.get("x-paystack-signature", "")

        expected_signature = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        if not received_signature or not hmac.compare_digest(
            expected_signature,
            received_signature,
        ):
            logger.warning("Rejected Paystack webhook with invalid signature.")
            return Response(
                {"detail": "Invalid webhook signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(
                {"detail": "Invalid JSON payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(payload, dict):
            return Response(
                {"detail": "Invalid webhook payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_type = str(payload.get("event", ""))
        data = payload.get("data") or {}

        if not isinstance(data, dict):
            return Response(
                {"detail": "Invalid webhook data."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reference = str(
            data.get("reference")
            or data.get("transaction_reference")
            or ""
        )

        event_hash = hashlib.sha256(raw_body).hexdigest()

        try:
            event, _ = PaystackWebhookEvent.objects.get_or_create(
                event_hash=event_hash,
                defaults={
                    "event_type": event_type,
                    "reference": reference,
                },
            )
        except IntegrityError:
            event = PaystackWebhookEvent.objects.get(event_hash=event_hash)

        if event.processed:
            return Response({"status": "ok", "duplicate": True})

        try:
            if event_type == "charge.success":
                if not reference:
                    raise PaymentIntegrityError(
                        "Successful charge event has no reference."
                    )

                try:
                    payment, gateway_data = verify_and_process_payment(
                        reference=reference
                    )
                except PaymentAttempt.DoesNotExist:
                    logger.critical(
                        "Signed Paystack event has unknown reference %s.",
                        reference,
                    )
                    event.processed = True
                    event.last_error = "Unknown payment reference."
                    event.processed_at = timezone.now()
                    event.save(
                        update_fields=[
                            "processed",
                            "last_error",
                            "processed_at",
                        ]
                    )
                    return Response({"status": "ok"})

                if gateway_data.get("status") != "success":
                    # The signed event and verify API disagree. Record it for
                    # investigation instead of fulfilling the order.
                    logger.critical(
                        "Paystack webhook/verify mismatch for %s.",
                        reference,
                    )
                    event.processed = True
                    event.last_error = "Verify API did not report success."
                    event.processed_at = timezone.now()
                    event.save(
                        update_fields=[
                            "processed",
                            "last_error",
                            "processed_at",
                        ]
                    )
                    return Response({"status": "ok"})

            elif event_type in {
                "refund.pending",
                "refund.processing",
                "refund.needs-attention",
                "refund.failed",
                "refund.processed",
            }:
                update_refund_from_webhook(event_type, data)

            # Unknown valid Paystack event types are acknowledged and ignored.
            event.processed = True
            event.last_error = ""
            event.processed_at = timezone.now()
            event.save(
                update_fields=[
                    "processed",
                    "last_error",
                    "processed_at",
                ]
            )

            return Response({"status": "ok"})

        except (PaystackTransportError, PaystackAPIError) as exc:
            # Leave processed=False so Paystack's retry can be useful.
            event.last_error = str(exc)[:500]
            event.save(update_fields=["last_error"])
            logger.warning(
                "Transient webhook processing failure for %s.",
                reference,
                exc_info=True,
            )
            return Response(
                {"detail": "Temporary payment verification failure."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PaymentIntegrityError as exc:
            logger.critical(
                "Webhook integrity failure for %s: %s",
                reference,
                exc,
                exc_info=True,
            )
            event.processed = True
            event.last_error = str(exc)[:500]
            event.processed_at = timezone.now()
            event.save(
                update_fields=["processed", "last_error", "processed_at"]
            )
            return Response({"status": "ok"})

        except Exception as exc:
            event.last_error = str(exc)[:500]
            event.save(update_fields=["last_error"])
            logger.exception(
                "Unexpected error processing Paystack webhook %s.",
                reference,
            )
            return Response(
                {"detail": "Webhook processing failed."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RefundPaymentView(APIView):
    """Admin-only full refund request."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request, order_id):
        serializer = RefundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payment = request_order_refund(
                order_id=order_id,
                merchant_note=serializer.validated_data["merchant_note"],
            )
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PaymentConflict as exc:
            return Response(
                {"detail": str(exc.detail)},
                status=status.HTTP_409_CONFLICT,
            )
        except PaystackTransportError:
            return Response(
                {
                    "detail": (
                        "The refund result is unresolved. Do not resubmit. "
                        "Check the Paystack Dashboard and refund webhooks."
                    ),
                    "refund_status": PaymentAttempt.RefundStatus.REQUESTING,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except PaystackAPIError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except PaystackError:
            logger.exception("Paystack refund request failed.")
            return Response(
                {"detail": "Unable to submit refund to Paystack."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "order_id": payment.order_id,
                "reference": payment.reference,
                "refund_reference": payment.refund_reference,
                "refund_amount": payment.refund_amount,
                "currency": payment.currency,
                "refund_status": payment.refund_status,
                "message": (
                    "Refund request submitted. Final status will be updated "
                    "when Paystack sends a refund webhook."
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )
