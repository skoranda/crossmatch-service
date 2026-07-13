"""WSGI config for the crossmatch project.

Exposes the WSGI callable as a module-level ``application``. Used by the web
workload's gunicorn server (``entrypoints/run_web.sh``) to serve the read-model
HTTP API; the ingest/crossmatch workloads do not import this.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')

application = get_wsgi_application()
