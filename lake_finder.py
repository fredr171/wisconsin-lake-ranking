"""
Pipeline: find every Wisconsin lake within a drive-time limit, gather its
data from public sources, score it, and write output/Lake Report.xlsx.

Run: `python lake_finder.py` (settings in config.py).

Steps, in the order main() runs them:
  1. geocode_start              START_ADDRESS -> coordinates          (OpenStreetMap Nominatim)
  2. find_candidate_counties    counties whose seat is roughly in range (Valhalla routing)
  3. compile_lakes              every lake in those counties           (WDNR statewide export)
  4. filter_candidates          big enough + real per-lake drive time  (Valhalla routing)
  5. scrape_lake_details        bottom substrate + trophic status      (WDNR lake pages)
  6. add_phosphorus_data        measured total phosphorus              (EPA Water Quality Portal)
  7. add_wetland_data           wetland acres near each lake           (WDNR Wetland Inventory)
  8. build_excel                score (see scoring.py) and export

Reliability rules the code follows:
  * Cheap filters run before expensive lookups, so nothing is fetched just to
    be thrown away.
  * Every expensive result is cached in data/ by lake ID (WBIC), so a re-run
    fetches only what's new. Caches and downloads are written atomically, so
    an interrupted run never leaves a half-written file behind.
  * A failed lookup is retried with backoff and is never cached, so the next
    run tries it again. It shows up as missing data, never as a real-looking
    value: a lake that can't be routed is reported as unrouted, not "too far".
"""
import concurrent.futures
import csv
import datetime
import json
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO

import pandas as pd
from bs4 import BeautifulSoup

import config
from scoring import (
    CLIMATE_CONFIDENCE_LABELS,
    MOSQUITO_CONFIDENCE_LABELS,
    has_trout,
    parse_num,
    score_lake,
    score_mosquito,
)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
OUTPUT_DIR = os.path.join(BASE, "output")

# Caches that depend on START_ADDRESS (rebuilt when it changes, see geocode_start).
START_POINT_CACHE = os.path.join(DATA_DIR, "start_point.json")
COUNTIES_CACHE = os.path.join(DATA_DIR, "counties_cache.csv")
DRIVE_TIME_CACHE = os.path.join(DATA_DIR, "drive_time_cache.csv")
LAKES_COMPILED = os.path.join(DATA_DIR, "lakes_compiled.csv")  # step 3 snapshot, for inspection only
# Caches that depend only on the lake, valid for any start point.
BULK_LAKES_XLSX = os.path.join(DATA_DIR, "wi_lakes_bulk.xlsx")
DETAILS_CACHE = os.path.join(DATA_DIR, "lake_details_cache.csv")
WQP_STATIONS_CACHE = os.path.join(DATA_DIR, "wqp_stations_cache.csv")
PHOSPHORUS_CACHE = os.path.join(DATA_DIR, "phosphorus_cache.csv")
WETLAND_CACHE = os.path.join(DATA_DIR, "wetland_cache.csv")

OUT_XLSX = os.path.join(OUTPUT_DIR, "Lake Report.xlsx")

USER_AGENT = "wisconsin-lake-ranking/1.0 (non-commercial lake research script)"
WBIC = "Waterbody ID Code (WBIC)"  # WDNR's unique lake ID: the join key for every cache

WORKERS = 10       # concurrent requests to WDNR, which handles this fine
ROUTE_WORKERS = 4  # Valhalla's free server silently fails most requests above ~4 concurrent
COUNTY_DRIVE_BUFFER_HOURS = 0.75  # a county's near edge can be well closer than its seat

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"
WDNR_BULK_EXPORT_URL = (
    "https://apps.dnr.wi.gov/lakes/lakepages/Results.aspx?advanced=true&location=ANY"
    "&name=ANY&latitude=ANY&longitude=ANY&clarity=ANY&boatord=ANY&bottom=ANY"
    "&sizeRange=ANY&toExcel=true")
WDNR_LAKE_PAGE_URL = "https://apps.dnr.wi.gov/lakes/lakepages/LakeDetail.aspx?wbic={wbic}&page=facts"
WQP_STATIONS_URL = (
    "https://www.waterqualitydata.us/data/Station/search?statecode=US:55"
    "&siteType=Lake%2C%20Reservoir%2C%20Impoundment&mimeType=csv&zip=no")
