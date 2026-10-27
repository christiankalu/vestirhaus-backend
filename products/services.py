
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Q


PAID_PAYMENT_STATUSES = {
    "paid",
    "success",
    "succeeded",
    "completed",
    "complete",
    "settled",
}

QUALIFYING_ORDER_STATUSES = {
    "paid",
    "processing",
    "shipped",
    "delivered",
    "completed",
    "complete",
    "fulfilled",
}

REJECTED_ORDER_STATUSES = {
    "pending",
    "cancelled",
    "canceled",
    "refunded",
    "failed",
}


def has_verified_purchase(user, product):
    """
    Return True only when a qualifying order item exists.

    Expected integration:
      orders.OrderItem -> order and (product or variant)
      orders.Order -> user and payment_status or status

    If these models/fields are not ready, fail closed.
    """
    if not user or not user.is_authenticated:
        return False

    try:
        order_item_model = apps.get_model("orders", "OrderItem")
        item_fields = {
            field.name: field
            for field in order_item_model._meta.get_fields()
        }

        if "order" not in item_fields:
            return False

        order_model = item_fields["order"].remote_field.model
        order_fields = {
            field.name: field
            for field in order_model._meta.get_fields()
        }

        if "user" not in order_fields:
            return False

        # Support either an order item's direct product FK or variant FK.
        product_filter = None

        if "product" in item_fields:
            product_field = item_fields["product"]
            related_model = getattr(
                product_field.remote_field,
                "model",
                None,
            )
            if (
                related_model
                and related_model._meta.label_lower == "products.product"
            ):
                product_filter = Q(product=product)

        if product_filter is None and "variant" in item_fields:
            variant_field = item_fields["variant"]
            variant_model = getattr(
                variant_field.remote_field,
                "model",
                None,
            )

            if (
                variant_model
                and variant_model._meta.label_lower
                == "products.productvariant"
            ):
                product_filter = Q(variant__product=product)

        if product_filter is None:
            return False

        queryset = order_item_model.objects.filter(
            product_filter,
            order__user=user,
        )

        if "payment_status" in order_fields:
            queryset = queryset.filter(
                order__payment_status__in=PAID_PAYMENT_STATUSES
            )

            # If the order has a status field, exclude known failed or
            # cancelled orders as an additional safety check.
            if "status" in order_fields:
                queryset = queryset.exclude(
                    order__status__in=REJECTED_ORDER_STATUSES
                )

        elif "status" in order_fields:
            queryset = queryset.filter(
                order__status__in=QUALIFYING_ORDER_STATUSES
            )

        else:
            return False

        return queryset.exists()

    except (LookupError, FieldDoesNotExist, AttributeError):
        # Until purchase records can be verified, reviews are not allowed.
        return False
