
from django.contrib import admin
from django.urls import include, path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)


class HealthCheckView(APIView):
    """Basic application health endpoint."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),

    path("api/v1/health/", HealthCheckView.as_view(), name="health-check"),

    path(
        "api/v1/auth/token/",
        TokenObtainPairView.as_view(),
        name="token-obtain-pair",
    ),
    path(
        "api/v1/auth/token/refresh/",
        TokenRefreshView.as_view(),
        name="token-refresh",
    ),
    path(
        "api/v1/auth/token/verify/",
        TokenVerifyView.as_view(),
        name="token-verify",
    ),
]
