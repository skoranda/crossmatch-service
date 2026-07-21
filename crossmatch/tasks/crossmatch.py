import lsdb
import pandas as pd
from celery import shared_task
from django.conf import settings
from django.db import transaction
from core.models import Alert, CatalogMatch, Notification
from matching.catalog import crossmatch_alerts, is_transient_read_error
from matching.payload import build_catalog_payload, build_published_payload
from core.log import get_logger
from core.metrics import CATALOG_SKIPS, CROSSMATCH_BATCHES, CROSSMATCH_MATCHES
logger = get_logger(__name__)


@shared_task(name="crossmatch_batch")
def crossmatch_batch(batch_ids: list, match_version: int = 1) -> None:
    """Process a batch of alerts through LSDB crossmatch against all catalogs.

    Args:
        batch_ids: List of alert UUID strings passed from the dispatcher.
        match_version: Schema version for match results.
    """
    if not batch_ids:
        logger.info('No batch IDs provided')
        return

    logger.info('Starting crossmatch batch',
                batch_size=len(batch_ids), match_version=match_version,
                catalogs=len(settings.CROSSMATCH_CATALOGS))
    try:
        # 1. Load alerts into DataFrame (once for all catalogs)
        alerts_qs = Alert.objects.filter(pk__in=batch_ids)
        alerts_df = pd.DataFrame(
            alerts_qs.values_list(
                'uuid', 'lsst_diaObject_diaObjectId', 'ra_deg', 'dec_deg'
            ),
            columns=['uuid', 'lsst_diaObject_diaObjectId', 'ra_deg', 'dec_deg']
        )
        # Convert UUID objects to strings so PyArrow can serialize them
        alerts_df['uuid'] = alerts_df['uuid'].astype(str)

        if alerts_df.empty:
            logger.warning('No alerts found for batch IDs',
                           batch_size=len(batch_ids))
            return

        # Build LSDB alerts catalog once, reuse for all reference catalogs
        clean_df = alerts_df.dropna(subset=['ra_deg', 'dec_deg'])
        if clean_df.empty:
            logger.warning('No alerts with valid coordinates to crossmatch')
            Alert.objects.filter(pk__in=batch_ids).update(
                status=Alert.Status.MATCHED
            )
            return
        alerts_catalog = lsdb.from_dataframe(
            clean_df, ra_column='ra_deg', dec_column='dec_deg'
        )

        # 2. Crossmatch against each configured catalog sequentially.
        # Accumulate notifications across all catalogs and create them together
        # with the MATCHED status update in one transaction at the end (step 4),
        # so a PENDING notification is never visible to dispatch_notifications
        # before its alert is MATCHED. Otherwise dispatch can send a notification
        # and run its MATCHED-gated transition while the alert is still QUEUED;
        # the transition no-ops and single-match alerts get stuck at MATCHED.
        # Track per-catalog outcome across the loop. A catalog "succeeds" when its
        # read completes -- matches, empty, or no-overlap all count; only a read
        # error (retries exhausted) is a skip. Best-effort resilience (R1/R2): one
        # persistently-failing catalog is skipped, not fatal. The >=1-success guard
        # (R3) below still fails the whole batch closed when EVERY catalog errored,
        # so a broad outage reverts instead of publishing empty crossmatches.
        succeeded_catalogs = set()
        skipped_catalogs = set()
        all_notifications = []
        for catalog_config in settings.CROSSMATCH_CATALOGS:
            catalog_name = catalog_config['name']
            source_id_col = catalog_config['source_id_column']
            ra_col = catalog_config['ra_column']
            dec_col = catalog_config['dec_column']
            payload_cols = catalog_config.get('payload_columns', [])

            try:
                result_df = crossmatch_alerts(alerts_catalog, catalog_config)
            except Exception as exc:
                # No spatial overlap is normal, not an error: the batch footprint
                # misses this catalog's footprint (e.g. DES's southern-only sky).
                # Counts as a success -- the catalog was read, it just has nothing
                # here -- so it must not trip the >=1-success guard below.
                if (isinstance(exc, RuntimeError)
                        and "Catalogs do not overlap" in str(exc)):
                    logger.info('No spatial overlap with catalog',
                                catalog=catalog_name, total=len(clean_df))
                    succeeded_catalogs.add(catalog_name)
                    continue
                # Decide skip-vs-fail-loud by the transient classification, not by
                # exception type. A DETERMINISTIC error -- a bad/missing/colliding
                # column raised by _get_catalog (ValueError), or a dependency/
                # version-skew mismatch -- must still fail loud so the batch reverts
                # and the misconfiguration is surfaced, rather than silently dropping
                # that catalog from every future batch.
                if not is_transient_read_error(exc):
                    logger.exception('Crossmatch failed for catalog',
                                     catalog=catalog_name)
                    raise
                # A transient read failure whose retries in matching/catalog.py are
                # exhausted (a source host that stays down under load). Skip this
                # catalog and continue rather than aborting the whole batch and
                # rolling back the catalogs that DID succeed (R1). The alert is
                # finalized best-effort with the rest; the skip is marked in the
                # published payload (R4) and counted for operators (R5).
                logger.warning('Catalog skipped after transient read failure',
                               catalog=catalog_name, error=str(exc))
                skipped_catalogs.add(catalog_name)
                CATALOG_SKIPS.labels(catalog=catalog_name).inc()
                continue

            succeeded_catalogs.add(catalog_name)
            if result_df.empty:
                logger.info('No matches found',
                            catalog=catalog_name, total=len(clean_df))
                continue

            # Rename _dist_arcsec so itertuples() can access it
            # (namedtuple fields cannot start with underscore)
            result_df = result_df.rename(columns={'_dist_arcsec': 'dist_arcsec'})

            # 3. Build CatalogMatch and Notification rows in a single pass.
            # Each row is built defensively: an unexpected value in one row logs
            # and skips that row without dropping the rest of the catalog's
            # matches or aborting the batch (R8). Both records are appended only
            # after both are built, so the two lists stay aligned.
            matches_to_create = []
            notifications_to_create = []
            for row in result_df.itertuples(index=False):
                try:
                    dia_id = row.lsst_diaObject_diaObjectId
                    src_id = str(getattr(row, source_id_col))
                    dist = row.dist_arcsec
                    ra = getattr(row, ra_col)
                    dec = getattr(row, dec_col)

                    # Catalog-specific core columns: lowercase keys, JSON-native
                    # values, stable key set (see matching/payload.py). Stored on
                    # the match record and nested under 'catalog_payload' in the
                    # published notification; top-level metadata is unchanged.
                    catalog_payload = build_catalog_payload(
                        {col: getattr(row, col) for col in payload_cols},
                        payload_cols,
                    )

                    match = CatalogMatch(
                        alert_id=dia_id,
                        catalog_name=catalog_name,
                        catalog_source_id=src_id,
                        match_distance_arcsec=dist,
                        source_ra_deg=ra,
                        source_dec_deg=dec,
                        catalog_payload=catalog_payload,
                        match_version=match_version,
                    )
                    notification = Notification(
                        alert_id=dia_id,
                        destination='hopskotch',
                        payload=build_published_payload(
                            dia_id, ra, dec, catalog_name, src_id, dist, catalog_payload
                        ),
                    )
                except Exception:
                    logger.exception('Skipping unbuildable match row',
                                     catalog=catalog_name)
                    continue
                matches_to_create.append(match)
                notifications_to_create.append(notification)

            CatalogMatch.objects.bulk_create(
                matches_to_create, batch_size=5000, ignore_conflicts=True
            )
            all_notifications.extend(notifications_to_create)
            CROSSMATCH_MATCHES.labels(catalog=catalog_name).inc(len(matches_to_create))
            logger.info('Wrote matches, queued notifications',
                        catalog=catalog_name,
                        matched=len(matches_to_create), total=len(clean_df))

        sorted_skipped = sorted(skipped_catalogs)

        # >=1-success guard (R3): if EVERY catalog's read errored (a broad outage,
        # not real "no matches"), fail the batch closed so the outer handler
        # reverts it to INGESTED and it retries -- rather than finalizing alerts
        # with zero matches. A skipped catalog does not count as a success (KTD5).
        if not succeeded_catalogs:
            raise RuntimeError(
                f'All {len(settings.CROSSMATCH_CATALOGS)} catalogs failed to read '
                f'for this batch; reverting rather than publishing empty '
                f'crossmatches (skipped={sorted_skipped})'
            )

        # Mark coverage (R4): stamp each published notification with the catalogs
        # skipped in this batch so a consumer can tell what the crossmatch covered.
        # The full skipped set is only known now -- a later catalog can fail after
        # an earlier one's notifications were built -- so stamp after the loop.
        # (No-skip batches keep the build-time default: catalogs_skipped=[],
        # partial=False.)
        if skipped_catalogs:
            for notification in all_notifications:
                notification.payload['catalogs_skipped'] = sorted_skipped
                notification.payload['partial'] = True

        # 4. Create notifications and transition ALL alerts to MATCHED atomically,
        # so notifications become dispatchable exactly when (not before) their
        # alerts are MATCHED. See the note at step 2.
        with transaction.atomic():
            Notification.objects.bulk_create(
                all_notifications, batch_size=5000
            )
            Alert.objects.filter(pk__in=batch_ids).update(
                status=Alert.Status.MATCHED
            )
        CROSSMATCH_BATCHES.labels(result='completed').inc()
        logger.info('Crossmatch batch complete',
                    batch_size=len(batch_ids),
                    notifications=len(all_notifications),
                    catalogs_succeeded=len(succeeded_catalogs),
                    catalogs_skipped=sorted_skipped)

    except Exception:
        CROSSMATCH_BATCHES.labels(result='failed').inc()
        logger.exception('Crossmatch batch failed, reverting to INGESTED',
                         batch_size=len(batch_ids))
        try:
            Alert.objects.filter(pk__in=batch_ids).update(
                status=Alert.Status.INGESTED, queued_at=None
            )
        except Exception:
            logger.exception('Failed to revert batch status')
        raise
