import json
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from core.pagination import StandardResultsSetPagination
from products.models import Product
from orders.models import Order, Coupon
from orders.serializers import AdminOrderUpdateSerializer
from orders.views import AdminOrderViewSet as ExistingAdminOrderViewSet

from .models import RefundRecord
from .permissions import IsStaffAdmin
from .serializers import (
    AdminProductSerializer,
    AdminOrderSerializer,
)
from orders.serializers import CouponSerializer


User = get_user_model()


class AdminHealthView(APIView):
    permission_classes = [IsStaffAdmin]

    def get(self, request):
        return Response({
            "success": True,
            "message": "Vestirhaus Admin API is running.",
            "admin": {
                "email": request.user.email,
                "is_staff": request.user.is_staff,
            },
        })


class AdminDashboardView(APIView):
    permission_classes = [IsStaffAdmin]

    def get(self, request):
        today = timezone.localdate()
        start_date = today - timedelta(days=29)

        paid_orders = Order.objects.filter(
            payment_status=Order.PaymentStatus.PAID
        )

        total_revenue = paid_orders.aggregate(
            amount=Sum("total")
        )["amount"] or 0

        orders_today = Order.objects.filter(
            created_at__date=today
        ).count()

        new_users = User.objects.filter(
            date_joined__date__gte=start_date
        ).count()

        total_products = Product.objects.count()

        daily_revenue = (
            paid_orders
            .filter(created_at__date__gte=start_date)
            .values("created_at__date")
            .annotate(revenue=Sum("total"))
        )

        revenue_lookup = {
            row["created_at__date"]: row["revenue"]
            for row in daily_revenue
        }

        revenue_series = []

        for day_number in range(30):
            date_value = start_date + timedelta(days=day_number)

            revenue_series.append({
                "date": date_value.isoformat(),
                "revenue": revenue_lookup.get(date_value, 0) or 0,
            })

        recent_orders = (
            Order.objects
            .select_related("user")
            .prefetch_related("items")
            .order_by("-created_at")[:8]
        )

        recent_data = AdminOrderSerializer(
            recent_orders,
            many=True,
            context={"request": request},
        ).data

        return Response({
            "stats": {
                "total_revenue_kobo": total_revenue,
                "orders_today": orders_today,
                "total_products": total_products,
                "new_users": new_users,
            },
            "revenue_last_30_days": revenue_series,
            "recent_orders": recent_data,
        })


class AdminProductViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStaffAdmin]
    serializer_class = AdminProductSerializer
    pagination_class = StandardResultsSetPagination

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_fields = [
        "audience",
        "is_active",
        "is_featured",
        "category__slug",
    ]

    search_fields = [
        "name",
        "slug",
        "brand",
        "description",
    ]

    ordering_fields = [
        "created_at",
        "base_price",
        "name",
    ]

    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Product.objects
            .select_related("category")
            .prefetch_related("images", "variants")
            .all()
        )

    def perform_destroy(self, instance):
        # Preserve order-item references and historical records.
        instance.is_active = False
        instance.save(update_fields=["is_active"])


class AdminOrderViewSet(ExistingAdminOrderViewSet):
    """
    Reuse the existing order state-transition logic,
    but protect the route with the new admin staff permission.
    """

    permission_classes = [IsStaffAdmin]
    serializer_class = AdminOrderSerializer

    def get_serializer_class(self):
        if self.action in ("partial_update", "update"):
            return AdminOrderUpdateSerializer

        return AdminOrderSerializer

    @action(
        detail=True,
        methods=["post"],
        url_path="refund",
    )
    def refund(self, request, pk=None):
        order = self.get_object()

        if order.payment_status != Order.PaymentStatus.PAID:
            raise ValidationError({
                "detail": "Only paid orders can be refunded."
            })

        if not order.paystack_reference:
            raise ValidationError({
                "detail": "This order has no Paystack reference."
            })

        existing = RefundRecord.objects.filter(
            order=order
        ).first()

        if existing and existing.status != "failed":
            return Response(
                {
                    "detail": "A refund has already been requested for this order.",
                    "refund_status": existing.status,
                    "refund_id": existing.paystack_refund_id,
                },
                status=status.HTTP_409_CONFLICT,
            )

        secret_key = getattr(settings, "PAYSTACK_SECRET_KEY", "")

        if not secret_key:
            raise APIException(
                "Paystack secret key is not configured."
            )

        reason = str(
            request.data.get("reason", "")
        ).strip()

        payload = {
            "transaction": order.paystack_reference,
            "merchant_note": (
                reason or f"Vestirhaus admin refund for order {order.order_number}"
            ),
            "customer_note": (
                reason or "Refund requested by the merchant."
            ),
        }

        paystack_request = urllib.request.Request(
            "https://api.paystack.co/refund",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                paystack_request,
                timeout=30,
            ) as response:
                gateway = json.loads(
                    response.read().decode("utf-8")
                )

        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")

            raise APIException({
                "detail": "Paystack rejected the refund request.",
                "gateway_response": detail,
            })

        except (urllib.error.URLError, TimeoutError):
            raise APIException(
                "Could not reach Paystack. Check the payment connection."
            )

        if not gateway.get("status"):
            raise APIException(
                gateway.get("message", "Paystack refund failed.")
            )

        refund_data = gateway.get("data") or {}

        refund_status = refund_data.get("status", "pending")
        refund_id = str(refund_data.get("id", ""))

        with transaction.atomic():
            record, created = RefundRecord.objects.update_or_create(
                order=order,
                defaults={
                    "requested_by": request.user,
                    "paystack_refund_id": refund_id,
                    "amount": order.total,
                    "status": refund_status,
                    "reason": reason,
                    "gateway_response": gateway,
                },
            )

        return Response({
            "success": True,
            "message": gateway.get(
                "message",
                "Refund request submitted to Paystack.",
            ),
            "refund_id": record.paystack_refund_id,
            "refund_status": record.status,
            "amount": record.amount,
        })


class AdminCustomerListView(ListAPIView):
    permission_classes = [IsStaffAdmin]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = User.objects.all().order_by("-date_joined")

        search = self.request.query_params.get("search", "").strip()

        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)

        if page is None:
            page = queryset

        results = []

        for customer in page:
            customer_orders = Order.objects.filter(
                user=customer
            )

            order_count = customer_orders.count()

            total_spend = customer_orders.filter(
                payment_status=Order.PaymentStatus.PAID
            ).aggregate(
                amount=Sum("total")
            )["amount"] or 0

            results.append({
                "id": customer.pk,
                "first_name": customer.first_name,
                "last_name": customer.last_name,
                "email": customer.email,
                "phone": customer.phone_number,
                "date_joined": customer.date_joined,
                "order_count": order_count,
                "total_spend": total_spend,
            })

        return self.get_paginated_response(results)


class AdminCouponViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStaffAdmin]
    serializer_class = CouponSerializer
    pagination_class = StandardResultsSetPagination

    filter_backends = [
        SearchFilter,
        OrderingFilter,
    ]

    search_fields = ["code"]
    ordering_fields = ["created_at", "code", "expiry_date"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Coupon.objects.all()