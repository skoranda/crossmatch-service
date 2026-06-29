"""Shared pytest fixtures for the crossmatch test suite."""
import pytest

from tests.factories import make_alert_with_notifications


@pytest.fixture
def make_alert():
    """Builder fixture: make_alert(status, [Notification.State, ...]) -> (alert, notifications).

    Tests using this still need the django_db marker (it writes rows).
    """
    return make_alert_with_notifications