WQP_RESULTS_URL = "https://www.waterqualitydata.us/data/Result/search"
# Layer 8 = "Wetland Class Areas" only. Open water is a separate layer, so a
# lake's own surface is never counted as wetland near itself.
WETLAND_LAYER_URL = ("https://dnrmaps.wi.gov/arcgis/rest/services/DW_Map_Dynamic/"
                     "WT_Wisconsin_Wetland_Inventory_NWI_WTM_Ext_Dynamic_L16/MapServer/8/query")

WI_COUNTY_SEATS = {
    "Adams": "Friendship", "Ashland": "Ashland", "Barron": "Barron", "Bayfield": "Washburn",
    "Brown": "Green Bay", "Buffalo": "Alma", "Burnett": "Siren", "Calumet": "Chilton",
    "Chippewa": "Chippewa Falls", "Clark": "Neillsville", "Columbia": "Portage",
    "Crawford": "Prairie du Chien", "Dane": "Madison", "Dodge": "Juneau", "Door": "Sturgeon Bay",
    "Douglas": "Superior", "Dunn": "Menomonie", "Eau Claire": "Eau Claire", "Florence": "Florence",
    "Fond du Lac": "Fond du Lac", "Forest": "Crandon", "Grant": "Lancaster", "Green": "Monroe",
    "Green Lake": "Green Lake", "Iowa": "Dodgeville", "Iron": "Hurley", "Jackson": "Black River Falls",
    "Jefferson": "Jefferson", "Juneau": "Mauston", "Kenosha": "Kenosha", "Kewaunee": "Kewaunee",
    "La Crosse": "La Crosse", "Lafayette": "Darlington", "Langlade": "Antigo", "Lincoln": "Merrill",
    "Manitowoc": "Manitowoc", "Marathon": "Wausau", "Marinette": "Marinette", "Marquette": "Montello",
    "Menominee": "Keshena", "Milwaukee": "Milwaukee", "Monroe": "Sparta", "Oconto": "Oconto",
    "Oneida": "Rhinelander", "Outagamie": "Appleton", "Ozaukee": "Port Washington", "Pepin": "Durand",
    "Pierce": "Ellsworth", "Polk": "Balsam Lake", "Portage": "Stevens Point", "Price": "Phillips",
    "Racine": "Racine", "Richland": "Richland Center", "Rock": "Janesville", "Rusk": "Ladysmith",
    "Sauk": "Baraboo", "Sawyer": "Hayward", "Shawano": "Shawano", "Sheboygan": "Sheboygan",
    "St. Croix": "Hudson", "Taylor": "Medford", "Trempealeau": "Whitehall", "Vernon": "Viroqua",
    "Vilas": "Eagle River", "Walworth": "Elkhorn", "Washburn": "Shell Lake", "Washington": "West Bend",
    "Waukesha": "Waukesha", "Waupaca": "Waupaca", "Waushara": "Wautoma", "Winnebago": "Oshkosh",
    "Wood": "Wisconsin Rapids",
}


# ---------------------------------------------------------------------------
# HTTP and file helpers
# ---------------------------------------------------------------------------

def fetch_bytes(url, method="GET", body=None, headers=None, timeout=20):
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_json(url, **kwargs):
    return json.loads(fetch_bytes(url, **kwargs).decode())


def with_retries(func, retries, backoff_seconds):
    """Call func(); on any exception wait backoff_seconds * attempt and retry. None if every try fails."""
    for attempt in range(retries + 1):
        try:
            return func()
        except Exception:
            if attempt < retries:
                time.sleep(backoff_seconds * (attempt + 1))
    return None


