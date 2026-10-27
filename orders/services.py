from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from products.models import ProductVariant

from .models import Cart, CartItem, Coupon, Order, OrderItem


SESSION_CART_KEY = "vestirhaus_cart"
SESSION_COUPON_KEY = "vestirhaus_coupon"
MAX_CART_QUANTITY = 99


def get_or_create_cart(user):
    return Cart.objects.get_or_create(user=user)


def get_active_variant(variant_id, lock=False):
    queryset = ProductVariant.objects.select_related(
        "product",
        "product__category",
    )

    if lock:
        queryset = queryset.select_for_update()

    try:
        variant = queryset.get(pk=variant_id)
    except (ProductVariant.DoesNotExist, ValueError, TypeError):
        raise ValidationError(
            {"product_variant": "This product variant does not exist."}
        )

    if not variant.product.is_active or not variant.product.category.is_active:
        raise ValidationError(
            {"product_variant": "This product is not currently available."}
        )

    return variant


def add_to_cart(request, variant_id, quantity):
    """Add quantity to the current customer's DB cart or guest session."""
    if not 1 <= quantity <= MAX_CART_QUANTITY:
        raise ValidationError(
            {"quantity": f"Quantity must be between 1 and {MAX_CART_QUANTITY}."}
        )

    user = request.user

    if user.is_authenticated:
        with transaction.atomic():
            cart, _ = Cart.objects.get_or_create(user=user)
            cart = Cart.objects.select_for_update().get(pk=cart.pk)

            variant = get_active_variant(variant_id, lock=True)

            item = CartItem.objects.select_for_update().filter(
                cart=cart,
                product_variant=variant,
            ).first()

            new_quantity = quantity + (item.quantity if item else 0)

            if new_quantity > MAX_CART_QUANTITY:
                raise ValidationError(
                    {"quantity": "The maximum quantity per variant is 99."}
                )

            if new_quantity > variant.stock_quantity:
                raise ValidationError(
                    {"quantity": "The requested quantity exceeds available stock."}
                )

            if item:
                item.quantity = new_quantity
                item.save(update_fields=["quantity", "updated_at"])
            else:
                CartItem.objects.create(
                    cart=cart,
                    product_variant=variant,
                    quantity=new_quantity,
                )

        return get_cart_summary(request)

    # Guest cart: mapping of variant ID to quantity, stored in the session.
    with transaction.atomic():
        variant = get_active_variant(variant_id, lock=True)

        cart_data = dict(request.session.get(SESSION_CART_KEY, {}))
        key = str(variant.pk)
        new_quantity = int(cart_data.get(key, 0)) + quantity

        if new_quantity > MAX_CART_QUANTITY:
            raise ValidationError(
                {"quantity": "The maximum quantity per variant is 99."}
            )

        if new_quantity > variant.stock_quantity:
            raise ValidationError(
                {"quantity": "The requested quantity exceeds available stock."}
            )

        cart_data[key] = new_quantity
        request.session[SESSION_CART_KEY] = cart_data
        request.session.modified = True

    return get_cart_summary(request)


def _primary_image_url(product):
    image = next(
        (item for item in product.images.all() if item.is_primary),
        None,
    )

    if image is None:
        image = next(iter(product.images.all()), None)

    if image is None or not image.image:
        return None

    try:
        return image.image.url
    except (ValueError, OSError):
        return None


