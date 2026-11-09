"""
Scoring: turns one lake's raw data into two 0-100 scores.

  * Climate Score  - how well the lake should hold up as summers get hotter
                     (deep, groundwater-fed, clean bottom, low nutrients).
  * Mosquito Score - how easy mosquitoes will be to live with on a waterfront
                     property there (few nearby wetlands, lots of wind).

For both, 100 is best. Everything here is a pure function of a lake's data
(no network, no files), so it can be tested on its own (see tests/).

Both scores follow the same pattern:
  1. Score each component 0-100 (or None when the lake has no data for it).
  2. Take a weighted average of the components that exist. The weights
     renormalize around missing data, so a gap neither helps nor hurts.
  3. Apply guardrails, so a lake with too little real data, or one that is
     too shallow, can't score highly anyway.

The reasoning and evidence behind each constant are in docs/methodology.md.
How they were checked is in docs/validation.md.
"""
import math
import re

import pandas as pd

# ---------------------------------------------------------------------------
# Climate Score: components and weights
# ---------------------------------------------------------------------------

WEIGHTS = {"volume": 0.35, "type": 0.25, "substrate": 0.25, "water_quality": 0.15}
TROUT_BONUS = 8  # trout need cold, oxygen-rich water: a free cross-check on the rest

# How a lake gets its water. Groundwater-fed (SPRING, SEEPAGE) lakes run cooler
# and import fewer nutrients than stream-fed ones. Per WDNR's definition, DRAINED
# lakes have no groundwater input at all, so they score below DRAINAGE.
LAKE_TYPE_SCORE = {"SPRING": 100, "SEEPAGE": 85, "DRAINAGE": 55, "DRAINED": 20}

# Water quality, best signal first: measured phosphorus, then WDNR's trophic
# class, then its coarser visual clarity rating.
TROPHIC_SCORE = {"OLIGOTROPHIC": 100, "MESOTROPHIC": 55, "EUTROPHIC": 15}
CLARITY_SCORE = {"VERY CLEAR": 100, "MODERATE": 60, "LOW": 30, "VERY LOW": 10}
# (Total phosphorus in ug/L, score). Anchored at the published trophic-state
# thresholds (Carlson's Trophic State Index) and set to the same scores as
# TROPHIC_SCORE there, so a real measurement never scores worse than the class.
PHOSPHORUS_ANCHORS = [(10, 100), (20, 55), (40, 15), (100, 5)]

# Volume (acre-feet = acres x depth) stands in for thermal mass. Log scale,
# because volume spans several orders of magnitude.
ACRE_FEET_FLOOR = 100      # scores 0 (about the smallest verified lake on file)
ACRE_FEET_CEILING = 20000  # scores 100 (about the 95th percentile on file)

# When only max depth is known, estimate mean depth as a fraction of it
# (on file, the median mean/max ratio is 0.44; 0.35 is deliberately
# conservative), then discount the volume score for the extra uncertainty.
UNVERIFIED_MAX_TO_MEAN_FRACTION = 0.35
UNVERIFIED_DEPTH_DISCOUNT = 0.8

# Stratification depth: a lake needs enough depth to keep a cold bottom layer
# through summer. Larger lakes get more wind, so they need more depth. The
# required mean depth grows with sqrt(acres): 20 ft at 300 acres, capped at 28 ft.
# Below it, the volume score is scaled down in proportion.
STRATIFICATION_REFERENCE_ACRES = 300
STRATIFICATION_BASE_FLOOR = 20
STRATIFICATION_FLOOR_CAP = 28

# Basin shape: a high max/mean depth ratio means a small deep hole inside a
# wide, weedy shallow shelf. On file, the median ratio is about 2.3. Above 3.0
# the volume score is scaled down, never below 60% of its value.
LITTORAL_RATIO_THRESHOLD = 3.0
LITTORAL_RATIO_FACTOR_FLOOR = 0.6

# Shallow-lake cap on the whole score: a lake 10 ft deep or less can score at
# most 50. The cap rises linearly to no cap at 20 ft, a ramp rather than a cliff.
ABSOLUTE_SHALLOW_DEPTH = 10
ABSOLUTE_SHALLOW_CAP = 50
ABSOLUTE_SHALLOW_RAMP_TOP = 20

# Confidence cap: when the components with data carry under half of the total
# weight, the score (before the trout bonus) is capped at 65.
CONFIDENCE_CAP_THRESHOLD = 0.5
CONFIDENCE_CAP_SCORE = 65

# Data sanity. 400 ft, not lower, because Wazee Lake (a flooded iron-mine pit)
# really is 355 ft deep. A max depth / sqrt(acres) ratio above 15 marks a likely
# pit or quarry lake. It's a warning flag, not a penalty: Wazee scores ~29, and
# the deepest natural lake on file ~10.7.
DEPTH_SANITY_CAP = 400
PIT_LAKE_RATIO_THRESHOLD = 15

