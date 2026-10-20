from rest_framework.routers import DefaultRouter
from .views import MeterViewSet, MeterMessageViewSet

router = DefaultRouter()
router.register("meters", MeterViewSet, basename="meter")
router.register("messages", MeterMessageViewSet, basename="message")

urlpatterns = router.urls
