"""U7: task events are enabled so grafana/celery-exporter can report per-task
success/failure/runtime metrics, not just broker queue length."""

from project.celery import celery_app


def test_worker_task_events_enabled():
    assert celery_app.conf.worker_send_task_events is True


def test_task_sent_event_enabled():
    assert celery_app.conf.task_send_sent_event is True