def write_atomic(path, write_func, mode="w"):
    """Write to a temp file in the same folder, then rename it over `path`.
    An interrupted run leaves either the old file or the new one, never half of one."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        kwargs = {} if "b" in mode else {"newline": "", "encoding": "utf-8"}
        with os.fdopen(fd, mode, **kwargs) as f:
            write_func(f)
        os.replace(tmp, path)
    except BaseException:
        os.remove(tmp)
        raise


def download_once(url, path, description, timeout):
    """Download a large reference file to `path` unless it is already there."""
    if not os.path.exists(path):
        print(f"  downloading {description} (one-time)...")
        data = fetch_bytes(url, timeout=timeout)
        write_atomic(path, lambda f: f.write(data), mode="wb")


def read_csv_cache(path, key="WBIC"):
    """Cache file -> {key: row dict}. Missing file = empty cache."""
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r[key]: r for r in csv.DictReader(f)}


def write_csv_cache(path, fieldnames, rows):
    rows = sorted(rows, key=lambda r: str(r[fieldnames[0]]))

    def write(f):
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    write_atomic(path, write)


def run_parallel(func, items, workers, label, report_every):
    """Map func over items in a thread pool, printing progress. Yields results in input order."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for done, result in enumerate(ex.map(func, items), start=1):
            if done % report_every == 0:
                print(f"  {done}/{len(items)} {label}")
            yield result


# Wisconsin's bounding box, slightly padded. WDNR's export places 251 lakes at (0, 0)
# and lists 13 with a positive longitude (minus sign dropped), so coordinates are checked.
WI_LAT_RANGE = (42.4, 47.4)
WI_LON_RANGE = (-93.0, -86.7)


def in_wisconsin(lat, lon):
    if pd.isna(lat) or pd.isna(lon):
        return False
    return WI_LAT_RANGE[0] <= lat <= WI_LAT_RANGE[1] and WI_LON_RANGE[0] <= lon <= WI_LON_RANGE[1]


def wbic_of(lake):
    return str(lake[WBIC])


