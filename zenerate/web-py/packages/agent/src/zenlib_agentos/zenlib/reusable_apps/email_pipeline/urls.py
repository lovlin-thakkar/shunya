"""Routes for ``/api/v1/email/``.

TODO (Phase 1): register your viewsets here.

Example:

    from rest_framework.routers import DefaultRouter
    from .views.thread import ThreadViewSet
    from .views.message import MessageViewSet
    from .views.event import ProcessedEventViewSet

    router = DefaultRouter()
    router.register(r"threads", ThreadViewSet, basename="thread")
    router.register(r"messages", MessageViewSet, basename="message")
    router.register(r"processed-events", ProcessedEventViewSet, basename="event")
    urlpatterns = router.urls
"""

from rest_framework.routers import DefaultRouter

router = DefaultRouter()
# router.register(...)

urlpatterns = router.urls
