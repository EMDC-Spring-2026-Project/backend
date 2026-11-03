import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def api_health(request):
    """Report readiness only when the API can reach its database."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        logger.exception("API readiness check failed because the database is unavailable")
        return JsonResponse({"status": "unavailable"}, status=503)

    return JsonResponse({"status": "ok"})