def haversine_miles(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Step 1: geocode the start point
# ---------------------------------------------------------------------------

def geocode(query):
    data = fetch_json(f"{NOMINATIM_URL}?q={urllib.parse.quote(query)}&format=json&limit=1")
    time.sleep(1)  # Nominatim's usage policy: at most 1 request per second
    return (float(data[0]["lat"]), float(data[0]["lon"])) if data else None


def geocode_start():
    """Geocode START_ADDRESS. If it changed since the last run, drop the drive-time
    caches, since every drive time in them was measured from the old start point."""
    previous = None
    if os.path.exists(START_POINT_CACHE):
        with open(START_POINT_CACHE, encoding="utf-8") as f:
            previous = json.load(f)
    if previous and previous["address"] == config.START_ADDRESS:
        lat, lon = previous["lat"], previous["lon"]
    else:
        coords = geocode(config.START_ADDRESS)
        if coords is None:
            raise ValueError(f"Could not geocode START_ADDRESS: {config.START_ADDRESS}")
        lat, lon = coords
        for stale in (COUNTIES_CACHE, DRIVE_TIME_CACHE):
            if os.path.exists(stale):
                os.remove(stale)
        record = {"address": config.START_ADDRESS, "lat": lat, "lon": lon}
        write_atomic(START_POINT_CACHE, lambda f: json.dump(record, f, indent=2))
    print(f"Step 1: start = {config.START_ADDRESS} -> {lat:.5f}, {lon:.5f}")
    return lat, lon


# ---------------------------------------------------------------------------
# Step 2: rough filter by county
# ---------------------------------------------------------------------------

def drive_route(lat1, lon1, lat2, lon2):
    """(miles, hours) by car, or (None, None) if routing failed after retries.

    Valhalla's free public server drops many requests under load (~73% failed
    at 10 concurrent in testing). A failure is retried and, if it persists,
    reported as unknown. It is never treated as "too far".
    """
    body = json.dumps({"locations": [{"lat": lat1, "lon": lon1}, {"lat": lat2, "lon": lon2}],
                       "costing": "auto", "units": "miles"}).encode()

    def call():
        s = fetch_json(VALHALLA_URL, method="POST", body=body,
                       headers={"Content-Type": "application/json"})["trip"]["summary"]
        return s["length"], s["time"] / 3600

    return with_retries(call, retries=4, backoff_seconds=0.5) or (None, None)


def find_candidate_counties(start_lat, start_lon):
    """Counties whose seat is within MAX_DRIVE_HOURS plus a buffer. This only
    narrows the search; step 4 makes the exact per-lake cut."""
    if config.STATE != "WI":
        raise NotImplementedError("Only Wisconsin is supported (WDNR is a Wisconsin-only data source).")

    cache = {c: float(r["Drive Hours"]) for c, r in read_csv_cache(COUNTIES_CACHE, key="County").items()}
    for county, seat in WI_COUNTY_SEATS.items():
        if county in cache:
            continue
        coords = geocode(f"{seat}, {county} County, WI")
        if coords is None:
            print(f"  WARNING: could not geocode the seat of {county} County - skipped this run")
            continue
        _, hours = drive_route(start_lat, start_lon, *coords)
        if hours is None:
            print(f"  WARNING: could not route to {county} County - skipped this run, retried next run")
            continue
        cache[county] = hours
    write_csv_cache(COUNTIES_CACHE, ["County", "Drive Hours"],
                    [{"County": c, "Drive Hours": h} for c, h in cache.items()])

    cutoff = config.MAX_DRIVE_HOURS + COUNTY_DRIVE_BUFFER_HOURS
    candidates = {c for c, h in cache.items() if h <= cutoff}
    print(f"Step 2: {len(candidates)} of {len(WI_COUNTY_SEATS)} counties have a seat within "
          f"{cutoff:.2f} hr ({config.MAX_DRIVE_HOURS} hr + {COUNTY_DRIVE_BUFFER_HOURS} hr buffer)")
    return candidates


# ---------------------------------------------------------------------------
# Step 3: every lake in the candidate counties
# ---------------------------------------------------------------------------

def compile_lakes(candidate_counties):
    """WDNR publishes one Excel export of every lake in the state (name, county,
    acreage, depths, lake type, clarity, fish, coordinates). Downloaded once."""
    download_once(WDNR_BULK_EXPORT_URL, BULK_LAKES_XLSX, "WDNR's statewide lake export", timeout=60)
    statewide = pd.read_excel(BULK_LAKES_XLSX)
    df = statewide[statewide["County"].isin(candidate_counties)]
    write_atomic(LAKES_COMPILED, lambda f: df.to_csv(f, index=False))
    print(f"Step 3: {len(df)} of {len(statewide)} Wisconsin lakes are in candidate counties")
    return df.to_dict("records")


# ---------------------------------------------------------------------------
# Step 4: exact filter by size and per-lake drive time
# ---------------------------------------------------------------------------

def filter_candidates(lakes, start_lat, start_lon):
    # 4a. Free filters first: one row per WBIC, big enough, valid coordinates.
    seen, sized, bad_coords, fixed_sign = set(), [], 0, 0
    for lake in lakes:
        if wbic_of(lake) in seen:
            continue
        seen.add(wbic_of(lake))
        if pd.isna(lake.get("Size (Acres)")) or lake["Size (Acres)"] < config.MIN_ACRES:
            continue
        lat, lon = lake.get("Latitude"), lake.get("Longitude")
        if not in_wisconsin(lat, lon) and in_wisconsin(lat, -lon):
            lake = {**lake, "Longitude": -lon}  # WDNR dropped the minus sign
            fixed_sign += 1
        elif not in_wisconsin(lat, lon):
            bad_coords += 1
            continue
        sized.append(lake)
    print(f"Step 4a: {len(sized)} lakes >= {config.MIN_ACRES} acres with coordinates")
    if fixed_sign:
        print(f"Step 4a: repaired {fixed_sign} positive longitudes (missing minus sign in WDNR's export)")
    if bad_coords:
        print(f"Step 4a: WARNING - {bad_coords} lakes >= {config.MIN_ACRES} acres have missing or "
              f"out-of-state coordinates in WDNR's export (e.g. 0, 0) and were skipped")

    # 4b. Real drive time for each lake, from cache where possible.
    cache = {w: (float(r["Drive Miles"]), float(r["Drive Hours"]))
             for w, r in read_csv_cache(DRIVE_TIME_CACHE).items()}
    to_route = [lake for lake in sized if wbic_of(lake) not in cache]
    print(f"Step 4b: {len(sized) - len(to_route)} drive times cached, routing {len(to_route)} new...")

    def route_one(lake):
        return lake, drive_route(start_lat, start_lon, lake["Latitude"], lake["Longitude"])

    def save():
        write_csv_cache(DRIVE_TIME_CACHE, ["WBIC", "Drive Miles", "Drive Hours"],
                        [{"WBIC": w, "Drive Miles": m, "Drive Hours": h} for w, (m, h) in cache.items()])

    unrouted = 0
    results = run_parallel(route_one, to_route, ROUTE_WORKERS, "routed", 100)
    for done, (lake, (miles, hours)) in enumerate(results, start=1):
        if hours is None:
            unrouted += 1  # not cached: retried on the next run
        else:
            cache[wbic_of(lake)] = (round(miles, 1), round(hours, 2))
        if done % 100 == 0:
            save()  # checkpoint: routing 1,000+ lakes takes about half an hour
    save()

    # 4c. Keep the lakes within the limit.
    kept = []
    for lake in sized:
        if wbic_of(lake) in cache:
            miles, hours = cache[wbic_of(lake)]
            if hours <= config.MAX_DRIVE_HOURS:
                kept.append({**lake, "Drive Miles": miles, "Drive Hours": hours})
    if unrouted:
        print(f"Step 4c: WARNING - {unrouted} lakes could not be routed after retries. They are "
              f"left out of this run (neither in nor out of range); re-run to retry them.")
    print(f"Step 4c: {len(kept)} lakes within {config.MAX_DRIVE_HOURS} hr real drive time")
    return kept


# ---------------------------------------------------------------------------
# Step 5: bottom substrate and trophic status from each lake's WDNR page
# ---------------------------------------------------------------------------

DETAIL_FIELDS = ["WBIC", "Sand %", "Gravel %", "Rock %", "Muck %", "Trophic Status", "Page Fetched"]


def parse_lake_detail(html):
    """Pull the substrate percentages and trophic status out of a WDNR lake page.
    Fields the page doesn't have come back as empty strings."""
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)

    idx = text.find("Bottom")
    bottom = text[idx:idx + 200] if idx >= 0 else ""

    def pct(material):
        m = re.search(rf"(\d+)%\s*{material}", bottom, re.IGNORECASE)
        return m.group(1) if m else ""

    trophic = re.search(r"Trophic Status\n([^\n]+)", text)
    return {"Sand %": pct("sand"), "Gravel %": pct("gravel"), "Rock %": pct("rock"),
            "Muck %": pct("muck"), "Trophic Status": trophic.group(1).strip() if trophic else ""}


