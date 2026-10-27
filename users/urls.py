
from django.conf import settings
from django.shortcuts import redirect
from django.urls import path, re_path
from django.views.generic import TemplateView

from .views import (
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshTokenView,
    RegisterView,
    ResetPasswordView,
    UserAddressDetailView,
    UserAddressListCreateView,
    VerifyEmailView,
)


def email_confirmation_redirect(request, key):
    """Fallback route that takes an email confirmation link to React."""
    return redirect(f"{settings.FRONTEND_BASE_URL}/verify-email/{key}")


def password_reset_redirect(request, uidb64, token):
    """Fallback route that takes a password reset link to React."""
    return redirect(
        f"{settings.FRONTEND_BASE_URL}/reset-password/{uidb64}/{token}"
    )


urlpatterns = [
    # Authentication
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path(
        "auth/token/refresh/",
        RefreshTokenView.as_view(),
        name="auth-token-refresh",
    ),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path(
        "auth/verify-email/",
        VerifyEmailView.as_view(),
        name="auth-verify-email",
    ),
    path(
        "auth/forgot-password/",
        ForgotPasswordView.as_view(),
        name="auth-forgot-password",
    ),
    path(
        "auth/reset-password/",
        ResetPasswordView.as_view(),
        name="auth-reset-password",
    ),

    # Authenticated user profile
    path("users/me/", MeView.as_view(), name="user-me"),

    # Saved delivery addresses
    path(
        "users/me/addresses/",
        UserAddressListCreateView.as_view(),
        name="user-address-list-create",
    ),
    path(
        "users/me/addresses/<int:pk>/",
        UserAddressDetailView.as_view(),
        name="user-address-detail",
    ),

    # Named routes required by the email-confirmation/reset integrations.
    re_path(
        r"^auth/account-confirm-email/(?P<key>[-:\w]+)/$",
        email_confirmation_redirect,
        name="account_confirm_email",
    ),
    re_path(
        r"^password-reset/confirm/"
        r"(?P<uidb64>[0-9A-Za-z_\-]+)/"
        r"(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,32})/$",
        password_reset_redirect,
        name="password_reset_confirm",
    ),
    
    path("auth/account-email-verification-sent/", TemplateView.as_view(), name="account_email_verification_sent"),
    
    re_path(r"^auth/account-confirm-email/(?P<key>[-:\w]+)/$", TemplateView.as_view(), name="account_confirm_email"),
]
