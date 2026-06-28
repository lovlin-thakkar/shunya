from django.urls import path
from .internal_views import CallStartView, CallTurnView, CallEndView

urlpatterns = [
    path("calls/start/", CallStartView.as_view(), name="call-start"),
    path("calls/<uuid:call_id>/turn/", CallTurnView.as_view(), name="call-turn"),
    path("calls/<uuid:call_id>/end/", CallEndView.as_view(), name="call-end"),
]
