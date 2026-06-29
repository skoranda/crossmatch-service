"""R7: _get_catalog validates requested columns up front — a column colliding
with an alert column, or one missing from the catalog schema, fails loud with a
clear ValueError instead of a cryptic error deep in .compute()."""
from unittest.mock import MagicMock

import pytest

import matching.catalog as catalog_mod
from matching.catalog import _get_catalog


@pytest.fixture(autouse=True)
def _reset_catalog_cache():
    # The module-level cache short-circuits validation; reset it per test.
    catalog_mod._catalog_cache.clear()
    yield
    catalog_mod._catalog_cache.clear()


def _cfg(payload_columns):
    return {
        "name": "t",
        "hats_url": "x",
        "source_id_column": "source_id",
        "ra_column": "ra",
        "dec_column": "dec",
        "payload_columns": payload_columns,
    }


def test_collision_with_alert_column_raises():
    with pytest.raises(ValueError, match="collide"):
        _get_catalog(_cfg(["ra_deg"]))  # ra_deg is a reserved alert column


def test_unknown_column_raises(monkeypatch):
    cat = MagicMock()
    cat.columns = ["source_id", "ra", "dec"]  # 'mag' absent
    monkeypatch.setattr(catalog_mod.lsdb, "open_catalog", lambda *a, **k: cat)

    with pytest.raises(ValueError, match="not found"):
        _get_catalog(_cfg(["mag"]))


def test_valid_columns_returns_catalog(monkeypatch):
    cat = MagicMock()
    cat.columns = ["source_id", "ra", "dec", "mag"]
    monkeypatch.setattr(catalog_mod.lsdb, "open_catalog", lambda *a, **k: cat)

    assert _get_catalog(_cfg(["mag"])) is cat
