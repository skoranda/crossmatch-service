"""Catalog source URLs: DES and DELVE read from their public S3 mirrors; SkyMapper
stays on data.lsdb.io HTTPS (no S3 mirror); Gaia is unchanged.

Guards the reliability fix that moved DES Y6 Gold and DELVE DR3 Gold off the
degraded data.lsdb.io CDN onto the anonymous stpubdata S3 mirrors (R1, R4).
"""

from django.conf import settings


def _hats_url(name: str) -> str:
    return next(
        c["hats_url"] for c in settings.CROSSMATCH_CATALOGS if c["name"] == name
    )


def test_des_reads_from_s3():
    url = _hats_url("des_y6_gold")
    assert url.startswith("s3://"), url
    assert "data.lsdb.io" not in url


def test_delve_reads_from_s3():
    url = _hats_url("delve_dr3_gold")
    assert url.startswith("s3://"), url
    assert "data.lsdb.io" not in url


def test_skymapper_stays_on_https():
    # No public S3 mirror exists for SkyMapper DR4; it stays on data.lsdb.io by
    # decision (its residual exposure is accepted; see the plan's KD3).
    assert "data.lsdb.io" in _hats_url("skymapper_dr4")


def test_gaia_unchanged():
    assert _hats_url("gaia_dr3").startswith("s3://stpubdata")