def get_cart_lines(request):
    """Return a normalized cart representation for either cart backend."""
    user = request.user
    lines = []

    if user.is_authenticated:
        cart = Cart.objects.filter(user=user).first()
        if cart is None:
            return []

        items = CartItem.objects.filter(cart=cart).select_related(
            "product_variant__product__category"
        ).prefetch_related(
            "product_variant__product__images"
        ).order_by("id")

        for item in items:
            variant = item.product_variant
            product = variant.product
            price = variant.current_price

            available = (
                product.is_active
                and product.category.is_active
                and variant.stock_quantity >= item.quantity
            )

            lines.append({
                "id": str(item.pk),
                "product_variant": {
                    "id": variant.pk,
                    "sku": variant.sku,
                    "size": variant.size,
                    "color": variant.color,
                    "color_hex_code": variant.color_hex_code,
                },
                "product_name": product.name,
                "product_slug": product.slug,
                "image_url": _primary_image_url(product),
                "quantity": item.quantity,
                "unit_price": price,
                "total_price": price * item.quantity,
                "stock_quantity": variant.stock_quantity,
                "available": available,
            })

        return lines

    cart_data = request.session.get(SESSION_CART_KEY, {})
    variant_ids = []

    for key, quantity in cart_data.items():
        try:
            variant_id = int(key)
            quantity = int(quantity)
            if quantity > 0:
                variant_ids.append(variant_id)
        except (ValueError, TypeError):
            continue

    variants = ProductVariant.objects.filter(
        pk__in=variant_ids,
    ).select_related(
        "product__category"
    ).prefetch_related(
        "product__images"
    )

    found_ids = set()

    for variant in variants:
        key = str(variant.pk)
        found_ids.add(key)
        quantity = int(cart_data.get(key, 0))
        product = variant.product
        price = variant.current_price

        available = (
            product.is_active
            and product.category.is_active
            and variant.stock_quantity >= quantity
        )

        lines.append({
            "id": f"guest-{variant.pk}",
            "product_variant": {
                "id": variant.pk,
                "sku": variant.sku,
                "size": variant.size,
                "color": variant.color,
                "color_hex_code": variant.color_hex_code,
            },
            "product_name": product.name,
            "product_slug": product.slug,
            "image_url": _primary_image_url(product),
            "quantity": quantity,
            "unit_price": price,
            "total_price": price * quantity,
            "stock_quantity": variant.stock_quantity,
            "available": available,
        })

    # Remove malformed or deleted variants from the guest session.
    cleaned = {
        key: quantity
        for key, quantity in cart_data.items()
        if str(key) in found_ids
    }

    if cleaned != cart_data:
        request.session[SESSION_CART_KEY] = cleaned
        request.session.modified = True

    return lines


def calculate_subtotal(lines):
    return sum(line["total_price"] for line in lines)


def get_applied_coupon(request):
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).select_related(
            "coupon"
        ).first()
        return cart.coupon if cart else None

    code = request.session.get(SESSION_COUPON_KEY)

    if not code:
        return None

    return Coupon.objects.filter(code=code.upper()).first()


def get_cart_summary(request):
    lines = get_cart_lines(request)
    subtotal = calculate_subtotal(lines)
    coupon = get_applied_coupon(request)

    discount = 0
    coupon_code = None
    coupon_error = None

    if coupon:
        coupon_code = coupon.code

        if coupon.is_available(subtotal):
            discount = coupon.calculate_discount(subtotal)
        else:
            coupon_error = (
                "This coupon is no longer available or its requirements "
                "are no longer satisfied."
            )

    shipping_fee = settings.CHECKOUT_SHIPPING_FEE_KOBO
    total = max(subtotal - discount, 0) + shipping_fee

    return {
        "items": lines,
        "subtotal": subtotal,
        "discount": discount,
        "shipping_fee": shipping_fee,
        "total": total,
        "coupon_code": coupon_code,
        "coupon_error": coupon_error,
    }


def apply_coupon_to_cart(request, code):
    """Validate a coupon against the current cart and attach it."""
    normalized_code = code.strip().upper()

    lines = get_cart_lines(request)
    subtotal = calculate_subtotal(lines)

    if not lines:
        raise ValidationError(
            {"cart": "Add at least one item before applying a coupon."}
        )

    try:
        coupon = Coupon.objects.get(code=normalized_code)
    except Coupon.DoesNotExist:
        raise ValidationError({"code": "This coupon is invalid."})

    if not coupon.is_available(subtotal):
        raise ValidationError(
            {
                "code": (
                    "This coupon is expired, inactive, fully used, "
                    "or does not meet the minimum order value."
                )
            }
        )

    if request.user.is_authenticated:
        cart, _ = get_or_create_cart(request.user)
        cart.coupon = coupon
        cart.save(update_fields=["coupon", "updated_at"])
    else:
        request.session[SESSION_COUPON_KEY] = coupon.code
        request.session.modified = True

    return get_cart_summary(request)


