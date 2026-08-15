# The rooftop classifier (roofclf)

!!! success "Shipped, and half the main workflow"

    `roofclf` is the instrument that covers everything **below** the segmentation
    model's 400 m<sup>2</sup> detection floor, and (inside its calibrated domain) it now
    also replaces segmentation's own rooftop estimate above that floor. Numbers on this
    page come from the 27-quadrat fit in `data/roofclf/summary.json` and the capacity run
    behind the published [evidence atlas](../results/capacity.md).

## What it is, in one paragraph

`roofclf` is a per-building classifier that answers a single question: **does this roof
carry solar PV?** It takes one building footprint, reads the Sentinel-2 pixels that fall
inside it, and returns a probability. It never draws a panel outline, never says how many
modules there are, and never looks at anything but that footprint and its own
neighbourhood. It is a regularised logistic regression, about 17 numbers wide, trained on
roughly a hundred thousand hand-checked buildings. It is deliberately the smallest model
in this project.

## Why the question changes at 400 m<sup>2</sup>

At Sentinel-2's 10 m ground sample distance, a 100 m<sup>2</sup> array is roughly one
mixed pixel. There is no outline to find, and the segmentation model is not even asked to
look: `chips.MIN_PV_AREA` burns everything below 400 m<sup>2</sup> into the training mask
as `ignore`, so the model receives no gradient there.

That is not a small blind spot. Germany's MaStR register is legally complete, and
[measured against it](mastr-validation.md) **65.5% of German rooftop capacity sits in
units below 72 kWp**, which is what 400 m<sup>2</sup> of module comes to. In Pakistan the
whole sub-500 m<sup>2</sup> class contributes about 8 MWp to the segmentation-based
national estimate, while one exhaustively mapped square kilometre of residential Lahore
holds 3.3 times more sub-100 m<sup>2</sup> PV area than the model finds in the entire
country.

The recall correction cannot repair this, because `1 / recall x ~0` is still about zero. A
class that is never detected is not recoverable by reweighting the class that is. It needs
a different estimator, and asking "does this building carry PV" is a far easier question
at one mixed pixel than "where are its panel edges": it only needs the footprint's
spectral signature to differ from a PV-free roof of the same kind.

## The flow, end to end

