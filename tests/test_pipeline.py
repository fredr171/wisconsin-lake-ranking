"""Pipeline behavior that doesn't need the network: parsing, caching, failure handling."""
import os

import pytest

import build_listing_report as report
import lake_finder as lf

WDNR_PAGE = """
<html><body>
  <h3>Trophic Status</h3><p>Mesotrophic</p>
  <h3>Bottom</h3><p>50% sand, 20% gravel, 10% rock, 20% muck</p>
</body></html>
"""


def test_parse_lake_detail_reads_substrate_and_trophic():
    assert lf.parse_lake_detail(WDNR_PAGE) == {
        "Sand %": "50", "Gravel %": "20", "Rock %": "10", "Muck %": "20", "Trophic Status": "Mesotrophic"}


def test_parse_lake_detail_page_without_those_sections():
    assert lf.parse_lake_detail("<html><body><p>Fish: walleye</p></body></html>") == {
        "Sand %": "", "Gravel %": "", "Rock %": "", "Muck %": "", "Trophic Status": ""}


def test_normalize_lake_name_drops_suffixes_and_punctuation():
    assert lf.normalize_lake_name("Big Sand Lake") == "BIG SAND"
    assert lf.normalize_lake_name("Lac Courte Oreilles") == "LAC COURTE OREILLES"
    assert lf.normalize_lake_name("Chippewa Flowage (Lake)") == "CHIPPEWA"


def test_wetland_buffer_grows_with_size_and_is_capped():
    assert lf.wetland_buffer_meters(100) < lf.wetland_buffer_meters(1000)
    assert lf.wetland_buffer_meters(100_000) == lf.WETLAND_BUFFER_MAX_METERS


def test_with_retries_recovers_then_gives_up():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise OSError("server busy")
        return "ok"

    assert lf.with_retries(flaky, retries=3, backoff_seconds=0) == "ok"
    assert lf.with_retries(lambda: 1 / 0, retries=2, backoff_seconds=0) is None


def test_write_atomic_keeps_old_file_when_writer_fails(tmp_path):
    path = tmp_path / "cache.csv"
    path.write_text("old")

    def broken_writer(f):
        f.write("half a fi")
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError):
        lf.write_atomic(str(path), broken_writer)
    assert path.read_text() == "old"
    assert os.listdir(tmp_path) == ["cache.csv"]  # temp file cleaned up


def _lakes(*wbics):
    return [{lf.WBIC: w, "Latitude": 46.0, "Longitude": -91.0, "Size (Acres)": 200} for w in wbics]


def test_failed_wetland_lookup_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "WETLAND_CACHE", str(tmp_path / "wetland_cache.csv"))
    monkeypatch.setattr(lf, "fetch_wetland_acres", lambda lat, lon, acres: None)
    out = lf.add_wetland_data(_lakes(1))
    assert out[0]["Nearby Wetland Acres"] == ""

    # Next run, the service is back: the lake is looked up again, not served from cache.
    monkeypatch.setattr(lf, "fetch_wetland_acres", lambda lat, lon, acres: 12.5)
    out = lf.add_wetland_data(_lakes(1))
    assert out[0]["Nearby Wetland Acres"] == 12.5


def test_zero_wetland_acres_is_a_real_cached_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "WETLAND_CACHE", str(tmp_path / "wetland_cache.csv"))
    monkeypatch.setattr(lf, "fetch_wetland_acres", lambda lat, lon, acres: 0.0)
    lf.add_wetland_data(_lakes(1))
    monkeypatch.setattr(lf, "fetch_wetland_acres", lambda *a: pytest.fail("should come from cache"))
    assert lf.add_wetland_data(_lakes(1))[0]["Nearby Wetland Acres"] == "0.0"


def test_failed_phosphorus_query_caches_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "PHOSPHORUS_CACHE", str(tmp_path / "phosphorus_cache.csv"))
    monkeypatch.setattr(lf, "build_phosphorus_lookup", lambda lakes: None)
    lf.add_phosphorus_data(_lakes(1, 2))
    assert not (tmp_path / "phosphorus_cache.csv").exists()


def test_failed_lake_page_is_retried_next_run(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "DETAILS_CACHE", str(tmp_path / "details.csv"))
    monkeypatch.setattr(lf, "with_retries", lambda func, retries, backoff_seconds: None)
    assert "Muck %" not in lf.scrape_lake_details(_lakes(1))[0]

    monkeypatch.setattr(lf, "with_retries", lambda func, retries, backoff_seconds: WDNR_PAGE)
    assert lf.scrape_lake_details(_lakes(1))[0]["Muck %"] == "20"


def test_coordinates_outside_wisconsin_are_rejected():
    assert lf.in_wisconsin(45.9, -91.5)
    assert not lf.in_wisconsin(0.0, 0.0)            # seen in WDNR's export
    assert not lf.in_wisconsin(float("nan"), -91.5)
    assert not lf.in_wisconsin(44.98, -93.27)       # Minneapolis


def test_bad_coordinates_are_skipped_and_dropped_signs_repaired(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "DRIVE_TIME_CACHE", str(tmp_path / "drive.csv"))
    monkeypatch.setattr(lf, "drive_route", lambda lat1, lon1, lat2, lon2: (100.0, 2.0) if lon2 < 0 else None)
    lakes = [
        {lf.WBIC: 1, "Latitude": 45.77, "Longitude": 90.65, "Size (Acres)": 200},   # sign dropped
        {lf.WBIC: 2, "Latitude": 0.0, "Longitude": 0.0, "Size (Acres)": 200},      # null island
    ]
    kept = lf.filter_candidates(lakes, 45.0, -93.0)
    assert [(k[lf.WBIC], k["Longitude"]) for k in kept] == [(1, -90.65)]


def test_unroutable_lake_is_neither_kept_nor_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "DRIVE_TIME_CACHE", str(tmp_path / "drive.csv"))
    monkeypatch.setattr(lf, "drive_route", lambda *a: (None, None))
    lakes = [{**lake, "Lake Name": "Test"} for lake in _lakes(1)]
    assert lf.filter_candidates(lakes, 45.0, -93.0) == []
    assert "1," not in (tmp_path / "drive.csv").read_text()


# --- listing page ----------------------------------------------------------

def test_zillow_override_beats_automatic_box():
    wbic = next(iter(report.MAP_BOUNDS))
    west = report.MAP_BOUNDS[wbic][0]
    assert f"{west}" in report.urllib.parse.unquote(report.zillow_search_url(wbic, 46.0, -91.0, 200))


def test_automatic_zillow_box_is_centered_on_the_lake():
    url = report.urllib.parse.unquote(report.zillow_search_url(-1, 46.0, -91.0, 400))
    radius = (report.RADIUS_FLOOR_MILES + 20 * report.RADIUS_ACRES_SCALE) / report.MILES_PER_DEGREE_LAT
    assert f'"south": {46.0 - radius}' in url and f'"north": {46.0 + radius}' in url


def test_overall_rank_falls_back_to_climate_score():
    assert report.overall_rank_score({"Climate Score": 80, "Mosquito Score": ""}) == 80
    assert report.overall_rank_score({"Climate Score": 80, "Mosquito Score": 60}) == pytest.approx(72)
