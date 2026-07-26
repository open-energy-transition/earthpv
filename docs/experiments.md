# Experiments

Most of what has been tried here did not work. That is worth writing down, because the
negative results are the map of where the 10 m resolution limit actually is, and because
every one of them cost real compute that nobody else needs to spend again.

Every experiment below has runnable code in the repository. Nothing was removed on
failure.

## Summary

| Experiment | Outcome | One line |
| --- | --- | --- |
| In-domain Pakistani training chips | <span class="outcome works">deployed</span> | Tripled large-array recall in Punjab. The single biggest lever found. |
| Building prior from VIDA Open Buildings | <span class="outcome works">deployed</span> | Makes "no building nearby" a usable false-positive signal. |
| Solar-glint corroboration | <span class="outcome works">deployed</span> | Calibrated likelihood ratios per size bucket, reward-only. |
| Tile-major glint fetching | <span class="outcome works">deployed</span> | 22x faster, numerically identical output. |
| Pre-boom epoch check | <span class="outcome works">deployed</span> | Persistent 2021 signal demotes a candidate. |
| Vegetation veto | <span class="outcome works">deployed</span> | 596 of 5,132 leads vetoed, and specifically the right ones. |
| Fraction-regression head | <span class="outcome works">deployed</span> | Municipal correlation 0.740 against MaStR, versus 0.499 for segmentation. |
| Recall correction and credible intervals | <span class="outcome works">deployed</span> | Turned a structural floor into an estimate with a stated interval. |
| Per-pixel glint amplitude trim | <span class="outcome mixed">narrow win</span> | Moves pixel IoU slightly; threshold gating by glint does not. |
| Glint as a direct detector | <span class="outcome mixed">mixed</span> | About 9 percent on model leads, about 1 percent on random buildings. |
| Ground-truth calibration quadrats | <span class="outcome open">in progress</span> | Five boxes mapped of a planned 25 to 35. |
| Two-season 20-band stacking | <span class="outcome negative">negative</span> | No recall gain anywhere; slightly worse on large arrays. |
| Sentinel-1 corner reflector | <span class="outcome negative">negative</span> | Backscatter enhancement indistinguishable from speckle. |
| Cell-aggregate glint density | <span class="outcome negative">negative</span> | Wrong statistic; a per-pixel version is the untried follow-up. |
| Missed-installation glint recovery | <span class="outcome negative">negative</span> | Control false-validation rate exceeded the recovery rate. |
| Roof-axis orientation prior | <span class="outcome negative">negative</span> | Flat concrete roofs do not constrain a tilt frame's azimuth. |
| Standard-pose matched filter | <span class="outcome negative">not recommended</span> | The densest pose bin covers under 10 percent of installations. |
| Super-resolution, three variants | <span class="outcome negative">negative</span> | No gain, and hallucination risk on the detection task. |
| Time-series step detection below 400 m<sup>2</sup> | <span class="outcome mixed">partial</span> | First non-zero recall under 500 m<sup>2</sup>, but the capacity claim failed its control. |
| Epoch jump as a recall signal | <span class="outcome open">designed</span> | Uses the unused positive half of the epoch comparison. |

## What worked

### In-domain training chips

Training on Germany alone gave 0.18 per-installation recall at or above 1,000 m<sup>2</sup>
in Punjab. Adding 274 Punjabi chips, merged with `scripts/merge_chip_index.py` and
oversampled twice so Germany's larger chip count does not swamp them, took that to 0.55.
Nothing else tried has moved the domain gap comparably, which is the empirical argument
for the [mapping flywheel](workflow.md): more verified Pakistani installations are worth
more than any architectural change tested here.

### The vegetation veto, and why the obvious version fails

Manual review of countryside leads found many green fields flagged as PV. Measuring NDVI
on the composite the model actually read does **not** separate them: 150 suspect leads had
a median NDVI of 0.10 there, statistically indistinguishable from confirmed PV's 0.04.
The field a validator sees as green today was dark fallow, harvested or flooded paddy soil
when the dry-season median was built. This is a season mismatch, not a spectral confusion
the model could have avoided.

The instrument that does discriminate is the annual vegetation cycle: every crop field
greens up at some point in the year and a panel never does. A free interim version takes
the maximum NDVI across every composite epoch already on disk; the thorough version,
`scripts/veg_annual_ndvi.py`, samples a year of scenes per lead and reports the 95th
percentile. A positive control on ten leads the free version had already flagged found
eight crossing 0.3 within the year, confirming the catches are real vegetation.

## What did not work

### Two-season stacking

A 20-band two-season stack (dry-season base plus a contrast season per cell) was built to
push detection below 1,000 m<sup>2</sup>, on the theory that PV is spectrally stable across
seasons while vegetation and roofs swing. The full path is wired and TerraMind duplicates
its pretrained patch embedding into both season slots.

On the same Punjab validation installations, recall for the 1,000+, 500 to 1,000 and 250 to
500 m<sup>2</sup> buckets was 0.51, 0.17 and 0.14 seasonal, versus 0.55, 0.16 and 0.14 for
the production 10-band model. Small buckets unchanged within noise, large slightly worse.
Likely causes: too few in-domain chips to learn a temporal signal, the tiny backbone's
capacity, and post-monsoon versus dry season simply not differing enough in arid Pakistan.

### Sentinel-1 corner reflection

A tilted PV row over flat ground forms a dihedral corner reflector, which should produce
strong radar backscatter, persistently, since Sentinel-1's orbit geometry is fixed
year-round and radar is not blocked by cloud. Tested on 17 glint-validated installations
spanning the full observed azimuth range, pulling two years of Sentinel-1 RTC.