![Flow chart of the roofclf pipeline in six stages. Stage one, inputs per calibration quadrat: a Rule-1 complete mapped boundary, VIDA building footprints, and the 10-band Sentinel-2 dry-season composite. Stage two, one row per building: a has_pv label from 5 percent footprint overlap, and features of log roof area plus 10 band means plus NDVI, NDBI, brightness and two ratios. Stage three, fit and measure: L2 logistic regression, leave-one-quadrat-out over 27 folds at 0.879 AUC and 0.834 within roof-size band, and a deployment threshold of 0.2511 at precision 0.50 and recall 0.63. Stage four, national scoring of 75.7 million buildings one cell at a time with SPPI computed alongside. Stage five, probability to capacity: restrict to 2,957 of 4,463 density-matched cells, remove buildings already counted by a detection or by OpenStreetMap, and convert roof area to MWp through a coverage ratio. Stage six, into the evidence atlas: Best estimate combines 7,890 plus 7,189 plus 62 MWp, floored per cell at hand-mapped OSM plus the stricter 2,180 MWp roofclf-and-SPPI agreement population.](../assets/figures/roofclf_flow.svg#only-light)
![Flow chart of the roofclf pipeline in six stages. Stage one, inputs per calibration quadrat: a Rule-1 complete mapped boundary, VIDA building footprints, and the 10-band Sentinel-2 dry-season composite. Stage two, one row per building: a has_pv label from 5 percent footprint overlap, and features of log roof area plus 10 band means plus NDVI, NDBI, brightness and two ratios. Stage three, fit and measure: L2 logistic regression, leave-one-quadrat-out over 27 folds at 0.879 AUC and 0.834 within roof-size band, and a deployment threshold of 0.2511 at precision 0.50 and recall 0.63. Stage four, national scoring of 75.7 million buildings one cell at a time with SPPI computed alongside. Stage five, probability to capacity: restrict to 2,957 of 4,463 density-matched cells, remove buildings already counted by a detection or by OpenStreetMap, and convert roof area to MWp through a coverage ratio. Stage six, into the evidence atlas: Best estimate combines 7,890 plus 7,189 plus 62 MWp, floored per cell at hand-mapped OSM plus the stricter 2,180 MWp roofclf-and-SPPI agreement population.](../assets/figures/roofclf_flow.dark.svg#only-dark)

The six stages below follow the chart from top to bottom.

## 1. Where the labels come from, and why they have to be quadrats

Ordinary OpenStreetMap is incomplete at small sizes, so a building with no mapped PV is
**not** a negative: it may simply be unmapped. A classifier trained on that learns to
predict mapping effort rather than solar panels.

The fix is the [calibration quadrat](calibration-quadrats.md): a small area, typically 1 to
7 km<sup>2</sup>, that a mapper has swept exhaustively and declared **Rule-1 complete**,
meaning every visible panel inside the boundary is mapped. Inside such a box, and only
inside it, a roof with no mapped PV is a genuine negative. That is exactly the supervision
missing in the failure regime, which is why the quadrats are spent on training rather than
only on after-the-fact correction.

Twenty-seven quadrats now carry Rule-1, spanning 79.9 km<sup>2</sup>, 16,303 mapped
installations and 118,755 buildings.

!!! warning "Rule-1 is relative to the mapping imagery, not to the model's imagery"

    Mapping happens against JOSM's background layers (Esri, Bing, Maxar), whose capture
    date is generally older than the Sentinel-2 composite the model reads. A panel built
    between the two dates is present in the model's input and absent from the labels. So
    measured **precision is a lower bound**, `base_rate` is a lower bound, and
    `rate_ratio` is an upper bound. Recall over mapped installations is unaffected, since
    it only ever divides by labels that exist. Closing this properly needs contemporaneous
    high-resolution imagery; `scripts/fraction_stale_label_audit.py` is the interim way to
    bound the size of the gap.

## 2. One row per building

`roofclf.building_table` turns each quadrat into a table, one row per VIDA building whose
representative point falls inside the boundary.

**The label.** A building is a positive (`has_pv = 1`) when mapped PV polygons cover at
least 5% of its footprint (`MIN_PV_OVERLAP_FRAC`). The threshold exists so an array that
merely clips a neighbour's roof edge does not label that neighbour. The true intersected
area is kept as `pv_area_true_m2`, and it is that column, not the building's size, that
later measures how much of a flagged roof the panels actually cover.

**The features.** Seventeen numbers, all read off the same dry-season composite the
segmentation model uses. No new imagery is fetched at any point.

| Block | Columns | What it carries |
| --- | --- | --- |
| Size | `log_roof_area`, `bf_confidence` | the adoption propensity that comes with a bigger roof, plus the footprint's own confidence score |
| Reflectance | 10 band means over the footprint | the roof's spectral signature, averaged over whatever real pixels it has |
| Derived | `ndvi`, `ndbi`, `brightness`, `swir_vis_ratio`, `blue_red_ratio` | vegetation and built-up contrast, and the dark, comparatively flat visible response with a SWIR drop that characterises a module |

Roughly half of Pakistani VIDA footprints are smaller than one pixel and rasterise to no
pixel at all. Those fall back to the pixel under their representative point, the same
convention `density.py` uses. Without that fallback the entire small-building population,
which is the population this module exists for, would drop out of the table.

Two feature blocks are computed and left switched off by default, because the ablation did
not support them: footprint shape (compactness, rectangularity, aspect ratio) and the
segmentation and fraction rasters as inputs. See [the ablation](#what-the-pixels-actually-add)
below.

## 3. The model, and how skill is measured

**A regularised logistic regression**, fitted with scipy's L-BFGS on standardised features,
with an unpenalised intercept. Gradient boosting was passed over deliberately. The output
is *summed* into an adoption rate and a capacity, not thresholded and forgotten, so it has
to be a calibrated probability; and with a few tens of thousands of rows across two dozen
spatial folds, a linear model in good features is the appropriate capacity. Leaving out
scikit-learn also keeps this stage runnable in the base environment, with no PyTorch.

**Skill is measured leave-one-quadrat-out.** Every building's reported score comes from a
model that never saw its quadrat. A random split would put two roofs on the same street in
train and test and report skill the model does not have.

| Measure | Value | Read it as |
| --- | --- | --- |
| Median fold AUC | **0.879** | ranking skill on a quadrat the model has never seen |
| Median fold AUC within roof-size band | **0.834** | the same, with size removed as a discriminator |
| Segmentation raster, within size band | **0.500** | chance. The 400 m<sup>2</sup> floor, measured |
| Fraction head, unconditional | 0.634 | better than segmentation, still well behind |

### Why the within-size number is the honest one

Adoption genuinely rises with house size: mappers report large houses packed with PV and
small ones much less. A classifier handed footprint area therefore scores well above
chance from that propensity alone, and in the ablation below `area_only` reaches 0.744
without the imagery contributing anything at all. `auc_within_size` scores inside roof-area
bands and weights by band size, which removes size as a discriminator entirely. What is
left is the pixels separating a PV roof from a PV-free roof **of the same size**. Quote
0.834, not 0.879.

### What the pixels actually add

Leave-one-quadrat-out median AUC per feature block:

| Feature block | AUC | AUC on buildings below 500 m<sup>2</sup> |
| --- | --- | --- |
| Size only | 0.737 | 0.721 |
| Reflectance only | 0.840 | 0.840 |
| **Size plus reflectance (shipped)** | **0.879** | **0.877** |
| Plus footprint shape | 0.878 | 0.876 |
| Plus the segmentation and fraction rasters | 0.878 | 0.870 |

Reflectance alone beats size alone by a wide margin, which is the result that matters: the
model is reading roofs, not guessing from a size prior. The last two rows move the number
by no more than about 0.001, well inside fold noise, so neither block is switched on. Adding the
segmentation raster in particular has no case: it is trained with sub-400 m<sup>2</sup>
arrays burned as `ignore`, so its probability there is noise a fit can only chase.

### Folds are not one population, and should never be pooled

Skill has to be read per quadrat. Industrial estates and dense residential neighbourhoods
are not the same problem, and the folds say so: the best fold reaches 0.98
(Muzaffargarh Rural Wide, 9 mapped installations) and the worst 0.66 (Khairpur Rural, a
rural box with three mapped installations, where AUC is barely defined). Mardan at 0.766
is the weakest fold with a real sample behind it and is excluded by name from the
capacity calibration. Nasirabad Rural, this project's first confirmed-zero-installation
quadrat (see [Calibration quadrats](calibration-quadrats.md)), has no AUC at all --
`roofclf.auc()` returns NaN by design when a fold has no positives to rank against,
rather than raising.

!!! danger "Ranking transfers between places. Absolute rates do not."

    `rate_ratio`, the model's predicted adoption rate divided by the true one, spans
    **0.28 to 4.41** across the 26 quadrats with a defined true base rate. The predicted
    rate is nearly flat (mean about 0.14) while the true base rate spans under 1% to over
    25%, so the ratio is close to `constant / base_rate` by arithmetic. Any published
    adoption rate or capacity needs a per-stratum correction first. Everything in stage 5
    exists because of this. (Nasirabad Rural's own `rate_ratio` is nominally in the
    millions -- dividing by a true base rate of exactly zero -- which is why it is excluded
    from this span rather than reported as if it meant something.)

## 4. The deployment threshold

A national scorer needs one operating point, and it is chosen for **precision**, not for
balanced sensitivity: this signal contributes to a capacity number that no human reviews,
so a false positive is expensive here in a way it is not in the mapping-leads queue.

`p_roofclf >= 0.2511` is the smallest threshold holding precision at 0.50 on the pooled
out-of-fold scores, and it catches 63% of PV-carrying buildings there. Both numbers are
still leave-one-quadrat-out measurements: one threshold instead of 27 per-fold ones, but
no building ever scored by a model that saw its own quadrat.

The threshold moves whenever the quadrat set changes, and it has moved a lot: 0.4555 at
nine quadrats, 0.3064 once Quetta was dropped, 0.2443 at 23 quadrats, 0.251 at 25 quadrats
(after Sanghar and Bahawalnagar Rural were added), **0.2511 today** (27 quadrats, after
Nasirabad Rural and Tank Rural were added and the model refit again, same day,
2026-08-13). Anything downstream that hard-codes it is a bug.

## 5. Scoring a country

`earthpv roofclf-score-national` applies one pooled fit, on all quadrats together, to
every VIDA building in the AOI, working one 0.1 degree cell at a time, resumable per cell
in the same way `density.py` is. For Pakistan that is about 75.7 million buildings across
4,463 cells and two to three hours on CPU. Each building gets `p_roofclf` and, from the
same five bands at no extra read cost, an [SPPI](../issues/sppi-spectral-index-evaluation.md)
value.

Two bugs were found here that are worth knowing about, because both produced enormous,
plausible-looking false-positive populations rather than crashing:

- **Composite fill read as near-certain PV.** A tile's bounds round-trip through lat/lon
  and back inflates the requested window past the tile, and the merge fills the excess with
  zeros. Zero reflectance is darker than any roof, and PV is dark, so an all-fill footprint
  scored 0.73. That was 2.86 million buildings, 45.6% of every flagged building in the
  country, in a band along every cell edge. Fill pixels are now excluded from the zonal
  statistics, and a footprint left with no valid pixel keeps its row but scores NaN, which
  can never clear a threshold. Full write-up:
  [cell-edge false positives](../issues/roofclf-cell-edge-false-positives.md).
- **The same building scored twice.** Composite tiles overlap, and Pakistan's tile set
  carries two grid origins describing the same ground, so a building could be claimed by
  two differently-named cells. Cells now come from a canonical, deduplicated manifest and
  each reads its own exact 0.1 degree box.

## 6. From a probability to a capacity number

A flagged building is not yet a megawatt. Three corrections stand between them, and each
one exists because skipping it produced a number that was wrong by a factor rather than by
a few percent.

**Restrict the domain.** roofclf only counts buildings in cells whose building density
falls inside the range spanned by the calibration quadrats themselves, currently 48.5 to
5,258 buildings per km<sup>2</sup>. That is 2,957 of Pakistan's 4,463 cells, 66.3% of cells
and 94.7% of national buildings. The restriction is the whole answer to the `rate_ratio`
problem above: rather than correcting a rate the evidence cannot support, the module
refuses to speak where no quadrat resembles the ground. **Rescaling the domain figure by
its share of cells or buildings to get a national total is exactly the error this design
prevents**, and `sub400_capacity`'s own returned summary says so.

Widening the domain therefore needs new ground truth, not new code, and the constraint is
subtle: a quadrat extends the range only if **its own** average density falls outside the
current band. A boundary traced around a village, the natural way to draw one, is dense by
construction no matter how empty the surrounding cell is. Two quadrats deliberately drawn
to include farmland alongside a settlement took the lower edge from 553 to 141
buildings/km<sup>2</sup> and grew the domain from 646 to 1,680 cells; a third,
Bahawalnagar Rural (hand-drawn in JOSM, own density 123.5 buildings/km<sup>2</sup>), pushed
it down again to 1,868 cells; a fourth, Nasirabad Rural (this project's first confirmed-zero-installation quadrat, own density 48.5 buildings/km<sup>2</sup>), pushed it down again to 2,957 cells the same day. Tank Rural, added alongside Nasirabad Rural, measured 55.75 buildings/km<sup>2</sup> -- inside the widened range, but not itself the new floor.

**Remove what is already counted.** A flagged building within 30 m of an existing
segmentation candidate, or of a mapped OpenStreetMap installation, is dropped. Anything
whose own footprint is at least 400 m<sup>2</sup> is dropped from the sub-400 figure too,
since that is a matching gap rather than small-PV signal. The OSM half of this was missing
until 2026-08-06 and was double-counting about 3% of the capacity.

**Convert area honestly.** Panels cover part of a roof, not all of it. Multiplying flagged
roof area by precision alone, which was the original approach, corrects for false positives
and silently assumes full coverage. Measured against the quadrats' own mapped
`pv_area_true_m2`, real coverage is about 0.19 of a flagged footprint for roofclf alone and
0.27 where roofclf and SPPI agree, so the original figures were 2.4 to 2.7 times too high.
The coverage ratio is now fitted per roof-size bin and per building-density band, then
0.18 kWp per m<sup>2</sup> of module converts covered area to capacity.

## Where the numbers land

| Component | Population | MWp |
| --- | --- | --- |
| Sub-400 m<sup>2</sup>, roofclf and SPPI agreeing, in domain | Internal floor on Best estimate | 2,180 |
| Sub-400 m<sup>2</sup>, roofclf alone, in domain | Best estimate | 7,890 |
| At or above 400 m<sup>2</sup> rooftop, roofclf, in domain | Best estimate | 7,189 |
| Sub-400 m<sup>2</sup>, roofclf and SPPI agreeing, outside the domain | Best estimate only | 62 |

The published atlas total, which also carries hand-mapped OSM and the segmentation model's
own ground-mount and out-of-domain rooftop estimates, is **Best estimate 18,279.6 MWp (90%
range 14,401 to 21,846)**.

The two Best-estimate roofclf rows are **recall-corrected as of 2026-08-15**: the coverage
ratio prices the PV on roofs roofclf flagged, and dividing by the measured share of true
mapped PV area that lands on a flagged roof (0.808 sub-400 m<sup>2</sup>, 0.978 at or above
400 m<sup>2</sup>, per size bin and density stratum) extends that to the roofs it missed --
the same correction the segmentation half has always used. The floor row is deliberately
left uncorrected, because a floor that extrapolates to installations neither detector saw
is not a floor. See [the capacity map](../results/capacity.md)'s "A twelfth change" for the
full derivation and the three ways the correction is a lower bound on itself.

Three things about that table are worth stating plainly:

- **SPPI is a second opinion, not a feature.** Adding SPPI as a roofclf input changes AUC
  from 0.8736 to 0.8734, which is nothing. Requiring the two to *agree* raises precision
  from 0.53 to 0.63 on the same quadrats, at 0.46 recall instead of 0.73. They share no
  training data, which is why agreement between them is evidence and why it sets the
  internal floor under the atlas's headline figure.
- **At or above 400 m<sup>2</sup>, roofclf replaces segmentation rather than adding to
  it**, inside the calibrated domain only. Measured on the identical 92 cells at the time
  of the swap, roofclf's rooftop estimate came to 2.18 times segmentation's. Outside the
  domain, segmentation's own recall-corrected number stays authoritative, because it is the
  only evidence-backed figure there.
- **The out-of-domain row is a labelled extrapolation.** All of those cells sit *below* the
  calibrated density band, with a median density roughly six times sparser than the least
  dense quadrat, so a coverage ratio measured on urban quadrats is being applied to rural
  ground where nothing constrains it. It feeds Best estimate only, and it
  is drawn with its own outline on the atlas map. It exists because the JOSM validation
  pass meant to test that population could not be done: the available reference imagery is
  too old to confirm or refute recent installations there.

## What roofclf cannot do

- **Ground-mounted PV below 400 m<sup>2</sup> has no instrument at all.** roofclf scores a
  building footprint, and a small free-standing array does not have one. This is a distinct
  open gap, not a smaller version of the rooftop one.
- **Very bright non-PV roofs.** A cluster of white-roofed buildings in cell `0061_0012`
  scores 0.98 to 1.00, and SPPI does not catch them either, so the AND-gate does not help.
  Retraining on the six known examples changed nothing, and oversampling them traded away
  general skill; mining more of the pattern is the open lead, and
  [mining them through glint](glint.md) works only for roofs at or above 1,000
  m<sup>2</sup>, which is not where this failure lives.
- **Exact attribution in dense clusters.** In the tightest quadrats the median spacing
  between neighbouring small installations is 15 to 20 m, at or below one Sentinel-2 pixel.
  A flagged polygon there can sit among several real arrays rather than on the one carrying
  the panels. That is a sensor-resolution ceiling, not a training defect.
- **Speak for the country.** Everything above is scoped to the calibrated domain, and the
  restriction is enforced in code rather than left to the reader.

## Running it

```bash
# 1. Fit on every discovered quadrat, evaluate leave-one-quadrat-out, pick the threshold.
pixi run earthpv roof-classifier --aoi pakistan

# 2. Score every building in the country. Long: two to three hours, CPU only, resumable.
pixi run earthpv roofclf-score-national --aoi pakistan

# 3. Essential, not optional: validate against randomly drawn cells in JOSM.
pixi run roofclf-tiles -- --random-cells 20 --seed <fresh int> --mapcss

# 4. Turn probabilities into capacity. Both are CPU only and take minutes, because the
#    domain restriction means only the matched cells are ever read.
pixi run earthpv sub400-capacity     --aoi pakistan --osm-solar <national OSM solar pull>
pixi run earthpv ge400-roof-capacity --aoi pakistan --osm-solar <national OSM solar pull>
```

Then rebuild the evidence atlas from the building-level parquets those two steps write:
see [Setup New Country](../reproduce.md) steps 13 to 15 for the exact `earthpv atlas`
invocation and its four `--sub400-*` / `--ge400-roof-cells` flags.

Quadrats are discovered from disk, so a new `*_calib_*_boundary.geojson` with a matching
mapped-solar pull is picked up with no flag. `roof-classifier` writes `data/roofclf/`:
`model_full.json` (the pooled fit every later step reads), `buildings.geoparquet` (every
labelled building with its out-of-fold probability), `folds.csv`, `ablation.csv` and
`summary.json`. Step 3 is part of the workflow rather than an extra: the quadrats are
curated and industrial-leaning, so scoring well on them is not evidence that the model
works on the un-curated rest of the country.

## Read next

| Topic | Page |
| --- | --- |
| The quadrats: how they are drawn, mapped and declared complete | [Calibration quadrats](calibration-quadrats.md), [Quadrat protocol](../calibration-mapping-protocol.md) |
| The random-cell validation protocol and its log | [Roofclf random-cell validation](roofclf-national-validation.md) |
| How the sub-400 m<sup>2</sup> capacity bracket was arrived at | [Capacity density](density.md) |
| The national deployment write-up and the temporal features that failed | [Roofclf national deployment](../issues/roofclf-national-deployment-and-temporal-features.md) |
| The cell-edge and tile-overlap bugs in full | [Roofclf cell-edge false positives](../issues/roofclf-cell-edge-false-positives.md) |
| SPPI, the zero-training index it is cross-checked against | [SPPI spectral index](../issues/sppi-spectral-index-evaluation.md) |
| Whether a complete register agrees with any of this | [Validation against MaStR](mastr-validation.md) |
