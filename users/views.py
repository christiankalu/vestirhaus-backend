
from dj_rest_auth.registration.views import (
    RegisterView as BaseRegisterView,
    VerifyEmailView as BaseVerifyEmailView,
)
from dj_rest_auth.views import (
    LoginView as BaseLoginView,
    LogoutView as BaseLogoutView,
    PasswordResetView as BasePasswordResetView,
    PasswordResetConfirmView as BasePasswordResetConfirmView,
    UserDetailsView as BaseUserDetailsView,
)
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from .serializers import (
    CustomLoginSerializer,
    CustomRegisterSerializer,
    UserAddressSerializer,
)

# A simple serializer for the schema documentation
class LogoutSchemaSerializer(serializers.Serializer):
    refresh = serializers.CharField(help_text="The refresh token to blacklist.")

class RegisterView(BaseRegisterView):
    serializer_class = CustomRegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_register"


class LoginView(BaseLoginView):
    serializer_class = CustomLoginSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "dj_rest_auth_login"
    
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200 and getattr(self, "user", None):
            from orders.services import merge_guest_cart_into_user

            merge_guest_cart_into_user(
                request._request,
                self.user,
            )

        return response


class RefreshTokenView(BaseTokenRefreshView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "dj_rest_auth"


class LogoutView(BaseLogoutView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "dj_rest_auth"
    serializer_class = LogoutSchemaSerializer


class VerifyEmailView(BaseVerifyEmailView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_verify"


class ForgotPasswordView(BasePasswordResetView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"


class ResetPasswordView(BasePasswordResetConfirmView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"


class MeView(BaseUserDetailsView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "profile"


class UserAddressListCreateView(generics.ListCreateAPIView):
    """List or create saved addresses belonging to the current user."""

    serializer_class = UserAddressSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "address"

    def get_queryset(self):
        return self.request.user.saved_addresses.all()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class UserAddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete one of the current user's addresses."""

    serializer_class = UserAddressSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "address"

    def get_queryset(self):
        # An address owned by another user is not in this queryset.
        return self.request.user.saved_addresses.all()
