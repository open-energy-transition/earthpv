## SPPI physics-based PV index: tested, not adopted for detection (2026-07-29)

!!! warning "SUPERSEDED in its title claim (as of 2026-08-11)"

    SPPI is now deployed nationally, as the corroborating half of the roofclf-AND-SPPI
    gate that defines the evidence atlas's Verified tier. Two of this doc's conclusions do
    still hold: SPPI cannot serve as a standalone capacity instrument, and adding it as a
    roofclf feature changes nothing. Its segmentation comparison figures should not be
    reused -- they came from a non-production raster scored over an all-sizes population,
    and a later audit measured the production checkpoint at 0.761-0.775 AUC on buildings
    at or above 400 m².

Evaluation of He et al. 2026, "Spectral-Feature-Driven photovoltaic Detection: A universal
Physics-Based index for rapid Localization" (Int. J. Applied Earth Obs. Geoinf. 147, 105164,
doi:10.1016/j.jag.2026.105164) -- `todo.md` item 12. Reproduce with
`.pixi/envs/default/bin/python scripts/sppi_index_test.py`.

The paper proposes SPPI, a zero-parameter spectral index:

    SPPI = (B01/B03) * (B11 - B03 - |B08 - B03| - |B12 - B03|) / (B11 + B03)

a visible "blue-shift" amplifier times a SWIR background-suppression term, combined
multiplicatively as a spectral AND. B01 is not in earthpv's 10-band composites
(`LOCAL_BANDS` drops B01/B09), so we substitute B02 -- the paper's own recommendation,
which it puts at +/-2% accuracy cost.

### Measured on our nine mapped quadrats

Scored per building over `data/roofclf/buildings.geoparquet` (roof-mean reflectance vs
exhaustively mapped PV), which is the sub-400 m<sup>2</sup> regime we care about. `_ws` is
the within-roof-size-band AUC this project treats as the honest number.

