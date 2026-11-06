# Mapping leads

The leads product is the half of EarthPV that has a human in the loop. It is a ranked
queue of places where the model thinks there is solar and OpenStreetMap does not yet say
so, exported in the formats mappers already use.

## Pakistan, country-wide

The country-wide run applied the production checkpoint at threshold 0.3, first over 122
densely built cells and then over the full build of roughly 4,470 cells, once cell
selection moved from the Overture set of buildings above 500 m<sup>2</sup> to VIDA Open
Buildings.

| Product | Count | File |
| --- | ---: | --- |
| All candidates | 6,566 | `pakistan_pv_candidates.geoparquet` |
| Rooftop placement | 1,312 | same, `placement == "rooftop"` |
| Ground-adjacent | 448 | same |
| No building within range | 4,806 | same |
| New leads, excluding mapped | 4,602 | `pakistan_pv_new_leads.geojson` |
| New leads after the epoch veto | 4,589 | `pakistan_pv_new_leads_epochclean.geojson` |
| MapRoulette challenge | ranked | `pakistan_pv_maproulette.geojson` |

Thirty percent of the raw candidates fall on solar already mapped in OpenStreetMap, which
is the pipeline's cheapest sanity check. The rest are the queue.

## How the queue is ordered

`rank_score` starts at the model's confidence and is multiplied by a building prior, so a
detection sitting squarely on a roof outranks an equally confident detection in open
country. Two further signals adjust it:

* **[Glint corroboration](../methods/glint.md)** multiplies upward, capped at four times,
  as the count of mutually consistent spike dates saturates. It never demotes.
* **The pre-boom epoch check** demotes. Pakistan's rooftop stock is overwhelmingly
  post-2022, so a candidate that already looked like PV in the 2021 dry-season composite
  is more likely a bright roof, concrete apron or rock outcrop than a new array.

Nothing else in the default export is dropped. A high-confidence detection with no building
anywhere near it may be an unmapped roof or a ground-mounted farm, and it still surfaces;
the exceptions are leads on steep ground and open-ground leads of low model probability (below).

## The one file that does drop things

`--exclude-mapped --epoch-clean --veg-max-ndvi 0.35` writes
`<aoi>_pv_new_leads_clean.geojson`, the single export artifact that removes candidates.
Two vetoes apply, and both require positive evidence: a lead that no instrument could
check is always kept.

**Distance to already-mapped solar.** `--min-distance-m 100` removes candidates within
100 m of an existing OpenStreetMap solar feature, which is not the same as intersecting
one; the intersects-only version missed adjacent-but-offset duplicates.

**Vegetation.** Manual review of countryside leads found a lot of green fields. Measuring
NDVI on the composite the model actually read does not catch them, because those fields
were dark fallow or flooded paddy soil when the dry-season median was built. What does
catch them is the annual cycle: every crop field greens up at some point in the year and a
panel never does. A 0.35 threshold on maximum composite NDVI vetoed 596 of 5,132 leads,
and the split confirms the veto is specific rather than blunt: 20.2 percent of
`no_building` leads, 10.5 percent of `ground_adjacent`, and only 0.3 percent of rooftop.

Vegetation-vetoed leads are written to `hard_negatives_veg.parquet` and fed back as
training negatives. Unlike epoch persistence, which real old PV also shows, an observed
crop cycle is near-conclusive non-PV evidence, and dark fallow soil is a confusion class
that German training data never contained.

## The released lead files: leads on steep ground left out

The lead file every atlas links (`scripts/release_leads.py`) leaves out leads on steep
ground, measured as the Copernicus GLO-90 slope at a point inside the outline: an outline
smaller than 1,000 m<sup>2</sup> on ground steeper than 15&deg; (owner decision, 2026-10-31),
and an outline of any size on ground steeper than 30&deg; (2026-11-01). Shaded hillsides,
cliff edges, gullies and the shadows under escarpments read like panels at 10 m. In Yemen's
first release a third of the leads stood on ground steeper than 12&deg;, against 0.5% of the
mapped solar in the same highlands, and 9 of 10 drawn at random were not solar on imagery.

