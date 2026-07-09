
# Why HEALPix Alert Clustering Is Better Than Using Rubin Visit Pointings for Gaia Cross-Matching

When cross-matching large batches of Rubin Observatory (LSST) alerts against a large catalog such as **Gaia stored in HATS format**, a common question is whether telescope **visit pointing information** can be used to restrict the search region. While this seems intuitive, in practice **grouping alerts by HEALPix cell is usually more efficient and scalable**.

This document explains why.

---

## 1. Alerts Already Provide Precise Sky Positions

Each LSST alert includes precise sky coordinates:

- `ra`
- `dec`
- astrometric uncertainties (~10–20 milliarcseconds)

Cross-matching is fundamentally a **point-based spatial query**:

(alert_ra, alert_dec) × Gaia catalog

Visit pointings only give the **center of a ~3.5° field**, which is far less precise than the alert coordinates themselves.

---

## 2. HATS Catalogs Are Indexed by HEALPix

Gaia catalogs stored in **HATS format** are partitioned by **HEALPix cells**.

The real performance bottleneck in cross-matching is determining:

which HEALPix tiles must be loaded

If alerts are grouped by HEALPix index, the workflow becomes:

alerts → HEALPix cell → Gaia HATS partition

This directly matches the catalog storage layout and minimizes disk reads.

---

## 3. Rubin Visit Footprints Are Too Large

A Rubin visit covers approximately:

- ~9.6 square degrees
- ~3.5° diameter

Gaia HATS partitions are typically much smaller:

- ~0.1–0.5 square degrees

This means a visit footprint intersects **dozens of HATS partitions**.

Using visit footprints therefore loads **many partitions that contain no alerts**, increasing I/O overhead.

HEALPix clustering loads **only tiles that actually contain alerts**.

---

## 4. Planned Visits Do Not Match Actual Alert Distribution

Visit-based filtering assumes alerts fill the entire field.

In reality:

- alerts are sparse
- only small parts of the field contain detections
- some CCDs may be masked or unusable

Using visit footprints therefore loads many Gaia tiles unnecessarily.

---

## 5. Alerts May Come From Multiple Visits

Even if processing a batch of 100k alerts, they may originate from:

- multiple visits
- multiple filters
- multiple nights

Visit-based grouping requires:

- timestamp heuristics
- footprint reconstruction
- visit identification

HEALPix clustering works automatically regardless of visit structure.

---

## 6. HEALPix Grouping Scales Better

For high-volume alert streams (millions per night), HEALPix batching naturally supports parallelization:

alerts → HEALPix cell → partition → crossmatch

Advantages:

- work units align with catalog partitions
- easier parallel processing
- simpler caching of Gaia tiles
- predictable performance scaling

Visit-based grouping does not align with the storage layout.

---

## 7. Simpler Implementation

HEALPix grouping only requires:

- `ra`
- `dec`

No external metadata is required.

Visit-based grouping requires:

- HEROIC visit metadata
- visit center extraction
- footprint geometry calculations
- possible corrections for dithering

---

## Summary

HEALPix clustering is usually superior for large-scale LSST alert cross-matching because:

- it uses **exact alert coordinates**
- it aligns directly with **HATS partitioning**
- it loads **only Gaia tiles containing alerts**
- it avoids reliance on **visit metadata**
- it scales efficiently to **millions of alerts**

Visit pointing information can be useful for **observatory operations or survey analysis**, but for **catalog cross-matching performance**, grouping alerts by **HEALPix cell is typically the optimal strategy**.