def _detail_is_cached(row):
    # Rows from older versions of this script have no "Page Fetched" column. An
    # old all-blank row may be a failed fetch, so it's fetched once more.
    return row.get("Page Fetched") == "yes" or any(row.get(f) for f in DETAIL_FIELDS[1:6])


def scrape_lake_details(lakes):
    cache = {w: r for w, r in read_csv_cache(DETAILS_CACHE).items() if _detail_is_cached(r)}
    for row in cache.values():
        row["Page Fetched"] = "yes"
    to_scrape = [lake for lake in lakes if wbic_of(lake) not in cache]
    print(f"Step 5: {len(lakes) - len(to_scrape)} lake pages cached, scraping {len(to_scrape)} from WDNR...")

    def scrape_one(lake):
        url = WDNR_LAKE_PAGE_URL.format(wbic=wbic_of(lake))
        html = with_retries(lambda: fetch_bytes(url).decode("utf-8", errors="replace"),
                            retries=2, backoff_seconds=1)
        return wbic_of(lake), html

    failed = 0
    for wbic, html in run_parallel(scrape_one, to_scrape, WORKERS, "scraped", 50):
        if html is None:
            failed += 1
        else:
            cache[wbic] = {"WBIC": wbic, **parse_lake_detail(html), "Page Fetched": "yes"}
    write_csv_cache(DETAILS_CACHE, DETAIL_FIELDS, cache.values())
    if failed:
        print(f"Step 5: WARNING - {failed} lake pages could not be fetched; "
              f"their substrate/trophic data is missing this run and will be retried next run")

    merged = []
    for lake in lakes:
        detail = cache.get(wbic_of(lake), {})
        merged.append({**lake, **{k: v for k, v in detail.items() if k not in ("WBIC", "Page Fetched")}})
    return merged


