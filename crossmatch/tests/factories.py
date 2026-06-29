"""factory_boy factories for the alert -> CatalogMatch -> Notification graph.

The Alert FKs on CatalogMatch / Notification use ``to_field='lsst_diaObject_diaObjectId'``
(not the uuid pk); SubFactory wiring below resolves that relation correctly so tests build
graphs the same way production does.
"""
import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from core.models import Alert, AlertDelivery, CatalogMatch, Notification


class AlertFactory(DjangoModelFactory):
    class Meta:
        model = Alert

    lsst_diaObject_diaObjectId = factory.Sequence(lambda n: 9_000_000_000 + n)
    lsst_diaSource_diaSourceId = factory.Sequence(lambda n: 8_000_000_000 + n)
    ra_deg = 180.0
    dec_deg = -30.0
    event_time = factory.LazyFunction(timezone.now)
    schema_version = 1
    payload = factory.LazyFunction(dict)
    status = Alert.Status.INGESTED


class AlertDeliveryFactory(DjangoModelFactory):
    class Meta:
        model = AlertDelivery

    alert = factory.SubFactory(AlertFactory)
    broker = "antares"


class CatalogMatchFactory(DjangoModelFactory):
    class Meta:
        model = CatalogMatch

    alert = factory.SubFactory(AlertFactory)
    catalog_name = "gaia_dr3"
    catalog_source_id = factory.Sequence(lambda n: str(7_000_000_000 + n))
    match_distance_arcsec = 0.5
    source_ra_deg = 180.0
    source_dec_deg = -30.0
    catalog_payload = factory.LazyFunction(dict)
    match_version = 1


class NotificationFactory(DjangoModelFactory):
    class Meta:
        model = Notification

    alert = factory.SubFactory(AlertFactory)
    destination = "hopskotch"
    payload = factory.LazyFunction(dict)
    state = Notification.State.PENDING


def make_alert_with_notifications(status, notification_states, destination="hopskotch"):
    """Build one Alert at ``status`` plus one Notification per entry in
    ``notification_states`` (each a Notification.State), all on ``destination``.

    Returns (alert, [notifications]).
    """
    alert = AlertFactory(status=status)
    notifications = [
        NotificationFactory(alert=alert, destination=destination, state=state)
        for state in notification_states
    ]
    return alert, notifications
