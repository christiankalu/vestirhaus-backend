
from decouple import config

from .base import *


DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)

# Django debug pages are useful locally, but never enable DEBUG
# in production.
INTERNAL_IPS = ["127.0.0.1"]