# ---------------------------------------------------------------------------
# Step 6: measured phosphorus from EPA's Water Quality Portal
# ---------------------------------------------------------------------------
# WDNR publishes only coarse trophic classes. EPA's Water Quality Portal (WQP)
# carries real phosphorus measurements, mostly from WDNR's Citizen Lake
# Monitoring Network. WQP stations have no WBIC, so each lake is matched to a
# station by name and distance. One bounding-box query covers every lake at once.

PHOSPHORUS_STATION_MAX_MILES = 1.0  # name match AND this close = the station is on this lake
PHOSPHORUS_LOOKBACK_YEARS = 15
PHOSPHORUS_REGION_PAD_DEGREES = 0.1  # ~7 miles around the lakes' bounding box


def normalize_lake_name(name):
    """'Big Sand Lake' -> 'BIG SAND', so WDNR and WQP spellings can be compared."""
    name = re.sub(r"[^A-Z0-9 ]", " ", str(name).upper())
    for suffix in (" LAKE", " FLOWAGE", " POND", " RESERVOIR", " IMPOUNDMENT"):
        name = name.replace(suffix, "")
    return " ".join(name.split())


def fetch_phosphorus_results(min_lat, max_lat, min_lon, max_lon):
    today = datetime.date.today()
    start = today.replace(year=today.year - PHOSPHORUS_LOOKBACK_YEARS).strftime("%m-%d-%Y")
    url = (f"{WQP_RESULTS_URL}?bBox={min_lon:.4f},{min_lat:.4f},{max_lon:.4f},{max_lat:.4f}"
           f"&siteType=Lake%2C%20Reservoir%2C%20Impoundment&characteristicName=Phosphorus"
           f"&startDateLo={start}&mimeType=csv&zip=no")
    return with_retries(lambda: pd.read_csv(BytesIO(fetch_bytes(url, timeout=120)), low_memory=False),
                        retries=3, backoff_seconds=2)


def build_phosphorus_lookup(lakes):
    """{WBIC: median recent total phosphorus (ug/L)} for lakes with a matching
    station, or None if WQP couldn't be reached (so nothing gets cached)."""
    try:
        download_once(WQP_STATIONS_URL, WQP_STATIONS_CACHE, "WQP's Wisconsin lake station list", timeout=120)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"Step 6: WARNING - WQP station list unavailable ({e}); skipping phosphorus this run")
        return None
    stations = pd.read_csv(WQP_STATIONS_CACHE, low_memory=False)[
        ["MonitoringLocationIdentifier", "MonitoringLocationName",
         "LatitudeMeasure", "LongitudeMeasure"]].dropna()

    pad = PHOSPHORUS_REGION_PAD_DEGREES
    min_lat = min(lake["Latitude"] for lake in lakes) - pad
    max_lat = max(lake["Latitude"] for lake in lakes) + pad
    min_lon = min(lake["Longitude"] for lake in lakes) - pad
    max_lon = max(lake["Longitude"] for lake in lakes) + pad
    stations = stations[stations["LatitudeMeasure"].between(min_lat, max_lat)
                        & stations["LongitudeMeasure"].between(min_lon, max_lon)]

    results = fetch_phosphorus_results(min_lat, max_lat, min_lon, max_lon)
    if results is None:
        print("Step 6: WARNING - WQP phosphorus query failed; skipping phosphorus this run")
        return None
    if results.empty:
        return {}

    results = results[results["ResultSampleFractionText"] == "Total"]
    if "ResultStatusIdentifier" in results.columns:
        results = results[results["ResultStatusIdentifier"] != "Rejected"]

    def to_ug_per_l(value, unit):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value * 1000 if "mg" in str(unit).lower() else value

    results = results.assign(TP_ugL=[to_ug_per_l(v, u) for v, u in
                                     zip(results["ResultMeasureValue"],
                                         results["ResultMeasure/MeasureUnitCode"], strict=True)])
    by_station = results.dropna(subset=["TP_ugL"]).groupby("MonitoringLocationIdentifier")["TP_ugL"].median()

    lookup = {}
    for lake in lakes:
        target = normalize_lake_name(lake["Lake Name"])
        if not target:
            continue
        best_id, best_dist = None, PHOSPHORUS_STATION_MAX_MILES
        for _, st in stations.iterrows():
            if target not in normalize_lake_name(st["MonitoringLocationName"]):
                continue
            dist = haversine_miles(lake["Latitude"], lake["Longitude"],
                                   st["LatitudeMeasure"], st["LongitudeMeasure"])
            if dist < best_dist:
                best_id, best_dist = st["MonitoringLocationIdentifier"], dist
        if best_id is not None and best_id in by_station.index:
            lookup[wbic_of(lake)] = round(by_station[best_id], 1)
    return lookup


