"""Generic LSDB HATS catalog crossmatch."""

import time

import lsdb
import pandas as pd
from django.conf import settings
from core.log import get_logger

logger = get_logger(__name__)

# Class names of transient remote-read failures worth retrying. The HATS
# catalogs for DES/DELVE/SkyMapper are served over HTTP from data.lsdb.io, which
# intermittently drops the connection mid parquet range read. aiohttp raises
# ServerDisconnectedError (and kin); fsspec's parquet cache then re-surfaces it
# as a confusing TypeError ("can't concat ServerDisconnectedError to bytes",
# "'ServerDisconnectedError' object is not subscriptable"). We match on the class
# name so both the raw aiohttp error and its fsspec-wrapped TypeError are caught,
# without importing aiohttp directly.
#
# FileNotFoundError is included deliberately: when data.lsdb.io is slow/flaky
# under a large batch's concurrent range reads, fsspec surfaces the dropped read
# as FileNotFoundError(url) even though the parquet file exists (a direct GET
# returns HTTP 200). Retrying recovers it. A genuinely missing file still fails
# loud after the retries are exhausted, so this only costs a little latency in
# the rare true-missing case; requested-column and catalog-schema errors are
# validated up front in _get_catalog and raise ValueError, not FileNotFoundError.
_TRANSIENT_READ_SIGNATURES = (
    'ServerDisconnectedError',
    'ServerTimeoutError',
    'ClientConnectionError',
    'ClientOSError',
    'ClientPayloadError',
    'ConnectionResetError',
    'FileNotFoundError',
)


def _is_transient_read_error(exc: BaseException) -> bool:
    """True if ``exc`` (or anything in its cause/context chain) is a transient
    remote-read failure worth retrying, matched by class name or message text so
    fsspec's TypeError-wrapped form is caught too. Deterministic errors (bad
    columns, no spatial overlap, version skew) return False so they still
    fail loud immediately.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        text = f'{type(cur).__name__}: {cur}'
        if any(sig in text for sig in _TRANSIENT_READ_SIGNATURES):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _read_with_retry(read_fn, catalog_name: str):
    """Run ``read_fn`` (a catalog read/compute), retrying only on transient
    remote-read disconnects with linear backoff. Non-transient errors re-raise
    immediately, preserving the fail-loud contract in tasks/crossmatch.py.
    """
    attempts = settings.CROSSMATCH_READ_RETRIES
    backoff = settings.CROSSMATCH_READ_RETRY_BACKOFF_SECONDS
    for attempt in range(1, attempts + 1):
        try:
            return read_fn()
        except Exception as exc:
            if attempt < attempts and _is_transient_read_error(exc):
                logger.warning(
                    'Transient catalog read error; retrying',
                    catalog=catalog_name,
                    attempt=attempt,
                    max_attempts=attempts,
                    error=str(exc),
                )
                time.sleep(backoff * attempt)
                continue
            raise

# Module-level cache: {catalog_name: lsdb_catalog}
_catalog_cache = {}

# Alert-catalog column names. A requested catalog column matching one of these
# would be renamed with a `_catalog` suffix by the crossmatch
# (suffix_method='overlapping_columns'), which would break payload key mapping
# in the task. None of the current payload columns collide; this guards future
# additions. Keep in sync with the alerts DataFrame built in tasks/crossmatch.py.
_ALERT_COLUMNS = {'uuid', 'lsst_diaObject_diaObjectId', 'ra_deg', 'dec_deg'}


def _load_columns(catalog_config):
    """Ordered, deduplicated list of columns to load for a catalog.

    The source-id / RA / Dec triple plus any configured ``payload_columns``
    (upstream-native case). ``ra``/``dec`` declared in ``payload_columns``
    collapse against ``ra_column``/``dec_column`` here rather than being
    requested twice.
    """
    return list(dict.fromkeys([
        catalog_config['source_id_column'],
        catalog_config['ra_column'],
        catalog_config['dec_column'],
        *catalog_config.get('payload_columns', []),
    ]))


def _get_catalog(catalog_config):
    """Return cached LSDB catalog, loading on first call.

    Loads only the configured columns: the source-id / RA / Dec triple plus the
    catalog's ``payload_columns`` (deduplicated). Requested columns are validated
    against the full catalog schema up front, so a misspelled or wrong-case
    column raises a clear error naming the offender instead of surfacing as a
    cryptic parquet error deep inside ``.compute()`` — which the crossmatch loop
    would otherwise swallow as a generic per-catalog failure.
    """
    name = catalog_config['name']
    if name not in _catalog_cache:
        url = catalog_config['hats_url']
        requested = _load_columns(catalog_config)

        collisions = [c for c in requested if c in _ALERT_COLUMNS]
        if collisions:
            raise ValueError(
                f"{name}: requested columns {collisions} collide with alert "
                f"columns; the crossmatch would suffix them and break payload "
                f"key mapping. Rename or drop them from payload_columns."
            )

        # open_catalog with no `columns` loads only the catalog's *default*
        # columns, so introspect the full schema with columns="all".
        available = set(lsdb.open_catalog(url, columns="all").columns)
        missing = [c for c in requested if c not in available]
        if missing:
            raise ValueError(
                f"{name}: requested columns not found in catalog schema: "
                f"{missing}. Check name/case against docs/references/"
                f"{name}-columns.md."
            )

        logger.info('Loading HATS catalog',
                    catalog=name, url=url, columns=len(requested))
        _catalog_cache[name] = lsdb.open_catalog(url, columns=requested)
    return _catalog_cache[name]


def crossmatch_alerts(alerts_catalog, catalog_config):
    """Crossmatch an LSDB alerts catalog against a single HATS catalog.

    Args:
        alerts_catalog: Pre-built LSDB catalog from lsdb.from_dataframe().
                        Built once in the task and reused for all catalogs.
        catalog_config: Dict with 'name', 'hats_url', 'source_id_column',
                        'ra_column', 'dec_column', and optional
                        'payload_columns' (extra columns loaded for the
                        published payload; see _get_catalog).

    Returns:
        DataFrame with matched rows. Source ID is in the column named by
        catalog_config['source_id_column']; the payload columns appear under
        their upstream-native names. Distance in _dist_arcsec. Returns empty
        DataFrame if no matches found.
    """
    # Alert DataFrame uses ra_deg/dec_deg; catalog RA/Dec and payload column
    # names vary (e.g. 'ra'/'dec' for Gaia, 'RA'/'DEC' for DES). The loaded set
    # is now the full payload_columns union, but none overlap the alert columns
    # (_get_catalog rejects any that do via _ALERT_COLUMNS), so
    # suffix_method='overlapping_columns' leaves the catalog columns un-suffixed.
    #
    # The read (catalog open + compute) runs under _read_with_retry so a
    # transient data.lsdb.io disconnect retries instead of failing the whole
    # multi-catalog batch; deterministic errors still fail loud immediately.
    def _read():
        catalog = _get_catalog(catalog_config)
        matches = alerts_catalog.crossmatch(
            catalog,
            n_neighbors=1,
            radius_arcsec=settings.CROSSMATCH_RADIUS_ARCSEC,
            suffixes=('_alert', '_catalog'),
            suffix_method='overlapping_columns',
        )
        return matches.compute()

    return _read_with_retry(_read, catalog_config['name'])
