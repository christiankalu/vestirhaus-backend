from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def csrf_cookie(request):
    return JsonResponse({
        "detail": "CSRF cookie set.",
        "csrfToken": get_token(request),
    })