CLIMATE_CONFIDENCE_LABELS = {4: "High", 3: "Moderate", 2: "Low", 1: "Screening only"}

# ---------------------------------------------------------------------------
# Mosquito Score: components and weights
# ---------------------------------------------------------------------------

# Nearby wetlands are the breeding source an owner can't treat away; wind
# (via lake size) keeps mosquitoes off the shore. Lake type, water quality and
# substrate are weak signals of how much weedy shoreline cover there is.
# These are the v2 weights, set after a leave-one-out ranking test (docs/validation.md).
MOSQUITO_WEIGHTS = {"wetland": 0.45, "fetch": 0.28, "type": 0.07,
                    "water_quality": 0.09, "substrate": 0.11}
MOSQUITO_CONFIDENCE_CAP_THRESHOLD = 0.5
MOSQUITO_CONFIDENCE_CAP_SCORE = 65
MOSQUITO_CONFIDENCE_LABELS = {5: "High", 4: "High", 3: "Moderate", 2: "Low", 1: "Screening only"}

# (Wetland acres near the lake, score). No published index exists for this, so
# the anchors sit on percentiles of this project's own 546-lake distribution:
# 1st, 10th, 50th, 75th, 90th and 99th.
WETLAND_ANCHORS = [(0.5, 100), (30, 85), (140, 55), (300, 35), (650, 18), (1500, 5)]

# Wind exposure, by lake size on a log scale: 75 acres (the smallest lake
# considered) scores 0 and 5,000 acres scores 100.
FETCH_ACRE_FLOOR = 75
FETCH_ACRE_CEILING = 5000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_num(value):
    """First number in a messy cell ('35 ft', '20%', 12.0, NaN), rounded to an int, or None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value))
    return round(float(m.group())) if m else None


def log_anchor_score(x, anchors):
    """Interpolate a score through (value, score) anchors on a log10(value) axis.

    Values beyond the first or last anchor get that anchor's score. Used for
    measurements that span orders of magnitude (phosphorus, wetland acres).
    """
    log_x = math.log10(max(1e-6, float(x)))
    points = [(math.log10(max(ax, 1e-6)), ay) for ax, ay in anchors]
    if log_x <= points[0][0]:
        return points[0][1]
    if log_x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x0 <= log_x <= x1:
            return y0 + (log_x - x0) / (x1 - x0) * (y1 - y0)


def _log_scale(value, floor, ceiling):
    """0 at `floor`, 100 at `ceiling`, linear in log10(value). Not clamped."""
    span = math.log10(ceiling) - math.log10(floor)
    return (math.log10(value) - math.log10(floor)) / span * 100


def _weighted_average(components):
    """components: [(score or None, weight)]. Returns (average, total weight, count) over non-None scores."""
    present = [(s, w) for s, w in components if s is not None]
    if not present:
        return None, 0.0, 0
    weight_present = sum(w for _, w in present)
    return sum(s * w for s, w in present) / weight_present, weight_present, len(present)


def has_trout(row):
    return "trout" in str(row.get("Fish Present", "")).lower()


# ---------------------------------------------------------------------------
# Component scores (each returns 0-100, or None when there's no data)
# ---------------------------------------------------------------------------

def lake_type_score(row):
    return LAKE_TYPE_SCORE.get(str(row.get("Lake Type", "")).strip().upper())


def substrate_score(row):
    """Share of the lake bottom that isn't muck."""
    muck = parse_num(row.get("Muck %"))
    return (100 - muck) if muck is not None else None


def phosphorus_score(tp_ugl):
    if tp_ugl is None:
        return None
    return log_anchor_score(tp_ugl, PHOSPHORUS_ANCHORS)


def water_quality_score(row):
    """Best available signal: measured phosphorus, then trophic status, then water clarity."""
    for score in (
        phosphorus_score(parse_num(row.get("Total Phosphorus (ug/L)"))),
        TROPHIC_SCORE.get(str(row.get("Trophic Status", "")).strip().upper()),
        CLARITY_SCORE.get(str(row.get("Water Clarity", "")).strip().upper()),
    ):
        if score is not None:
            return score
    return None