def add_phosphorus_data(lakes):
    """Cache value: a number, or "" for "checked, no matching station"."""
    col = "Total Phosphorus (ug/L)"
    cache = {w: r[col] for w, r in read_csv_cache(PHOSPHORUS_CACHE).items()}
    to_check = [lake for lake in lakes if wbic_of(lake) not in cache]
    print(f"Step 6: {len(lakes) - len(to_check)} lakes already checked for phosphorus, "
          f"checking {len(to_check)} new...")
    if to_check:
        lookup = build_phosphorus_lookup(to_check)
        if lookup is not None:  # on failure, cache nothing, so the next run retries
            for lake in to_check:
                cache[wbic_of(lake)] = lookup.get(wbic_of(lake), "")
            write_csv_cache(PHOSPHORUS_CACHE, ["WBIC", col],
                            [{"WBIC": w, col: v} for w, v in cache.items()])

    matched = sum(1 for lake in lakes if cache.get(wbic_of(lake)))
    print(f"Step 6: {matched} of {len(lakes)} lakes have a measured phosphorus value")
    return [{**lake, col: cache.get(wbic_of(lake), "")} for lake in lakes]


# ---------------------------------------------------------------------------
# Step 7: nearby wetland acreage from WDNR's Wisconsin Wetland Inventory
# ---------------------------------------------------------------------------
# The service only supports a point-plus-radius search, and no lake shoreline
# polygons are available, so a lake is treated as a circle of its own acreage
# around its center point, plus a near-shore margin.

ACRES_TO_SQ_METERS = 4046.86
WETLAND_BUFFER_BASE_METERS = 300   # near-shore margin beyond the lake's own footprint
WETLAND_BUFFER_MAX_METERS = 3000   # keeps the search sane for the few huge lakes


def wetland_buffer_meters(acres):
    """Radius of a circle with the lake's area, plus the near-shore margin, capped."""
    radius = math.sqrt(max(acres, 1) * ACRES_TO_SQ_METERS / math.pi)
    return min(WETLAND_BUFFER_MAX_METERS, radius + WETLAND_BUFFER_BASE_METERS)


def fetch_wetland_acres(lat, lon, acres):
    """Total acreage of wetland polygons touching the buffer, or None on failure.
    Each polygon counts in full (ACRE_AMT), even if only its edge is inside the
    buffer, so a lake next to one huge wetland complex is over-counted."""
    params = urllib.parse.urlencode({
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "distance": wetland_buffer_meters(acres), "units": "esriSRUnit_Meter",
        "spatialRel": "esriSpatialRelIntersects", "outFields": "ACRE_AMT",
        "returnGeometry": "false", "f": "json",
    })

    def call():
        data = fetch_json(f"{WETLAND_LAYER_URL}?{params}")
        if "error" in data:  # ArcGIS reports errors as HTTP 200 with an error body
            raise RuntimeError(data["error"])
        return round(sum(f["attributes"].get("ACRE_AMT") or 0 for f in data.get("features", [])), 1)

    return with_retries(call, retries=3, backoff_seconds=0.5)


