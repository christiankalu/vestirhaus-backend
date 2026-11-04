from rest_framework.permissions import BasePermission


class IsStaffAdmin(BasePermission):
    """
    Allow access only to authenticated Django staff members.
    """

    message = "You do not have permission to access the admin panel."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and user.is_staff
        )