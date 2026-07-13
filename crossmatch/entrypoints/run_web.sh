#!/bin/env bash

set -euo pipefail

cd "${APP_ROOT_DIR:-/opt}/crossmatch"

bash entrypoints/wait-for-it.sh ${DATABASE_HOST}:${DATABASE_PORT:-5432} --timeout=0

gunicorn project.wsgi:application \
    --bind 0.0.0.0:${WEB_PORT:-8000} \
    --workers ${WEB_WORKERS:-2} \
    --log-level ${WEB_LOG_LEVEL:-info}
