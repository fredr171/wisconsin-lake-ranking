# Validation log

How the scoring was checked, what that turned up, and what changed as a result.

The working rule: **a claim gets checked against the data or the live source before
anything changes**, whether it comes from me, from an AI reviewer, or from a formula that
"looks reasonable". Each entry below is something that check caught.

## 1. Every data source was tested live before any code used it

- **WDNR lake pages, the Wetland Inventory and the Water Quality Portal** were each queried
  by hand against a known lake, and the response format was confirmed, before any
  pipeline step was written for them.
- **Zillow search by name doesn't work for lakes.** "Silver Lake, Barron County, WI"
  opened the Silver Lake neighborhood of Los Angeles. Links are built from coordinates
  instead.
- **OSRM rejected as a backup router.** An AI review suggested it as a fallback. Checking
  showed its public demo server is limited to 1 request per second, stricter than
  Valhalla, and it had already been dropped earlier for inaccurate travel times.
- **Valhalla's failure mode was measured.** About 73% of requests failed at 10 concurrent,
  and the failures were silent. Hence the 4-worker cap, retry with backoff, and reporting
  unroutable lakes as unrouted rather than out of range.

## 2. Data-quality catches

| What looked wrong | What checking showed | Outcome |
|---|---|---|
| A Barron County lake (WBIC 2081200) with 106 ft max depth but 3 ft mean depth | Matches WDNR's own page | Kept as genuine |
| Drained lakes always scoring low | WDNR's definition: Drained lakes have zero groundwater input, worse than Drainage for this purpose | Ordering confirmed (Drained 20 < Drainage 55) |
| Substrate adding up to 115% on some rows | That's what WDNR publishes | Documented as a limitation |
| A 355 ft lake failing the original 150 ft depth sanity cap | Wazee Lake is a real flooded iron-mine pit | Cap raised to 400 ft, plus the pit/quarry flag |
| Lake Onalaska (8,391 acres of Mississippi River backwater, known for dense marsh) returning 0 wetland acres and the top Mosquito Score (91.6) | Points along that whole river stretch return no wetlands: a coverage gap in WDNR's inventory, not a scoring bug | Documented as a limitation; the score's confidence fields already show it |
| One lake that the routing server could never route, on any retry | WDNR's export lists it at latitude 0, longitude 0. Scanning the whole export found 251 lakes at (0, 0) and 13 more with the longitude's minus sign dropped (placing them in China) | Coordinates outside Wisconsin are skipped with a warning; a dropped minus sign is repaired and counted |
| First wetland anchors (single-digit acres = "clean") | Picked by guess. On the real distribution, all but the cleanest ~5% of lakes landed at the bottom of the scale | Anchors re-set on real percentiles; scores now spread across 0-100 |

## 3. Climate Score: changes from review rounds

A CSV export of the results went through several rounds of independent AI review. Each
concrete claim was checked against WDNR data or computed directly on the dataset.

**Adopted, because they held up:**
- **Confidence cap.** A lake known only by its lake-type label scored 85 and outranked
  lakes with measured depth and substrate.
- **Absolute shallow cap**, later changed from a hard cutoff to a ramp. An 8 ft lake
  scored 73.5 on good type, substrate and trout. The first fix was a hard cutoff at 10 ft,
  which let a 12 ft lake score in the 80s while a 9.9 ft lake was held to 50.
- **Max/mean depth ratio** for basin shape.
- **A real bug:** the trout bonus was added *after* the shallow cap and could push a
  shallow lake back over it. The cap now runs last (pinned by
  `test_trout_bonus_cannot_lift_a_shallow_lake_past_the_cap`).
- **Total phosphorus and the pit/quarry flag**, from a review asked to address the known
  limitations. Phosphorus anchors were checked against Carlson's Trophic State Index, not
  taken from the review.

**Rejected, because they didn't survive a check:**
- A "DNR stratification test" claiming several deep, well-documented lakes don't
  stratify. No such test exists.
- A lake's substrate described as "mediocre" when the file says 98% clean.
- One review round was discarded entirely after its spot-checks contained errors like these.

**Deferred:** watershed and land-use data. It does exist on WDNR's open data portal, but
it needs a real GIS pipeline (spatial joins, land-cover rasters).

## 4. Mosquito Score: the second review round

The finished implementation (formula, weights, anchors and the real distribution from a
546-lake run) was sent separately to two AI models for critique.

**Adopted: lower weight on lake type.** Both reviews flagged lake type (15% at the time)
as overweighted. A leave-one-component-out test supported this. Each component was dropped
in turn, and the new ranking was compared with the full ranking (Spearman rank correlation):

| Component dropped | Spearman ρ vs. full ranking |
|---|---|
| Water quality | 0.989 |
| Substrate | 0.979 |
| Lake type | 0.978 |
| Wind exposure | 0.903 |
| Nearby wetland | 0.667 |

Dropping lake type barely changed the order, while wetland and wind carry most of the
signal. Weight moved from lake type to wetland and wind (the v2 weights in `scoring.py`).

**Rejected:**
- *"Raw wetland acreage is biased by lake size"* (bigger lake, bigger search circle, more
  wetland found), with a proposed switch to wetland density. Measured: the correlation
  between wetland acres and lake size is 0.092. The bias isn't there, so the fix wasn't
  applied.
- *"Water quality and substrate are near-duplicates, drop one."* Measured correlation:
  0.30. Both kept.
- *"Flip lake type's direction (groundwater lakes are worse for mosquitoes)."* Uncited, and
  there's no way to check it against this data. The weight was cut; the direction was left
  alone.
- *"Hard-cap river and flowage lakes with 0 wetland acres"* (aimed at Lake Onalaska). Too
  specific to one river system, and inconsistent with the pit-lake flag, which is a general
  rule rather than a named-lake exception. The other review's view, that this is a
  data-confidence problem already shown by the confidence columns, matched the existing
  design and stands.

**Left as future work:** distance-weighting wetlands within the search circle, and a
wetland × wind interaction term. Both are plausible, but there's no ground truth to test
them against.

## 5. Reliability fixes made while preparing this repository

The pipeline was refactored (scoring moved into `scoring.py`) and re-run from a new start
point. For all 546 lakes the old and new runs share, the Climate Score, Mosquito Score,
fields-used counts, volumes and data flags match exactly.

Re-reading the pipeline for publication turned up three ways a **transient failure could
become permanent, wrong data**. In each case the failure was written to the cache, so later
runs never retried it:

- **Lake page fetch fails** → cached as "no substrate data", so the lake scored without
  substrate forever.
- **Wetland lookup fails** → cached as blank.
- **Water Quality Portal down** → every lake in the batch cached as "no phosphorus station".

A fourth gap: the drive-time cache was written only after all routing finished. Routing
about 1,300 lakes on the free server takes about half an hour, and an interruption lost all of
it. The cache is now saved every 100 lakes.

Now nothing is cached unless the lookup succeeded, and a warning names how many lookups
failed. Older all-blank lake-page cache rows, which can't be told apart from failures, are
fetched once more and then marked `Page Fetched = yes`. Cache files and downloads are also
written atomically (temp file + rename), so an interrupted run can't leave a truncated
cache. Tests in `tests/test_pipeline.py` cover each case.
