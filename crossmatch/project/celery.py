import glob
import os

from celery import Celery
from celery.signals import worker_init, worker_process_shutdown

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')

celery_app = Celery("app")
celery_app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
# celery_app.autodiscover_tasks()

# Connect to remote Dask scheduler if configured
from core import dask  # noqa: F401 — registers worker_process_init signal

# If the worker is running in Kubernetes, enable the liveness probe
if os.getenv('KUBERNETES_SERVICE_HOST', ''):
    from core.k8s import LivenessProbe
    celery_app.steps["worker"].add(LivenessProbe)


@worker_init.connect
def _start_worker_metrics(**kwargs):
    """Serve aggregated golden-signal metrics from the worker parent (U6).

    Prefork forks child processes after this fires; with PROMETHEUS_MULTIPROC_DIR
    set each child writes metric files there and this parent server aggregates
    them (a single in-process registry would report only one child). Clear stale
    files first: a container restart reuses the pod's emptyDir and old files
    would double-count. Without the env var (e.g. local dev) it degrades to the
    parent's in-process registry.
    """
    from core.metrics import start_metrics_server

    mp_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR')
    if mp_dir and os.path.isdir(mp_dir):
        for path in glob.glob(os.path.join(mp_dir, '*.db')):
            try:
                os.remove(path)
            except OSError:
                pass
    start_metrics_server()


@worker_process_shutdown.connect
def _cleanup_worker_metrics(**kwargs):
    """Prune a shutting-down prefork child's per-process metric files."""
    if os.environ.get('PROMETHEUS_MULTIPROC_DIR'):
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(os.getpid())


if __name__ == '__main__':
    celery_app.start()