Median enhancement rate was 3.2 percent (VV) and 1.7 percent (VH) of scenes, within plain
speckle noise. Critically, ascending and descending passes gave near-identical rates,
1.7 versus 1.8 percent, with no correlation to the implied row axis. A real corner
reflector should show sharp asymmetry between orbit headings, and its absence says this
is not a usable channel at these sites through a simple per-footprint aggregate.

A lighter use of Sentinel-1 remains untried and is **not** ruled out by this: multi-temporal
backscatter *variance* separates permanent structures from seasonally changing fields, and
greenhouse metal frames give a bright return, the opposite of PV, making radar a cheap
post-hoc false-positive filter.

### Two glint routes to density, both negative

**Cell-aggregate spike counting.** Small residential arrays are individually sub-pixel and
rarely glint alone, so the hypothesis was that a dense neighbourhood of independently
oriented arrays would union their narrow glint windows into a high combined spike count.
Tested against a fully mapped Lahore cluster with up to 120 separately mapped generators in
a single 300 m block: zero-PV control cells averaged 1.0 spike, PV-bearing cells 1.45,
medians tied at 1.0, and the 120-installation hotspot showed one spike in two years.
This is probably a methodology failure rather than a physics one. A 90th-percentile
statistic over a whole cell only moves if roughly 10 percent of the cell brightens at once,
and even every installation in the busiest hotspot glinting simultaneously covers under
half of that. The correct next test is a per-pixel anomaly count, each pixel against its
own baseline, which was not attempted.

**Recovering missed installations.** Find real mapped installations the thresholded mask
misses entirely, glint-validate them, and add their area back. Tested on 43 missed German
and 208 missed Lahore installations against matched non-PV controls. Both fail the one
thing this needs to do: Germany's control false-validation rate of 20.8 percent is
uncomfortably close to the 37.2 percent rate on missed installations, and Lahore's control
rate of 8.7 percent is *higher* than its 5.3 percent missed rate, which is worse than
chance. Recovered area was 10.8 percent of the Lahore gap even before accounting for that.

### Super-resolution

Three feasibility tests, run in sequence by `scripts/run_sr_experiments.sh`: guided fusion
of the 20 m bands to 10 m, multi-image super-resolution from repeated overpasses, and
internal-learning single-image super-resolution. None improved detection, and the last
carries an obvious hallucination risk on a task whose whole output is "is there a panel
here". Scripts are kept for future reference.

## The partial result worth watching

### Time-series step detection below the floor

The Lahore calibration box contains 1,034 mapped installations with a median area near
50 m<sup>2</sup>, at which the trained model reads 0.000 probability on 99.8 percent of true
footprints and glint validates zero of 1,021. Static appearance is exhausted. But
*appearance in time* is a different signal: a panel installed in 2023 is a step change in a
dense per-pixel Sentinel-2 series, even if no single scene shows it.

`scripts/pv_step_signal.py` removes common-mode atmosphere against reference pixels, guards
co-registration by phase correlation, learns the PV installation change vector spectrally
rather than assuming a fixed index, deseasonalises with annual harmonics and per-orbit
offsets, and scans for the best breakpoint per pixel.

**The good part.** Area under the ROC curve of 0.875 and 0.74 on held-out halves, against
0.50 for the model on the same footprints. That is the first non-zero discrimination
anyone here has achieved below 500 m<sup>2</sup>.

**The part that failed.** Converting that into a city-scale unmapped-capacity number was
**rejected by its own control**. The method's estimate of unmapped area per built-up pixel
sat inside the false-area floor measured on two PV-free cropland control cubes, so
`usable_for_unmapped_total` is false and nothing in the totals block is quotable as
capacity. What survives is the ranking: step-leads are defensible as a lead ordering, and
recovery on *known* PV is licensed separately.

Two landmines are documented for anyone continuing: a propensity confound (the households
that install panels differ systematically from those that do not, in ways visible from
space) and duplicated Sentinel-2 baseline products that silently double-count dates.

## Open opportunities

Ranked by expected value over cost.

1. **Keep turning the flywheel.** More human-verified Pakistani installations, retrain,
   measure. Everything in the "worked" column above is smaller than this.
2. **Finish the quadrat programme.** Five of a planned 25 to 35 boxes are mapped. Enough
   quadrats replace optimistic snapshot recall with measured recall, which is currently the
   widest term in the capacity interval. Multan is the highest-priority target: confirmed
   solar-dense, with zero OpenStreetMap solar features.
3. **Manual review of the small bins.** In 100 to 500 m<sup>2</sup>, `p_real` is only pinned
   to [0.10, 0.89]. Twenty verdicts per bin collapse that.
4. **[Epoch jump as a recall signal](issues/epoch-jump-recall-signal.md).** The pre-boom
   comparison is currently only used to demote. A building below the candidate threshold
   today whose PV probability genuinely rose since 2021 is stronger evidence than either
   epoch alone, and the imagery already exists at zero extra network cost.
5. **Per-pixel glint anomaly counting**, the statistic the cell-aggregate test should have
   used.
6. **Sentinel-1 backscatter variance** as a false-positive filter, distinct from the
   corner-reflector idea that failed.
7. **Per-locality pose calibration**, fitting a local panel pose from whatever
   installations a subdivision already has, rather than assuming a national standard pose.
8. **Growth as a product.** Per-epoch density estimates make capacity a time series, so the
   2022 to 2026 boom becomes measurable per district and independently checkable against
   NEPRA net-metering registrations and customs import series.
