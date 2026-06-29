# Developer documentation

## Requirements

- Docker with Compose plugin "docker compose"

## Launch local deployment

If you wish to override any of the environment variables, create a `.env` file in the `/docker` directory:

```bash
echo 'DEV_MODE = true' >> docker/.env
```

Launch the local deployment by navigating to the root directory of your repo clone and executing:

```bash
docker compose -f docker/docker-compose.yaml up -d --build
```

## Testing

## Virtual environment

You may want to use a Python virtual environment when developing code or when testing. In general it is possible to `docker exec` into a running container where the environment is already configured, but sometimes it is convenient to run a script on your host machine. In these cases, you can create a virtual environment and install the requirements locally.

```bash
# Create the venv once
$ python -m venv .venv
# Thereafter, source the activate script prior to running Python scripts that require the project dependencies
$ source .venv/bin/activate
(.venv) 
# Install/update all dependencies 
$ pip install -r crossmatch/requirements.base.txt 
```

## Unit tests

Tests run with `pytest` (via `pytest-django`) in-container, against the compose
`django-db` Postgres service. Bring up the stack, then run the suite:

```bash
docker compose -f docker/docker-compose.yaml up -d
# test deps come from crossmatch/requirements.dev.txt (pytest, pytest-django, factory_boy)
docker exec -it crossmatch-celery-worker-1 sh -c 'cd /opt/crossmatch && python -m pytest'
```

Config lives in `crossmatch/pytest.ini` (`DJANGO_SETTINGS_MODULE`, test paths).
Run a subset with a path or `-k`, e.g. `python -m pytest tests/test_dispatch_notifications.py`.
Tests that depend on commit semantics (the dispatch/ordering tests) use
`@pytest.mark.django_db(transaction=True)` and require Postgres — they will not
behave on SQLite.
