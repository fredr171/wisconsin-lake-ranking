"""Scoring rules, tested on small hand-built lakes. No network or files needed."""
import math

import pytest

import scoring as s


def lake(**fields):
    """A lake row with only the given fields (column names match WDNR's export)."""
    names = {
        "acres": "Size (Acres)", "max_depth": "Official Max Depth", "mean_depth": "Official Mean Depth",
        "lake_type": "Lake Type", "muck": "Muck %", "trophic": "Trophic Status",
        "clarity": "Water Clarity", "phosphorus": "Total Phosphorus (ug/L)",
        "fish": "Fish Present", "wetland": "Nearby Wetland Acres",
    }
    return {names[k]: v for k, v in fields.items()}


# A deep, clean, groundwater-fed lake with every field present.
STRONG = dict(acres=300, max_depth=60, mean_depth=25, lake_type="SEEPAGE", muck=5, trophic="Oligotrophic")


def test_weights_sum_to_one():
    assert math.isclose(sum(s.WEIGHTS.values()), 1.0)
    assert math.isclose(sum(s.MOSQUITO_WEIGHTS.values()), 1.0)


# --- parsing and interpolation -------------------------------------------

@pytest.mark.parametrize("raw, expected", [("35 ft", 35), ("20%", 20), (12.6, 13), (float("nan"), None),
                                           (None, None), ("n/a", None)])
def test_parse_num(raw, expected):
    assert s.parse_num(raw) == expected


def test_log_anchor_score_hits_anchors_and_clamps():
    anchors = [(10, 100), (100, 0)]
    assert s.log_anchor_score(10, anchors) == 100
    assert s.log_anchor_score(math.sqrt(10 * 100), anchors) == pytest.approx(50)  # log midpoint
    assert s.log_anchor_score(1, anchors) == 100      # below the first anchor
    assert s.log_anchor_score(10_000, anchors) == 0   # above the last anchor


def test_phosphorus_matches_trophic_class_at_its_thresholds():
    # A measured value must never score worse than the coarse class it falls into.
    assert s.phosphorus_score(10) == s.TROPHIC_SCORE["OLIGOTROPHIC"]
    assert s.phosphorus_score(20) == s.TROPHIC_SCORE["MESOTROPHIC"]
    assert s.phosphorus_score(40) == s.TROPHIC_SCORE["EUTROPHIC"]


def test_water_quality_prefers_phosphorus_then_trophic_then_clarity():
    assert s.water_quality_score(lake(phosphorus="10", trophic="Eutrophic", clarity="Low")) == 100
    assert s.water_quality_score(lake(trophic="Eutrophic", clarity="Very Clear")) == 15
    assert s.water_quality_score(lake(clarity="Very Clear")) == 100
    assert s.water_quality_score(lake()) is None


# --- Climate Score --------------------------------------------------------

def test_strong_lake_scores_high_with_all_four_fields():
    score, basis, flag, _, fields_used = s.score_lake(lake(**STRONG))
    assert score > 85 and fields_used == 4 and basis == "mean" and flag == ""


def test_missing_component_neither_helps_nor_hurts():
    # Without water quality, the other three components are re-weighted, so a
    # lake whose components all score 100 still scores 100.
    perfect = dict(acres=300, mean_depth=67, max_depth=100, lake_type="SPRING", muck=0)
    score, *_, fields_used = s.score_lake(lake(**perfect))
    assert fields_used == 3 and score == 100


def test_confidence_cap_on_lake_type_alone():
    # SEEPAGE alone would be 85, but 25% of the weight isn't enough evidence.
    score, *_, fields_used = s.score_lake(lake(acres=200, lake_type="SEEPAGE"))
    assert fields_used == 1 and score == s.CONFIDENCE_CAP_SCORE


def test_no_data_at_all_is_unscored():
    assert s.score_lake(lake(acres=200))[0] is None


def test_shallow_cap_ramps_rather_than_cliffs():
    assert s.shallow_cap(8) == 50
    assert s.shallow_cap(10) == 50
    assert s.shallow_cap(15) == pytest.approx(75)
    assert s.shallow_cap(20) is None
    assert s.shallow_cap(None) is None


def test_trout_bonus_cannot_lift_a_shallow_lake_past_the_cap():
    shallow = dict(acres=100, mean_depth=8, max_depth=12, lake_type="SPRING", muck=0,
                   trophic="Oligotrophic", fish="Brook Trout, Bass")
    assert s.score_lake(lake(**shallow))[0] == s.ABSOLUTE_SHALLOW_CAP


def test_big_shallow_lake_volume_is_discounted_for_its_size():
    # Same mean depth, very different size: the big lake needs more depth to
    # stratify, so its volume score is cut by depth / required_depth.
    small, *_ = s.volume_score_and_basis(acres=100, max_d=25, mean_d=12)
    big, *_ = s.volume_score_and_basis(acres=1264, max_d=25, mean_d=12)
    big_raw = min(100, s._log_scale(1264 * 12, s.ACRE_FEET_FLOOR, s.ACRE_FEET_CEILING))
    assert big == pytest.approx(big_raw * 12 / s.STRATIFICATION_FLOOR_CAP)
    assert small == pytest.approx(min(100, s._log_scale(1200, s.ACRE_FEET_FLOOR, s.ACRE_FEET_CEILING)))


def test_littoral_ratio_penalty_only_above_threshold():
    normal, *_ = s.volume_score_and_basis(acres=300, max_d=60, mean_d=25)      # ratio 2.4
    shelf, *_ = s.volume_score_and_basis(acres=300, max_d=125, mean_d=25)      # ratio 5.0
    assert shelf == pytest.approx(normal * s.LITTORAL_RATIO_THRESHOLD / 5.0)


def test_max_depth_only_is_estimated_discounted_and_flagged():
    score, basis, flag, acre_feet, depth_used = s.volume_score_and_basis(acres=200, max_d=40, mean_d=None)
    assert basis == "max (unverified)"
    assert depth_used == pytest.approx(40 * s.UNVERIFIED_MAX_TO_MEAN_FRACTION)
    assert acre_feet == round(200 * depth_used)
    assert "No mean depth" in flag


def test_pit_lake_is_flagged_not_penalized():
    # Wazee Lake: ~146 acres, 355 ft max depth.
    _, _, flag, *_ = s.volume_score_and_basis(acres=146, max_d=355, mean_d=60)
    assert "quarry/pit" in flag


def test_impossible_depth_is_excluded():
    score, basis, flag, *_ = s.volume_score_and_basis(acres=200, max_d=900, mean_d=None)
    assert score is None and "implausible" in flag


# --- Mosquito Score -------------------------------------------------------

def test_wetland_score_direction_and_missing_data():
    assert s.wetland_score(0) == 100
    assert s.wetland_score(140) == 55
    assert s.wetland_score(5000) == 5
    assert s.wetland_score("") is None  # failed lookup, not "no wetland"


def test_fetch_score_bounds():
    assert s.fetch_score(75) == 0
    assert s.fetch_score(10) == 0
    assert s.fetch_score(5000) == 100
    assert s.fetch_score(None) is None


def test_mosquito_score_counts_fields_and_caps_thin_data():
    full, fields = s.score_mosquito(lake(**STRONG, wetland=0.5))
    assert fields == 5 and full > 50
    # Lake type + water quality + substrate = 27% of the weight: capped at 65.
    thin, fields = s.score_mosquito(lake(lake_type="SPRING", trophic="Oligotrophic", muck=0))
    assert fields == 3 and thin == s.MOSQUITO_CONFIDENCE_CAP_SCORE
