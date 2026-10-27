from datetime import date

from django.db import transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardResultsSetPagination
from products.models import ProductVariant
from users.permissions import IsPlatformAdmin, IsVerifiedUser

from .models import Cart, CartItem, Order
from .serializers import (
    AdminOrderUpdateSerializer,
    ApplyCouponSerializer,
    CartAddSerializer,
    CartQuantitySerializer,
    CartSummarySerializer,
    CheckoutSerializer,
    OrderSerializer,
)
from .services import (
    add_to_cart,
    apply_coupon_to_cart,
    cancel_order,
    checkout_user_cart,
    get_cart_summary,
)


class CartCSRFView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class CartView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(CartSummarySerializer(get_cart_summary(request)).data)

    def post(self, request):
        serializer = CartAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = add_to_cart(
            request,
            variant_id=serializer.validated_data["variant_id"],
            quantity=serializer.validated_data["quantity"],
        )

        return Response(
            CartSummarySerializer(result).data,
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class CartItemDetailView(APIView):
    permission_classes = [AllowAny]

    def put(self, request, item_id):
        serializer = CartQuantitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quantity = serializer.validated_data["quantity"]

        if request.user.is_authenticated:
            try:
                with transaction.atomic():
                    cart = Cart.objects.select_for_update().get(
                        user=request.user
                    )
                    item = CartItem.objects.select_for_update().get(
                        cart=cart,
                        pk=int(item_id),
                    )
                    variant = ProductVariant.objects.select_for_update().select_related(
                        "product__category"
                    ).get(pk=item.product_variant_id)

                    if (
                        not variant.product.is_active
                        or not variant.product.category.is_active
                    ):
                        raise ValidationError(
                            {"item": "This product is no longer available."}
                        )

                    if quantity > variant.stock_quantity:
                        raise ValidationError(
                            {"quantity": "Quantity exceeds available stock."}
                        )

                    item.quantity = quantity
                    item.save(update_fields=["quantity", "updated_at"])

            except (Cart.DoesNotExist, CartItem.DoesNotExist, ValueError,
                    ProductVariant.DoesNotExist):
                return Response(
                    {"detail": "Cart item not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        else:
            if not item_id.startswith("guest-"):
                return Response(
                    {"detail": "Guest cart item not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            try:
                variant_id = int(item_id.removeprefix("guest-"))
                cart_data = dict(request.session.get("vestirhaus_cart", {}))

                if str(variant_id) not in cart_data:
                    raise ValueError

                variant = ProductVariant.objects.select_related(
                    "product__category"
                ).get(pk=variant_id)

                if (
                    not variant.product.is_active
                    or not variant.product.category.is_active
                ):
                    raise ValidationError(
                        {"item": "This product is no longer available."}
                    )

                if quantity > variant.stock_quantity:
                    raise ValidationError(
                        {"quantity": "Quantity exceeds available stock."}
                    )

                cart_data[str(variant_id)] = quantity
                request.session["vestirhaus_cart"] = cart_data
                request.session.modified = True

            except (ValueError, ProductVariant.DoesNotExist):
                return Response(
                    {"detail": "Guest cart item not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        return Response(
            CartSummarySerializer(get_cart_summary(request)).data
        )

    def delete(self, request, item_id):
        if request.user.is_authenticated:
            try:
                with transaction.atomic():
                    cart = Cart.objects.select_for_update().get(
                        user=request.user
                    )
                    CartItem.objects.filter(
                        cart=cart,
                        pk=int(item_id),
                    ).delete()
            except (Cart.DoesNotExist, ValueError):
                return Response(
                    {"detail": "Cart item not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        else:
            if not item_id.startswith("guest-"):
                return Response(
                    {"detail": "Guest cart item not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            try:
                variant_id = int(item_id.removeprefix("guest-"))
            except ValueError:
                return Response(
                    {"detail": "Guest cart item not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            cart_data = dict(request.session.get("vestirhaus_cart", {}))
            cart_data.pop(str(variant_id), None)
            request.session["vestirhaus_cart"] = cart_data
            request.session.modified = True

        return Response(
            CartSummarySerializer(get_cart_summary(request)).data
        )


@method_decorator(csrf_protect, name="dispatch")
class ApplyCouponView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ApplyCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = apply_coupon_to_cart(
            request,
            serializer.validated_data["code"],
        )

        return Response(CartSummarySerializer(result).data)


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = checkout_user_cart(
            request.user,
            serializer.validated_data["shipping_address"],
        )

        return Response(
            OrderSerializer(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class OrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return (
            Order.objects.filter(user=self.request.user)
            .prefetch_related("items")
            .order_by("-created_at")
        )


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "order_id"

    def get_queryset(self):
        return (
            Order.objects.filter(user=self.request.user)
            .prefetch_related("items")
        )


class CancelOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        order = cancel_order(request.user, order_id)

        return Response(
            OrderSerializer(order, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


class AdminOrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsPlatformAdmin]
    serializer_class = OrderSerializer
    pagination_class = StandardResultsSetPagination
    http_method_names = ["get", "patch", "head", "options"]

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "payment_status"]
    search_fields = ["user__email", "coupon_code_snapshot"]
    ordering_fields = ["created_at", "total", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = (
            Order.objects.select_related("user")
            .prefetch_related("items")
        )

        created_from = self.request.query_params.get("created_from")
        created_to = self.request.query_params.get("created_to")

        for key, value in (
            ("created_from", created_from),
            ("created_to", created_to),
        ):
            if value:
                try:
                    parsed = date.fromisoformat(value)
                except ValueError:
                    raise ValidationError(
                        {key: "Use a valid date in YYYY-MM-DD format."}
                    )

                if key == "created_from":
                    queryset = queryset.filter(created_at__date__gte=parsed)
                else:
                    queryset = queryset.filter(created_at__date__lte=parsed)

        return queryset

    def get_serializer_class(self):
        if self.action in ("partial_update", "update"):
            return AdminOrderUpdateSerializer
        return OrderSerializer

    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()

        update_serializer = AdminOrderUpdateSerializer(
            order,
            data=request.data,
            partial=True,
        )
        update_serializer.is_valid(raise_exception=True)

        new_status = update_serializer.validated_data.get("status")

        if order.stock_restored and new_status != order.status:
            raise ValidationError(
                {"status": "A cancelled order cannot be reopened."}
            )

        if new_status == Order.Status.CANCELLED:
            order = cancel_order(order.user, order.pk)
            return Response(OrderSerializer(order).data)

        update_serializer.save()
        return Response(OrderSerializer(order).data)
    
    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()

        update_serializer = AdminOrderUpdateSerializer(
            order,
            data=request.data,
            partial=True,
        )
        update_serializer.is_valid(raise_exception=True)

        if "status" not in update_serializer.validated_data:
            raise ValidationError(
                {"status": "Provide the order status to update."}
            )

        new_status = update_serializer.validated_data["status"]

        if new_status == order.status:
            return Response(OrderSerializer(order).data)

        if order.stock_restored:
            raise ValidationError(
                {"status": "An order with restored stock cannot be reopened."}
            )

        allowed_transitions = {
            Order.Status.PENDING: {
                Order.Status.CONFIRMED,
                Order.Status.CANCELLED,
            },
            Order.Status.CONFIRMED: {
                Order.Status.PROCESSING,
                Order.Status.CANCELLED,
            },
            Order.Status.PROCESSING: {
                Order.Status.SHIPPED,
            },
            Order.Status.SHIPPED: {
                Order.Status.DELIVERED,
            },
            Order.Status.DELIVERED: set(),
            Order.Status.CANCELLED: set(),
            Order.Status.REFUNDED: set(),
        }

        if new_status not in allowed_transitions.get(order.status, set()):
            raise ValidationError(
                {
                    "status": (
                        f"Cannot change an order from '{order.status}' "
                        f"to '{new_status}'."
                    )
                }
            )

        if new_status in {
            Order.Status.CONFIRMED,
            Order.Status.PROCESSING,
            Order.Status.SHIPPED,
            Order.Status.DELIVERED,
        } and order.payment_status != Order.PaymentStatus.PAID:
            raise ValidationError(
                {"status": "The order must be paid before fulfilment proceeds."}
            )

        if new_status == Order.Status.CANCELLED:
            order = cancel_order(order.user, order.pk)
            return Response(OrderSerializer(order).data)

        update_serializer.save()
        return Response(OrderSerializer(order).data)

        search_fields = ("user__email", "coupon_code_snapshot")