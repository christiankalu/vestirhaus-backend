
from rest_framework import serializers


class InitializePaymentSerializer(serializers.Serializer):
    order_id = serializers.IntegerField(min_value=1)


class RefundRequestSerializer(serializers.Serializer):
    merchant_note = serializers.CharField(
        max_length=250,
        required=False,
        allow_blank=True,
        default="Vestirhaus order refund",
    )


class PaymentAttemptSerializer(serializers.Serializer):
    reference = serializers.CharField()
    amount = serializers.IntegerField()
    currency = serializers.CharField()
    status = serializers.CharField()
    refund_status = serializers.CharField()
    authorization_url = serializers.URLField()
    paid_at = serializers.DateTimeField(allow_null=True)
