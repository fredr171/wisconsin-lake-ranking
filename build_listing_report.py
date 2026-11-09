"""
Builds output/Lake Listings.html from output/Lake Report.xlsx.

Run after lake_finder.py: `python build_listing_report.py`.

The page is one self-contained HTML file, with nothing linked locally. It
lists every named lake in order of a blended rank (see OVERALL_RANK_WEIGHTS).
Each lake gets a card with both scores, a plain-English explanation of them,
and a link to a live Zillow waterfront search around that lake.
docs/methodology.md is embedded in the page, behind a "read it here" toggle.

About the Zillow links: Zillow has no public listings API and its terms
prohibit scraping, so this collects no listing data. It only builds a URL for
Zillow's own map search. The search is by coordinates, not by name, because a
name search for a common lake name goes elsewhere: in a test, "Silver Lake,
Barron County, WI" opened Silver Lake, Los Angeles.
"""
import html
import json
import math
import os
import shutil
import tempfile
import urllib.parse

import markdown
import pandas as pd

import config
from zillow_overrides import MAP_BOUNDS

BASE = os.path.dirname(os.path.abspath(__file__))
METHODOLOGY_PATH = os.path.join(BASE, "docs", "methodology.md")
IN_XLSX = os.path.join(BASE, "output", "Lake Report.xlsx")
OUT_HTML = os.path.join(BASE, "output", "Lake Listings.html")

# Page order: a blend of the two scores, weighted toward climate resilience.
# This is a presentation choice. It changes neither score, only the order
# and the #1, #2, ... rank on each card. Lakes with no Mosquito Score rank
# by Climate Score alone. (Lake Report.xlsx stays sorted by Climate Score.)
OVERALL_RANK_WEIGHTS = {"climate": 0.6, "mosquito": 0.4}

# Zillow search box: a square around the lake's center, half-width =
# 1 mile + 0.02 miles * sqrt(acres). Bigger lakes have more shoreline to cover.
MILES_PER_DEGREE_LAT = 69.0
RADIUS_FLOOR_MILES = 1.0
RADIUS_ACRES_SCALE = 0.02

LAKE_TYPE_BLURB = {
    "SPRING": "A Spring lake: groundwater-fed with no stream inflow, the most climate-resilient type",
    "SEEPAGE": "A Seepage lake: groundwater-fed, with no stream inflow to warm it or bring in nutrients",
    "DRAINAGE": "A Drainage lake: stream-fed, so more exposed to warm or nutrient-rich inflow",
    "DRAINED": "A Drained lake: has an outlet but no real inflow, and no groundwater input",
}

# Score badge colors: red (0) -> yellow (50) -> green (100), as in matplotlib's RdYlGn.
SCORE_COLOR_STOPS = [(0, (165, 0, 38)), (50, (255, 255, 191)), (100, (0, 104, 55))]
# Card background: blends from the mosquito box's green (poor lake) to the
# climate box's blue (strong lake), by the average of the lake's two scores.
# (fill, border) pairs, matching .methodology-bugs and .methodology-water below.
POOR_TINT = ((0xf0, 0xf0, 0xd6), (0xcd, 0xc9, 0x78))
GOOD_TINT = ((0xe7, 0xf3, 0xfa), (0xb9, 0xdc, 0xed))


def has_value(x):
    return pd.notna(x) and x != ""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def overall_rank_score(row):
    if has_value(row["Mosquito Score"]):
        return (OVERALL_RANK_WEIGHTS["climate"] * row["Climate Score"]
                + OVERALL_RANK_WEIGHTS["mosquito"] * float(row["Mosquito Score"]))
    return row["Climate Score"]


