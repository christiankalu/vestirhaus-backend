from decouple import config
import dj_database_url

from .base import *


DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)

# Use Railway's public database URL when supplied.
# Otherwise, keep using the local PostgreSQL settings from base.py.
database_url = config(
    "DATABASE_PUBLIC_URL",
    default=config("DATABASE_URL", default=""),
)

if database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            database_url,
            conn_max_age=600,
            ssl_require=True,
        )
    }

INTERNAL_IPS = ["127.0.0.1"]