A larger lead on ground between 15&deg; and 30&deg; stays in the file, marked `steep_review`,
because a solar farm can stand on a mountainside and a person has to look at it. Every lead
carries the slope it was judged on (`slope_deg`), and `earthpv export` applies the same
screen to a run's own `<aoi>_pv_new_leads.geojson`.

The 30&deg; cap came from 60 leads in Wadi Hadramawt that the owner flagged as shadow: the
15&deg; rule had removed 38, and 19 of the 20 larger ones it kept stood above 30&deg;, on
cliffs. Two more lie on flat ground at the foot of a cliff, which a slope read at one point
cannot see; they stay for now.

Across the twelve lead files of 2026-11-01 the rules remove 10,098 of 156,170 leads (6,306
small ones and 3,792 larger ones above 30&deg;; Yemen 472, India 7,942, Poland 3) and keep
3,298 as `steep_review`. On solar known to be real they would remove 2 of the 22,370 model
outlines that found a mapped installation, none of them larger than 1,000 m<sup>2</sup>, and
at most 0.03% of any country's mapped solar area. Yemen's file also reads a newer
OpenStreetMap pull (2026-10-31), so 246 of its leads mapped in the week before left it. Of 89 small steep leads drawn at random and
checked on imagery by the owner, none was solar (86 were not, 3 could not be settled); of 64
larger ones none was solar either (62 were not, 2 could not be settled), and the 23 of them
above 30&deg; were all judged not solar. A few below 30&deg;, such as a farmstead in German hill
country, could be solar, which is why those stay
([experiment register](../experiments.md#small-leads-on-steep-ground-2026-10-31),
`results/leads_steep_screen/`).

## Open ground at low probability, and pans and ponds

From the lead files released after 2026-11-01 two more kinds of lead are left out, and
`earthpv export` applies both to a run's own lead file
([experiment register](../experiments.md#open-ground-at-low-probability-and-pans-and-ponds-2026-11-01),
`results/fp_filter_survey/`).

**Open ground at low probability.** A lead with no building near it whose highest model
probability inside the outline is below 0.9 is left out, at any size. Among such outlines
the share that turns out to be mapped solar is low and does not rise between 0.3 and 0.9:
0 to 1.3% in most countries (4 to 7% in France, Germany and Poland), against 2 to 53% for
the open-ground outlines above 0.9. Germany's register, which locates every unit of 30 kW or
more, finds one inside 0 to 5% of them in every size bin, against 10 to 38% of the confident
ones. None of 18 drawn at random in Pakistan and South Africa was solar on imagery: fields,
riverbeds, shaded hillsides, forest, a farm reservoir, a quarry floor. Leaving them out loses
at most 1.5% of the mapped solar area the model finds (France) and none of the 81 parks above
the merge cap that the owner confirmed in India. A lead next to a building is kept whatever
its probability: many are rooftop arrays overrunning an undersized building outline. So is a
`steep_review` lead: the owner kept the large leads on steep ground for a person to look at,
and the rule would otherwise take 2,017 of the 3,298.

**Pans and ponds, in some countries.** Where the screen is switched on (Pakistan, Egypt and
Namibia; `lead_water_screen` in `configs/aoi.yaml`), a lead not on a rooftop of which at
least a quarter was ever under water between 1984 and 2020 in JRC Global Surface Water is
left out: seasonal pans, salt pans, fish and wastewater ponds. On its own it flags 197 of
Namibia's 825 leads, most of them in the Cuvelai basin, and none of the 57 outlines that found
mapped solar; in Egypt none of 9 flagged leads checked on imagery was solar. It stays off
elsewhere because solar stands on water or wet ground: in India it would flag 7.6% of the
mapped ground-mounted area (Khavda on the Rann of Kutch salt marsh, the floating plants at
Omkareshwar and Ramagundam) and in Vietnam 17% (floating and pond-mounted plants; 3 of 9
flagged leads there were real arrays not yet mapped).

## Very large outlines in a file of their own, and how much to check

Since 2026-11-01 each country's leads come as two files: `<country>_pv_new_leads.geojson`,
most promising first, and `<country>_pv_blob_leads.geojson`, the outlines above the
100,000 m<sup>2</sup> merge cap, largest first (`scripts/release_leads.py`; the files of
`pv-new-leads-2026-11-01b` were split in place, the same leads under the same date). Twelve
countries hold 100,556 leads and 3,127 blobs between them; France's audited release already
kept its 29 apart. A blob is whatever the 10 m pixels merged into one shape, and what that
is varies by country: 1,427 of the 1,640 judged on imagery in India were parks, 41% of
Germany's 581 hold a registered unit, and of the 121 in Pakistan's file of July 2026 three
have been mapped since, of Yemen's 29 none. On 3 November the owner judged the queued blobs
of eleven more countries, 913 of 919: parks were the rule in Poland (113 of 142), Yemen (5
of 6) and Vietnam (32 of 56), common in France (12 of 29), and rare elsewhere: Egypt 4 of
23, South Africa 5 of 249, Pakistan 2 of 41, Morocco 1 of 40, Zambia 1 of 73, Nigeria 1 of
226 and Namibia none of 28. Turkey's and Germany's followed on 6 November: 396 of 773 and
149 of 581 are parks.
**No blob counts towards capacity until it is
mapped in OpenStreetMap or a person has judged it solar on the Sentinel-2 imagery the model
saw** (owner, 2026-11-01; `density.load_oversize_admission`). That ended India's admission of
its 1,562 unreviewed blobs at the review sample's share real (see
[India](india.md)); `scripts/oversize_review.py draw`, a step of every country's run, queues
each blob for a verdict, largest first.

**How much of a lead file is worth checking** (`scripts/lead_share.py`,
`results/lead_share/`). The files are ranked, and the real installations sit near the top:

| where a reference exists | leads | real | share of the real ones in the top third | real below the top third |
| --- | ---: | ---: | ---: | ---: |
| Pakistan, v3's file of 2026-07-16, mapped by the 2026-10-25 pull | 4,435 | 385 | 69% | 4.1% |
| Yemen, file of 2026-10-28, mapped by 2026-10-31 | 2,259 | 246 | 87% | 2.1% |
| Germany, file of 2026-11-01, a registered unit inside | 14,535 | 6,408 | 46% | 35.9% |

"Mapped since" is a lower bound on real and leans towards where people looked, which in
Yemen was the top of the file; the German register does not, and there the ranking is
weaker. Small leads are the worst: under 1,000 m<sup>2</sup> 3.9% were mapped since in
Pakistan, 3.2% in Yemen, and 6.9% hold a registered unit in Germany, against 12 to 59% for
leads of 10,000 to 100,000 m<sup>2</sup>. So Silver asks for about a third of a lead file's
leads, worked from the top, and a third of its blobs to have a verdict before the model is
retrained on them (`atlas.LEAD_SHARE_MIN`), not every lead: past the top third, Pakistan's
and Yemen's mappers would have found 2 to 4 installations per 100 leads checked.

## Getting the leads into OpenStreetMap

```bash
pixi run earthpv export --aoi pakistan --exclude-mapped --min-distance-m 100 \
    --epoch-clean --veg-max-ndvi 0.35
```

That writes GeoParquet, GeoJSON and a MapRoulette challenge sorted by `rank_score`. Load
the challenge in MapRoulette, or open the GeoJSON directly in JOSM or QGIS alongside the
Esri and Bing layers. Every published atlas links its country's lead file, and
[Map the leads with JOSM](../contribute/leads.md) is the step-by-step workflow for it.

When mapping a lead, tag it the way the rest of OpenStreetMap does
(`generator:source=solar` on a rooftop generator, `power=plant` with
`plant:source=solar` for a plant) so the next `overpass-labels` run picks it up as
training data. Mapped installations returning through that path are what closes the
[flywheel](../how-it-works.md#workflow).

## Other regions

`results/gujarat_pv_candidates.geojson` and `results/gujarat_pv_new_leads.geojson` hold a
first pass over Gujarat, India, produced with no locally cached data at all. Gujarat is
the worked template for [running on a new region](../reproduce.md#running-on-a-new-region);
India's national [evidence atlas](../atlas-india.md) has since replaced its first
capacity estimate.
