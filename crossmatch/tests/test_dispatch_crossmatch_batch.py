"""R9: dispatch_crossmatch_batch dispatches only when a threshold is met and
auto-recovers stuck QUEUED alerts. Uses transaction=True so the dispatcher's
transaction.on_commit enqueue and select_for_update behave like production."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.test import override_settings
from django.utils import timezone

import tasks.crossmatch as crossmatch_mod
from core.models import Alert
from tasks.schedule import dispatch_crossmatch_batch
from tests.factories import AlertFactory


@pytest.fixture
def delay_mock(monkeypatch):
    m = MagicMock()
    monkeypatch.setattr(crossmatch_mod.crossmatch_batch, "delay", m)
    return m


@pytest.mark.django_db(transaction=True)
@override_settings(
    CROSSMATCH_BATCH_MAX_SIZE=2, CROSSMATCH_BATCH_MAX_WAIT_SECONDS=100000
)
def test_count_threshold_dispatches(delay_mock):
    AlertFactory.create_batch(2, status=Alert.Status.INGESTED)

    dispatch_crossmatch_batch()

    assert delay_mock.called
    assert Alert.objects.filter(status=Alert.Status.QUEUED).count() == 2


@pytest.mark.django_db(transaction=True)
@override_settings(
    CROSSMATCH_BATCH_MAX_SIZE=100, CROSSMATCH_BATCH_MAX_WAIT_SECONDS=100000
)
def test_below_threshold_does_not_dispatch(delay_mock):
    AlertFactory(status=Alert.Status.INGESTED)

    dispatch_crossmatch_batch()

    assert not delay_mock.called
    assert Alert.objects.filter(status=Alert.Status.INGESTED).count() == 1


@pytest.mark.django_db(transaction=True)
@override_settings(CROSSMATCH_BATCH_MAX_SIZE=100, CROSSMATCH_BATCH_MAX_WAIT_SECONDS=0)
def test_time_threshold_dispatches(delay_mock):
    AlertFactory(status=Alert.Status.INGESTED)

    dispatch_crossmatch_batch()

    assert delay_mock.called
    assert Alert.objects.filter(status=Alert.Status.QUEUED).count() == 1


@pytest.mark.django_db(transaction=True)
@override_settings(CROSSMATCH_BATCH_MAX_SIZE=1, CROSSMATCH_BATCH_MAX_WAIT_SECONDS=0)
def test_young_queued_batch_blocks_dispatch(delay_mock):
    # A young QUEUED alert means a batch is in progress -> skip even though an
    # INGESTED alert otherwise meets the threshold.
    AlertFactory(status=Alert.Status.QUEUED, queued_at=timezone.now())
    AlertFactory(status=Alert.Status.INGESTED)

    dispatch_crossmatch_batch()

    assert not delay_mock.called
    assert Alert.objects.filter(status=Alert.Status.INGESTED).count() == 1


@pytest.mark.django_db(transaction=True)
@override_settings(CROSSMATCH_BATCH_MAX_SIZE=2, CROSSMATCH_BATCH_MAX_WAIT_SECONDS=100000)
def test_dispatch_stamps_queued_at(delay_mock):
    # Dispatching a batch records when each alert entered QUEUED, so stuck
    # detection can measure real batch runtime rather than ingest age.
    AlertFactory.create_batch(2, status=Alert.Status.INGESTED)

    dispatch_crossmatch_batch()

    queued = Alert.objects.filter(status=Alert.Status.QUEUED)
    assert queued.count() == 2
    assert all(a.queued_at is not None for a in queued)


@pytest.mark.django_db(transaction=True)
@override_settings(
    CROSSMATCH_BATCH_STUCK_SECONDS=3600,
    CROSSMATCH_BATCH_MAX_SIZE=100,
    CROSSMATCH_BATCH_MAX_WAIT_SECONDS=100000,
)
def test_stuck_queued_auto_recovers(delay_mock):
    # QUEUED whose queued_at is older than CROSSMATCH_BATCH_STUCK_SECONDS is a
    # hard-killed batch (the task's own revert never ran) -> revert to INGESTED
    # and clear queued_at.
    stuck = AlertFactory(
        status=Alert.Status.QUEUED,
        queued_at=timezone.now() - timedelta(hours=2),
    )

    dispatch_crossmatch_batch()

    stuck.refresh_from_db()
    assert stuck.status == Alert.Status.INGESTED
    assert stuck.queued_at is None


@pytest.mark.django_db(transaction=True)
@override_settings(
    CROSSMATCH_BATCH_STUCK_SECONDS=3600,
    CROSSMATCH_BATCH_MAX_SIZE=1,
    CROSSMATCH_BATCH_MAX_WAIT_SECONDS=0,
)
def test_live_batch_of_old_alerts_not_reverted(delay_mock):
    # Regression: age must key off queued_at, not ingest_time. An alert ingested
    # long ago but only just dispatched is a live batch and must not be reverted
    # even though its ingest age exceeds the stuck threshold.
    live = AlertFactory(status=Alert.Status.QUEUED, queued_at=timezone.now())
    Alert.objects.filter(pk=live.pk).update(
        ingest_time=timezone.now() - timedelta(hours=5)
    )

    dispatch_crossmatch_batch()

    live.refresh_from_db()
    assert live.status == Alert.Status.QUEUED
    assert not delay_mock.called
