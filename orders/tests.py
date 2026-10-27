from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError

from products.models import Category, Product, ProductVariant
from users.models import User

from .models import Cart, CartItem, Coupon, Order, OrderItem
from .services import cancel_order, checkout_user_cart


@override_settings(CHECKOUT_SHIPPING_FEE_KOBO=0)
class CheckoutServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="customer@example.com",
            password="A-Strong-Test-Password-123!",
            is_verified=True,
        )

        self.category = Category.objects.create(
            name="Test Clothing",
            slug="test-clothing",
            is_active=True,
        )

        self.product = Product.objects.create(
            name="Test Shirt",
            slug="test-shirt",
            category=self.category,
            audience=Product.Audience.UNISEX,
            base_price=10000,
            is_active=True,
        )

        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=ProductVariant.Size.M,
            color="Black",
            stock_quantity=10,
        )

        self.cart = Cart.objects.create(user=self.user)
        self.cart_item = CartItem.objects.create(
            cart=self.cart,
            product_variant=self.variant,
            quantity=2,
        )

    def test_checkout_reserves_stock_and_snapshots_price(self):
        order = checkout_user_cart(
            self.user,
            {
                "recipient_name": "Test Customer",
                "phone_number": "+2348012345678",
                "address_line_1": "1 Test Street",
                "address_line_2": "",
                "city": "Lagos",
                "state": "Lagos",
                "postal_code": "",
                "country": "Nigeria",
            },
        )

        self.variant.refresh_from_db()

        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PENDING)
        self.assertEqual(order.subtotal, 20000)
        self.assertEqual(order.total, 20000)
        self.assertEqual(self.variant.stock_quantity, 8)
        self.assertEqual(order.items.count(), 1)

        item = order.items.get()
        self.assertEqual(item.unit_price, 10000)
        self.assertEqual(item.total_price, 20000)

        self.assertFalse(CartItem.objects.filter(cart=self.cart).exists())

    def test_insufficient_stock_does_not_create_order(self):
        self.variant.stock_quantity = 1
        self.variant.save(update_fields=["stock_quantity", "updated_at"])

        with self.assertRaises(ValidationError):
            checkout_user_cart(
                self.user,
                {
                    "recipient_name": "Test Customer",
                    "phone_number": "+2348012345678",
                    "address_line_1": "1 Test Street",
                    "city": "Lagos",
                    "state": "Lagos",
                    "country": "Nigeria",
                },
            )

        self.variant.refresh_from_db()

        self.assertEqual(self.variant.stock_quantity, 1)
        self.assertFalse(Order.objects.filter(user=self.user).exists())

    def test_cancellation_restores_stock_once(self):
        order = checkout_user_cart(
            self.user,
            {
                "recipient_name": "Test Customer",
                "phone_number": "+2348012345678",
                "address_line_1": "1 Test Street",
                "city": "Lagos",
                "state": "Lagos",
                "country": "Nigeria",
            },
        )

        cancel_order(self.user, order.pk)
        self.variant.refresh_from_db()

        self.assertEqual(self.variant.stock_quantity, 10)

        # Repeating cancellation must not increase stock again.
        cancel_order(self.user, order.pk)
        self.variant.refresh_from_db()

        self.assertEqual(self.variant.stock_quantity, 10)

    def test_coupon_usage_is_released_on_cancellation(self):
        coupon = Coupon.objects.create(
            code="TEST10",
            discount_type=Coupon.DiscountType.PERCENTAGE,
            value=10,
            min_order_value=0,
            max_uses=10,
            is_active=True,
        )

        self.cart.coupon = coupon
        self.cart.save(update_fields=["coupon", "updated_at"])

        order = checkout_user_cart(
            self.user,
            {
                "recipient_name": "Test Customer",
                "phone_number": "+2348012345678",
                "address_line_1": "1 Test Street",
                "city": "Lagos",
                "state": "Lagos",
                "country": "Nigeria",
            },
        )

        coupon.refresh_from_db()
        self.assertEqual(coupon.used_count, 1)
        self.assertEqual(order.discount, 2000)
        self.assertEqual(order.total, 18000)

        cancel_order(self.user, order.pk)

        coupon.refresh_from_db()
        self.assertEqual(coupon.used_count, 0)