def volume_score_and_basis(acres, max_d, mean_d):
    """Score the lake's water volume, discounted for shallowness and basin shape.

    Returns (score, depth_basis, data_flags, acre_feet, depth_used). The score
    is None when no usable depth exists. depth_basis is "mean" (verified) or
    "max (unverified)" (mean estimated from max).
    """
    flags = []
    if max_d and max_d > DEPTH_SANITY_CAP:
        flags.append(f"Max depth ({max_d} ft) implausible - excluded")
        max_d = None

    if max_d and acres and (max_d / math.sqrt(acres)) > PIT_LAKE_RATIO_THRESHOLD:
        flags.append("Possible quarry/pit lake (extreme depth vs. footprint) - "
                     "verify littoral zone before relying on score")

    if mean_d is not None and (max_d is None or mean_d <= max_d):
        depth_used, basis, discount = mean_d, "mean", 1.0
    elif max_d is not None:
        depth_used = max_d * UNVERIFIED_MAX_TO_MEAN_FRACTION
        basis, discount = "max (unverified)", UNVERIFIED_DEPTH_DISCOUNT
        flags.append("No mean depth on record - basin shape/volume unverified")
    else:
        return None, "", "; ".join(flags), None, None

    acre_feet = acres * depth_used
    raw = _log_scale(max(acre_feet, 1), ACRE_FEET_FLOOR, ACRE_FEET_CEILING)

    required_depth = min(STRATIFICATION_FLOOR_CAP,
                         STRATIFICATION_BASE_FLOOR * math.sqrt(acres / STRATIFICATION_REFERENCE_ACRES))
    shallowness_factor = min(1.0, depth_used / required_depth)

    littoral_factor = 1.0
    if basis == "mean" and max_d and mean_d:  # a ratio needs a real mean depth
        ratio = max_d / mean_d
        if ratio > LITTORAL_RATIO_THRESHOLD:
            littoral_factor = max(LITTORAL_RATIO_FACTOR_FLOOR, LITTORAL_RATIO_THRESHOLD / ratio)

    score = max(0, min(100, raw)) * shallowness_factor * littoral_factor * discount
    return score, basis, "; ".join(flags), round(acre_feet), depth_used


def shallow_cap(depth_ft):
    """Highest Climate Score a lake this shallow may get (None = no cap)."""
    if depth_ft is None or depth_ft >= ABSOLUTE_SHALLOW_RAMP_TOP:
        return None
    if depth_ft <= ABSOLUTE_SHALLOW_DEPTH:
        return ABSOLUTE_SHALLOW_CAP
    frac = (depth_ft - ABSOLUTE_SHALLOW_DEPTH) / (ABSOLUTE_SHALLOW_RAMP_TOP - ABSOLUTE_SHALLOW_DEPTH)
    return ABSOLUTE_SHALLOW_CAP + frac * (100 - ABSOLUTE_SHALLOW_CAP)


def fetch_score(acres):
    """Wind exposure, by lake size."""
    if not acres:
        return None
    raw = _log_scale(max(acres, FETCH_ACRE_FLOOR), FETCH_ACRE_FLOOR, FETCH_ACRE_CEILING)
    return max(0, min(100, raw))


def wetland_score(nearby_wetland_acres):
    """Fewer wetland acres near the lake = higher score. Blank = lookup failed = None."""
    if nearby_wetland_acres in (None, ""):
        return None
    return log_anchor_score(float(nearby_wetland_acres), WETLAND_ANCHORS)


# ---------------------------------------------------------------------------
# The two scores
# ---------------------------------------------------------------------------

def score_lake(row):
    """Climate Score for one lake row.

    Returns (score, depth_basis, data_flags, acre_feet, fields_used). The score
    is None when the lake has no data for any component.
    """
    acres = row.get("Size (Acres)")
    max_d = parse_num(row.get("Official Max Depth"))
    mean_d = parse_num(row.get("Official Mean Depth"))
    vol_score, basis, flag, acre_feet, depth_used = volume_score_and_basis(acres, max_d, mean_d)

    base, weight_present, fields_used = _weighted_average([
        (vol_score, WEIGHTS["volume"]),
        (lake_type_score(row), WEIGHTS["type"]),
        (substrate_score(row), WEIGHTS["substrate"]),
        (water_quality_score(row), WEIGHTS["water_quality"]),
    ])
    if base is None:
        return None, basis, flag, acre_feet, 0

    # Guardrail 1: too little real data behind the score.
    if weight_present < CONFIDENCE_CAP_THRESHOLD:
        base = min(base, CONFIDENCE_CAP_SCORE)

    total = base + (TROUT_BONUS if has_trout(row) else 0)

    # Guardrail 2: too shallow. Applied last, after the trout bonus, so trout
    # (likely stocked in a lake this shallow) can't lift a lake past the cap.
    cap = shallow_cap(depth_used)
    if cap is not None:
        total = min(total, cap)

    return round(min(100, total), 1), basis, flag, acre_feet, fields_used


def score_mosquito(row):
    """Mosquito Score for one lake row. Returns (score or None, fields_used)."""
    base, weight_present, fields_used = _weighted_average([
        (wetland_score(row.get("Nearby Wetland Acres")), MOSQUITO_WEIGHTS["wetland"]),
        (fetch_score(row.get("Size (Acres)")), MOSQUITO_WEIGHTS["fetch"]),
        (lake_type_score(row), MOSQUITO_WEIGHTS["type"]),
        (water_quality_score(row), MOSQUITO_WEIGHTS["water_quality"]),
        (substrate_score(row), MOSQUITO_WEIGHTS["substrate"]),
    ])
    if base is None:
        return None, 0
    if weight_present < MOSQUITO_CONFIDENCE_CAP_THRESHOLD:
        base = min(base, MOSQUITO_CONFIDENCE_CAP_SCORE)
    return round(min(100, base), 1), fields_used
