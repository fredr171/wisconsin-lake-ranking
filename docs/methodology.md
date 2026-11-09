# Methodology

Every lake gets two independent 0-100 scores. For both, **100 is best**.

- **Climate Score**: how well the lake should hold up as summers get hotter.
- **Mosquito Score**: how easy mosquitoes will be to live with on a waterfront property there.

Both scores use the same three steps (code: `scoring.py`):

1. **Score each component 0-100**, or mark it missing when the lake has no data for it.
2. **Take a weighted average of the components that exist.** The weights renormalize around
   missing data, so a lake missing its water-quality reading isn't dragged down or pushed
   up by the gap.
3. **Apply guardrails**, so a lake with too little real data, or one that is too shallow,
   can't score highly anyway.

## Climate Score

The idea: a lake that stays cool and clean as the climate warms is deep enough to keep a
cold bottom layer all summer (it *stratifies*), is fed by groundwater rather than warm
streams, has a sandy or rocky bottom rather than muck, and is low in nutrients. Warm,
shallow, mucky, nutrient-rich water is where weeds, algae blooms and bacteria take over.

| Component | Weight | How it's scored |
|---|---|---|
| Est. volume | 35% | Acres × depth (acre-feet), log scale from 100 (score 0) to 20,000 (score 100). More water means more thermal mass to buffer heat waves. Discounted for shallowness and basin shape (below). |
| Lake type | 25% | Spring 100, Seepage 85, Drainage 55, Drained 20. Groundwater-fed lakes run cooler and import fewer nutrients. By WDNR's definition, Drained lakes have no groundwater input at all, so they rank below Drainage. |
| Bottom substrate | 25% | 100 − muck %. The most direct available signal for weed- and bacteria-prone bottoms. |
| Water quality | 15% | Measured total phosphorus where a monitoring station exists. Otherwise WDNR's trophic status (Oligotrophic 100, Mesotrophic 55, Eutrophic 15), otherwise its water-clarity rating. |
| Trout bonus | +8 | Trout need cold, oxygen-rich water, so their presence is a free cross-check. |

### Why volume, not depth alone

A depth-only score tops out once a lake is "deep enough". A 75-acre lake and a 5,000-acre
lake at similar depths would score the same, even though the larger lake holds roughly 90
times the water. Volume lets size count once depth is adequate.

### Stratification depth scales with lake size

Volume alone lets a wide, shallow lake cheat: lots of surface area adds up to many
acre-feet, yet wind mixes the whole lake every summer and no cold layer survives. The
motivating example is a 1,400+ acre lake with a 9 ft mean depth. Bigger lakes also catch
more wind, so they need *more* depth to stay stratified.

The required mean depth is `20 ft × √(acres / 300)`, capped at 28 ft. Below it, the volume
score is multiplied by `depth / required depth`. Published work describes the same principle
(the Osgood Index relates mean depth to surface area), but its exact coefficients couldn't
be verified, so this is a calibration of the principle, not a reproduction of the index.
It was checked against reference lakes: small deep lakes and large deep lakes are
unaffected, while a 1,264-acre lake at 12 ft mean depth drops from clearly ahead of a
comparable smaller lake to roughly level with it.

### Basin shape (max/mean depth ratio)

Two lakes can share a mean depth but differ in shape: one is a uniform bowl, the other a
small deep hole surrounded by a wide, weedy shallow shelf. The median max/mean ratio on
file is about 2.3. Above 3.0, the volume score is multiplied by `3.0 / ratio`, never below
0.6. This applies only when mean depth is actually measured.

### Missing mean depth

When only max depth is on record, mean depth is estimated as 35% of max (the median
mean/max ratio on file is 0.44, so this is conservative). The volume score is then
discounted by 20% more, and the row is flagged `max (unverified)`.

### Guardrails

- **Confidence cap.** If the components with data carry under 50% of the total weight, the
  score is capped at 65 before the trout bonus. Without it, a lake known only by its
  "Seepage" label scored 85 and outranked lakes with measured depth and substrate.
- **Shallow-lake cap.** Lakes 10 ft deep or less score at most 50. The cap rises linearly
  to no cap at 20 ft. An earlier hard cutoff at 10 ft let a 12 ft lake score in the 80s
  while a 9.9 ft lake was held to 50. The cap is applied last, after the trout bonus,
  because trout in water that shallow are almost certainly stocked.
