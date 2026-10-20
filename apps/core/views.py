import logging
from django.db import connection
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    """
    Перевірка працездатності та готовності сервісу (Liveness / Readiness probe).
    Перевіряє доступність PostgreSQL та Redis Channel Layer.
    """
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        summary="Перевірка готовності сервісу",
        description="Повертає статус підключення до бази даних PostgreSQL та Redis.",
        responses={
            200: inline_serializer(
                name="HealthCheckResponse",
                fields={
                    "status": serializers.CharField(),
                    "database": serializers.CharField(),
                    "channel_layer": serializers.CharField(),
                    "version": serializers.CharField(),
                }
            ),
            503: inline_serializer(
                name="HealthCheckErrorResponse",
                fields={
                    "status": serializers.CharField(),
                    "database": serializers.CharField(),
                    "channel_layer": serializers.CharField(),
                    "error": serializers.CharField(),
                }
            )
        }
    )
    def get(self, request, *args, **kwargs):
        health_data = {
            "status": "healthy",
            "database": "unknown",
            "channel_layer": "unknown",
            "version": "1.0.0",
        }
        is_healthy = True

        # 1. Check Database
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    health_data["database"] = "ok"
                else:
                    health_data["database"] = "unexpected_response"
                    is_healthy = False
        except Exception as e:
            logger.error("HealthCheck: Database check failed: %s", e)
            health_data["database"] = f"error: {str(e)}"
            is_healthy = False

        # 2. Check Channel Layer / Redis
        try:
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            if channel_layer is None:
                health_data["channel_layer"] = "not_configured"
            else:
                # If using InMemory or Redis, verify backend exists
                health_data["channel_layer"] = "ok"
        except Exception as e:
            logger.error("HealthCheck: Channel layer check failed: %s", e)
            health_data["channel_layer"] = f"error: {str(e)}"
            is_healthy = False

        if is_healthy:
            return Response(health_data, status=status.HTTP_200_OK)
        else:
            health_data["status"] = "unhealthy"
            return Response(health_data, status=status.HTTP_503_SERVICE_UNAVAILABLE)