def load_lake_rows():
    """Read the report and sort it by overall rank. It reads a temp copy,
    because reading the .xlsx in place while Excel has it open can fail on Windows."""
    if not os.path.exists(IN_XLSX):
        raise FileNotFoundError(f"{IN_XLSX} not found - run `python lake_finder.py` first")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = os.path.join(tmp_dir, "lake_report.xlsx")
        shutil.copy(IN_XLSX, tmp)
        df = pd.read_excel(tmp)
    df["Overall Rank Score"] = df.apply(overall_rank_score, axis=1)
    return df.sort_values("Overall Rank Score", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Links and colors
# ---------------------------------------------------------------------------

def zillow_url_for_bounds(west, east, south, north):
    """A Zillow map search for waterfront homes in a box, cheapest first.

    searchQueryState has no public schema. "wat" (waterfront) and "pricea"
    (price, low to high) were found by setting those filters in Zillow's own
    UI and reading the resulting URL.
    """
    state = {
        "pagination": {},
        "isMapVisible": True,
        "mapBounds": {"west": west, "east": east, "south": south, "north": north},
        "filterState": {"sort": {"value": "pricea"}, "wat": {"value": True}},
        "isListVisible": True,
    }
    return "https://www.zillow.com/homes/for_sale/?searchQueryState=" + urllib.parse.quote(json.dumps(state))


def zillow_search_url(wbic, lat, lon, acres):
    """The hand-picked box from zillow_overrides.py if there is one, else an automatic box."""
    if wbic in MAP_BOUNDS:
        return zillow_url_for_bounds(*MAP_BOUNDS[wbic])
    radius_miles = RADIUS_FLOOR_MILES + math.sqrt(max(acres, 1)) * RADIUS_ACRES_SCALE
    lat_pad = radius_miles / MILES_PER_DEGREE_LAT
    lon_pad = radius_miles / (MILES_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    return zillow_url_for_bounds(lon - lon_pad, lon + lon_pad, lat - lat_pad, lat + lat_pad)


def score_color(score):
    """(background, text) hex colors for a 0-100 score badge."""
    score = max(0, min(100, score))
    rgb = SCORE_COLOR_STOPS[-1][1]
    for (s0, c0), (s1, c1) in zip(SCORE_COLOR_STOPS, SCORE_COLOR_STOPS[1:], strict=False):
        if s0 <= score <= s1:
            frac = (score - s0) / (s1 - s0)
            rgb = tuple(round(c0[i] + frac * (c1[i] - c0[i])) for i in range(3))
            break
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return "#{:02x}{:02x}{:02x}".format(*rgb), ("#1c2b26" if luminance > 140 else "#ffffff")


def lake_tint_color(climate_score, mosquito_score):
    """(fill, border) hex colors for a card, from the average of its scores."""
    scores = [s for s in (climate_score, mosquito_score) if has_value(s)]
    frac = max(0, min(1, (sum(scores) / len(scores) if scores else 50) / 100))

    def blend(poor, good):
        return "#{:02x}{:02x}{:02x}".format(*(round(poor[i] + frac * (good[i] - poor[i])) for i in range(3)))

    return blend(POOR_TINT[0], GOOD_TINT[0]), blend(POOR_TINT[1], GOOD_TINT[1])


# ---------------------------------------------------------------------------
# Plain-English explanations
# ---------------------------------------------------------------------------

def explain_ranking(row):
    parts = [f"Climate-resilience score: {row['Climate Score']:.1f}/100 ({row['Climate Confidence']} "
             f"confidence, {row['Climate Fields Used']}/4 scoring signals available)."]

    lake_type = str(row.get("Lake Type", "")).strip().upper()
    if lake_type in LAKE_TYPE_BLURB:
        parts.append(LAKE_TYPE_BLURB[lake_type] + ".")

    mean_d, max_d = row.get("Mean Depth (ft)"), row.get("Max Depth (ft)")
    if pd.notna(mean_d):
        parts.append(f"Verified mean depth of {mean_d:.0f} ft"
                     + (f" (max {max_d:.0f} ft)." if pd.notna(max_d) else "."))
    elif pd.notna(max_d):
        parts.append(f"Only an unverified max depth of {max_d:.0f} ft on record, no mean depth.")

    muck = row.get("Muck %")
    if pd.notna(muck):
        parts.append(f"Bottom is {100 - muck:.0f}% sand/gravel/rock, {muck:.0f}% muck.")

    tp, trophic, clarity = row.get("Total Phosphorus (ug/L)"), row.get("Trophic Status"), row.get("Water Clarity")
    if pd.notna(tp):
        parts.append(f"Measured total phosphorus: {tp:.1f} µg/L.")
    elif isinstance(trophic, str) and trophic:
        parts.append(f"Trophic status: {trophic}.")
    elif isinstance(clarity, str) and clarity:
        parts.append(f"Water clarity: {clarity}.")

    if row.get("Trout Present") == "Yes":
        parts.append("Trout present, a cross-check for cold, oxygen-rich water.")

    flag = row.get("Data Flag")
    if isinstance(flag, str) and flag:
        parts.append(f"Note: {flag}.")
    return " ".join(parts)


def explain_mosquito(row):
    m_score = row.get("Mosquito Score")
    if not has_value(m_score):
        return "Mosquito score: not enough data on this lake to estimate."
    parts = [f"Mosquito control score: {m_score:.1f}/100 ({row['Mosquito Confidence']} confidence, "
             f"{row['Mosquito Fields Used']}/5 scoring signals available)."]

    wetland = row.get("Nearby Wetland Acres")
    if has_value(wetland):
        if wetland < 1:
            parts.append("Little to no mapped wetland near the lake.")
        else:
            parts.append(f"About {wetland:.0f} acres of mapped wetland (marsh or swamp) near the lake, "
                         f"a likely mosquito source.")

    acres = row.get("Size (Acres)")
    if pd.notna(acres):
        if acres >= 500:
            parts.append("Large, open lake: more wind to keep mosquitoes off the shore.")
        elif acres < 150:
            parts.append("Smaller, more sheltered lake: less wind to rely on.")
    return " ".join(parts)


def render_methodology():
    """docs/methodology.md as HTML, with headings shifted down two levels to sit under the page's own."""
    with open(METHODOLOGY_PATH, encoding="utf-8") as f:
        body = markdown.markdown(f.read(), extensions=["tables"])
    for level in (4, 3, 2, 1):
        body = body.replace(f"<h{level}>", f"<h{level + 2}>").replace(f"</h{level}>", f"</h{level + 2}>")
    return body


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

CARD_TEMPLATE = """
<article class="card" data-search="{search_key}" style="background:{card_bg};border-color:{card_border};">
  <div class="rank">#{rank}</div>
  <div class="card-body">
    <div class="card-head">
      <h2>{name}</h2>
      <span class="county">{county} County</span>
      <span class="acres">{acres:.0f} acres</span>
      <span class="score-badge" title="Climate-resilience score" style="background:{badge_bg};color:{badge_fg};">&#x1F41F; {score:.1f}</span>
      <span class="score-badge mosquito-badge" title="Mosquito control score (100 = easiest to control)" style="background:{mosquito_badge_bg};color:{mosquito_badge_fg};">&#x1F99F; {mosquito_badge_text}</span>
    </div>
    <div class="drive">~{drive_hours:.2f} hour drive from the start point</div>
    <p class="explain">{explain}</p>
    <p class="explain">{mosquito_explain}</p>
    <a class="zillow-link" href="{zillow_url}" target="_blank" rel="noopener">View current waterfront listings on Zillow &rarr;</a>
  </div>
</article>
"""

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cool Water, Close By</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin:0; background:#f6f0e6; color:#1c2b26; font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }}
  header {{ background:linear-gradient(160deg,#0f3d33 0%,#1d5c6b 55%,#e39b5b 130%); color:#eef7f2; padding:48px 24px; }}
  header h1 {{ margin:0 0 8px; font-size:2.6em; font-weight:800; letter-spacing:-0.02em; line-height:1.05; }}
  header p {{ margin:0; color:#cfe5db; max-width:60ch; }}
  .methodology {{ max-width:900px; margin:24px auto 0; padding:18px 22px; box-sizing:border-box;
                  border:1px solid #dfe6e2; border-radius:10px; }}
  .methodology p, .methodology ul {{ margin:0 0 10px; color:#37473f; font-size:0.92em; }}
  .methodology ul {{ padding-left:1.2em; }}
  .methodology li {{ margin-bottom:4px; }}
  .methodology-water {{ background:#e7f3fa; border-color:#b9dced; }}
  .methodology-bugs {{ background:#f0f0d6; border-color:#cdc978; }}
  .methodology-footnote {{ max-width:900px; margin:12px auto 0; padding:0 22px; box-sizing:border-box;
                            color:#6b7d76; font-size:0.85em; }}
  .readme-toggle {{ background:none; border:none; padding:0; font:inherit; font-weight:600;
                    color:#0f3d33; text-decoration:underline; cursor:pointer; }}
  .readme-toggle:hover {{ opacity:0.7; }}
  #readme-section {{ max-width:900px; margin:12px auto 0; padding:0 16px; box-sizing:border-box; }}
  .readme-content {{ max-height:60vh; overflow-y:auto; background:#fff; border:1px solid #dfe6e2;
                     border-radius:10px; padding:20px 24px; color:#37473f; font-size:0.92em; }}
  .readme-content h3 {{ margin:0 0 12px; font-size:1.3em; color:#0f3d33; }}
  .readme-content h4 {{ margin:22px 0 10px; font-size:1.05em; color:#0f3d33; }}
  .readme-content h5 {{ margin:16px 0 8px; font-size:0.98em; color:#0f3d33; }}
  .readme-content p, .readme-content ul, .readme-content ol {{ margin:0 0 12px; line-height:1.55; }}
  .readme-content code {{ background:#f0f0d6; border-radius:4px; padding:1px 5px; font-size:0.92em;
                          font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
  .readme-content table {{ width:100%; border-collapse:collapse; margin:0 0 14px; font-size:0.95em; }}
  .readme-content th, .readme-content td {{ text-align:left; padding:6px 10px; border-bottom:1px solid #e6ece9;
                                            vertical-align:top; }}
  .readme-content th {{ color:#6b7d76; font-weight:600; }}
  .controls {{ max-width:900px; margin:16px auto 0; padding:0 16px; }}
  #search {{ width:100%; box-sizing:border-box; padding:10px 14px; font-size:1em;
             border:1px solid #c7d4ce; border-radius:8px; }}
  main {{ max-width:900px; margin:0 auto; padding:16px; }}
  .card {{ display:flex; gap:14px; border:1px solid #dfe6e2; border-radius:10px;
           padding:16px 18px; margin-bottom:12px; }}
  .rank {{ flex:0 0 auto; width:2.4em; font-weight:700; color:#5c7268; font-size:1.1em; }}
  .card-body {{ flex:1 1 auto; min-width:0; }}
  .card-head {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
  .card-head h2 {{ margin:0; font-size:1.15em; }}
  .drive {{ color:#5c7268; font-size:0.8em; font-weight:600; text-transform:uppercase;
            letter-spacing:0.03em; margin:4px 0; }}
  .county, .acres {{ color:#6b7d76; font-size:0.9em; }}
  .acres::before {{ content:"\\00b7"; margin-right:10px; }}
  .score-badge {{ font-weight:700; font-size:1.1em; padding:3px 10px; border-radius:999px; }}
  .score-badge:first-of-type {{ margin-left:auto; }}
  .mosquito-badge {{ font-size:0.85em; }}
  .explain {{ margin:8px 0 12px; color:#37473f; font-size:0.95em; }}
  .zillow-link {{ display:inline-block; font-weight:600; color:#0f3d33; text-decoration:none;
                  border-bottom:2px solid #0f3d33; padding-bottom:1px; }}
  .zillow-link:hover {{ opacity:0.7; }}
  .empty {{ text-align:center; color:#6b7d76; padding:40px; display:none; }}
  footer {{ text-align:center; color:#8a9a93; font-size:0.85em; padding:24px; }}
</style>
</head>
<body>
<header>
  <h1>Cool Water, Close By</h1>
  <p>Every named Wisconsin lake within a {max_drive_hours}-hour drive of the start point, ranked
     {climate_pct}% by climate resilience and {mosquito_pct}% by mosquito control. Both scores
     appear on every card, with a live Zillow waterfront search.</p>
</header>
<div class="methodology methodology-water">
  <p><strong>&#x1F41F; Climate-resilience score</strong>: 0-100, how well the lake should
     hold up as summers get hotter.</p>
  <ul>
    <li><strong>Est. volume (35%)</strong>: acres &times; depth, discounted when the lake is too
        shallow for its size to keep a cold bottom layer</li>
    <li><strong>Lake type (25%)</strong>: groundwater-fed (Spring/Seepage) beats stream-fed (Drainage/Drained)</li>
    <li><strong>Bottom substrate (25%)</strong>: more sand and rock, less muck</li>
    <li><strong>Water quality (15%)</strong>: measured phosphorus where available, else trophic status or clarity</li>
    <li><strong>Trout present</strong>: a small bonus, as a cold-water cross-check</li>
  </ul>
</div>
<div class="methodology methodology-bugs">
  <p><strong>&#x1F99F; Mosquito control score</strong>: 0-100, how easy mosquitoes will be to
     live with on a property here (100 = easiest).</p>
  <ul>
    <li><strong>Nearby wetland (45%)</strong>: marsh and swamp acreage near the lake, the breeding
        source an owner can't treat away</li>
    <li><strong>Wind exposure (28%)</strong>: bigger, more open lakes get more wind</li>
    <li><strong>Lake type (7%), water quality (9%), substrate (11%)</strong>: less weedy shoreline cover</li>
  </ul>
</div>
<p class="methodology-footnote">Full methodology, guardrails and known limitations -
   <button class="readme-toggle" id="readme-toggle" type="button" aria-expanded="false">read it here</button>.</p>
<div id="readme-section" hidden>
  <div class="readme-content">
{methodology_html}
  </div>
</div>
<div class="controls">
  <input id="search" type="text" placeholder="Filter by lake or county (comma-separate for several)...">
</div>
<main id="cards">
{cards}
<p class="empty" id="empty-msg">No lakes match that search.</p>
</main>
<footer>
  Zillow links open a live search on Zillow's own site, filtered to waterfront. No listing data
  is collected or stored here. An empty result only means nothing nearby is currently tagged
  waterfront; widen the map or remove the filter on Zillow's page.
</footer>
<script>
  const search = document.getElementById('search');
  const cards = Array.from(document.querySelectorAll('.card'));
  const emptyMsg = document.getElementById('empty-msg');
  search.addEventListener('input', () => {{
    // Comma-separated terms are OR'd: "silver, stone" shows lakes matching either.
    const terms = search.value.toLowerCase().split(',').map(t => t.trim()).filter(t => t);
    let visible = 0;
    cards.forEach(c => {{
      const match = terms.length === 0 || terms.some(t => c.dataset.search.includes(t));
      c.style.display = match ? '' : 'none';
      if (match) visible++;
    }});
    emptyMsg.style.display = visible === 0 ? 'block' : 'none';
  }});
  const toggle = document.getElementById('readme-toggle');
  const section = document.getElementById('readme-section');
  toggle.addEventListener('click', () => {{
    const open = !section.hidden;
    section.hidden = open;
    toggle.setAttribute('aria-expanded', String(!open));
    toggle.textContent = open ? 'read it here' : 'hide it';
    if (!open) section.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
  }});
</script>
</body>
</html>
"""


def render_card(rank, row):
    badge_bg, badge_fg = score_color(row["Climate Score"])
    m_score = row.get("Mosquito Score")
    if has_value(m_score):
        mosquito_bg, mosquito_fg = score_color(m_score)
        mosquito_text = f"{m_score:.1f}"
    else:
        mosquito_bg, mosquito_fg, mosquito_text = "#dfe6e2", "#6b7d76", "N/A"
    card_bg, card_border = lake_tint_color(row["Climate Score"], m_score)
    return CARD_TEMPLATE.format(
        rank=rank,
        name=html.escape(str(row["Lake Name"])),
        county=html.escape(str(row["County"])),
        acres=row["Size (Acres)"],
        score=row["Climate Score"],
        badge_bg=badge_bg, badge_fg=badge_fg,
        mosquito_badge_bg=mosquito_bg, mosquito_badge_fg=mosquito_fg, mosquito_badge_text=mosquito_text,
        card_bg=card_bg, card_border=card_border,
        drive_hours=row["Drive Hours"],
        explain=html.escape(explain_ranking(row)),
        mosquito_explain=html.escape(explain_mosquito(row)),
        zillow_url=html.escape(zillow_search_url(int(row["WBIC"]), row["Latitude"], row["Longitude"],
                                                 row["Size (Acres)"]), quote=True),
        search_key=html.escape(f"{row['Lake Name']} {row['County']}".lower(), quote=True),
    )


def build_report():
    df = load_lake_rows()
    # WDNR scores many lakes it never named ("Unnamed T20n R01e S31-05a"). There's
    # nothing to search Zillow for, so they're left off this page (kept in the .xlsx).
    unnamed = df["Lake Name"].str.strip().str.upper().str.startswith("UNNAMED")
    if unnamed.any():
        print(f"Skipping {unnamed.sum()} unnamed lakes (they stay in Lake Report.xlsx)")
    df = df[~unnamed].reset_index(drop=True)

    page = PAGE_TEMPLATE.format(
        max_drive_hours=f"{config.MAX_DRIVE_HOURS:g}",
        climate_pct=round(OVERALL_RANK_WEIGHTS["climate"] * 100),
        mosquito_pct=round(OVERALL_RANK_WEIGHTS["mosquito"] * 100),
        cards="\n".join(render_card(i + 1, row) for i, row in df.iterrows()),
        methodology_html=render_methodology(),
    )
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {len(df)} lakes to {os.path.relpath(OUT_HTML, BASE)}")


if __name__ == "__main__":
    build_report()
