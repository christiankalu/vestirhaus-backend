
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from dj_rest_auth.registration.serializers import (
    RegisterSerializer as BaseRegisterSerializer,
)
from dj_rest_auth.serializers import (
    LoginSerializer as BaseLoginSerializer,
    UserDetailsSerializer as BaseUserDetailsSerializer,
)

from .models import UserAddress


User = get_user_model()


class CustomRegisterSerializer(BaseRegisterSerializer):
    """Registration serializer that creates customer accounts only."""

    # The custom user model has no username field.
    username = None

    first_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
    )
    last_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
    )
    phone_number = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )
    address = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
    )

    def validate_email(self, email):
        email = email.strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "An account with this email address already exists."
            )

        return super().validate_email(email)

    def get_cleaned_data(self):
        data = super().get_cleaned_data()
        data.update(
            {
                "first_name": self.validated_data.get("first_name", "").strip(),
                "last_name": self.validated_data.get("last_name", "").strip(),
                "phone_number": self.validated_data.get(
                    "phone_number", ""
                ).strip(),
                "address": self.validated_data.get("address", "").strip(),
            }
        )
        return data

    def save(self, request):
        user = super().save(request)

        # Never accept role or verification status from public registration.
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.phone_number = self.cleaned_data["phone_number"]
        user.address = self.cleaned_data["address"]
        user.role = User.Role.CUSTOMER
        user.is_verified = False

        user.save(
            update_fields=[
                "first_name",
                "last_name",
                "phone_number",
                "address",
                "role",
                "is_verified",
            ]
        )
        return user


class CustomLoginSerializer(BaseLoginSerializer):
    """Require email confirmation before issuing customer JWTs."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = attrs["user"]

        # Allow trusted Django staff accounts to access administration.
        if not (user.is_staff or user.is_superuser):
            verified_email_exists = user.emailaddress_set.filter(
                email__iexact=user.email,
                verified=True,
            ).exists()

            if not verified_email_exists:
                raise serializers.ValidationError(
                    {
                        "email": (
                            "Please verify your email address before logging in."
                        )
                    }
                )

        return attrs


class UserDetailsSerializer(BaseUserDetailsSerializer):
    """Expose safe profile fields while keeping security fields read-only."""

    class Meta(BaseUserDetailsSerializer.Meta):
        fields = (
            "pk",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "address",
            "role",
            "is_verified",
            "date_joined",
        )
        read_only_fields = (
            "pk",
            "email",
            "role",
            "is_verified",
            "date_joined",
        )


class UserAddressSerializer(serializers.ModelSerializer):
    """Serialize a customer's saved addresses without exposing ownership control."""

    class Meta:
        model = UserAddress
        fields = (
            "id",
            "user",
            "label",
            "recipient_name",
            "phone_number",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "postal_code",
            "country",
            "is_default",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "user", "created_at", "updated_at")

    def create(self, validated_data):
        user = validated_data.pop(
            "user",
            self.context["request"].user,
        )

        with transaction.atomic():
            if validated_data.get("is_default", False):
                UserAddress.objects.filter(
                    user=user,
                    is_default=True,
                ).update(is_default=False)

            return UserAddress.objects.create(user=user, **validated_data)

    def update(self, instance, validated_data):
        with transaction.atomic():
            will_be_default = validated_data.get(
                "is_default", instance.is_default
            )

            if will_be_default:
                UserAddress.objects.filter(
                    user=instance.user,
                    is_default=True,
                ).exclude(pk=instance.pk).update(is_default=False)

            return super().update(instance, validated_data)
