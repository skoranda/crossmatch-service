"""URL patterns for the read-model API, included under ``api/`` by the root
URLconf (``project/urls.py``)."""

from django.urls import path

from api import views

urlpatterns = [
    path(
        'recent-crossmatches',
        views.recent_crossmatches_view,
        name='recent-crossmatches',
    ),
]
