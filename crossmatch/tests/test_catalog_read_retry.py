"""Transient remote-read resilience for catalog crossmatch.

The HATS catalogs for DES/DELVE/SkyMapper are served over HTTP from
data.lsdb.io, which intermittently drops the connection mid parquet range read.
aiohttp raises ServerDisconnectedError, which fsspec's parquet cache re-surfaces
as confusing TypeErrors ("can't concat ServerDisconnectedError to bytes",
"'ServerDisconnectedError' object is not subscriptable"). Without retry, one
transient blip on one catalog fails the whole multi-catalog crossmatch batch.

These cover the retry helpers in matching/catalog.py: retry ONLY on the
transient network signature, re-raise everything else immediately so the
fail-loud path still surfaces real errors (version skew, bad columns, no overlap).
"""

from unittest import mock

import pytest
from django.test import override_settings

from matching.catalog import _read_with_retry, _transient_read_signature


class _FakeServerDisconnectedError(Exception):
    """Stands in for aiohttp.client_exceptions.ServerDisconnectedError by name."""


def test_transient_detected_via_wrapping_typeerror_message():
    # The exact surface fsspec produces from a dropped range read. The signature
    # names the underlying transient cause even though the wrapper is a TypeError.
    exc = TypeError("can't concat ServerDisconnectedError to bytes")
    assert _transient_read_signature(exc) == "ServerDisconnectedError"


def test_transient_detected_via_exception_chain():
    try:
        try:
            raise _FakeServerDisconnectedError("Server disconnected")
        except _FakeServerDisconnectedError as cause:
            raise TypeError(
                "'ServerDisconnectedError' object is not subscriptable"
            ) from cause
    except TypeError as exc:
        # The walk follows __cause__ to the real connection failure.
        assert _transient_read_signature(exc) == "ServerDisconnectedError"


def test_filenotfound_from_flaky_endpoint_is_transient():
    # data.lsdb.io drops a range read under load; fsspec surfaces it as
    # FileNotFoundError(url) even though the parquet file exists (GET -> 200).
    exc = FileNotFoundError(
        "https://data.lsdb.io/hats/des/des_y6_gold/des_y6_gold_5arcs/"
        "dataset/Norder=5/Dir=0/Npix=4351.parquet"
    )
    assert _transient_read_signature(exc) == "FileNotFoundError"


def test_deterministic_errors_are_not_transient():
    # Deterministic errors match no signature, so they still fail loud.
    assert _transient_read_signature(ValueError("requested columns not found")) is None
    assert _transient_read_signature(RuntimeError("Catalogs do not overlap")) is None


@override_settings(CROSSMATCH_READ_RETRIES=3, CROSSMATCH_READ_RETRY_BACKOFF_SECONDS=0)
def test_retries_filenotfound_then_succeeds():
    calls = {"n": 0}

    def read_fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileNotFoundError(
                "https://data.lsdb.io/hats/des/des_y6_gold/des_y6_gold_5arcs/"
                "dataset/Norder=5/Dir=0/Npix=4351.parquet"
            )
        return "matches"

    with mock.patch("matching.catalog.time.sleep"):
        result = _read_with_retry(read_fn, "des_y6_gold")

    assert result == "matches"
    assert calls["n"] == 2


@override_settings(CROSSMATCH_READ_RETRIES=3, CROSSMATCH_READ_RETRY_BACKOFF_SECONDS=0)
def test_retries_transient_then_succeeds():
    calls = {"n": 0}

    def read_fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("can't concat ServerDisconnectedError to bytes")
        return "matches"

    with mock.patch("matching.catalog.time.sleep"):
        result = _read_with_retry(read_fn, "skymapper_dr4")

    assert result == "matches"
    assert calls["n"] == 2


@override_settings(CROSSMATCH_READ_RETRIES=3, CROSSMATCH_READ_RETRY_BACKOFF_SECONDS=0)
def test_transient_exhausts_retries_then_raises():
    calls = {"n": 0}

    def read_fn():
        calls["n"] += 1
        raise TypeError("can't concat ServerDisconnectedError to bytes")

    with mock.patch("matching.catalog.time.sleep"):
        with pytest.raises(TypeError):
            _read_with_retry(read_fn, "des_y6_gold")

    assert calls["n"] == 3  # all attempts consumed, then re-raised


@override_settings(CROSSMATCH_READ_RETRIES=3, CROSSMATCH_READ_RETRY_BACKOFF_SECONDS=0)
def test_deterministic_error_not_retried():
    calls = {"n": 0}

    def read_fn():
        calls["n"] += 1
        raise ValueError("requested columns not found in catalog schema")

    with mock.patch("matching.catalog.time.sleep"):
        with pytest.raises(ValueError):
            _read_with_retry(read_fn, "gaia_dr3")

    assert calls["n"] == 1  # surfaced immediately, fail-loud preserved


@override_settings(CROSSMATCH_READ_RETRIES=3, CROSSMATCH_READ_RETRY_BACKOFF_SECONDS=0)
def test_soft_time_limit_is_not_retried():
    # A batch soft time limit must propagate, never be retried -- even when it
    # chains a transient error via __context__ (the soft signal fired mid-read
    # while a disconnect was being handled), which the transient signature would
    # otherwise match and absorb as a retry, defeating the batch self-heal.
    from celery.exceptions import SoftTimeLimitExceeded

    calls = {"n": 0}

    def read_fn():
        calls["n"] += 1
        try:
            raise _FakeServerDisconnectedError("Server disconnected")
        except _FakeServerDisconnectedError:
            raise SoftTimeLimitExceeded()

    with mock.patch("matching.catalog.time.sleep"):
        with pytest.raises(SoftTimeLimitExceeded):
            _read_with_retry(read_fn, "des_y6_gold")

    assert calls["n"] == 1  # propagated immediately despite the chained transient