def merge_guest_cart_into_user(request, user):
    """Merge the guest session cart into the authenticated user's cart."""
    if not user or not user.is_authenticated:
        return

    guest_data = request.session.get(SESSION_CART_KEY, {})
    guest_coupon_code = request.session.get(SESSION_COUPON_KEY)

    if not guest_data and not guest_coupon_code:
        return

    with transaction.atomic():
        cart, _ = Cart.objects.get_or_create(user=user)
        cart = Cart.objects.select_for_update().get(pk=cart.pk)

        parsed_items = {}

        for variant_id, quantity in guest_data.items():
            try:
                parsed_items[int(variant_id)] = int(quantity)
            except (ValueError, TypeError):
                continue

        variant_ids = sorted(parsed_items.keys())

        variants = ProductVariant.objects.select_for_update().select_related(
            "product__category"
        ).filter(
            pk__in=variant_ids
        ).order_by("pk")

        for variant in variants:
            product = variant.product
            guest_quantity = parsed_items[variant.pk]

            # Do not merge deleted, inactive, or unavailable products.
            if (
                not product.is_active
                or not product.category.is_active
                or variant.stock_quantity < 1
                or guest_quantity < 1
            ):
                continue

            item = CartItem.objects.select_for_update().filter(
                cart=cart,
                product_variant=variant,
            ).first()

            old_quantity = item.quantity if item else 0
            merged_quantity = min(
                old_quantity + guest_quantity,
                variant.stock_quantity,
                MAX_CART_QUANTITY,
            )

            if merged_quantity < 1:
                continue

            if item:
                item.quantity = merged_quantity
                item.save(update_fields=["quantity", "updated_at"])
            else:
                CartItem.objects.create(
                    cart=cart,
                    product_variant=variant,
                    quantity=merged_quantity,
                )

        # Preserve the customer's existing coupon, unless none is set.
        if guest_coupon_code and not cart.coupon_id:
            coupon = Coupon.objects.filter(
                code=guest_coupon_code.upper()
            ).first()

            if coupon:
                subtotal = sum(
                    item.product_variant.current_price * item.quantity
                    for item in CartItem.objects.filter(
                        cart=cart
                    ).select_related("product_variant__product")
                )

                if coupon.is_available(subtotal):
                    cart.coupon = coupon

        cart.save(update_fields=["coupon", "updated_at"])

    # Clear session data only after the DB transaction succeeds.
    request.session.pop(SESSION_CART_KEY, None)
    request.session.pop(SESSION_COUPON_KEY, None)
    request.session.modified = True
    
    
