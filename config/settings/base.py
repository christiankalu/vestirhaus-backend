
import os
from datetime import timedelta
from pathlib import Path

from decouple import Csv, config


# backend/config/settings/base.py
# BASE_DIR resolves to the backend/ directory.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# Security and environment configuration.
SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = False

ALLOWED_HOSTS = config(
    "DJANGO_ALLOWED_HOSTS",
    default="localhost,127.0.0.1",
    cast=Csv(),
)


# Django and third-party applications.
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "cloudinary",
    "cloudinary_storage",
]

LOCAL_APPS = [
    "users",
    "products",
    "orders",
    "payments",
    "core",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# Middleware order matters: CORS middleware should be high in the list.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# PostgreSQL database.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="aso_db"),
        "USER": config("DB_USER", default="aso_user"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="127.0.0.1"),
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
    }
}


# Custom email-based user model.
AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# Internationalization.
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True


# Static and uploaded media.
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": config("CLOUDINARY_CLOUD_NAME", default=""),
    "API_KEY": config("CLOUDINARY_API_KEY", default=""),
    "API_SECRET": config("CLOUDINARY_API_SECRET", default=""),
}

STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}


# Default primary key type.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Django REST Framework.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": (
        "rest_framework.pagination.PageNumberPagination"
    ),
    "PAGE_SIZE": 20,
}


# JWT configuration.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config(
            "JWT_ACCESS_TOKEN_MINUTES",
            default=15,
            cast=int,
        )
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config(
            "JWT_REFRESH_TOKEN_DAYS",
            default=7,
            cast=int,
        )
    ),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# Required for refresh-token blacklisting.
INSTALLED_APPS += ["rest_framework_simplejwt.token_blacklist"]


# CORS and CSRF.
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:5173",
    cast=Csv(),
)

CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:5173",
    cast=Csv(),
)


# Email backend defaults to the console during development.
# Production should configure a real email service.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL",
    default="noreply@aso.example",
)


# Paystack credentials: consumed by the payments app later.
PAYSTACK_PUBLIC_KEY = config(
    "PAYSTACK_PUBLIC_KEY",
    default="",
)
PAYSTACK_SECRET_KEY = config(
    "PAYSTACK_SECRET_KEY",
    default="",
)
PAYSTACK_WEBHOOK_SECRET = config(
    "PAYSTACK_WEBHOOK_SECRET",
    default="",
)