def add_wetland_data(lakes):
    col = "Nearby Wetland Acres"
    # A blank value can only be a failed lookup (a successful one returns a
    # number, even 0), so blanks are not treated as cached.
    cache = {w: r[col] for w, r in read_csv_cache(WETLAND_CACHE).items() if r[col] != ""}
    to_check = [lake for lake in lakes if wbic_of(lake) not in cache]
    print(f"Step 7: {len(lakes) - len(to_check)} lakes already checked for wetlands, "
          f"querying {len(to_check)} new...")

    def check_one(lake):
        return wbic_of(lake), fetch_wetland_acres(lake["Latitude"], lake["Longitude"], lake["Size (Acres)"])

    failed = 0
    for wbic, acres in run_parallel(check_one, to_check, WORKERS, "checked", 50):
        if acres is None:
            failed += 1
        else:
            cache[wbic] = acres
    if to_check:
        write_csv_cache(WETLAND_CACHE, ["WBIC", col], [{"WBIC": w, col: v} for w, v in cache.items()])
    if failed:
        print(f"Step 7: WARNING - {failed} wetland lookups failed; those lakes' mosquito scores "
              f"run without wetland data this run, and the lookups are retried next run")
    return [{**lake, col: cache.get(wbic_of(lake), "")} for lake in lakes]


# ---------------------------------------------------------------------------
# Step 8: score and export
# ---------------------------------------------------------------------------

def build_excel(lakes):
    print(f"Step 8: scoring {len(lakes)} lakes...")
    final = []
    for row in lakes:
        score, basis, flag, acre_feet, fields_used = score_lake(row)
        if score is None:
            continue  # no data for any climate component, so nothing to rank on
        mosquito, mosquito_fields = score_mosquito(row)
        final.append({
            "Lake Name": row["Lake Name"], "County": row["County"],
            "Climate Score": score,
            "Climate Confidence": CLIMATE_CONFIDENCE_LABELS.get(fields_used, "Screening only"),
            "Climate Fields Used": fields_used,
            "Mosquito Score": "" if mosquito is None else mosquito,
            "Mosquito Confidence": "" if mosquito is None else MOSQUITO_CONFIDENCE_LABELS[mosquito_fields],
            "Mosquito Fields Used": mosquito_fields,
            "Nearby Wetland Acres": row.get("Nearby Wetland Acres", ""),
            "Size (Acres)": round(row["Size (Acres)"]),
            "Max Depth (ft)": parse_num(row.get("Official Max Depth")) or "",
            "Mean Depth (ft)": parse_num(row.get("Official Mean Depth")) or "",
            "Est. Volume (acre-ft)": acre_feet or "",
            "Depth Basis": basis, "Lake Type": row.get("Lake Type", ""),
            "Trophic Status": row.get("Trophic Status", ""), "Water Clarity": row.get("Water Clarity", ""),
            "Total Phosphorus (ug/L)": row.get("Total Phosphorus (ug/L)", ""),
            "Trout Present": "Yes" if has_trout(row) else "",
            "Sand %": row.get("Sand %", ""), "Gravel %": row.get("Gravel %", ""),
            "Rock %": row.get("Rock %", ""), "Muck %": row.get("Muck %", ""),
            "Drive Miles": row["Drive Miles"], "Drive Hours": row["Drive Hours"],
            "Data Flag": flag, "Latitude": row["Latitude"], "Longitude": row["Longitude"],
            "WBIC": row[WBIC],
        })

    final.sort(key=lambda r: r["Climate Score"], reverse=True)
    df = pd.DataFrame(final)
    out_path = OUT_XLSX
    try:
        df.to_excel(out_path, index=False, sheet_name="Lakes")
    except PermissionError:  # the report is open in Excel
        out_path = OUT_XLSX.replace(".xlsx", " (new).xlsx")
        print(f"  {OUT_XLSX} is locked (open in Excel?) - writing {out_path} instead")
        df.to_excel(out_path, index=False, sheet_name="Lakes")
    print(f"Step 8: wrote {len(final)} lakes to {os.path.relpath(out_path, BASE)}")
    return final


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    start_lat, start_lon = geocode_start()
    counties = find_candidate_counties(start_lat, start_lon)
    lakes = compile_lakes(counties)
    lakes = filter_candidates(lakes, start_lat, start_lon)
    lakes = scrape_lake_details(lakes)
    lakes = add_phosphorus_data(lakes)
    lakes = add_wetland_data(lakes)
    build_excel(lakes)


if __name__ == "__main__":
    main()
