"""Generic LSDB HATS catalog crossmatch."""

import lsdb
import pandas as pd
from django.conf import settings
from core.log import get_logger

logger = get_logger(__name__)

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
    catalog = _get_catalog(catalog_config)
    # Alert DataFrame uses ra_deg/dec_deg; catalog RA/Dec and payload column
    # names vary (e.g. 'ra'/'dec' for Gaia, 'RA'/'DEC' for DES). The loaded set
    # is now the full payload_columns union, but none overlap the alert columns
    # (_get_catalog rejects any that do via _ALERT_COLUMNS), so
    # suffix_method='overlapping_columns' leaves the catalog columns un-suffixed.
    matches = alerts_catalog.crossmatch(
        catalog,
        n_neighbors=1,
        radius_arcsec=settings.CROSSMATCH_RADIUS_ARCSEC,
        suffixes=('_alert', '_catalog'),
        suffix_method='overlapping_columns',
    )
    return matches.compute()