- **Pit/quarry flag.** Max depth ÷ √acres above 15 usually means a flooded mine pit (Wazee
  Lake, a former iron mine, is about 29; the highest natural lake on file is about 10.7).
  It's a `Data Flag` warning, not a penalty: a pit lake really won't have summer algae
  problems, but it also has little natural shoreline or habitat.
- **Depth sanity cap.** Depths over 400 ft are treated as data errors. The cap is that high
  because Wazee Lake really is 355 ft deep.

### Total phosphorus

WDNR's trophic status is a three-bucket label. Where EPA's Water Quality Portal has
measured phosphorus for a lake (mostly from WDNR's Citizen Lake Monitoring Network), the
median of the last 15 years of readings is used instead. Lakes are matched to monitoring
stations by name and a distance of 1 mile or less, because the portal has no WDNR lake
ID to join on. The score is log-interpolated through anchors at the standard
trophic-state thresholds (10, 20, 40 and 100 µg/L, consistent with Carlson's Trophic State
Index). At those thresholds it gives the same scores as the trophic-status buckets, so a
real measurement never scores worse than the label it falls under. Roughly 1 lake in 8
has a usable station.

## Mosquito Score

A different question from the climate score: not "is this a healthy lake?" but "how hard
will mosquitoes be to live with here?"

| Component | Weight | How it's scored |
|---|---|---|
| Nearby wetland | 45% | Acres of mapped marsh, swamp and wet meadow near the lake (WDNR Wetland Inventory). The breeding source an owner can't spray away. |
| Wind exposure | 28% | Lake size, log scale from 75 acres (score 0) to 5,000 acres (score 100). Open water means wind, and wind keeps mosquitoes off the shore. |
| Bottom substrate | 11% | 100 − muck %. A weak signal here: muck goes with weedy, warm water, not directly with breeding. |
| Water quality | 9% | Same signal as the climate score. Nutrients feed the shoreline weeds mosquitoes shelter in. |
| Lake type | 7% | Same scale as the climate score. Groundwater-fed lakes tend to have less shoreline vegetation. |

The same confidence cap applies (under 50% of the weight backed by data → at most 65).

### Wetland search area

The wetland service only supports a point-and-radius search, and no lake shoreline polygons
are available. Each lake is therefore treated as a circle of its own acreage
(radius = √(acres × 4,046.86 / π) meters), plus a 300 m near-shore margin, capped at
3,000 m. The circle is centered on the lake's center point, so the search is most accurate
for round lakes and least accurate for long or irregular ones.

### Wetland score anchors

Wetland acreage spans orders of magnitude, so it's scored on a log scale. No published
index links wetland acres to mosquito pressure, so the anchors sit on this project's own
distribution (546 lakes): 0.5 acres (1st percentile) → 100, 30 (10th) → 85, 140 (median)
→ 55, 300 (75th) → 35, 650 (90th) → 18, 1,500 (99th) → 5.

## Overall rank (listings page only)

`Lake Listings.html` orders lakes by 60% Climate Score + 40% Mosquito Score (Climate Score
alone when a lake has no Mosquito Score). This is a presentation choice that weights
climate resilience as the main factor. It doesn't change either score, and
`Lake Report.xlsx` stays sorted by Climate Score.

## Known limitations

- **No direct bacteria or weed data.** Depth, lake type, substrate and nutrients are the
  best available stand-ins.
- **No watershed or land-use data.** The data exists (WDNR and EPA GIS layers), but using
  it means building a watershed-delineation and land-cover pipeline, not making an API call.
  The same goes for internal phosphorus loading from bottom sediment.
- **The Mosquito Score covers a whole lake, not a property.** Without shoreline polygons
  and wind direction, it can't tell a windward shore from a sheltered bay.
- **Wetland data has gaps.** A large stretch of the Mississippi River corridor returns no
  wetlands at all, so 0 acres means "nothing in WDNR's inventory", not "verified wetland-free".
- **Whole wetland polygons are counted.** A wetland that only clips the edge of the search
  circle counts its full acreage, which over-counts lakes next to one huge wetland complex.
- **Substrate is missing for some lakes**, whose WDNR pages have no bottom section. A few
  lakes' substrate percentages sum past 100%. That's what WDNR publishes, so treat
  individual substrate numbers as approximate.
- **Wisconsin only.** Another state would need its own equivalent of WDNR's lake export.
- **Free routing server.** Valhalla's public server drops requests under load. The
  pipeline retries, and it reports lakes it still can't route instead of treating them as
  out of range. Many unrouted lakes usually means the server is having a bad day.
