
from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission


User = get_user_model()


class IsVerifiedUser(BasePermission):
    """Allow only authenticated, verified accounts."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_verified
        )


class IsPlatformAdmin(BasePermission):
    """Check Vestirhaus administrative role, not merely staff status."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (
                user.role == User.Role.ADMIN
                or user.is_superuser
            )
        )


class IsVendorOrAdmin(BasePermission):
    """Allow a vendor or administrator to access a protected operation."""

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and (
                user.role in (
                    User.Role.VENDOR,
                    User.Role.ADMIN,
                )
                or user.is_superuser
            )
        )
