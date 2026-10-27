
import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from .models import PaystackWebhookEvent
from .views import PaystackWebhookView


@override_settings(PAYSTACK_SECRET_KEY="sk_test_vestirhaus_test_only")
class PaystackWebhookTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = PaystackWebhookView.as_view()

        self.payload = json.dumps(
            {
                "event": "charge.success",
                "data": {
                    "reference": "VH-TEST-REFERENCE-123",
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")

        self.signature = hmac.new(
            b"sk_test_vestirhaus_test_only",
            self.payload,
            hashlib.sha512,
        ).hexdigest()

    def make_request(self, signature=None):
        return self.factory.generic(
            "POST",
            "/api/payments/webhook/",
            self.payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=(
                signature if signature is not None else self.signature
            ),
        )

    def test_invalid_signature_is_rejected(self):
        response = self.view(self.make_request(signature="invalid"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PaystackWebhookEvent.objects.count(), 0)

    def test_duplicate_webhook_body_is_processed_once(self):
        with patch(
            "payments.views.verify_and_process_payment",
            return_value=(None, {"status": "success"}),
        ) as verify:
            first = self.view(self.make_request())
            second = self.view(self.make_request())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PaystackWebhookEvent.objects.count(), 1)
        verify.assert_called_once()

        event = PaystackWebhookEvent.objects.get()
        self.assertTrue(event.processed)
        self.assertEqual(event.event_type, "charge.success")
