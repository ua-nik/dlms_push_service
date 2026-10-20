"""
URL configuration for dlms_push_service project.
"""
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from apps.core.views import HealthCheckView

urlpatterns = [
    # Health checks
    path('api/health/', HealthCheckView.as_view(), name='health-check'),

    # OpenAPI Schema & Interactive Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # Versioned API
    path('api/v1/', include('apps.meters.urls')),
]