| signal | median AUC | median AUC within size band |
| --- | ---: | ---: |
| **SPPI** (zero training) | **0.823** | **0.828** |
| SPI (Tian 2022, the paper's baseline) | 0.819 | 0.782 |
| NDPI | 0.789 | 0.740 |
| our fraction head | 0.702 | 0.704 |
| our segmentation raster | 0.511 | 0.501 |
| our roof classifier (17 features, fitted) | 0.874 | 0.842 |

Two results matter here.

**SPPI beats both of our trained model rasters, with no training at all.** In
`karachi_coast` -- the Rule-1-complete quadrat where the segmentation model scores exactly
0.500 and predicts 0.0 m<sup>2</sup> of PV against 13,964 m<sup>2</sup> mapped -- SPPI scores
0.755/0.723. It is not blind where our detector is. That is a real finding and it
independently corroborates the roof-classifier ablation's conclusion that per-footprint
*reflectance* carries the small-array signal (0.841 alone) while the detection rasters do
not.

**But it adds nothing to the shipped classifier**, because that classifier already contains
every band SPPI is built from, with fitted rather than hand-specified weights:

| feature set | median AUC | within size band |
| --- | ---: | ---: |
| default (17 features) | 0.8736 | **0.8423** |
| default + SPPI | 0.8734 | 0.8377 |
| `log_roof_area` + SPPI only (2 features) | 0.8351 | 0.8231 |

Adding SPPI moves the headline metric by -0.005, i.e. nothing, in the same
within-noise band as the seg/frac raster features. **So: no change to `roofclf`'s default
feature set.** Worth recording that SPPI is a very efficient *compression* of that
information -- two features reach 0.823 where seventeen reach 0.842 -- which is what makes
the cold-start use below attractive.

The paper's claimed advantage over the older SPI partly reproduces: nearly identical on raw
AUC (+0.004) but a genuine +4.6 points on the size-conditional metric, so its refinements do
buy something specifically on small roofs.

### Follow-up (2026-07-29): can SPPI carry capacity on its own? No.

Prompted by the proposal to build an SPPI-only density estimator, bypassing the foundation
model. AUC measures *ranking*; capacity needs *area*, so this needed a separate test.

SPPI's correlation with each footprint's true PV areal fraction has median Pearson
**r = 0.42 (r<sup>2</sup> = 0.18)**. That is better than the fraction head's r = 0.22, but it
still leaves ~82% of the variance in how much PV a roof carries unexplained. Aggregate
predicted-over-true PV area, leave-one-quadrat-out, i.e. the same `scale` column
`roofclf.exp_scale_anchor` reports:

| quadrat | stratum | SPPI scale |
| --- | --- | ---: |
| Lahore DHA | 1 affluent residential | 0.261 |
| Multan | 6 industrial | 0.270 |
| Sundar | 6 industrial | 0.303 |
| SITE Karachi | 6 industrial | 0.377 |
| Faisalabad | 6 industrial | 0.431 |
| Karachi coastal | 1 affluent residential | 0.574 |
| Mardan | 1/3 planned residential | 0.928 |
| Sialkot | 2 dense old urban | 2.218 |
| **Quetta** | **5 arid / bare-land** | **4.678** |

**18x spread, so SPPI cannot be a standalone capacity instrument** -- better than the
fraction head's 49x, but nowhere near a publishable single constant, and it fails the same
way for the same reason: no per-stratum intercept exists.

**The specific failure mode is disqualifying for our geography.** SPPI's worst
over-prediction, 4.7x, is in the *arid* quadrat -- bare ground reading as PV, which is
already earthpv's dominant false-positive mode and the entire reason
`plausibility.py` exists. SPPI's SWIR background-suppression term was supposed to kill
exactly that class and does not. Pakistan is largely arid, and the regions whose numbers
are already least trustworthy (Balochistan, Gilgit-Baltistan) are the arid ones, so
deploying SPPI nationally without a stratum correction would make the worst existing
problem worse, not better.

**This also retracts the corroborator suggestion made above.** The previous section proposed
using SPPI to adjudicate whether Gilgit-Baltistan's 288 `no_building` candidates are real.
It cannot: sharing the bare-ground failure mode means SPPI firing there is not independent
evidence of PV, only evidence that bright arid ground fools spectral methods generally.
Glint remains the genuinely independent channel, because its physics (specular geometry) is
unrelated to broadband brightness.

### But it is strongly complementary, which is the real finding

Both detectors flagging their own top-K buildings (K = the true PV-building count per
quadrat, a matched operating point), share of true PV **area** captured:

| | median |
| --- | ---: |
| fraction head alone | 42.3% |
| SPPI alone | 61.4% |
| both agree | 30.6% |
| **SPPI only (the increment)** | **17.7%** |
| **union** | **73.1%** |

They overlap on only 30.6% of the area, so they are substantially independent detectors,
and the union captures **+30.8 points** more true PV area than the fraction head alone.
That is a real, large complementarity effect and it is the one part of the
SPPI-in-parallel proposal that the data supports.

!!! danger "Complementarity does not mean 'add it to the total'"
    The headline `est_mwp_rc` is already **recall-corrected**: calibrated detected area
    divided by measured per-bin recall. The PV a second detector would find is therefore
    *already in the published number*, carried by the 1/recall multiplier. Adding an
    SPPI-derived capacity on top double-counts it.

    The correct operation is to combine the detectors, then **re-measure recall of the
    combined detector**. Recall rises, so the divisor rises too, and the estimate can move
    in either direction or barely move at all. **The payoff is not a bigger number -- it is
    a more defensible one.** Today the small-size bins carry recall of roughly 3-33%, so
    `est_mwp_rc` leans on a 3-30x extrapolation there; lifting measured area capture from
    ~42% to ~73% shrinks how much of the answer is extrapolation rather than measurement.
    That is worth doing on its own terms, and it is a different goal from increasing
    capacity.

### On routing SPPI to urban areas specifically

The measurement does not support this. SPPI vs the shipped classifier, within size band,
on the four urban/residential quadrats: Sialkot **0.842 vs 0.770** (SPPI +7.2), Mardan
0.681 vs 0.661 (+2.0), Lahore 0.747 vs 0.762 (-1.5), Karachi coastal **0.723 vs 0.846**
(-12.3). So two favour SPPI, two favour the classifier, and the largest single gap favours
the classifier -- in the Rule-1-complete quadrat, the one with trustworthy negatives.

A more specific pattern is weakly visible: SPPI leads in *dense older/informal* fabric
(Sialkot) and trails badly in *affluent planned* housing (Karachi coastal). A roof-material
homogeneity story would explain that, but it rests on n=1 quadrat per side and the two
strata are not separable by any label the density stage currently carries. Not enough to
route on.

### Where it is worth adopting: cold start, not detection

The case is not accuracy, it is **not needing a trained model**. Our pipeline requires a
checkpoint, a GPU, and OSM labels to reach a new region; SPPI needs one arithmetic pass over
five bands. Concrete uses, none of which is "improve the detector":

1. **New-AOI reconnaissance.** ~0.82 AUC immediately in a country with no labels and no
   trained model, before `labels`/`chips`/`train` are viable. Fits `scripts/new_region.py`'s
   preflight role.
2. ~~An independent corroboration channel for the Gilgit-Baltistan question.~~
   **Retracted by the arid-quadrat result above** -- SPPI over-predicts 4.7x on bare ground,
   so it shares the failure mode it would have been adjudicating. Use glint instead.
3. **A second detector in a recall-raising ensemble** -- the complementarity result above
   (42% -> 73% of true PV area captured) is the strongest case in this document, with the
   caveat in the danger box: it buys a less-extrapolated estimate, not a larger one.
4. **Re-ranking**, as another `rank_score` term. Lower priority: candidate polygons are
   already >= 400 m<sup>2</sup> where our own confidence is decent, so this is the regime
   SPPI adds least to.

### What it does not solve

**It does not reach below our detection floor as a segmentation/polygon detector.** The
paper states a 3x3-pixel minimum, which at Sentinel-2's 10 m GSD is ~900 m<sup>2</sup> --
*above* earthpv's existing 400 m<sup>2</sup> floor, not below it. The 0.828 above is a
per-building *classification* score on footprints we already have, not evidence that SPPI
can delineate an 86 m<sup>2</sup> array. For the sub-400 m<sup>2</sup> front, it is another
per-building instrument alongside `roofclf`, and a slightly weaker one.

### Caveats on the paper's own numbers

- **Its urban/rooftop results are not Sentinel-2-alone.** Fig. 12's small-installation
  detection uses imagery *fused with GaoFen-2 at 0.8 m*. The rooftop claims do not transfer
  to an S2-only pipeline.
- **Overall accuracy is inflated by class imbalance** (94-99% OA where PV is a tiny pixel
  fraction). The Kappa spread is the informative figure and it swings 0.564 (mountainous
  Hebei, heterogeneous -- our hard case) to 0.936 (desert Qinghai). The abstract's 0.778
  hides that.
- **Thresholds are tuned per scene** by maximizing Kappa, which undercuts the "universal,
  no recalibration" framing. Our test above is threshold-free (AUC), so it sidesteps this.
- **The "1240x faster" claim compares DL training+inference against index calculation
  only**, as the paper's own table note concedes.
- SPPI's user-accuracy standard deviation (+/-13.7%) is double MixFormer's (+/-6.8%).
