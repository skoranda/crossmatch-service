"""Sanity checks that the factories build a valid alert -> notification graph,
including the to_field FK relation (the wiring behind two of the production bugs)."""

import pytest

from core.models import Alert, Notification
from tests.factories import AlertFactory, CatalogMatchFactory, NotificationFactory


@pytest.mark.django_db
def test_alert_factory_persists():
    alert = AlertFactory(status=Alert.Status.MATCHED)
    assert alert.pk is not None
    assert Alert.objects.filter(status=Alert.Status.MATCHED).count() == 1


@pytest.mark.django_db
def test_notification_and_match_resolve_via_natural_key():
    alert = AlertFactory()
    match = CatalogMatchFactory(alert=alert)
    notif = NotificationFactory(
        alert=alert, catalog_match=match, state=Notification.State.SENT
    )
    # FK uses to_field=lsst_diaObject_diaObjectId, not the uuid pk.
    assert notif.alert_id == alert.lsst_diaObject_diaObjectId
    assert match.alert_id == alert.lsst_diaObject_diaObjectId
    assert alert.notification_set.get().state == Notification.State.SENT


@pytest.mark.django_db
def test_make_alert_with_notifications_builder():
    alert, notifs = make_builder()
    assert alert.status == Alert.Status.MATCHED
    assert [n.state for n in notifs] == [
        Notification.State.SENT,
        Notification.State.PENDING,
    ]


def make_builder():
    from tests.factories import make_alert_with_notifications

    return make_alert_with_notifications(
        Alert.Status.MATCHED,
        [Notification.State.SENT, Notification.State.PENDING],
    )
