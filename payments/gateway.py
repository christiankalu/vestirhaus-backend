
import logging

import requests
from django.conf import settings


logger = logging.getLogger(__name__)

PAYSTACK_API_BASE = "https://api.paystack.co"


class PaystackError(Exception):
    """Base exception for Paystack integration errors."""


class PaystackTransportError(PaystackError):
    """Network errors or timeout with an ambiguous gateway outcome."""


class PaystackAPIError(PaystackError):
    """Paystack returned a definitive error response."""


def paystack_request(method, path, payload=None):
    """Make an authenticated, bounded-time request to Paystack."""

    secret_key = settings.PAYSTACK_SECRET_KEY

    if not secret_key:
        raise PaystackError("PAYSTACK_SECRET_KEY is not configured.")

    try:
        response = requests.request(
            method=method,
            url=f"{PAYSTACK_API_BASE}{path}",
            headers={
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=(5, 20),
        )
    except requests.RequestException as exc:
        logger.warning("Paystack transport failure: %s", exc.__class__.__name__)
        raise PaystackTransportError(
            "Unable to reach Paystack. Check the transaction status before retrying."
        ) from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise PaystackAPIError(
            "Paystack returned an invalid response."
        ) from exc

    if not response.ok or body.get("status") is not True:
        message = body.get("message", "Paystack request failed.")
        raise PaystackAPIError(message)

    return body.get("data", {})


def initialize_transaction(
    *,
    email,
    amount,
    reference,
    callback_url,
    metadata,
):
    """Initialize a Paystack transaction from the backend."""

    return paystack_request(
        "POST",
        "/transaction/initialize",
        {
            "email": email,
            "amount": str(amount),
            "currency": "NGN",
            "reference": reference,
            "callback_url": callback_url,
            "metadata": metadata,
        },
    )


def verify_transaction(reference):
    """Fetch the authoritative state of a transaction by reference."""

    from urllib.parse import quote

    safe_reference = quote(reference, safe="")
    return paystack_request(
        "GET",
        f"/transaction/verify/{safe_reference}",
    )


def initiate_full_refund(*, reference, merchant_note):
    """Initiate a full refund; final status comes from later notification."""

    return paystack_request(
        "POST",
        "/refund",
        {
            "transaction": reference,
            "merchant_note": merchant_note,
        },
    )
