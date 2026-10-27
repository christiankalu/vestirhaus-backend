from django.dispatch import receiver
from allauth.account.signals import email_confirmed


@receiver(email_confirmed)
def mark_user_email_verified(request, email_address, **kwargs):
    """Mirror confirmation of the login email on the User model."""

    user = email_address.user

    # Only verification of the current login email marks the account verified.
    if email_address.email.casefold() == user.email.casefold():
        type(user).objects.filter(pk=user.pk).update(is_verified=True)