def checkout_user_cart(user, shipping_address):
    """Create an order and reserve stock atomically."""
    with transaction.atomic():
        cart = Cart.objects.filter(user=user).first()

        if cart is None:
            raise ValidationError({"cart": "Your cart is empty."})

        cart = Cart.objects.select_for_update().get(pk=cart.pk)

        cart_items = list(
            CartItem.objects.select_for_update().filter(
                cart=cart
            ).order_by("product_variant_id")
        )

        if not cart_items:
            raise ValidationError({"cart": "Your cart is empty."})

        variant_ids = sorted({
            item.product_variant_id for item in cart_items
        })

        variants = list(
            ProductVariant.objects.select_for_update().select_related(
                "product__category"
            ).filter(
                pk__in=variant_ids
            ).order_by("pk")
        )
        variant_by_id = {variant.pk: variant for variant in variants}

        # Validate every line and its available stock before making changes.
        for item in cart_items:
            variant = variant_by_id.get(item.product_variant_id)

            if variant is None:
                raise ValidationError(
                    {"cart": "A product variant no longer exists."}
                )

            if (
                not variant.product.is_active
                or not variant.product.category.is_active
            ):
                raise ValidationError(
                    {
                        "cart": (
                            f"{variant.product.name} is no longer available. "
                            "Remove it from your cart and try again."
                        )
                    }
                )

            if item.quantity > variant.stock_quantity:
                raise ValidationError(
                    {
                        "cart": (
                            f"Not enough stock for {variant.product.name}. "
                            f"Available: {variant.stock_quantity}."
                        )
                    }
                )

        subtotal = sum(
            variant_by_id[item.product_variant_id].current_price
            * item.quantity
            for item in cart_items
        )

        coupon = None
        discount = 0

        if cart.coupon_id:
            coupon = Coupon.objects.select_for_update().get(
                pk=cart.coupon_id
            )

            if not coupon.is_available(subtotal):
                raise ValidationError(
                    {
                        "coupon": (
                            "Your cart coupon is no longer valid. "
                            "Remove it or apply another coupon."
                        )
                    }
                )

            discount = coupon.calculate_discount(subtotal)

        shipping_fee = settings.CHECKOUT_SHIPPING_FEE_KOBO

        if shipping_fee < 0:
            raise ValidationError(
                {"shipping_fee": "The configured shipping fee is invalid."}
            )

        total = subtotal - discount + shipping_fee

        order = Order.objects.create(
            user=user,
            status=Order.Status.PENDING,
            payment_status=Order.PaymentStatus.PENDING,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            discount=discount,
            total=total,
            shipping_address=shipping_address,
            coupon=coupon,
            coupon_code_snapshot=coupon.code if coupon else "",
            coupon_use_reserved=bool(coupon),
        )

        # Reserve stock only after every item has passed validation.
        for item in cart_items:
            variant = variant_by_id[item.product_variant_id]
            quantity = item.quantity
            unit_price = variant.current_price

            variant.stock_quantity -= quantity
            variant.save(
                update_fields=["stock_quantity", "updated_at"]
            )

            OrderItem.objects.create(
                order=order,
                product_variant=variant,
                quantity=quantity,
                unit_price=unit_price,
                total_price=unit_price * quantity,
                product_name=variant.product.name,
                variant_sku=variant.sku,
                size=variant.size,
                color=variant.color,
            )

        # Count a coupon use when the checkout reservation succeeds.
        # Cancellation releases the count if the reservation is cancelled.
        if coupon:
            coupon.used_count += 1
            coupon.save(update_fields=["used_count"])

        cart_items_to_delete = CartItem.objects.filter(cart=cart)
        cart_items_to_delete.delete()

        cart.coupon = None
        cart.save(update_fields=["coupon", "updated_at"])

        return order
    
    
def cancel_order(user, order_id):
    """Cancel an unpaid order and restore its reserved stock once."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(
            pk=order_id,
            user=user,
        ).first()

        if order is None:
            # Do not reveal whether another customer's order exists.
            raise ValidationError({"order": "Order not found."})

        if order.stock_restored:
            if order.status == Order.Status.CANCELLED:
                return order

            raise ValidationError(
                {"order": "Stock was already restored for this order."}
            )

        if order.payment_status == Order.PaymentStatus.PAID:
            raise ValidationError(
                {
                    "order": (
                        "This order has been paid. Use the refund process "
                        "before cancelling it."
                    )
                }
            )

        allowed_statuses = {
            Order.Status.PENDING,
            Order.Status.CONFIRMED,
        }

        if order.status not in allowed_statuses:
            raise ValidationError(
                {"order": "This order can no longer be cancelled."}
            )

        order_items = list(
            OrderItem.objects.select_for_update().filter(
                order=order
            ).order_by("product_variant_id")
        )

        variant_ids = sorted({
            item.product_variant_id for item in order_items
        })

        variants = {
            variant.pk: variant
            for variant in ProductVariant.objects.select_for_update().filter(
                pk__in=variant_ids
            ).order_by("pk")
        }

        # Restore stock once for every order line.
        for item in order_items:
            variant = variants.get(item.product_variant_id)

            if variant is None:
                # Normally impossible because OrderItem protects variants.
                raise ValidationError(
                    {"order": "Cannot restore stock for a missing variant."}
                )

            variant.stock_quantity += item.quantity
            variant.save(
                update_fields=["stock_quantity", "updated_at"]
            )

        if order.coupon_use_reserved and order.coupon_id:
            coupon = Coupon.objects.select_for_update().get(
                pk=order.coupon_id
            )
            coupon.used_count = max(0, coupon.used_count - 1)
            coupon.save(update_fields=["used_count"])
            order.coupon_use_reserved = False

        order.status = Order.Status.CANCELLED
        order.stock_restored = True
        order.save(
            update_fields=[
                "status",
                "stock_restored",
                "coupon_use_reserved",
                "updated_at",
            ]
        )

        return order