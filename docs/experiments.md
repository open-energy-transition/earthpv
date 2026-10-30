# Experiments: what was tried, and what it cost

Most of what has been tried in this project did not ship. That is worth writing down for two
reasons: the negative results are the map of where Sentinel-2's 10 m resolution limit
actually sits, and every one of them cost real compute that nobody else needs to spend
again.

This page is the register. It covers everything that was measured, whether it ended up in
[the pipeline](how-it-works.md) or not. Every experiment has runnable code in the
repository; nothing was deleted on failure.

#### How to read the verdicts:

- <span class="outcome works">shipped</span> : part of the current main workflow
- <span class="outcome mixed">partial</span> : useful measured signal, but not strong enough to promote
- <span class="outcome negative">rejected</span> : underperformed the alternative or failed its control
- <span class="outcome open">superseded</span>: previously shipped, but since replaced

## The register

| Experiment | Verdict | One line |
| --- | --- | --- |
| In-domain Pakistani training chips | <span class="outcome works">shipped</span> | Tripled large-array recall in Punjab, 0.18 to 0.55. The single biggest lever found. |
| Building prior from VIDA Open Buildings | <span class="outcome works">shipped</span> | Makes "no building nearby" a usable false-positive signal. |
| Quadrats as training data, not just correction | <span class="outcome works">shipped</span> | Became `roofclf`, now half the main workflow. |
| [roofclf, a per-building classifier](methods/roofclf.md) | <span class="outcome works">shipped</span> | 0.879 AUC (0.834 within size band) on 27 quadrats where segmentation scores near chance. |
| SPPI as a corroborating second opinion | <span class="outcome works">shipped</span> | Zero-training spectral index; agreement with roofclf sets an internal floor on the atlas's headline figure. |
| Coverage ratio stratified by size and density | <span class="outcome works">shipped</span> | Replaced precision as the multiplier, and a flat ratio with a measured per-stratum one. |
| Placement-split precision and recall | <span class="outcome works">shipped</span> | Unpooling rooftop from ground-mount moved both, in opposite directions. |
| OSM and a recall-corrected total: combine, don't add | <span class="outcome works">shipped</span> | Mapped misses were counted twice; Germany's Best fell 4.8%, Pakistan's rose 0.4% net. |
| [End-to-end validation against a complete register](methods/mastr-validation.md) | <span class="outcome works">shipped</span> | Germany ran nationally at last: 99.75% of MaStR capacity covered, and segmentation recovers about a third of what it can see. |
| [p_unmapped from a geolocated register](methods/mastr-validation.md) | <span class="outcome works">shipped</span> | Replaced Germany's `p_unmapped: 0.0` floor with chance-corrected register evidence, split by placement. |
| [Recall measured against any candidate, not the same placement](methods/mastr-validation.md) | <span class="outcome works">shipped</span> | Rooftop recall was understated up to 24x because a big array overruns its footprint and the finder gets labelled ground. |
| [The module constant, measured against a register](methods/france-validation.md) | <span class="outcome works">shipped</span> | France put `DEFAULT_KWP_PER_M2_MODULE` at 0.150 kWp/m<sup>2</sup> against the assumed 0.180. Germany could not do this at all. |
| [Reading a register back to the imagery epoch](methods/france-validation.md) | <span class="outcome works">shipped</span> | Dated ODRE vintages remove a 53% inflation that comes purely from PV installed after the flight. |
| [Localizing the detector by retraining on France](#localizing-the-detector-what-french-chips-bought-2026-09-12) | <span class="outcome works">shipped</span> | Rank correlation against the register 0.29 to 0.45, closing half the gap to Germany. Slope barely moved. |
| [The 400 m<sup>2</sup> floor, measured from outside](#the-detection-floor-measured-against-sub-metre-truth-2026-09-12) | <span class="outcome works">shipped</span> | Recall climbs with size (rho +0.83) while the sub-metre control stays flat (-0.29). Retraining on French data does not move it. |
| [v5 against v4 on a third country](results/nigeria.md#the-finding-v4-and-v5-disagree-and-v5-is-right) | <span class="outcome works">shipped</span> | Nigeria is in neither checkpoint's training data: pooled recall 0.565 to 0.728, strictly dominant, McNemar p=0.000. The v5 gain is not only French. |
| [Localizing the detector on Vietnam](results/vietnam.md#localizing-the-detector) | <span class="outcome works">shipped</span> | v9, trained with Vietnam's own OSM labels, against v5 on the held-out Central Highlands: pixel IoU 0.724 to 0.762, recall on arrays of 500 m<sup>2</sup> and up tied (0.973 against 0.960). The localized checkpoint ships. |
| [The 5 km<sup>2</sup> ground cap, outside Germany](results/vietnam.md) | <span class="outcome works">shipped</span> | Vietnam's five largest mapped parks, 5.6 to 8.3 km<sup>2</sup>, are 92 to 99% detected. An evidence-gated exception keeps them: Verified 6,258 to 8,180 MWp. |
| [Localizing the detector on India](results/india.md#localizing-the-detector-and-why-v5-ships) | <span class="outcome negative">rejected</span> | v10, trained with India's own OSM labels, against v5 on the held-out Surat-Bharuch-Vadodara box: recall on arrays of 500 m<sup>2</sup> and up 0.938 to 0.911, pixel IoU 0.686 to 0.663. v5 ships. India's labels are 84% ground-mount, a population v5 already covers. |
| [Compose scenes ranked by cell coverage](results/india.md#a-compose-defect-found-here-and-fixed-for-every-later-country) | <span class="outcome works">shipped</span> | Scenes covering the whole cell now rank before partial ones, and a whole band lost to failed reads now raises. Rewa's cell went from 87.4% to 0.0% empty; composites built earlier were not rebuilt. |
| [Solar-thermal removed from the OSM labels](results/india.md#candidate-population) | <span class="outcome works">shipped</span> | OSM tags CSP plants and water heaters with the same `generator:source=solar`. Morocco's pull was half thermal (1,697 of 3,440 features, the Noor CSP complex). Filtered for every country after India. |
| [Mapped park outlines in Best get the Verified gate](results/india.md#the-ground-perimeter-screen-and-the-5-km2-cap) | <span class="outcome works">shipped</span> | An OSM outline swapped in for a model candidate is exempt from the merge cap. It is now always ground, and above 5 km<sup>2</sup> it is credited at its detected share unless the ground screen keeps it, the rule Verified already applied. India's Best went from 75,856 to 72,271 MWp: Khavda's two outlines 3,789 to 796 MWp, and 101 park outlines VIDA had placed on rooftops moved to ground (model rooftop 4,109 to 843 MWp). Verified unchanged. |
| [Widening India's compose away from buildings](results/india.md#widening-the-compose-away-from-buildings) | <span class="outcome works">shipped</span> | Every cell within three of the building and label selection (+3,573) imaged on the same checkpoint. Best 72,271 to 72,705 MWp: Khavda's outlines imaged whole (+330), about 220 MWp of false positives on Himalayan slopes and snow edges, and a precision floor diluted by the new unmapped candidates (-140). Found unmapped parks in Rajasthan as leads. Verified unchanged. |
| [Unmapped parks above the merge cap, priced by review](results/india.md#parks-the-model-found-that-nobody-has-mapped) | <span class="outcome works">shipped</span> | In India the 100,000 m<sup>2</sup> cap was excluding solar parks OSM does not hold: 30 of the 30 largest new-lead outlines and 50 of 60 drawn by area from the rest are parks. Admitted at that share outside the Himalaya, and mapped outlines above 5 km<sup>2</sup> now credited at their detected share in Verified instead of dropped: Best 72,705 to 99,542 MWp, Verified 67,593 to 70,523 (owner-reviewed). |
| [India against its register](results/india.md#against-the-mnre-register) | <span class="outcome works">shipped</span> | MNRE's state-wise register (MoSPI eSankhyiki), January 2026: ground-mounted Best 0.88 of registered utility PV (0.79 on an AC basis), rank correlation 0.95 over 19 states, 14 within a factor of 1.5. Rooftop 7.5%: household systems are below the sensor. |
| [Localizing the detector on Egypt](results/egypt.md#localizing-the-detector) | <span class="outcome works">shipped</span> | v12, trained with Egypt's own OSM labels, against v5 on the held-out Cairo Governorate: recall on arrays of 500 m<sup>2</sup> and up 0.043 to 0.217 (1 and 5 of 23), pixel IoU 0.066 to 0.062. The localized checkpoint ships, on a thin holdout (seven positive chips, four installations of margin). |
| [Label cells cover a park's whole outline](results/egypt.md#a-compose-gap-closed-before-publication) | <span class="outcome works">shipped</span> | `compose` imaged one cell per mapped solar feature, by its representative point, so a park crossing a cell edge was half imaged and the ground screen dropped it. Every cell an outline touches is now imaged. Egypt gained five cells and two parks: Verified 2,375 to 3,315 MWp. |
| [Localizing the detector on Yemen](results/yemen.md#localizing-the-detector) | <span class="outcome mixed">partial</span> | v13, trained with Yemen's own OSM labels, against v5 on the held-out 'Amran Governorate: both find 0 of 25 arrays of 500 m<sup>2</sup> and up, pixel IoU 0 for both. The tie ships v13 under the rule, on no evidence either way. |
| [Yemen's mapped PV at Sentinel-2 resolution](results/yemen.md#why-neither-model-sees-yemens-mapped-pv) | <span class="outcome negative">rejected</span> | 1,697 of 1,892 labels are ~600 m<sup>2</sup> solar irrigation arrays in Tihama farmland, mapped in 2023. Inside-to-ring reflectance contrast is 2% per band against 8 to 25% in Egypt and Vietnam, no offset explains it, and v13 lights up 2 of 1,466 mapped features nationally. Training them as masks failed. **Revised 2026-10-23: the cause is the labels' geometry, not the sensor.** The Tihama polygons are four-corner rectangles drawn around plots; the same size of array, traced as panels in 'Amran, reads 8 to 21% darker than its ring, and the Tihama rectangles do hold a PV-like pixel when read as bags (next row). |
| [Farm ground PV from pixels, weak OSM labels as bags](methods/groundclf.md) | <span class="outcome works">shipped</span> | A footprint-free pixel model (bands, SPPI, local contrast) for arrays beside fields, which roofclf cannot see (6.6% of 'Amran's array area lies on a footprint) and segmentation does not (0 of 283). On 306 owner-traced 'Amran arrays: held-out pixel AUC 0.983, precision 0.63 at 62% array recall (a floor: unmapped and post-imagery arrays). Tihama's oversized OSM rectangles train it as multiple-instance bags (held-out bag AUC 0.934), and 88 of 150 Tihama leads were confirmed and mapped. Built with a cropland-stratified `calib-candidates --farmland` mode. Since 2026-10-24 a standard field on every atlas, in Best inside its calibration domain; recalibrated the same day on seven farm areas ('Amran and six Tihama areas), each cell priced by the region it resembles in cropland, buildings and elevation: 169.1 MWp in Yemen (90% 77 to 327). One box around all areas put Tihama's ratio (1.19, against 'Amran's 0.17) on highland terraces and reached 3.5 GWp, above Yemen's import ceiling. |
| [Farm ground PV on Pakistan's farm areas](methods/groundclf.md#pakistan-arrays-too-small-to-see-2026-10-29) | <span class="outcome negative">rejected</span> | groundclf fitted on Pakistan's first eight farm areas (four landscapes, mapped 2026-10-29) plus 35 building quadrats: held-out pixel AUC 0.81 to 0.84 where dozens of arrays are mapped, but object precision 2 to 5% at every threshold, and at the deployed one Jhang f5 (102 installations) and Swabi (57) show no array found. Ground arrays median 44 to 106 m<sup>2</sup>, against 'Amran's 581. Not scored nationally; Pakistan's farm ground PV stays unmeasured. |
| [Localizing the detector on South Africa](results/south-africa.md#localizing-the-detector) | <span class="outcome works">shipped</span> | v14, trained with South Africa's own OSM labels, against v5 on the held-out Western Cape (452 positive chips, 1,742 mapped polygons of 400 m<sup>2</sup> and up): recall on arrays of 500 m<sup>2</sup> and up 0.744 to 0.794, 1,000 m<sup>2</sup> and up 0.708 to 0.858, pixel IoU 0.364 to 0.671. The first decisive localization win of the 2026-10 queue; v5 still finds slightly more arrays below 1,000 m<sup>2</sup>, at half the pixel agreement. |
| [Localizing the detector on Morocco](results/morocco.md#localizing-the-detector) | <span class="outcome mixed">partial</span> | v11, trained with Morocco's own OSM labels (49 train chips, accepted by the owner below the chain's floor of 50), against v5 on the held-out Drâa-Tafilalet: recall on arrays of 500 m<sup>2</sup> and up 0.994 to 0.992, pixel IoU 0.938 to 0.935. A tie, shipped to v11 under the rule; the holdout is three parks (Noor IV, Noor Erfoud, Noor Zagora) with no small arrays, so it cannot separate the checkpoints where they differ. |
| [Localizing the detector on Poland](results/poland.md#localizing-the-detector) | <span class="outcome works">shipped</span> | v15, trained with Poland's own OSM labels, against v5 on a held-out Lublin region (706 chips, 361 with PV): recall on arrays of 500 m<sup>2</sup> and up 0.927 to 0.960, 1,000 m<sup>2</sup> and up 0.826 to 0.917, pixel IoU 0.571 to 0.645. A checkpoint-picker bug (a killed run's last.ckpt) first selected the wrong epoch; caught before publication and fixed. |
| [Localizing the detector on Namibia](results/namibia.md#localizing-the-detector) | <span class="outcome works">shipped</span> | v17, trained with Namibia's own OSM labels (mostly traced panel rows) plus South Africa's chips, against v5 on a held-out Erongo region (36 chips): recall on arrays of 500 m<sup>2</sup> and up 0.766 to 0.952, 1,000 m<sup>2</sup> and up 0.179 to 0.795, pixel IoU 0.456 to 0.662. It also reads the Cuvelai basin's seasonal pans as ground-mounted panels, about 54 MWp of Best. |
| [Quadrat candidates from a mapped-solar heatmap](https://github.com/open-energy-transition/earthpv/blob/main/scripts/heatmap_quadrat_candidates.py) | <span class="outcome mixed">partial</span> | OpenInfraMap's solar heatmap, rebuilt from the OSM pull per 1.5 km box and per 1,000 VIDA buildings, ranks boxes where a quadrat may already be close to complete. Against Germany's register (count completeness per municipality): 71% of 38 candidates sit in municipalities at least 30% complete, against 10% of all mapped boxes, and 21% against 3% at 50%; mapped density ranks completeness far more than adoption (rho 0.94 against 0.14, partly by construction, since both share the mapped count). A candidate generator, not a certificate: four in five picks sit in municipalities under 50% complete, and every one still needs the imagery sweep. In Pakistan only 404 of 263,442 boxes hold any mapped small PV, and four of the six picks are existing quadrats. |
| [roofclf on French residential PV](results/france.md#earthpv-against-france-the-sub-400-m2-instrument-does-not-transfer) | <span class="outcome negative">rejected</span> | 0.627 AUC within size band against Pakistan's ~0.834. A 20 m<sup>2</sup> array is a fifth of a Sentinel-2 pixel. |
| [13x the roofclf labels, from OpenPVMapper](results/france.md#was-it-just-too-few-labels-no) | <span class="outcome negative">rejected</span> | 16,435 positives against 1,231 moves AUC by -0.005. The model scores 0.683 even on its own label source. |
| [Authoritative footprints instead of VIDA](#authoritative-footprints-the-french-cadastre-against-vida-2026-09-12) | <span class="outcome mixed">partial</span> | VIDA misses 58% of French buildings. Fixing that is worth +0.027 AUC, which is 14% of the gap to Pakistan. |
| [roofclf transfer to Germany](results/germany.md#does-roofclf-transfer-to-germany) | <span class="outcome mixed">partial</span> | A foreign model transfers (0.70-0.72) and it barely matters which country; in-domain German training is worth +0.08. |
| [Pakistan's roofclf on Yemen's roofs](results/yemen.md#rooftop-pv-below-400-m2-borrowing-pakistans-classifier-2026-10-28) | <span class="outcome mixed">partial</span> | Ranks Yemen's four building boxes with PV as well as Yemen's own fit (median AUC 0.809 against 0.813; pooled at equal shares 0.818, now `roof-classifier --extra-table`), but saturates on rural stone houses, roofless shells and greenhouse tunnels: 13 of the 24 windows it scores highest showed no panel on Esri imagery, every window with panels was a town. Ranking is not Yemen's problem; the level is. It drew ten PV-rich town boxes (`calib-candidates --pv-rich`). The first two mapped, Yafi' and Qa'tabah town (2026-10-29), measured it: AUC 0.79 and 0.89 on household roofs, but scores summing to 3.6 per PV roof (170 over 47) against 1.115 in Pakistan's quadrats, about 3.2 times the PV there (high-leaning: the boxes were picked on their scores; Qa'tabah, picked on the fewest, reads 2.5). |
| [The sub-400 m<sup>2</sup> estimator against a complete register](results/germany.md#the-sub-400-m2-estimator-against-the-register) | <span class="outcome mixed">partial</span> | Beaten by total roof area in Germany (23% vs 58% error), beats it 3.4x in Pakistan. Regime-specific, and a perfect national total hid 47% per-municipality error. |
| [A register-calibrated German roofclf half](results/germany.md#a-calibrated-german-estimate-and-why-it-is-not-in-the-atlas) | <span class="outcome mixed">partial</span> | 52.37 GWp against a registered 54.29, but still behind a roof-area baseline (48.4% vs 37.8% error), so it is reported beside the atlas rather than inside it. |
| [Register coordinates as roofclf labels](results/germany.md#register-labels-a-better-classifier-that-makes-a-worse-estimate) | <span class="outcome negative">rejected</span> | +0.023 building AUC, 15.5 points WORSE municipal error: the geolocated band is 6.9 of 49.0 GWp, so the estimand and the labels disagree. |
| [Register counts as a known class prior](results/germany.md#calibrating-germany-without-a-mapped-quadrat-the-whole-picture) | <span class="outcome mixed">partial</span> | Fixes the label problem (33.4% against 70.6%) but ties the roof-area baseline on representative municipalities. The 18.2% first result was a PV-dense sample. |
| [Size-stratified adoption intensity](results/germany.md#the-estimator-that-finally-beats-the-baseline-and-what-rid-corrected-about-it) | <span class="outcome works">shipped</span> | First estimator to beat the German roof-area baseline: 35.4% against 37.8%, using the 200-400 m<sup>2</sup> band and no classifier. |
| [Size-dependent OSM rooftop conversion](results/germany.md#reconciling-in-grid-osm-the-overstatement-was-rooftop-not-ground) | <span class="outcome works">shipped</span> | Ground reconciled at 0.91; rooftop was 2.5x over because large polygons are roof outlines (0.051 kWp/m<sup>2</sup>) not arrays (0.200). Germany Verified 38,508 -> 25,921 MWp. |
| [RID as a control on the size relationship](results/germany.md#the-estimator-that-finally-beats-the-baseline-and-what-rid-corrected-about-it) | <span class="outcome mixed">partial</span> | Exhaustive labels confirm the band but refute the mechanism, and price OSM's size bias at +0.729 against a true +0.349. |
| [OpenPVMapper as an external reference](results/france.md) | <span class="outcome mixed">partial</span> | 91% of the register's sub-72 kWp capacity, but 0.67 recall against hand-mapped truth and a model output throughout. |
| [SPPI alone as Germany's sub-400 estimator](#sppi-alone-as-germanys-sub-400-estimator-2026-09-18) | <span class="outcome negative">rejected</span> | Orders German roofs better than the trained classifier does (33.7% against 36.8% municipal error) and still loses to crediting roof area with no classifier at all (31.2%). |
| Dividing register p_unmapped by an OSM positive control | <span class="outcome negative">rejected</span> | The control is contaminated by the same sub-30 kWp coordinate suppression it was meant to absorb. |
| OSM geometry dissolve and closest-match dedup | <span class="outcome works">shipped</span> | Nested `plant`/`generator` ways were double-counting real installations. |
| Recall correction and credible intervals | <span class="outcome works">shipped</span> | Turned a structural floor into an estimate with a stated interval. |
| Recall correction for roofclf, not just segmentation | <span class="outcome works">shipped</span> | The roofclf half was counting only the roofs it flagged; correcting it moved Best 16.6 to 18.3 GWp. |
| Quadrat-bootstrap uncertainty on the atlas | <span class="outcome works">shipped</span> | The headline figure now carries a 90% range. |
| Solar-glint corroboration | <span class="outcome works">shipped</span> | Calibrated likelihood ratios per size bucket, reward-only, never demoting. |
| Tile-major glint fetching | <span class="outcome works">shipped</span> | 22x faster, numerically identical output. |
| [Glint tile copies counted once](#glint-tile-copies-and-token-expiry-2026-10-22) | <span class="outcome works">shipped</span> | Overlapping tiles deliver one pass twice, and a glint seen in both had validated a pose on its own. Pakistan's pose survey: 346 to 336 fits, none of the rest moved. |
| [France glint pose survey](results/france.md#panel-pose-from-sentinel-2-glint-2026-10-26) | <span class="outcome works">shipped</span> | Every OSM installation of 1,000 m<sup>2</sup> or more: 1,277 of 6,337 get a pose (20.2%, Pakistan 23.2% at that size), now on the France atlas with each point's OSM id, name and place. No French control yet. |
| [A fresh Planetary Computer token for every read](#glint-tile-copies-and-token-expiry-2026-10-22) | <span class="outcome works">shipped</span> | The client cached a 45-minute token and replaced it only with under 60 s left, the cause of the silent scene loss in long glint pulls. |
| Pre-boom epoch check | <span class="outcome works">shipped</span> | A persistent 2021 signal demotes a candidate. |
| Vegetation veto | <span class="outcome works">shipped</span> | 596 of 5,132 leads vetoed, and specifically the right ones. |
| Hard-negative mining for segmentation | <span class="outcome works">shipped</span> | Bi-temporal confirmed negatives cut false-positive pixels 28.6%. |
| Fraction-regression head | <span class="outcome mixed">partial</span> | Beats segmentation on small arrays by 23x in the residential quadrat, never promoted into a published number. |
| Time-series step detection below 400 m² | <span class="outcome mixed">partial</span> | First non-zero recall under 500 m², but the capacity claim failed its own control. |
| Glint as a direct detector | <span class="outcome mixed">partial</span> | About 9% on model leads against about 1% on random buildings. |
| Per-pixel glint amplitude trim | <span class="outcome mixed">partial</span> | Moves pixel IoU slightly; threshold gating by glint does not. |
| roofclf hard-negative retrain from known false positives | <span class="outcome negative">rejected</span> | n=6 is not enough signal; oversampling trades overall skill for it. |
| Quadrat-supervised fraction retrain | <span class="outcome negative">rejected</span> | A large in-sample win the holdout does not support. |
| Two-season 20-band stacking | <span class="outcome negative">rejected</span> | No recall gain anywhere; slightly worse on large arrays. |
| Boom-window (2021 vs current) stacking | <span class="outcome negative">rejected</span> | Inconclusive: training collapsed on 332 chips. |
| Sentinel-1 corner reflection | <span class="outcome negative">rejected</span> | Backscatter enhancement indistinguishable from speckle. |
| [Snow-cover contrast for small rooftop PV](#snow-cover-contrast-and-the-one-commune-that-nearly-sold-it-2026-09-08) | <span class="outcome negative">rejected</span> | Sound physics, wrong calendar: 0.096 usable scenes per commune-winter outside the Alps. |
| Cell-aggregate glint density | <span class="outcome negative">rejected</span> | Wrong statistic for the question. |
| Missed-installation glint recovery | <span class="outcome negative">rejected</span> | Control false-validation rate exceeded the recovery rate. |
| Roof-axis orientation prior | <span class="outcome negative">rejected</span> | Flat concrete roofs do not constrain a tilt frame's azimuth. |
| Standard-pose matched filter | <span class="outcome negative">rejected</span> | The densest pose bin covers under 10% of installations. |
| [Glint PSF matched filter](issues/glint-psf-matched-filter.md) | <span class="outcome negative">rejected</span> | The PSF is real and measured, but every filter variant scores below the aperture statistic it would replace. |
| [Verified-negative false-spike rate](issues/glint-psf-matched-filter.md) | <span class="outcome works">shipped</span> | 2.0% against 8.7-20.3% on model-negative controls, which reopens the spike-rate density estimator. |
| Super-resolution, three variants | <span class="outcome negative">rejected</span> | No gain, and hallucination risk on a detection task. |
| Two-endmember spectral unmixing | <span class="outcome negative">rejected</span> | 0.659 AUC, worse than both SPPI and roofclf, with a 92x scale spread. |
| Epoch jump / step change as roofclf features | <span class="outcome negative">rejected</span> | Measured at exactly zero effect, and worse in the reflectance variant. |
| [Keeping more than the median composite](#keeping-more-than-the-median-composite-2026-09-19) | <span class="outcome negative">rejected</span> | Per-pixel p10/p90/std off the same scenes the median already downloads: +0.0003 AUC, 16 of 30 folds, sign test p=0.57. |
| [Bilinear resampling of the native-20 m bands](#the-20-m-bands-and-what-sharpening-them-costs-2026-09-19) | <span class="outcome works">shipped</span> | The model's biggest coefficients sit on bands replicated nearest-neighbour from 20 m. De-blocking them: +0.0041 AUC within size band, 20 of 30 folds, p=0.061. |
| [Regression sharpening of the 20 m bands](#the-20-m-bands-and-what-sharpening-them-costs-2026-09-19) | <span class="outcome negative">rejected</span> | Predicting SWIR from the visible bands costs 0.0047 AUC, 7 of 30 folds, p=0.008. The SWIR signal is not synthesisable. |
| [Footprint-constrained spatial unmixing](#unmixing-the-pixel-against-a-known-footprint-2026-09-19) | <span class="outcome negative">rejected</span> | Cuts reflectance error 67% on synthetic sub-pixel buildings and loses 0.0323 AUC within size band on real ones, 2 of 30 folds, p=0.000. |
| [Top-of-atmosphere instead of Sen2Cor](#l1c-against-l2a-the-correction-is-not-the-problem-2026-09-19) | <span class="outcome negative">rejected</span> | An exact coin flip, 15 of 30 folds, p=1.00, at triple the fold-to-fold spread. |
| [Temporal unmixing](#temporal-unmixing-the-dry-season-window-removes-its-own-signal-2026-09-19) | <span class="outcome negative">rejected</span> | PV pixels vary as much as PV-free roofs (ratio 1.02), so there is no damping to measure. The gain tracks background dynamism as predicted, at 0.0015 AUC. |
| [Gradient boosting instead of the linear model](#the-model-class-ranking-and-calibration-disagree-2026-09-19) | <span class="outcome mixed">partial</span> | Ranks WORSE (-0.023 within size band, 4 of 30 folds) and calibrates BETTER (per-quadrat rate error 0.031 to 0.017, 20 of 29 quadrats). |
| [Footprint shape as model features](#the-model-class-ranking-and-calibration-disagree-2026-09-19) | <span class="outcome negative">rejected</span> | -0.0001 AUC, 14 of 30 folds, p=1.00. The 0.8593 that made it look best was a difference of medians. |
| [Area-weighted training loss](#aiming-at-the-aggregate-weighting-and-recalibration-2026-09-19) | <span class="outcome negative">rejected</span> | Improves the area ratio it optimises (1.084 to 1.035) and loses on both ranking (-0.0111 AUC) and count calibration (0.0308 to 0.0395). |
| [A pre-boom epoch as the roof's own control](#the-roof-is-its-own-control-2026-09-20) | <span class="outcome mixed">partial</span> | +0.0234 within size band over the SHIPPED read path (25 of 29 folds, p = 0.0002, placebo null) but only **+0.0067 over the noise-reduced one** (23 of 29, p = 0.002). The two levers are not additive, and the old epoch is not yet deep enough. |
| [Within-footprint pixel distribution](#most-footprints-are-one-pixel-2026-09-20) | <span class="outcome negative">rejected</span> | Extremes and spread of the same pixels the zonal mean averages: -0.0006 to -0.0015 within size band, 11 to 12 of 29 folds, p = 0.27 to 0.46. |
| [Per-stratum deployment thresholds](#one-threshold-is-already-the-right-one-2026-09-20) | <span class="outcome negative">rejected</span> | Equal precision per size/density stratum COSTS 3.0 to 9.2 points of recall at matched precision (4 to 7 of 25 quadrats, p = 0.001 to 0.029). |
| [Per-stratum score recalibration, one global cut](#one-threshold-is-already-the-right-one-2026-09-20) | <span class="outcome negative">rejected</span> | The theoretically-correct version. Pooled +1.3 points of recall, median per-quadrat +0.0000, 12 of 24 quadrats, p = 1.00. |
| [Post-hoc recalibration of roofclf](#aiming-at-the-aggregate-weighting-and-recalibration-2026-09-19) | <span class="outcome negative">rejected</span> | Recovers 38% of gradient boosting's calibration gain at p=0.069. No monotone map reaches it, so that gain is a reordering. |
| [Medoid instead of band-wise median compositing](#spectral-coherence-and-where-transferability-lives-2026-09-19) | <span class="outcome negative">rejected</span> | A real artifact, but one date's spectrum loses more to noise than it gains in coherence: -0.0074 AUC. |
| [Context-relative spectral features](#spectral-coherence-and-where-transferability-lives-2026-09-19) | <span class="outcome mixed">partial</span> | Within-cell z-scores alone TIE the shipped model's ranking while doubling its rate error: ranking is relative, calibration is absolute. |
| [Local-contrast brightness (`plus_local_contrast`)](#spectral-coherence-and-where-transferability-lives-2026-09-19) | <span class="outcome negative">rejected</span> | Unmeasurable since 2026-08-09 through a NaN bug; fixed and measured at +0.0000 AUC, 13 of 30 folds. |
| [Cell-level brightness as a feature](#the-level-half-of-brightness-does-not-transfer-2026-09-20) | <span class="outcome negative">rejected</span> | Predicted to help calibration; makes it significantly WORSE, closer in 7 of 29 quadrats, p=0.008. |
| [Snow-covered roofs in Germany](#snow-in-germany-the-opportunity-is-real-the-contrast-is-not-concludable-2026-09-20) | <span class="outcome mixed">partial</span> | Answers France's opportunity objection at a 10.3% scene rate; the contrast itself is 6 scenes, bimodal, p=0.39. |
| [The composite reducer: mean, not median](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20) | <span class="outcome works">shipped-pending</span> | +0.0286 AUC within size band, 25 of 30 folds, p=0.0001. Larger than every feature block in this register combined. |
| [Multi-frame super-resolution](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20) | <span class="outcome negative">rejected</span> | Sub-pixel diversity is 1.3 m, a quarter of what fusion needs; applying the shifts is WORSE than not. |
| [SEN2SR single-image super-resolution](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20) | <span class="outcome negative">rejected</span> | -0.0367 AUC within size band, 6 of 30 folds. Invented texture dilutes real contrast. |
| [GlobalBuildingAtlas building height](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20) | <span class="outcome negative">rejected</span> | d'=+0.651 alone and +0.0006 on top of the model: height is a proxy for footprint area. |
| [The spectral SNR budget](#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19) | <span class="outcome works">shipped</span> | Measured, not argued: the noise is roof heterogeneity at 20-40x the sensor's, and the linear spectral limit is already reached. |
| [Local background conditioning](#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19) | <span class="outcome negative">rejected</span> | Cuts noise 23-43% and signal faster, at every scale from 31 m to 369 m, because PV adoption is spatially clustered. |
| [PV-free neighbours as the background](#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19) | <span class="outcome negative">rejected</span> | Undoes the clustering (0.94x of raw separation, against 0.75x) but not the loss: visible and SWIR contrast is neighbourhood-level. -0.0001 to -0.0016 AUC, 10 to 13 of 29 folds. |
| [Glint geometry as a scene-level SNR lever](#sun-geometry-neither-glint-nor-high-sun-raises-the-contrast-2026-09-19) | <span class="outcome negative">rejected</span> | The apparent gain is solar elevation: partialling it out leaves +0.025 (p=0.70). |
| [Compositing in a high-sun window](#sun-geometry-neither-glint-nor-high-sun-raises-the-contrast-2026-09-19) | <span class="outcome negative">rejected</span> | Roofs are 21% brighter pre-monsoon and the contrast is unchanged (0.98x): d-prime is illumination-invariant. |
| [Yard features for small ground-mount](issues/small-ground-mount-instrument.md) | <span class="outcome mixed">partial</span> | The building index brackets 98.5% of the population, but detection lands at 1-2% precision. |
| [Yard-SPPI and roofclf AND-gate for ground-mount](issues/small-ground-mount-instrument.md#making-sppi-and-roofclf-agree-does-not-rescue-it-either) | <span class="outcome negative">rejected</span> | The rooftop floor's construction does not transfer: 2% precision, and the best operating point turns the roofclf side off. |
| [Parcel label for roofclf](methods/roofclf.md#the-parcel-label-parcel-label-2026-08-16) | <span class="outcome works">shipped</span> | Counting PV in the yard, not just on the roof. 80% of what it recovers turns out to be rooftop PV overhanging an undersized footprint, not ground-mount. |
| Yard feature block in the roofclf model | <span class="outcome negative">rejected</span> | Loses to roof-only features even against the parcel label it was built for: 0.8712 against 0.8734. |
| SPPI as a roofclf input feature | <span class="outcome negative">rejected</span> | 0.8736 to 0.8734 AUC. It helps by disagreeing, not by being a column. |
| Glint-date imagery as a roofclf feature | <span class="outcome negative">rejected</span> | Only 7-24% of rooftops can ever glint into a near-nadir view; size-controlled AUC moves 0.7875 to 0.7879. |
| Opportunity-normalised glint sensitivity | <span class="outcome works">shipped</span> | Sensitivity varies ~2x with opportunity inside a size bin; now modelled per target instead of pooled. |
| Glint-mined roofclf hard negatives | <span class="outcome negative">rejected</span> | 126 negatives at 1.2% contamination moved held-out AUC by 0.0003. Quantity, not quality, is the binding constraint. |
| OSM as a complete reference in Germany | <span class="outcome negative">rejected</span> | 3.6% complete by unit count; implied kWp/m² unstable by more than the constant itself. |
| [A sub-400 m² level without quadrats](#a-sub-400-m2-level-without-quadrats-from-osm-and-a-past-epoch-2026-10-20) | <span class="outcome negative">rejected</span> | The same roofs in 2021 are not negatives: roofclf's 2021 score predicts today's PV at AUC 0.83 against 0.87. |
| [Google's AlphaEarth satellite embeddings in roofclf](#alphaearth-embeddings-propensity-not-panels-2026-10-22) | <span class="outcome negative">rejected</span> | Adding the 2025 embedding: -0.0003 AUC, 14 of 29 folds, recall at precision 0.5 down 0.017. The pre-boom 2021 embedding does as well, so what little it adds is propensity. |
| [AlphaEarth change as a ground-mount precision check](#alphaearth-change-finds-unmapped-ground-mount-2026-10-22) | <span class="outcome mixed">partial</span> | 2017-to-2025 change separates real ground arrays from their surroundings at AUC 0.96, and a blind review puts the real share of unmapped ground detections at about 0.15, where the precision table books 0.0. Not applied; needs your review. |
| [AlphaEarth as a second >= 400 m2 detector](#alphaearth-against-segmentation-a-different-detector-not-a-better-one-2026-10-22) | <span class="outcome mixed">partial</span> | Not better overall: lower precision where PV is mixed with farmland (0.65-0.70 against 0.83-0.88), but equal precision and higher rooftop recall (0.51 against 0.35) on the quadrats, and it finds different arrays: the union lifts quadrat rooftop recall to 0.60. |
| [Probability-weighted capacity pricing](#the-capacity-chain-is-a-quantification-problem-2026-10-22) | <span class="outcome works">shipped</span> | Pricing roof area by score instead of by a flag cuts the per-quadrat PV-area error from 0.386 to 0.094 below 400 m<sup>2</sup> (20 of 29 quadrats). The default since 2026-10-25: Pakistan's Best 24.4 to 34.6 GWp, floor unchanged. Untested in sparse national cells; `--weighting threshold` restores the old count. |
| [Prevalence estimators for prior shift](#the-capacity-chain-is-a-quantification-problem-2026-10-22) | <span class="outcome negative">rejected</span> | EM prior adjustment and adjusted counts collapse to zero in most quadrats: they differ by more than their base rate. |
| [Gradient boosting, priced end to end](#the-capacity-chain-is-a-quantification-problem-2026-10-22) | <span class="outcome negative">rejected</span> | Its better per-quadrat adoption rate does not survive the capacity chain: 12 of 29 quadrats closer, p = 0.46. |
| [The pre-boom epoch already on disk](#the-capacity-chain-is-a-quantification-problem-2026-10-22) | <span class="outcome mixed">partial</span> | composite_1 covers 4,467 of 4,473 Pakistani cells, so no download is needed; +0.0024 within size band (20 of 29, p = 0.061) and nothing under probability pricing. Not deployed. |
| [THOR at 8 px tokens instead of TerraMind's 16 px](#a-finer-token-grid-thor-at-8-px-against-terramind-2026-10-24) | <span class="outcome mixed">partial</span> | No pooled recall gain at matched precision: rooftop 400-5,000 m<sup>2</sup> 0.585 against 0.574 (p = 0.08), ground 0.928 against 0.933. Sharper outlines (pixel IoU 0.656 against 0.633) at 2.2x the training cost per batch. Not adopted. |
| [THOR on TerraMind's own token grid](#a-finer-token-grid-thor-at-8-px-against-terramind-2026-10-24) | <span class="outcome negative">rejected</span> | Ties v14 on rooftop recall (0.573 against 0.574), 1 point behind on ground. With 320 m SWIR tokens instead, it loses everywhere (rooftop 0.29). |
| [Checkpoint selection by val mIoU](#a-finer-token-grid-thor-at-8-px-against-terramind-2026-10-24) | <span class="outcome mixed">partial</span> | v14's second-best epoch finds 0.621 of rooftop arrays against the shipped epoch's 0.565, at precision 0.717 against 0.736: epoch noise is as large as the backbone effect. A recall-aware selection rule is untested. |
| [OlmoEarth embeddings as a >= 400 m2 detector](#olmoearth-embeddings-ahead-in-pakistan-behind-in-south-africa-2026-10-25) | <span class="outcome mixed">partial</span> | At segmentation's false-alarm budget it matches segmentation's precision in both countries, but its recall does not transfer: far higher in Pakistan (quadrat rooftop 0.65 against 0.35), half in South Africa's held-out Western Cape (0.22 against 0.43, and 0.26 with Western Cape training added), where it also fires on substations. Not adopted: it does not transfer, a restrictive licence, ~0.5-1 TB per country. |
| [One segmentation model pooled from every country (v18)](#one-segmentation-model-for-every-country-v18-pooled-2026-10-30) | <span class="outcome negative">rejected</span> | At matched pixel precision it finds fewer installations than v14 over 14 holdouts: rooftop 400-5,000 m<sup>2</sup> 0.474 against 0.573 (+144/-609, p < 1e-60), ground 0.910 against 0.916. It wins only Egypt (23 installations, its own training data) and loses in South Africa and France, whose share of the corpus it halved. As trained; longer training is untested. |
| [TerraMind's own input standardisation (v21)](#feeding-terramind-the-input-it-was-pretrained-on-v21-2026-10-30) | <span class="outcome negative">rejected</span> | Every checkpoint saw DN / 10000, never TerraMind's pretraining standardisation. A frozen-feature probe said that cost a lot (held-out token AP 0.469 against 0.737), but fine-tuned with v14's recipe otherwise unchanged it ties v14 on rooftop recall (0.575 against 0.574 at matched precision, p = 0.87) and is 0.6 points behind on ground. It converges in half the epochs; its one regional effect beyond epoch noise is a loss in France. |
| [PSF weights, buffered footprints, context and model-form blocks](#the-capacity-chain-is-a-quantification-problem-2026-10-22) | <span class="outcome negative">rejected</span> | Eleven more feature, weighting and training-set variants; none better than +0.0005 within size band. |
| External corroboration: nightlights and a wealth index | <span class="outcome mixed">partial</span> | VIIRS nightlights and Meta's Relative Wealth Index correlate with published capacity (r=0.76, r=0.66), but partial correlation shows most of that tracks the same building-density confound (0.54, 0.35). Kept as a plausibility citation, not promoted to a stratification input. |
| Unrestricted national roofclf capacity | <span class="outcome open">superseded</span> | 18 to 37 GWp, rejected as miscalibrated; replaced by the domain-restricted estimate. |
| Low/Central/High/All-PV bracket atlas | <span class="outcome open">superseded</span> | Replaced by the two-tier evidence atlas, which sorts by standard of proof instead. |
| Out-of-domain AND-gate extrapolation | <span class="outcome open">superseded</span> | Published 2026-08-11 to 2026-08-15, then dropped: the one Best-estimate component not measured where it was applied, and unreviewable by eye under stale imagery. -62 MWp. |
| The Ceiling tier | <span class="outcome open">superseded</span> | A threshold change roughly doubled it with no new validation, so it stopped bounding anything. |
| National dashboard bundle | <span class="outcome open">superseded</span> | Replaced by plain per-artifact result pages; the CLI still works. |

## What worked, and why

### In-domain training chips

Training on Germany alone gave 0.18 per-installation recall at or above 1,000 m² in Punjab.
Adding 274 Punjabi chips, merged with `scripts/merge_chip_index.py` and oversampled twice so
Germany's larger chip count does not swamp them, took that to 0.55. Nothing else tried has
moved the domain gap comparably, which is the empirical argument for the
[mapping flywheel](how-it-works.md#workflow): more verified Pakistani installations are
worth more than any architectural change tested here.

### A per-building classifier instead of a better segmenter

The decisive finding of this project is that below roughly 400 m² the question has to change.
Segmentation asks "where is the polygon", and at 10 m ground sampling distance a 50 m²
rooftop array does not have one. `roofclf` asks "does this *building* carry PV", which turns
an unresolvable localisation problem into a per-footprint classification problem with a
strong size prior and reflectance features. On the 27 mapped quadrats it reaches **0.879
AUC**, and **0.834** with roof size controlled for, where the segmentation raster scores
close to chance on the same buildings. That gap, not any architectural change to the
segmenter, is why the pipeline now runs two detectors.

### Requiring two detectors to agree

`SPPI` is a zero-training spectral index from the literature. As a standalone capacity
instrument it is unusable (an 18x scale spread across quadrats, 4.7x over-prediction in arid
Quetta), and as an extra column in `roofclf` it does nothing at all (0.8736 to 0.8734 AUC).
What it is good for is **disagreeing**: requiring roofclf and SPPI to agree lifts precision
from 0.496 to 0.540 at matched recall, and the gain concentrates in exactly the low-adoption
places where roofclf alone is known to over-predict. That is why agreement between the two
sets the internal floor under the evidence atlas's headline figure, rather than either
model on its own.

### One estimator, applied to both halves

The segmentation half already corrects for missed installations: each detection represents 1/recall real installations within its size class. The roofclf half did not. Its coverage ratio was measured only over flagged roofs, effectively assigning zero capacity to PV on missed roofs, even though roofclf contributed roughly four-fifths of the published estimate.

Using the existing labels from 16 trusted quadrats, area recall was estimated as the share of mapped PV area on buildings flagged by roofclf, by roof-size bin and building-density stratum. It is 0.808 below 400 m² and 0.978 at or above 400 m², rising from 0.34 for the smallest PV-carrying roofs to 0.99 for the largest. Area recall is used because missing a 300 m² array matters far more to capacity than missing a 20 m² one.

The correction raised the two roofclf components from 6,372 to 7,890 MWp and from 7,031 to 7,189 MWp, increasing the published Best estimate from 16,609 to 18,280 MWp. The internal floor was left unchanged because it is defined by agreement between two independent detectors and should not extrapolate to installations neither observed.

Coverage ratio and recall are refit within the same bootstrap replicates because they share the same quadrats and labels. The correction also remains conservative, chiefly because mapping completeness is certified only for the imagery epoch, so some recent installations on unflagged roofs can still be missed.

### OSM and a recall-corrected total: combine, don't add (2026-10-20)

Segmentation's recall-corrected figure divides every detection by the measured recall of its size class, so it already stands in for the installations the model missed. That recall is measured as the share of OpenStreetMap-mapped installations some detection matches. Best then added the mapped installations no detection matched, which are exactly those misses, so in expectation they were counted twice. Only the two countries with a recall correction are affected, Pakistan and Germany; every other atlas adds OSM to an uncorrected, detected-only figure, which is right as it stands.

Best now takes, per placement and size bin, the larger of the satellite total and the satellite-detected part plus the mapped misses: mapped misses fill in the satellite's estimate of its misses instead of stacking on it. The reduction comes out of the satellite figure's unlocated scale-up, never below what a cell actually detected, so the mapped installations stay in their own cells. An installation also counts as detected at the recall table's own 100 m, not the atlas's 30 m.

The same audit found a gap in the other direction in Pakistan. Inside the area where roofclf replaces segmentation on rooftops, a mapped rooftop array that segmentation had also detected was counted nowhere: not from the map, because a detection matched it; not by roofclf, which skips mapped buildings; and not by segmentation, whose rooftop figure is discarded there. 687 installations, 466 MWp, of which the per-cell floor had restored 36. They are now counted from the map.

Both atlases were rebuilt after a legacy rebuild (`--legacy-osm-addition`) reproduced the published data blocks exactly, so the moves are the fix and nothing else. **Germany: Best 88,709 to 84,473 MWp (-4.8%)**, 1,571 MWp absorbed from the rooftop scale-up and 2,414 from ground-mount; it is still about 9.7 GW above its ~74.8 GW register, so this explains roughly a third of that excess. **Pakistan: Best 24,330 to 24,407 MWp (+0.3%)**: 233 MWp absorbed from the ground-mount scale-up, more than offset by the restored rooftop arrays. Verified did not move in either, since it holds no satellite estimate.

A third gap, closed the same day: the sub-400 m² roofclf populations dropped every flagged roof within 30 m of any segmentation candidate, including rooftop candidates inside that same domain (whose figure Best discards) and 124 oversize blobs excluded from capacity altogether. They now dedup only against candidates whose figure Best uses (`sub400_capacity.dedup_candidates`; `--legacy-seg-dedup` reproduces the old run, and did so exactly before the new one was built). The count-based guess was ~300 MWp; measured, it is **31.6 MWp** in the central estimate and 23.4 MWp in the agreement floor, because two-thirds of the 17,670 freed roofs sit next to an OSM-mapped installation and correctly stay excluded now that it is counted from the map. **Pakistan Best 24,406.8 to 24,438.3 MWp, Verified 6,970.7 to 6,994.1 MWp.** A guess from counts and a national average was a tenth right; measure before quoting.

### The vegetation veto, and why the obvious version fails

Manual review of countryside leads found many green fields flagged as PV. Measuring NDVI on
the composite the model actually read does **not** separate them: 150 suspect leads had a
median NDVI of 0.10 there, statistically indistinguishable from confirmed PV's 0.04. The
field a validator sees as green today was dark fallow, harvested or flooded paddy soil when
the dry-season median was built. This is a season mismatch, not a spectral confusion the
model could have avoided.

The instrument that does discriminate is the annual vegetation cycle: every crop field greens
up at some point in the year and a panel never does. `scripts/veg_annual_ndvi.py` samples a
year of scenes per lead and reports the 95th percentile. A positive control on ten leads the
free version had already flagged found eight crossing 0.3 within the year, confirming the
catches are real vegetation.

### External corroboration from nightlights and a wealth index

Two proxies that had never appeared anywhere in this codebase before -- VIIRS nighttime-lights
radiance and Meta's Relative Wealth Index -- were correlated against the published atlas's
per-cell Best estimate to ask a narrower question than validation: does detected PV track the
same "built-up, electrified, and (for RWI) relatively wealthy" signal an independent,
non-imagery-derived dataset would predict. Neither proxy sees solar panels; agreement is
evidence the estimate is *plausible*, not evidence it is *correct*, and it is cited that way in
[Validity and limitations](methods/validity.md#evidence-that-the-signal-is-physical), not used
as a calibration input.

`scripts/build_pv_external_comparison.py` computes `log(1+radiance)` vs. `log(1+MWp)` and,
separately, RWI vs. `log(1+MWp)`, per 0.1&deg; cell, plus the same correlation after partialling
out each cell's building footprint area (`roof_area_m2`) -- the obvious shared confound, since a
bigger built-up cell is both brighter and has more roof to put PV on. It had run once,
2026-08-12, and was never registered here. Rerun 2026-08-26 against the then-current
18,826.7 MWp atlas (14% higher than the 16,441.4 MWp the first run saw): nightlights at
Pearson 0.761 raw, 0.545 once roof area is controlled for; the wealth index at 0.661 raw,
0.345 controlled. Both partial correlations had barely moved since the first run (0.548 to
0.545, 0.373 to 0.345), which read at the time as a stable property of the estimate's
geography.

**Rerun 2026-10-21 against the current 24,438.3 MWp atlas, and that stability did not
hold.** Nightlights correlate at **Pearson 0.755** raw (Spearman 0.750), dropping to
**0.477** once roof area is controlled for (n=4,463 cells); the wealth index at **0.748** raw
(Spearman 0.656), dropping to **0.449** (4,428 of 4,463 cells have RWI coverage). The raw
nightlights figure is unchanged, but what it carries beyond roof area fell by 0.07 while the
wealth index's rose by 0.10. The step is the 2026-09-21 area-weighted zonal refit and
national rescoring, not the 2026-10-20 fixes: the same script on the 24,330.0 MWp atlas
between them gives 0.473 and 0.447, within 0.004 of today. So the partial correlations
describe one estimate's geography, not a fixed property of PV placement in Pakistan: the
current estimate follows relative wealth more closely, and lit built-up area less, than the
August one did. The reference-hex rank correlation rose over the same step (0.82 to 0.87;
[capacity map](results/capacity.md#what-this-map-cannot-tell-you-and-what-an-independent-estimate-confirms-it-can)).

The honest reading is that both proxies carry *some* information about PV placement beyond
"this cell has more buildings" -- the partial correlations are positive and well clear of zero
-- but a majority share of the raw correlation is exactly that confound, not new information.
That is consistent with [Capacity density](methods/density.md)'s own three failed attempts at
finding any coarse per-cell proxy (candidate density, roofclf's predicted rate, SPPI agreement
rate) for which quadrat-regime a cell resembles: neither nightlights nor RWI has been tried in
that specific role, and this result is why they are not expected to do much better than the
three proxies that already failed there.
The same script also recomputes the reference-hex comparison already published on
[the capacity map](results/capacity.md#what-this-map-cannot-tell-you-and-what-an-independent-estimate-confirms-it-can)
via the same grid match, as an internal consistency check rather than a second citation of it.

### A legally-complete register as a precision instrument (2026-09-01)

Germany's own accuracy check had a hole in it: with no instrument for `p_unmapped`, its
calibration table shipped `0.0`, pricing every un-mapped candidate at zero and holding
`est_mwp_cal` to an OLS slope of 0.038 against the register.

MaStR closes it over part of the range. Coordinates are published only at or above 30 kWp
&mdash; zero of the 4.17 million units below that carry one, a privacy policy rather than
missing data, while the fill rate is 99.7% above the 72 kWp / 400 m&sup2; segmentation
floor. So a registered installation's address point falling inside an unmapped candidate is
direct evidence that the candidate is real, for exactly the population segmentation
targets. Measured per placement, the term runs from 0.061 to 0.688 for rooftop and 0.000 to
0.246 for ground, chance-corrected against the same polygons displaced 500-1,000 m.

Two things generalise beyond Germany. The register is **silent below 30 kWp**, which is the
`roofclf` domain, so this improves the instrument that was already working and does nothing
for the one that needed help most &mdash; a register does not remove the need for mapped
quadrats. And the natural refinement, dividing by an OSM-mapped positive control the way
the glint inversion does, **fails here**: German OSM rooftop PV is the 3.6%-complete
enthusiast-mapped tail, which skews below 30 kWp and so carries no coordinates, making the
control contaminated by the very suppression it was meant to absorb. Full derivation and
the rejected control:
[Validating against a complete register](methods/mastr-validation.md).

### The recall denominator, found by fixing something else (2026-09-02)

Correcting Germany's `p_unmapped` moved `est_mwp_cal` the right way and pushed
`est_mwp_rc_roof` from 0.262 to 3.11 against the register &mdash; from understating truth
to overstating it threefold. Two errors had been cancelling, and removing one exposed the
other.

The cause was not either hypothesis first written down. It was that
`derive_placement_tables` restricted **both** sides of the recall measurement by placement:
a rooftop reference installation only counted as found if the finding candidate was itself
classified `rooftop`. Precision and recall are asymmetric here. `mapped_frac` asks "is this
candidate real", so its corroboration must come from references of its own placement.
Recall asks "was this real installation detected at all", and how `postprocess` labelled
the candidate that found it is irrelevant.

Measured on Germany, rooftop recall against same-placement candidates versus against any
candidate:

| Bin | same placement | any candidate | factor |
|---|---|---|---|
| 500-1k m&sup2; | 0.128 | 0.167 | 1.3x |
| 1k-5k | 0.214 | 0.268 | 1.25x |
| 5k-50k | 0.096 | 0.693 | 7.3x |
| &gt;50k | 0.036 | 0.852 | 23.9x |

The mechanism explains why the error grew with size: a large array overruns its
imagery-derived VIDA footprint, `building_overlap_frac` collapses, and the candidate that
correctly found a rooftop installation is classified `ground_adjacent` or `no_building` &mdash;
the same footprint undersizing the parcel label exists to handle. `1/recall` then inflated
those candidates by up to the 20x clamp.

**Pakistan is affected too**, which only a complete register could have revealed: rooftop
recall there moves 0.423 to 0.808 in the 5k-50k bin and 0.065 to 0.952 above 50k, and
ground 0.107 to 0.417 in 500-1k. Its published figures come from the checked-in calibration
table and do not move until that is deliberately re-derived, which needs the glint sample
and calibration boxes. Direction: Pakistan's `est_mwp_rc` is **overstated**.

Two hypotheses were written down first and both were measured and **refuted**: that
oversize `rooftop` reference features deflated the top bin (they recall at 0.841, no
different from the rest), and that count-recall applied to area inflated the estimator
(the area/count ratio is 1.01 to 1.08, negligible). Recorded because the wrong diagnosis
was the plausible one.

### A second register, and what it could measure that the first could not (2026-09-04)

Germany's register settled the question above the 400 m<sup>2</sup> floor and was
structurally silent below it: MaStR publishes no coordinates under 30 kWp, which is
`roofclf`'s entire domain. France's register is censored in the same direction, below
36 kW, but two features of it reach where Germany could not.

**It publishes dated year-end vintages.** Because a small installation cannot be dated
individually inside an aggregate row, the current snapshot cannot be filtered to a past
epoch, but a past snapshot can simply be downloaded. Interpolating per-commune small-PV
capacity between straddling year-ends puts the reference on the same day as the imagery a
label was drawn against. That correction is worth 53%: the same fourteen communes read
0.230 kWp/m<sup>2</sup> against today's register and 0.150 against the register as it stood
when the aerial imagery was flown. The difference is entirely PV France installed in
between, and any comparison that skips the step measures growth and reports it as physics.

**Fourteen communes were swept exhaustively by hand**, on sub-metre imagery, with
solar-thermal collectors tagged separately from PV. That makes the register's small-unit
aggregate and the mapped sub-200 m<sup>2</sup> polygons the same population, and dividing
one by the other measures `DEFAULT_KWP_PER_M2_MODULE` externally for the first time. It
comes out at **0.150 kWp/m<sup>2</sup> against the 0.180 the project assumes**, ratio 0.83,
stable at 0.147 under the widest reasonable definition of what counts as PV. The
[German attempt at the same measurement](methods/mastr-validation.md) failed and was
recorded as a negative result: 3.6% OSM completeness and an implied constant spanning
0.02 to 0.99 on mapper convention.

Two findings fell out of it that were not the point of the exercise.

**The below-floor share is not transferable, now measured twice rather than argued once.**
Germany's page inferred that from dispersion across municipalities. France settles it:
17.3% of all registered French PV capacity sits below 72 kWp, 31.1% of low-voltage-connected
capacity, against Germany's 65.5% of rooftop. France's fleet is far more ground-mount-heavy,
so the practical cost of the floor is genuinely smaller there. Two complete registers differ
by a factor of two to four on the quantity this project once transferred as a constant.

**Solar thermal is a systematic confusion for imagery-based detection, and it is invisible
without the tag.** 381 of 3,335 mapped features are hot-water collectors: black glazed
rectangles on south-facing roofs producing no electricity. 137 OpenPVMapper polygons in
these communes sit on one. Any validation whose ground truth does not separate them books
that as a detection error or, worse, as capacity.

France also cannot do one thing Germany can. Its register carries **no coordinates at any
size**, so the `p_unmapped` precision instrument has no French counterpart, and **no
rooftop/ground attribute**, so every share is bracketed rather than stated.

### Where the sub-400 m² instrument stops working (2026-09-04)

`roofclf` is the half of this project that has no external check, so France was the place to
get one. It did not survive it.

Fitted on 13 exhaustively hand-mapped French communes (44,314 buildings, 1,231 with PV,
leave-one-quadrat-out, parcel label), it reaches **median fold AUC 0.710 and 0.627 within
size band**, against Pakistan's 0.857 and roughly 0.834. Building footprint size alone gets
0.673, so **spectral reflectance is worth about 0.037 AUC** here. At a threshold tuned for
50% precision it flags 16 buildings out of 44,314. Segmentation scores **exactly 0.500 in
all 13 folds**.

The cause is not the model. The median mapped French installation is **20 m<sup>2</sup>**
against a **100 m<sup>2</sup>** Sentinel-2 pixel, so the array is a fifth of a mixed pixel
that is mostly roof tile. The control that isolates this is OpenPVMapper, which recalls the
same installations at 0.67 from sub-metre aerial imagery with no size gradient across
0 to 400 m<sup>2</sup>: the annotations are findable, the sensor cannot find them.

**This bounds `roofclf` rather than refuting it.** Pakistani quadrats contain installations
that are small relative to the 400 m<sup>2</sup> segmentation floor but still large relative
to a 10 m pixel. French residential PV sits below even that, and the instrument degrades to
little more than a size prior there. The practical consequence for the published Pakistani
atlas is a caution, not a correction: the sparse-density stratum, already the least
well-supported part of the coverage-ratio fit, is the one nearest this regime.

It also answers, negatively, the "independent test of the 400 m<sup>2</sup> floor" that
had been left open. The floor is real, it is a sensor limit, and
below roughly a pixel of module area there is no Sentinel-2 instrument here at all.

### Localizing the detector: what French chips bought (2026-09-12)

France was the first country this project inferred **zero-shot** -- the v4 checkpoint was
trained on Germany, Pakistan, Punjab and Gujarat and had never seen a French roof -- and the
first where a complete register could score that decision both before and after retraining.
Same 20,501 communes, same 93.0% capacity coverage, so the two runs are directly comparable.

| estimator | zero-shot slope | retrained slope | zero-shot &rho; | retrained &rho; | Germany slope | Germany &rho; |
| --- | --- | --- | --- | --- | --- | --- |
| `est_mwp_det` | 0.127 | **0.160** | 0.262 | **0.446** | 0.340 | 0.661 |
| `est_mwp_exp` | 0.162 | **0.170** | 0.290 | **0.449** | 0.388 | 0.656 |

**The gain is in placement, not magnitude.** Spearman rose 55% and closed about half the gap
to in-domain Germany; slope moved 5 to 25% and total recovered capacity went from 26% to 34%
of registered above-floor low-voltage capacity. Spearman is scale-free, so unlike slope it
cannot be explained away by conversion constants or by France's proxy denominator (the
register has no rooftop/ground field, so "above floor, low voltage" still contains
BT-connected ground-mount). The zero-shot model was putting capacity in the wrong communes;
the retrained one largely is not.

**What changed underneath is more interesting than the totals.** The candidate population did
not simply grow, it changed shape: 13,419 candidates became 39,462, the median candidate
shrank from 8,301 to 1,400 m<sup>2</sup>, rooftop share doubled from 26.9% to 50.3%, blobs at
or above 10,000 m<sup>2</sup> fell from 6,036 to 2,076, and **total detected area went down**,
364 to 255 km<sup>2</sup>. `polygonize_chips` merges touching thresholded pixels with no upper
bound, so a sheet of weak false positives becomes one multi-hectare "installation"; a
zero-shot model tuned on Pakistani and German industrial roofs produced exactly that over
France. Three times as many objects, six times smaller, with a third less total area, is the
signature of a detector matched to a fleet of small rooftop arrays.

A prediction recorded before the baseline ran was half right and worth keeping as calibration
on this kind of forecast: the slope band (0.15 to 0.35) was about right for the uncalibrated
estimators but anchored on the wrong comparator, and the rank-correlation collapse -- flagged
in advance as "the more interesting failure" -- was the thing that actually happened, at 0.29
against Germany's 0.66.

**The caveat, stated because it limits the claim.** France is **73.6%** of the retrained
corpus (18,577 chips against 6,661 from every other region combined), so this result confounds
"French data is present" with "the corpus is 3.8x larger". A France-capped run of about 3,200
chips, matching Germany's share, would separate them and has not been run. The checkpoint
(`v5_combined_france`, epoch 25, early-stopped at 33) is applied to **France only**; Pakistan
and Germany keep v4 and their published figures are unaffected.


### The detection floor, measured against sub-metre truth (2026-09-12)

The 400 m&sup2; floor was always an argument from the sensor, four Sentinel-2 pixels, checked
against quadrats labelled off the same class of imagery. The fourteen French communes are
swept on sub-metre IGN orthophotos, so for the first time a missed installation is provably a
miss rather than an annotation gap. `mapped_vs_earthpv` measures recall per size bin against
them.

Recall climbs monotonically with installation size, Spearman **+0.83 (p = 0.042)**, from
0.000 below 20 m&sup2; to 0.095 in the 200 to 400 m&sup2; bin. **OpenPVMapper, reading the
same installations inside the same boundaries from sub-metre imagery, is flat: -0.29
(p = 0.58)**, recalling 0.58 to 0.80 in every bin. That contrast is the whole point of the
measurement. A gradient present in a 10 m detector and absent in a sub-metre one, against
identical truth, is the sensor rather than the mapper.

**The finding survives retraining, across three models.** v4 zero-shot (no French chips),
v6 (3,201) and v5 (17,059) return pooled count recall of 0.0118, 0.0103 and 0.0118, with
gradients of +0.89, +0.89 and +0.83, even though v5 tripled the national candidate count and
cut median candidate area from 8,301 to 1,400 m&sup2;. In these communes only 28 candidates
appear at all, and the median distance from a 400 m&sup2;-plus mapped installation to the
nearest one is 807 m.

This corroborates [roofclf's French result](#where-the-sub-400-m2-instrument-stops-working-2026-09-04)
from the segmentation side, by a fully independent route: the classifier found no signal in
the pixels, and the segmenter finds no polygons in the same places.

**What it does not settle.** The 400 m&sup2;-plus bin holds 44 installations, recall 0.045
with a 95% Wilson interval of 0.013 to 0.151, far too thin to claim EarthPV fails above its
own floor. These communes were chosen to be exhaustively mappable, not to hold large arrays.
The transferable result is the gradient against the control, not the level in any one bin,
and it bounds the sensor rather than the method: Pakistani arrays are small against the
400 m&sup2; floor but still large against a 100 m&sup2; pixel.

### Authoritative footprints: the French cadastre against VIDA (2026-09-12)

`roofclf` reads VIDA Open Buildings, which is imagery-derived. That is the right choice where
no authoritative footprint layer exists, which is the case across most of the project's
target geography, but it is not free. Measured over the fourteen hand-mapped French communes
against the DGFiP cadastre published through Etalab:

| | Buildings | PV-bearing | Median footprint | AUC | Within size band |
| --- | --- | --- | --- | --- | --- |
| VIDA | 44,314 | 1,231 | 163 m&sup2; | 0.7103 | 0.6274 |
| Cadastre | 103,697 | 1,759 | 53 m&sup2; | 0.7369 | 0.6548 |

**VIDA finds 43% of the buildings and 70% of the PV-bearing ones.** In Toussieu specifically
it returns 672 footprints where the cadastre returns 3,366, with a median of 146 m&sup2;
against 22 m&sup2;, and 1.9x less total built area. Bad footprints degrade three things at
once: the roof-area feature, which is the single strongest predictor; the zonal spectral
means, which get averaged over the wrong pixels; and the label itself, which is mapped PV
intersected with the footprint.

Fixing all three is worth **+0.027 AUC within size band**, closing 14% of the gap to
Pakistan's 0.821. Real, worth adopting for future French work, and not remotely enough to
make the instrument deployable. The other 86% is
[the sensor](#the-detection-floor-measured-against-sub-metre-truth-2026-09-12).

**Two operational findings came out of this.** Overture carries essentially the same French
footprints (3,826 in the Toussieu bbox against the cadastre's 3,366 inside the boundary) but
costs a global S3 scan at roughly 166 seconds per commune against the cadastre's two, and
Overture prunes its release directory to the last two releases, so `configs/aoi.yaml`'s pinned
`2026-06-17.0` no longer exists and fails as "No files found", which reads like an empty area
rather than an expired release. The cadastre is published per commune keyed by INSEE, which is
already the unit the French quadrats use.

`building_table` gained an optional `buildings` override for this; the default keeps the VIDA
fetch, so no existing caller changed.

### Glint tile copies and token expiry (2026-10-22)

Both defects surfaced while validating the France pose survey's fetch against the old path
on real data.

**One pass, counted twice.** Neighbouring MGRS tiles overlap by about 10 km, so one
Sentinel-2 pass arrives as two to four items. Their granule sensing times differ by about
14 s. `tile_scene_series_batch` dedupes on the sensing minute, so the copies survived
whenever they straddled a minute: the France pilot read 308 items for 126 dates. A glint
seen in two copies then counted as two dates that agree on one panel plane, which is the
validation criterion itself.

Re-analysed from cached series, after first confirming each published summary reproduced
exactly:

* **country2000:** 290 to 281 fits.
* **Second regional top-up:** 33 to 32 fits.
* **First top-up and the 500-target sensitivity study:** unaffected. The 500-target study
  was pulled per target, so its curve and the rank multipliers stand.
* **Surviving fits:** none moved.

`glint.annotate_spikes` now collapses rows sharing a day and a view azimuth, so every
analysis path is safe, including series pulled the old way. `tile_scene_series_batch(
dedupe_items=True)` avoids downloading the copies at all: each target is read from the one
item whose footprint holds it deepest. The default fetch is unchanged, so earlier pulls
still reproduce.

The 662-candidate glint sample behind Pakistan's `p_unmapped` was pulled through the same
path, but its series were never cached, so it cannot be checked without a re-pull.

**The token.** Search signs every asset URL with a cached 45-minute SAS token, and
`planetary_computer` replaces it only once it has under 60 s left. A tile group read late,
or for longer than the token had left, failed at open, and the guards turned each failure
into a silently missing scene. `glint._asset_href` now re-signs the bare URL at the moment
of use, and a deliberately stale href opens.

## What did not work

### Two-season stacking

A 20-band two-season stack (dry-season base plus a contrast season per cell) was built to
push detection below 1,000 m², on the theory that PV is spectrally stable across seasons
while vegetation and roofs swing. The full path is wired and TerraMind duplicates its
pretrained patch embedding into both season slots.

On the same Punjab validation installations, recall for the 1,000+, 500 to 1,000 and 250 to
500 m² buckets was 0.51, 0.17 and 0.14 seasonal, against 0.55, 0.16 and 0.14 for the
production 10-band model. Small buckets unchanged within noise, large slightly worse. Likely
causes: too few in-domain chips to learn a temporal signal, the tiny backbone's capacity, and
post-monsoon versus dry season simply not differing enough in arid Pakistan. A later
variant using a 2021 pre-boom epoch instead of a contrast season
([boom-window stacking](issues/boom-window-stacking-experiment.md)) was inconclusive rather
than negative: training collapsed on only 332 usable chips, so it did not test the
hypothesis either way.

### Sentinel-1 corner reflection

A tilted PV row over flat ground forms a dihedral corner reflector, which should produce
strong radar backscatter, persistently, since Sentinel-1's orbit geometry is fixed year-round
and radar is not blocked by cloud. Tested on 17 glint-validated installations spanning the
full observed azimuth range, pulling two years of Sentinel-1 RTC.

Median enhancement rate was 3.2% (VV) and 1.7% (VH) of scenes, within plain speckle noise.
Critically, ascending and descending passes gave near-identical rates, 1.7 against 1.8%, with
no correlation to the implied row axis. A real corner reflector should show sharp asymmetry
between orbit headings, and its absence says this is not a usable channel at these sites
through a simple per-footprint aggregate.

A lighter use of Sentinel-1 remains untried and is **not** ruled out by this: multi-temporal
backscatter *variance* separates permanent structures from seasonally changing fields, and
greenhouse metal frames give a bright return, the opposite of PV, making radar a cheap
post-hoc false-positive filter.

### Two glint routes to density, both negative

#### 1. Cell-level spike counting

The idea was that a dense neighbourhood of sub-pixel residential arrays might produce more cell-level glint spikes, even when individual arrays rarely glint strongly enough to detect alone. This was tested on a fully mapped Lahore cluster with up to 120 installations within a 300 m block.

- Zero-PV controls: **1.0** mean spike
- PV-bearing cells: **1.45** mean spikes
- Median for both: **1.0**
- The 120-installation hotspot produced only one spike in two years

The signal was too weak to distinguish PV-rich cells reliably. This likely reflects the statistic rather than the underlying glint physics, since a 90th-percentile cell measure only responds when a large fraction of the cell brightens at once.

#### 2. Recovering missed installations

A second approach tested whether glint could validate real PV installations missed entirely by the segmentation mask, allowing their area to be added back. It was evaluated on 43 missed German installations and 208 missed Lahore installations, each compared with matched non-PV controls.

- **Germany:** 37.2% validation on missed PV vs 20.8% on controls
- **Lahore:** 5.3% validation on missed PV vs 8.7% on controls

The separation is not strong enough for reliable recovery. In Germany, the control false-validation rate remains high, while in Lahore the control rate is actually higher than the missed-PV rate, indicating no useful discriminative signal.

### A measured glint PSF, and the control set that mattered more (2026-08-17)

The astronomical version of the sub-pixel problem: measure the instrument's point-spread
function from strongly-validated glints, then matched-filter against it, the way stellar
photometry pulls faint sources out of noise. Full write-up:
[Glint PSF and matched filtering](issues/glint-psf-matched-filter.md).

The PSF part works. Fitting a forward model (polygon rasterised at 1 m, Gaussian-blurred,
block-averaged onto each scene's own grid at the target's true sub-pixel position) over 68
targets below 500 m² gives **sigma 0.65 px, 90% CI 0.60 to 0.70**, against an optical theory
range of 0.49 to 0.62 px implied by ESA's stated MTF. The residual excess is covered by a
measured per-scene source displacement of 0.72 px median, so the fitted kernel is an
effective one that already contains co-registration.

The detector part does not. Every variant tested, centroid-pinned, offset-fitted, and
point-source, scores **below** the p98-minus-annulus statistic already in the pipeline
(AUC 0.485 to 0.620 against 0.648 to 0.655), significantly so over all sizes. The reason is
visible in the fit itself: sigma climbs from 0.65 to 2.20 px with installation area while
variance explained collapses from 0.49 to 0.06, because a specular glint comes from whichever
patch satisfies the mirror condition on that date rather than from the whole array. Matched
filtering is optimal for a known shape at a known position and a glint has neither, which is
the one property stars have that makes the analogy work.

The valuable result was the control set built to test it. 600 verified negatives, buildings
inside the 27 Rule-1 complete quadrats carrying `has_pv == 0`, give a false-spike rate of
**2.0%**, against the 8.7 to 20.3% previously measured on merely model-negative controls. An
ablation puts the per-pixel SCL cloud veto at half of that improvement (4.5% with it
disabled) and unmapped real PV in the old controls at the rest. Against true detection rates
the instrument separates by 15x at 100 to 500 m² and 7.9x below 100 m², so
[the spike-rate density estimator](issues/glint-spike-rate-density-estimator.md)'s stated
blocker, that false rate equals or exceeds true rate below 500 m², does not hold against
verified negatives.

### Super-resolution

Three feasibility tests, run in sequence by `scripts/run_sr_experiments.sh`: guided fusion of
the 20 m bands to 10 m, multi-image super-resolution from repeated overpasses, and
internal-learning single-image super-resolution. None improved detection, and the last carries
an obvious hallucination risk on a task whose whole output is "is there a panel here".
Scripts are kept for reference.

### Choosing the imagery date so panels glint

A well-motivated idea that the geometry refuses. `roofclf` reads a dry-season median
composite, and a median is built to suppress exactly the transient specular events that mark
a panel, so reading the dates when panels *should* glint ought to raise the signal-to-noise
ratio, especially in dense blocks where many would brighten at once.

Measured two ways. First the ceiling, from real granule sun and view angles over two years
at all 23 quadrats: because Sentinel-2 views near-nadir, the pose that reflects sunlight into
the sensor is a narrow locus, and only a **median 13.2% of a plausible south-facing installed
population (range 6.7 to 23.6%)** can land on it at all. A textbook south-facing array at
tilt 30 misses by 8.6 degrees on every scene in the archive. The single best date reaches
**1.0 to 1.8%** of rooftops, so the "one optimal date" framing fails specifically.

Then the feature itself, on the Lahore quadrat (13,500 buildings, 3,432 with mapped PV, the
densest ground truth here and exactly the dense-urban case the idea targets). It separates PV
standalone at 0.613 AUC, but **0.528 within roof-size band**, i.e. nearly all of that was
size. Added to `roofclf`'s own features under a spatial holdout, size-controlled AUC moves
**0.7875 to 0.7879**.

Full derivation, the pose-window figure and before/after imagery of the best-case buildings:
[Solar glint](methods/glint.md#can-a-predicted-glint-date-boost-the-roof-classifier). Two
narrower versions survive untouched: per-locality pose calibration, and glint's existing role
corroborating individual large arrays.

### Snow-cover contrast, and the one commune that nearly sold it (2026-09-08)

The physics here is better than the glint idea's, and it targets a weakness this project can
name precisely. Panels are tilted, smooth and dark, so they shed and melt snow faster than
the roof around them: under lying snow a small array stops being a dark patch on a dark slate
roof and becomes a dark patch on a white one. At 10 m, for a 20 m<sup>2</sup> array in a
100 m<sup>2</sup> pixel, that is the difference between a **8% reflectance deficit against a
slate roof, inside BRDF noise**, and a **19% deficit against snow on a brighter, higher-SNR
background** -- roughly 2.4x the signal, and aimed squarely at the dark-roof contrast problem
that makes French rooftops harder than Pakistani ones.

It fails on opportunity, which is the same thing that killed
[choosing the imagery date so panels glint](#choosing-the-imagery-date-so-panels-glint), and
it was measured the same way: not by building a detector, but by counting how many chances a
roof actually gets. `scripts/snow_opportunity.py` reads SCL on its native 20 m grid inside a
rasterised mask of each commune's VIDA footprints -- snow over farmland says nothing about
whether roofs were white -- and counts a scene as an opportunity when snow exceeds 5% of roof
pixels while cloud stays under 20% of them. Both conditions matter, and the cloud one is easy
to forget: in France a snowfall usually arrives with the system that hides it.

Across **1,556 scenes, 14 communes and four winters (2021/22 to 2024/25): 84 opportunities,
of which 79 are in a single commune.** Saint-Martin-de-la-Porte, alpine Maurienne at roughly
1,000 m, returns 19.8 per winter and peaks at 99.7% roof snow. Chambery returns 0.50 per
winter, Grenoble, Langoat and Saulny 0.25 each, and **nine of the fourteen communes return
zero in four winters**. Excluding the one alpine commune leaves **0.096 opportunities per
commune-winter**, about one usable scene per commune per decade.

Three things then compound, and the first is decisive:

- **The signal is where the fleet is not.** On a deliberately generous definition of mountain
  departements (Alps, high Pyrenees, Jura, Vosges, Massif Central), only **10.8% of France's
  34.6 GWp of registered PV** sits there.
- **It would need a retrain, not a processing change.** Snow currently *causes* false
  positives here: `growth.py` records 91 of 155 km<sup>2</sup> of spurious "vanishing" PV
  above latitude 34 as winter snow, and `imagery.py` excludes SCL class 11 from composites by
  design. The contrast could not be harvested by the current model, only by one trained on
  snow-bearing labels that do not exist.
- **Winter geometry adds a false-positive mode.** At 45 N in December the sun sits near 20
  degrees elevation, so shadows become large relative to buildings at 10 m, precisely while
  the method hunts dark patches on bright roofs.

**The methodological lesson is about the pilot, not the physics.** The alpine commune was run
first as a smoke test and on its own it argued the opposite conclusion, roughly 20
opportunities per winter. It is the outlier, not the norm, and a single-site pilot would have
justified building the whole thing. Opportunity has to be counted over the population the
method would be applied to.

One variant survives and is worth stating: **Germany**, which has more reliable lowland snow
and is already the largest region in the training corpus, so the retrain objection is weaker
there. If the snow hypothesis is ever tested properly it should be tested there, not in
France. Raw counts: `results/france_snow_opportunity.csv`.

### The 20 m bands, and what sharpening them costs (2026-09-19)

Six of the ten composite bands are 20 m at the sensor: B05, B06, B07, B8A, B11 and B12.
The composite is written at 10 m, and `odc.stac` was replicating each 20 m value
nearest-neighbour into a 2x2 block. Measured on cell 0122_0077, B11 and B12 are constant
across 2x2 blocks in **100.0%** of the raster, against 0.0% for B02 and B08.

That matters more than it sounds, because of where the classifier's weight sits:

| Coefficient | Value | Native |
| --- | --- | --- |
| `b11_mean` | +4.33 | 20 m |
| `swir_vis_ratio` | -3.92 | uses SWIR |
| `ndvi` | +3.73 | 10 m |
| `ndbi` | +3.65 | uses SWIR |
| `b12_mean` | -3.23 | 20 m |
| `b02_mean` | +2.78 | 10 m |

The four largest are SWIR or SWIR-derived. So the model leans hardest on bands that carry
no independent information at the grid it is scored on, and a 100 m² building's SWIR value
comes from a 20 m cell whose centre can be 10 m away from it.

Two fixes were measured against the 30 production quadrats, leave-one-quadrat-out, paired
per fold, changing nothing but how the same downloaded pixels reach the 10 m grid:

| Variant | AUC | Within size band | Folds better | Sign test |
| --- | --- | --- | --- | --- |
| Baseline (nearest) | 0.8575 | 0.8206 | -- | -- |
| Bilinear from the true 20 m grid | 0.8574 | **0.8322** | 20 of 30 | p = 0.061 |
| Regression sharpening | 0.8570 | 0.8060 | 7 of 30 | p = 0.008 |

**They point in opposite directions, and that is the finding.** Regression sharpening
predicts each 20 m band from the four native-10 m bands and adds back the residual, and it
**hurts significantly**: -0.0047 AUC, -0.0052 within size band, better in only 7 of 30
folds. The interpretation is the useful part. If SWIR were largely a function of the
visible bands, synthesising its 10 m structure from them would be nearly free; that it
costs skill says **the SWIR signal the classifier uses is genuinely independent of the
visible bands**, and replacing real-but-coarse SWIR with a visible-derived estimate throws
it away. This is a property of PV worth remembering: it is spectrally distinctive in the
shortwave infrared precisely where the visible bands cannot see it coming.

Simply removing the blockiness, by taking each band back to its true 20 m grid and
resampling bilinearly, moves the other way: **+0.0041 AUC within size band, better in 20
of 30 folds, p = 0.061**, with the median within-size AUC going 0.8206 to 0.8322. That is
suggestive rather than established, and it is free. It says the defect worth fixing is the
**misregistration**, not the missing detail.

**Shipped** as `imagery.BAND_RESAMPLING` / `annual_composite(resampling=...)`, default
`"20m-bilinear"`, with `--resampling nearest` to reproduce the old behaviour. Every
composite records which it used in an `earthpv_resampling` tag; a composite with no such
tag predates this and is nearest. **The two must not be mixed within one AOI**: the change
is small but systematic, and a model calibrated on nearest composites and scored on
bilinear ones is a domain shift rather than an improvement. That is enforced rather than
documented -- `compose` inherits an AOI's existing mode and gives only a fresh AOI the new
default, because a country-scale run is a restart loop and the first pass after a default
changes is where silent mixing happens. Pakistan, Germany, France, Zambia and Nigeria
(20,160 cells between them) are all nearest today and stay that way until someone
recomposes one wholesale, which on p=0.061 evidence is not worth the bandwidth.
SCL keeps nearest regardless, because interpolating between class 4 and class 8 invents
class 6.

### Unmixing the pixel against a known footprint (2026-09-19)

A zonal mean over a building's pixels is a mean of MIXTURES: a 100 m² roof is one 10 m
pixel it shares with road, yard and neighbours. That dilution is the mechanism behind
nearly every negative result in this register. Blind two-endmember unmixing was rejected at
0.659 AUC, but this is a different problem and a better-posed one, because the abundances
are **known**: the footprints say what fraction of each pixel belongs to which building, so

    y_p = sum_j A_pj r_j + (1 - sum_j A_pj) b_p

is a linear inverse problem for the per-building reflectance `r`, solved for a whole
quadrat at once with a ridge toward the zonal mean (`preprocess.unmix_buildings`).

**On synthetic data it works exactly as intended.** With buildings deliberately offset from
the pixel grid and 36 to 196 m² in size, so the median building fills 38% of its brightest
pixel, unmixing cuts mean reflectance error against truth by **67%** (0.0975 to 0.0319) and
recovers **84% of the true dark/bright contrast** where the zonal mean recovers 28%.

**On real quadrats it is the worst result in this register:** -0.0205 AUC and **-0.0323
within size band**, better in **2 of 30 folds**, sign test p = 0.000. Not noise, not a tie,
a substantial loss.

Two explanations, and the second is the interesting one:

- **The footprints are not that good.** The solve assumes `A` is exact. VIDA is
  imagery-derived and systematically undersized -- this project already measured 117,003 m²
  of mapped rooftop PV overhanging VIDA outlines across 27 quadrats, which is 80% of what
  [the parcel label](methods/roofclf.md#the-parcel-label-parcel-label-2026-08-16) recovers.
  A wrong `A` does not merely fail to help, it attributes the wrong pixels to the building.
- **The mixture is not purely a nuisance.** The parcel label shipped because PV *beside* a
  building counts toward it, and the yard carries label-correlated signal. Unmixing does
  the exact opposite: it strips the surroundings out in order to isolate the roof. Running
  it against a parcel label is close to self-defeating, and the size of the loss suggests
  the context is worth more than the purity.

The honest summary is that **dilution is real but removing it is not the same as
recovering the signal**, and an instrument that assumes its geometry is exact inherits
every error in that geometry. Kept as `roof-classifier`-side machinery behind
`building_table(preprocess="unmix")` for anyone who arrives with authoritative footprints
-- the French cadastre is the obvious candidate, since it already bought +0.027 AUC within
size band over VIDA there -- but off, and not recommended on an imagery-derived layer.

Raw numbers for both: `results/roofclf_preprocess_ablation.json` and
`results/roofclf_preprocess_*_folds.csv`.

### L1C against L2A: the correction is not the problem (2026-09-19)

Sen2Cor's surface-reflectance retrieval assumes a **Lambertian** surface and constrains
aerosol from dark targets. A PV module is specular AND dark, so on the face of it L2A
models the wrong physics over exactly the target of interest, in a geometry-dependent way,
and it clips the saturation a real glint produces. If that costs anything, the fix is free:
use L1C top-of-atmosphere reflectance instead.

Getting the data was the awkward part and is worth recording. Planetary Computer publishes
L2A only, and Earth Search's `sentinel-2-l1c` assets point at ESA's **requester-pays**
`s3://sentinel-s2-l1c`, which needs AWS credentials. Google's `gcp-public-data-sentinel-2`
mirrors the same SAFE archives and is anonymously readable, so `imagery.l1c_composite`
runs discovery on STAC and reads pixels as JP2 over HTTPS from GCS, on the parent
composite's own pixel grid. L1C carries no usable cloud mask (QA60 is empty from baseline
04.00), so the mask comes from the L2A scenes of the same solar days. Serially this costs
about 12 minutes a quadrat, nearly all of it JP2 opens; a thread pool over the 120
(scene, band) reads brings it to 108 s.

The composite validates against L2A exactly as atmospheric physics requires: TOA/BOA is
**1.42 in the blue, 1.19 green, 1.09 red, 0.97 NIR, 0.93 and 0.89 in the SWIR** -- strong
Rayleigh path radiance at short wavelengths giving way to absorption at long ones.

**And it makes no difference.** Over the same 30 quadrats, same rows, same features:

| | AUC | Within size band |
| --- | --- | --- |
| L2A (shipped) | 0.8575 | 0.8206 |
| L1C | 0.8429 | 0.8102 |
| Paired delta | +0.0004, **15 of 30 folds, p = 1.00** | -0.0039, 12 of 30, p = 0.46 |

Fifteen folds each way is as null as a result can be, so **the Lambertian objection, while
physically real, costs the classifier nothing measurable.**

The interesting part is the spread rather than the centre. The paired median is zero while
the median AUC drops 0.0146, and the fold-to-fold IQR is about three times the other
variants tested here (-0.0274 to +0.0128 within size band, against -0.0007 to +0.008 for
bilinear resampling). A few quadrats get much worse under L1C while the typical one is
unchanged. That is what an absent atmospheric correction should look like in a
leave-one-quadrat-out design: path radiance varies with aerosol and geometry BETWEEN
quadrats, so removing the correction adds cross-quadrat variance without touching
per-building discrimination. **The correction earns its place in transferability, not in
contrast** -- which is precisely the property a model trained on some quadrats and applied
to a whole country depends on.

Kept as `building_table(preprocess="l1c")` plus `scripts/compose_l1c_quadrats.py`, because
the reader is the reusable part: it is the project's only route to TOA reflectance, and
glint work has a standing interest in saturation that L2A discards.

### Temporal unmixing: the dry-season window removes its own signal (2026-09-19)

The third and last unmixing attempt, and the only one that needs neither the footprint nor
a known endmember spectrum. Its constraint is that a PV array's AREAL FRACTION of a pixel
is constant while the background's reflectance is not, so taking the temporal spread of

    y_p(t) = f_p . r_PV + (1 - f_p) . b_p(t)

gives `spread(y_p) = (1 - f_p) . spread(b_p)`, and `f_p` is one minus the ratio of a
pixel's temporal spread to its local background's. That is self-normalising against roof
colour, where absolute reflectance is not: a dark roof and a panel look alike in a median
composite, and the claim is that they move differently through a season.

**On synthetic data the estimator is near-unbiased**, recovering 0.492 for a true fraction
of 0.50 and 0.247 for 0.25, and refusing (100% NaN) when the background is held still.

**On real quadrats the premise is simply false.** `scripts/pv_temporal_invariance.py`
compares per-pixel temporal MAD inside mapped PV against PV-free roof pixels in the same
quadrat, which tests the assumption directly and needs no classifier:

| | Median across 22 quadrats | Range |
| --- | --- | --- |
| PV pixels / PV-free roof pixels | **1.02** | 0.89-1.23 |
| Open background / roof pixels | **1.12** | 0.91-2.02 |

A PV pixel varies over time **exactly as much as the roof beside it**, so there is no
damping to measure; and the open background moves only 12% more than a roof, so there is
barely a denominator to divide by. Only 1 quadrat of 22 has a background moving more than
1.5x a roof. At 70-150 DN of MAD against 2,000-2,800 DN of reflectance, what is being
measured is a common floor of per-scene radiometric residual and BRDF, not surface
dynamics, and a floor is added AFTER mixing so it is not attenuated by `f` at all.

The ablation agrees, over 30 quadrats leave-one-quadrat-out: **+0.0003 AUC (17 of 30
folds, p=0.46)** and +0.0011 within size band (18 of 30, p=0.26). Damping plus size alone
reaches 0.7388 / 0.5863, against a size-only baseline of 0.7441 / 0.5773.

**The conditional test is what makes this more than another null.** Registered before the
run: if the mechanism is real but starved, the gain should rise with how much a quadrat's
background actually moves. It does. Spearman between the within-size gain and
`open_over_roof` is **+0.401 (p = 0.071, n = 21 folds)**, and splitting at the median:

| | Gain within size band | Folds better |
| --- | --- | --- |
| Dynamic half (open/roof >= 1.13) | +0.0015 | **9 of 11** |
| Still half (open/roof < 1.13) | -0.0001 | 4 of 10 |

So the physics is visible in the structure of the result and worth nothing in its
magnitude. Treat that cautiously: n is 21, p = 0.071, and the single most dynamic quadrat
(malok, open/roof 2.02) runs against the trend at -0.0013, so the relationship is not
driven by its own extreme.

**The most useful thing here is why the denominator is missing, because it is
self-inflicted.** `annual_composite` takes a DRY-SEASON window of the twelve least-cloudy
scenes, chosen precisely to suppress phenological and atmospheric variation and produce a
stable composite. That is the right choice for everything else the pipeline does, and it
removes exactly the background dynamics this estimator needs. The honest next test is a
full-year stack including the monsoon, where cropland actually swings; that is different
data, not a different estimator, and it is still
open. Until then this is rejected for the window the
project actually composites.

A methodological note worth keeping: the first precondition check measured temporal
amplitude over WHOLE quadrats and looked ample (median 148 DN, all 31 quadrats clearing
the bar). The denominator that matters is the background near a BUILDING, which is other
roofs and pavement, and measuring that population gave 1.12. Checking the precondition on
the wrong population is the same error the
[snow-cover experiment](#snow-cover-contrast-and-the-one-commune-that-nearly-sold-it-2026-09-08)
records, in a different costume.

Artifacts: `results/pv_temporal_invariance.json`, `results/roofclf_temporal_unmix.json`,
`results/roofclf_temporal_unmix_folds.csv`.

### The model class: ranking and calibration disagree (2026-09-19)

Every feature block this project has measured -- SPPI, glint, the yard, epoch jump,
temporal statistics, temporal unmixing, sharpening, spatial unmixing, L1C -- was priced
against `fit_logistic`, an L2-regularised LINEAR model. A linear score cannot express a
conjunction, and "is this a PV roof?" reads like one: dark AND spectrally flat across the
visible AND the right SWIR drop AND large AND in a dense-adoption area. Six blocks landing
within 0.005 of each other is consistent with the functional form being the constraint
rather than the features, so it is worth testing directly.

Two declared `HistGradientBoostingClassifier` configurations, conservative and larger,
fixed in the script rather than selected on the held-out folds, on the same 30 quadrats
and the same table.

| Model and features | AUC | Within size band | Median per-quadrat rate error |
| --- | --- | --- | --- |
| Logistic (shipped) | 0.8574 | **0.8206** | 0.0308 |
| Logistic + shape | 0.8593 | 0.8196 | 0.0309 |
| GBM small | 0.8582 | 0.8006 | 0.0204 |
| GBM large | 0.8526 | 0.7979 | 0.0177 |
| GBM large + shape | 0.8618 | 0.7921 | **0.0165** |

**On ranking the linear model wins, and not marginally.** Paired per fold, every GBM
variant loses: -0.0089 to -0.0121 AUC and -0.0163 to -0.0231 within size band, better in
only 4 to 6 of 30 folds, p <= 0.002. The larger configuration is worse than the smaller
one, which is the signature of a flexible model learning each quadrat's idiosyncrasy
rather than what transfers between them. Note that `gbm_large_shape` has the highest median
AUC in the table (0.8618) while losing on 25 of 30 folds: a difference of medians is not a
paired gain, which is the same trap the shape block below fell into.

**So the linear model is not the bottleneck, and the feature experiments were fair.** That
is worth having established, because it is the assumption every one of them rested on.

**On calibration the answer reverses, and for this project that matters.** The atlas
consumes an aggregate adoption rate, not a ranking, and the register already records that
ranking transfers across quadrats while absolute rates do not -- which is why the
coverage-ratio-by-size-and-density machinery exists at all. Measured per quadrat, GBM
predicts the adoption rate substantially better: median absolute error **0.0308 to 0.0165**,
closer to truth in **20 of 29 quadrats for `gbm_large` (Wilcoxon p = 0.006)** and 21 of 29
with shape (sign test p = 0.024).

The obvious objection is that a model can tighten `rate_ratio` by hedging toward the global
mean, which would be worthless. It is not doing that: the spread of predicted rates across
quadrats is 0.0806 against a true 0.0798, and the correlation with the true rate RISES from
0.776 to 0.869. It keeps the dispersion and gets the level right more often.

**The two objectives genuinely disagree, and nobody had noticed because only AUC was
reported.** Nothing is being swapped on the strength of one run: the lead product and the
precision-thresholded population that feeds the coverage ratio both depend on per-building
ranking, where the linear model is better, while the capacity half depends on the rate,
where it is not. The honest next step is to price a GBM end to end through
`sub400-capacity` against the same quadrats, not to change the classifier.

#### Footprint shape, settled

`plus_shape` had scored 0.8593 against the shipped 0.8574 in the ablation table and had sat
unadopted since 2026-08-09, the best-looking block never promoted. Given the paired test
every rejected idea got, it is **noise: -0.0001 AUC, 14 of 30 folds, p = 1.00**, and
-0.0003 within size band. The apparent gain was a difference of medians across folds rather
than a per-fold improvement. Closed.

Artifacts: `results/roofclf_model_class.json`, `results/roofclf_model_class_folds.csv`.

### Aiming at the aggregate: weighting and recalibration (2026-09-19)

The [model-class test](#the-model-class-ranking-and-calibration-disagree-2026-09-19) found
that gradient boosting ranks worse and predicts per-quadrat adoption rates better. Two
cheap interventions follow from it, neither touching the feature set, both aimed at the
aggregate the atlas consumes rather than at AUC.

| Variant | AUC | Within size band | Median per-quadrat rate error | Area ratio |
| --- | --- | --- | --- | --- |
| Baseline (shipped) | **0.8574** | **0.8206** | 0.0308 | 1.084 |
| Area-weighted loss | 0.8506 | 0.8046 | 0.0395 | **1.035** |
| Isotonic, global | 0.8570 | 0.8199 | 0.0268 | 1.095 |
| Isotonic, by size tercile | 0.8560 | 0.8166 | **0.0253** | 1.128 |
| Platt | 0.8574 | 0.8206 | 0.0287 | 1.070 |
| Gradient boosting, for reference | 0.8526 | 0.7979 | *0.0165* | -- |

**Area weighting does what it promises, and that is not what the product needs.** Capacity
is area-weighted while the fit treats a 30 m² shed and a 390 m² warehouse as equally
important rows, so weighting the likelihood by roof area is the obvious correction. It
improves the quantity it optimises -- the predicted-over-true flagged roof AREA moves 1.084
to 1.035 -- and it is worse at everything else: -0.0111 AUC, -0.0160 within size band, and
a COUNT rate error that rises 0.0308 to 0.0395. Trading the population that carries the
labels against the aggregate loses more than it gains at this sample size. Available as
`fit_logistic(sample_weight=...)`, off by default, and `None` reproduces the unweighted fit
bit-for-bit.

**The calibration gain is not recoverable by recalibration, which is the useful half.** A
monotone map cannot change a ranking, so if gradient boosting were merely a better-calibrated
version of the same score, isotonic or Platt would capture it for free. They do not. The best
variant, isotonic fitted within roof-area terciles, cuts the median per-quadrat rate error
0.0308 to 0.0253 and is closer in 19 of 29 quadrats, but at **Wilcoxon p = 0.069** it is not
significant, and it recovers only **38% of the gradient-boosted improvement** (which reached
0.0165 at p = 0.006). Platt moved AUC by exactly 0.0000 in 0 of 30 folds, which is the clean
check that a strictly monotone map reorders nothing; isotonic moves it by 0.0002 only because
it creates ties.

So **gradient boosting's advantage is a genuine reordering of buildings, not a calibration
curve**, and it cannot be had cheaply. That sharpens
an open question: if the aggregate matters more than the ranking for
the capacity half, the GBM has to be deployed properly, plumbing and all, rather than
approximated by post-processing the linear model.

Calibrators were fitted NESTED -- inside each leave-one-quadrat-out fold the 29 training
quadrats were split into five blocks by quadrat, and the calibrator was fitted on the inner
out-of-fold scores. Fitting on in-sample scores would be optimistic in exactly the direction
being measured. Artifacts: `results/roofclf_weighting_calibration.json`,
`results/roofclf_weighting_calibration_folds.csv`.

### Spectral coherence, and where transferability lives (2026-09-19)

Two more attempts at the features the classifier leans hardest on, both using data already
on disk.

| Variant | AUC | Within size band | Median rate error | Paired vs shipped |
| --- | --- | --- | --- | --- |
| Baseline (shipped) | 0.8574 | **0.8206** | 0.0308 | -- |
| Medoid composite | 0.8415 | 0.7896 | 0.0280 | -0.0074, 9 of 30 |
| Plus context features | 0.8540 | 0.8166 | 0.0291 | -0.0003, 14 of 30 |
| **Context features ONLY** | 0.8595 | 0.8189 | **0.0569** | **-0.0011, 14 of 30** |
| Medoid plus context | 0.8546 | 0.7982 | 0.0287 | -0.0070, 9 of 30 |

**The band-wise median really does invent a spectrum, and fixing it does not pay.**
`annual_composite` reduces with `median(dim="time")` over a Dataset, so each band's median
is taken independently: a pixel's B02 can come from January and its B11 from March, and the
result is a spectrum no scene observed. That is harmless for one band and not harmless for a
RATIO, which is what the model weights most (`swir_vis_ratio` -3.92, `ndbi` +3.65,
`blue_red_ratio` -1.56). A medoid -- the single date per pixel whose whole spectrum is
closest to the median -- is coherent by construction, and verified to equal exactly one real
date where the band-wise median equals none. It scores **-0.0074 AUC and -0.0102 within size
band**. The trade is visible in the construction: a medoid is ONE observation, so it forfeits
the twelve-scene median's noise averaging, and that costs more than incoherent ratios do. It
does improve the rate error slightly (0.0308 to 0.0280), which is consistent with the
diagnosis rather than with the medoid being simply worse.

**The result worth keeping is the context-only row.** `local_zscore` re-centres a building
against its own quadrat or cell, and ships applied to `brightness` alone, one feature of
fifteen. Extended to every spectral feature, added alongside the absolute ones it changes
nothing (-0.0003, 14 of 30). But **replacing them entirely ties the shipped model**
(-0.0011, 14 of 30, p = 1.00) while nearly doubling the rate error, 0.0308 to 0.0569.

That separates two things this project had confounded:

- **Ranking is relative.** Which building in a cell carries PV is fully answerable from
  within-cell contrast; the absolute reflectance level adds nothing to it.
- **Calibration is absolute.** Z-scoring removes the level that says one quadrat is more
  PV-dense than another, and the aggregate collapses.

For scaling that is a useful thing to know in both directions. The ranking half -- the leads
product, and the precision-thresholded population the coverage ratio is fitted on -- should
transfer to a new country robustly, because it is immune to the cross-quadrat level shifts
that atmospheric and seasonal differences produce. The aggregate half depends on absolute
reflectance being comparable between places, which is exactly why removing atmospheric
correction in [the L1C test](#l1c-against-l2a-the-correction-is-not-the-problem-2026-09-19)
tripled the fold-to-fold spread without touching the median.

**A footnote that turned out to be a defect.** `brightness_zscore` re-centres a building's
brightness against its own quadrat or cell and has shipped as an available block,
`plus_local_contrast`, since 2026-08-09. It had never actually been measured: `local_zscore`
used `np.median` rather than `np.nanmedian`, and it runs inside `building_table` BEFORE the
fill/edge rows are dropped, so a single building whose footprint has no valid pixel turned
the entire quadrat's z-scores into NaN. That was 21% of rows and 5 of 30 quadrats entirely
NaN -- among them sialkot and sukkur, the two quadrats already recorded here as carrying
composite fill. One NaN poisons a logistic fit, so every fold trained on those quadrats
returned NaN and `pivot_table` silently dropped the block from the ablation output. Fixed
2026-09-19 (NaN-safe, and bit-identical on clean input), after which the block measures
**+0.0000 AUC, 13 of 30 folds** and is rejected on its merits rather than by accident.

Neither is adopted. The context block is kept as `roofclf.CONTEXT_FEATURES` /
`add_context_features`, the medoid as `preprocess.medoid_composite` and
`building_table(preprocess="medoid")`. One caveat on the medoid comparison: its table has 36
more rows than the baseline (123,903 against 123,867), because a scene stack covers the
quadrat geobox plus margin rather than the boundary bbox. At 0.03% that cannot carry the
result, but the two are not row-identical the way the earlier preprocessing comparisons were.

Artifacts: `results/roofclf_medoid_context.json`,
`results/roofclf_medoid_context_*_folds.csv`.

### The spectral SNR budget, and why the domain is exhausted (2026-09-19)

After a run of null preprocessing results it is worth asking what the spectral signal
actually IS, rather than trying another representation of it. Detection here is a mixture,
`y = f.r_PV + (1 - f).r_bg`, so the signal is `f.(r_PV - r_bg)` and the question is what
each term is worth. Measured on the 30-quadrat table, in B08, the highest-contrast band:

| Term | Value |
| --- | --- |
| Panel-minus-roof contrast at full cover | 0.0579 reflectance = **1.34 background sd** |
| Median fill fraction on a PV roof | 0.309 |
| Typical available signal | **0.41 sd** |
| Background sd between PV-free roofs | 0.0431 reflectance |
| Sentinel-2 radiometric noise at this level | ~0.001-0.002 reflectance |

The mixture model holds tightly: B08 falls linearly with fill fraction
(`B08 = 0.3142 - 0.0579 x f`), and the separation grows with it exactly as predicted --
d' of -0.25, -0.36, -0.54, -0.83 across fill-fraction bands averaging 0.08, 0.15, 0.29 and
0.65.

**The noise is not the sensor, and this rules out a whole class of ideas by arithmetic.**
Roof-to-roof heterogeneity is twenty to forty times Sentinel-2's radiometric noise. Every
intervention aimed at measurement quality -- more scenes, a better atmospheric correction,
denoising, spectral coherence -- is tuning a term worth about 2% of the variance. That is
the retrospective explanation for
[temporal statistics](#keeping-more-than-the-median-composite-2026-09-19),
[L1C](#l1c-against-l2a-the-correction-is-not-the-problem-2026-09-19),
[the medoid](#spectral-coherence-and-where-transferability-lives-2026-09-19) and
[sharpening](#the-20-m-bands-and-what-sharpening-them-costs-2026-09-19) all landing at zero.

**The linear spectral limit is already reached.** The Mahalanobis separation across all ten
bands is d' = 1.226, an implied AUC of **0.807**, while `spectral_only` measures **0.8333**
in leave-one-quadrat-out -- the shipped model is at or past the Gaussian linear bound,
exceeding it because the hand-made ratios are nonlinear in the raw bands. Whitening buys
1.95x over the best single band (0.629, B08) and the model already has it. With 79.3% of
band variance in the first principal component and a maximum inter-band correlation of
0.984, there are roughly two effective dimensions here. **No new index, matched filter or
whitening of these bands can add meaningful signal.** (The bound is in-sample and assumes
Gaussian classes, so read it as an order of magnitude, not a decimal.)

**That leaves shrinking the denominator, which fails for an interesting reason.** Since the
noise IS roof diversity, estimating a background per building from its nearest neighbours
should raise SNR directly, and roofing material is spatially clustered so the neighbours are
the right reference. It does cut the noise: the PV-free standard deviation falls **23 to 43%**
across bands. It cuts the signal faster. Median d' falls to **0.36x**, B11 even changes sign,
and the multivariate separation drops 1.226 to 0.904.

The cause is a property this project already documents: **PV adoption is spatially
clustered**, which is why `nn_median_m` exists. A PV roof's neighbours disproportionately
carry PV, so the local median is itself pulled toward the panel spectrum and subtracting it
cancels the contrast. Sweeping the neighbourhood scale shows there is no escape:

| Neighbours | Median radius | Mahalanobis d' | Against raw |
| --- | --- | --- | --- |
| 10 | 31 m | 0.717 | 0.58x |
| 50 | 78 m | 0.904 | 0.74x |
| 200 | 169 m | 0.980 | 0.80x |
| 800 | 369 m | 1.022 | 0.83x |
| none | -- | **1.226** | 1.00x |

Monotone, and asymptotic toward not conditioning at all. This also explains why the
quadrat-scale version
([context features](#spectral-coherence-and-where-transferability-lives-2026-09-19)) merely
TIED rather than helped or hurt: at 1-4 km² the group is large enough that adoption
clustering does not dominate its median, so it neither cancels signal nor removes much
heterogeneity.

**Conclusion: the spectral domain is exhausted for this sensor.** The remaining term in the
budget is fill fraction, which no amount of processing changes -- it is set by pixel size
against array size, and it is the same quantity that
[makes France fail and Pakistan work](results/france.md#earthpv-against-france-the-sub-400-m2-instrument-does-not-transfer).
Kept as `roofclf.add_neighbour_features` for anyone who wants to re-measure. Panels are
strongly polarising, which would be a nearly background-free channel, but no free satellite
measures it.

**PV-free neighbours only (2026-10-23), also rejected.** The obvious repair is to build the
background from neighbours that carry no PV, which removes the clustering that cancels the
contrast. Measured on the area-weighted table (raw d' 1.564 there, against 1.226 in the
pixel-centre measurement above), 50 nearest buildings in the same quadrat: neighbours chosen
by label keep **0.90x** of the raw separation against the all-neighbour **0.75x**, and choosing
them by out-of-fold score below the deployment threshold, which needs no labels, keeps
**0.94x**. It still does not help. The PV-free spread falls 42% in every variant, but even with
label-chosen neighbours the visible and SWIR bands keep only 0 to 0.4x of their separation
(B11 changes sign) while B06 to B8A keep all of it: most of the visible and SWIR contrast is
neighbourhood-level, which roof stock adopts PV, rather than panel physics. Dividing by the
neighbours' spread, a local z-score, is worse than plain differencing. Added to the shipped
features, every variant moves within-size AUC by -0.0001 to -0.0016 per fold, better in 10 to
13 of 29 folds, none significant; on their own they reach 0.769 to 0.774 against 0.819. The
score-chosen version carries a second-order leak (a neighbour's score comes from a model that
saw the held-out quadrat), which can only flatter it. Script:
`scripts/roofclf_pvfree_neighbour_contrast.py`; artifacts
`results/roofclf_pvfree_neighbour_contrast_sep_k50.csv` and `_folds_k50.csv`.

### Sun geometry: neither glint nor high sun raises the contrast (2026-09-19)

Two follow-ups to [the SNR budget](#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19),
asking whether some sun-sensor geometry gives a better look at the same panels.

**Glint is not a scene-level lever.** A glass-fronted panel is specular, so on a date when
the sun-panel-sensor geometry approaches the mirror condition it should stand out. Scored
over 239 scenes in 22 quadrats, using each scene's own sun and view angles and the **192
poses fitted from real Pakistani installations** rather than an assumed one, near-specular
scenes do show 34% more contrast: d' -0.549 in the nearest quartile of misalignment (1.17
deg) against -0.409 in the farthest (8.54 deg).

It is not glint. Misalignment and solar zenith are collinear at +0.475 by construction, and
partialling out the sun kills the geometry term while the sun survives:

| | Spearman | p |
| --- | --- | --- |
| d' vs misalignment | +0.101 | 0.12 |
| d' vs solar zenith | +0.204 | 0.0015 |
| **d' vs misalignment, controlling for solar zenith** | **+0.025** | **0.70** |
| d' vs solar zenith, controlling for misalignment | +0.161 | 0.013 |

The sign was wrong for glint from the start: PV gets DARKER relative to the roof near
specular, not brighter. And glint could not work as a scene selector even if it were real,
because **93.7% of scenes already have some pose within 10 deg of specular** (median 3.77
deg) -- the condition almost never discriminates between observations. What this does NOT
test is per-target glint on individual installations, which is how `glint.py` uses it and
where it does work: no scene has more than half the pose population glinting, so a narrow
lobe on a few panels is diluted by pixel-averaging across a quadrat.

**And a high-sun window does not help either, which refutes a prediction made here.** The
winter fit was `d' = -1.296 + 0.0145 x sun_zenith`, which extrapolated to roughly double the
contrast at summer sun angles and suggested the dry-season compose window might be costing
signal. Measured against pre-monsoon May-June scenes over 10 quadrats:

| | Pre-monsoon | Dry season |
| --- | --- | --- |
| Median d' | -0.601 | -0.672 |
| Roof brightness | **3,064 DN** | 2,532 DN |

**Gain 0.98x, better in 5 of 10 quadrats, Wilcoxon p = 0.77.** The first half of the
mechanism happened exactly as predicted -- roofs really are 21% brighter under high sun --
and the contrast did not move, because d' is a NORMALISED quantity: illumination scales the
panel, the roof and the between-roof spread together, so numerator and denominator grow in
step and the ratio is invariant to first order.

That means the within-window correlation the prediction rested on was not illumination
scaling at all; more likely seasonal surface change (moisture, dust, vegetation) tracking
date across a narrow 37-59 deg span. **The compose window is not costing contrast**, and
acting on the extrapolation would have meant recompositing a country onto a worse epoch for
no gain. Artifacts: `results/glint_geometry_snr.json`,
`results/summer_window_contrast.json` and their per-scene CSVs.

### The level half of brightness does not transfer (2026-09-20)

`absolute = cell_mean + deviation`, and `roofclf` sees only `absolute`, which confounds
"this building is bright" with "this cell is bright". Handing it the cell mean adds one
degree of freedom per feature. The motivation was the measured split reported above:
within-cell z-scores alone tie the shipped ranking while doubling the rate error, so ranking
is relative and calibration is absolute. The level half looked like the unexploited part.

Registered before measuring: a cell-constant feature adds the same number to every
building's logit inside a held-out quadrat, so it cannot reorder them, and any AUC movement
can only come from refitting the other coefficients. That half held -- the single cell-mean
moved AUC by **+0.0001**.

The substantive half failed, and significantly.

| Block | AUC | Within size band | Rate error | Rate ratio |
| --- | --- | --- | --- | --- |
| Baseline | 0.8574 | 0.8206 | **0.0308** | 1.061 |
| Plus brightness cell-mean | 0.8571 | 0.8220 | 0.0309 | 1.056 |
| Plus all 15 cell-means | 0.8494 | 0.8229 | 0.0430 | 1.012 |

Calibration gets **worse**: the per-quadrat adoption rate is closer to truth in only **7 of
29 quadrats, sign test p = 0.008, Wilcoxon p = 0.002**. The 15-feature version pushes median
rate error 0.0308 to 0.0430 while pulling the ratio to 1.012, which is the signature of
centring the level and widening its spread.

The reason is this register's own finding, turned against the idea. A cell-constant feature
is fitted across 29 quadrats and then extrapolated to an unseen one, so the model learns a
BETWEEN-quadrat relationship between brightness and adoption rate -- and between-quadrat
absolute rates are exactly what does not transfer. Adding the level as a feature does not
give the model the level; it gives it a spurious slope to extrapolate along. Kept as
`roofclf.CELL_LEVEL_FEATURES` / `add_cell_level_features` for re-measurement.

### Snow in Germany: the opportunity is real, the contrast is not concludable (2026-09-20)

[Snow-cover contrast](#snow-cover-contrast-and-the-one-commune-that-nearly-sold-it-2026-09-08)
was rejected for France on opportunity, 0.096 usable scenes per commune-winter outside the
Alps, and that entry named the one variant worth testing: Germany, which has more reliable
lowland snow. Tested over the 8 densest PV cells in the German OSM rooftop layer, three
winters, with SCL class 11 deliberately KEPT (the shipped mask drops classes outside 4-7 and
would discard every observation under test) and snow measured over building footprints
rather than over the cell.

**The opportunity objection is answered.** 6 snow scenes out of 58 low-cloud scenes, a
**10.3% rate**, against France's 0.096 per commune-winter. Observations of snow-covered roofs
genuinely exist in Germany.

**The contrast is not.** Six scenes, Mann-Whitney **p = 0.39**, and bimodal:

| Cell | Snow on roofs | Roof DN | PV DN | d' |
| --- | --- | --- | --- | --- |
| 137_515 | 61% | 2,035 | 1,146 | -2.40 |
| 137_515 | 100% | 3,806 | 2,405 | -1.72 |
| 149_513 | 20% | 1,647 | 829 | -1.03 |
| 149_513 | 100% | 4,333 | 1,702 | -1.74 |
| 60_508 | 100% | 3,250 | **8,143** | **+3.84** |
| 60_508 | 84% | 3,524 | **5,588** | **+2.48** |

Four scenes behave as the physics predicts. The two that inverted are explained by array
size rather than by snow: cell 60_508's mapped arrays have a **median area of 126 m²**,
about 1.3 pixels at 10 m, against 338 and 320 m² in the two well-behaved cells. At roughly
1.2 PV pixels per array the mask is mostly snow-covered ROOF, which reads brighter than a
roof average that includes shadowed and wet surfaces. The project's central limitation,
array size against pixel size, reappears here amplified rather than relieved.

The headline ratio of 15.9x is not usable either: it divides by a bare-season baseline of
**-0.087**, i.e. German OSM rooftop PV barely separates from PV-free roofs in bare winter at
all, which is consistent with a control contaminated by the 96.4% of German rooftop PV that
OSM does not map. A near-zero denominator makes any ratio large.

What would settle it is more cells and a restriction to arrays large enough to own a pixel.
Recorded as partial rather than shipped or rejected, because the half that killed the French
version is genuinely answered and the half that matters is untested at this sample size.
Artifacts: `results/germany_snow_contrast.json`, `results/germany_snow_contrast_scenes.csv`.

### The composite reducer is the biggest lever in this register (2026-09-20)

Chasing Google's Open Buildings 2.5D Temporal, which fuses up to 32 Sentinel-2 acquisitions
to reach an effective ~4 m, produced the largest single improvement measured anywhere in
this register -- and it turned out to have nothing to do with super-resolution.

`annual_composite` reduces the scene stack with a per-pixel **median**. Replacing it with a
**mean** gains **+0.0188 AUC within size band** at 10 m, with no change to resolution,
features or model.

**That figure is smaller than first reported here, and the correction matters.** The variants
below reduce the saved SCENE STACKS while the baseline reduces the COMPOSITE FILES, and the
two were fetched at different times through different read paths. A control run afterwards --
the MEDIAN of the same stack, which should score zero if the two paths are equivalent --
scores **+0.0098 within size band (21 of 30, p = 0.024)**. So roughly a third of the original
+0.0286 was the path, not the estimator:

| Effect | AUC | Within size band |
| --- | --- | --- |
| Path (stack median against composite median) | +0.0054 | +0.0098 |
| **Estimator (mean against median, same stack)** | **+0.0122** | **+0.0188** |
| Estimator, trimmed mean | -- | +0.0102 |

The estimator effect is real and significant either way, and the path effect is worth its own
look: the baseline reads through `composite_index.read_window`, which mosaics and can carry
the documented cell-edge fill frame, while a stack is a clean geobox read. If that is the
cause it is a free win independent of any reducer.

The decomposition that isolates it:

| Variant | AUC | Within size band | Folds better |
| --- | --- | --- | --- |
| Baseline, median at 10 m (composite file) | 0.8575 | 0.8206 | -- |
| Median at 10 m (same stack) -- PATH CONTROL | 0.8628 | +0.0098 | 21 of 30 |
| **Mean at 10 m** | 0.8756 | **+0.0286 (+0.0188 net of path)** | 25 of 30 |
| Mean at 5 m | 0.8789 | +0.0313 | 25 of 30 |
| Multi-frame fusion at 5 m | 0.8767 | +0.0273 | 26 of 30 |
| Area-weighted zonal means at 10 m | 0.8588 | +0.0113 | 25 of 30 |
| Area-weighted zonal means, as SHIPPED (nodata-masked, no rows dropped) | 0.8682 | **+0.0119** | 24 of 29 |
| Median at 5 m, nearest | 0.8623 | +0.0058 | 23 of 30 |
| SEN2SR single-image at 2.5 m | 0.8402 | **-0.0367** | 6 of 30 |

So **91% of the effect is the estimator**, about 9% is the finer grid, and the fusion itself
is NEGATIVE: applying measured sub-pixel shifts scores below not applying them.

Why the mean wins is not mysterious once separated out. SCL masking already removes cloud,
shadow and snow, so the median's robustness is largely redundant, and at twelve samples a
median carries about 1.57x the variance of a mean. Less feature noise, better separation,
and it helps most for the sub-pixel footprints whose single pixel is noisiest.

**The route there was three wrong mechanisms in a row, which is worth recording.** The gain
first looked like multi-frame fusion; a zero-shift control beat the fused version, so it
looked like resolution; plain upsampling recovered only a fifth of it, so it looked like
footprint sampling; exact area-weighted zonal means recovered a third. Only the mean
explains it, and `tmean_up2` reproduces the shift-and-add control to four decimals, which is
the consistency check that the accumulator had been computing a mean all along.

**Why fusion cannot work here, measured rather than assumed.** Multi-frame super-resolution
needs frames that sample the ground at different sub-pixel phases. Measured across 298 frame
pairs in 30 quadrats, the median inter-acquisition shift is **0.122 px (1.22 m)**, with phase
offsets at roughly a quarter of the uniform-spread ideal and only about 3 frames in 12
usefully displaced. Re-measured from **native granules** with no reprojection or resampling,
to rule out our own loading path as the cause: **0.132 px (1.32 m)**, essentially identical.
The diversity really is that small. A synthetic check puts the consequence precisely: with
ideal phases shift-and-add recovers +0.166 of correlation against an upsample, and at the
diversity Sentinel-2 actually provides, +0.015 -- about 9% of the achievable gain.

**And single-image super-resolution actively hurts.** SEN2SRLite (CC0-1.0, runs in 0.31 GB on
a GTX 1060) produces a faithful 2.5 m raster -- downsampled it correlates 0.9976 with the
original and it genuinely adds high-frequency energy, 0.688 to 0.918. It still costs
**-0.0367 AUC within size band, 6 of 30 folds**, because it cannot add information: it
redistributes 10 m content using learned priors, and texture uncorrelated with PV dilutes
real contrast. That is the 2026-07 rejection reproduced with a much better model, and it
answers the hallucination objection empirically rather than by assertion.

**Building height, from GlobalBuildingAtlas, is redundant.** Height alone separates PV from
PV-free roofs at d' = +0.651 (median 6.74 m against 4.03 m), comparable to the best single
spectral band. On top of the model it is worth **+0.0006 within size band, 6 of 9 folds,
p = 0.51**, and height-plus-size alone scores 0.173 BELOW baseline: tall buildings are large
buildings, and `log_roof_area` already carries it. Measured on the 5 quadrats where GBA
covers more than half our footprints, a biased subsample. GBA heights are CC BY-NC 4.0 in any
case, which would have blocked deployment.

**The mean's weakness is real, and a trimmed mean is the answer.** The median is there to
reject residual cloud that SCL missed, and a mean cannot: with one unmasked cloud pixel among
twelve frames, a clean value near 100 reads 100.7 under the median, 100.2 under a 20%-trimmed
mean, and **924.4 under a plain mean**. Measured on the quadrats, the trimmed mean keeps most
of the gain:

| Reducer | Within size band | Folds better | One unmasked cloud |
| --- | --- | --- | --- |
| Median (current) | -- | -- | 100.7 |
| **Trimmed mean (drop top and bottom decile)** | **+0.0200 (+0.0102 net of path)** | 25 of 30 | **100.2** |
| Mean | +0.0286 (+0.0188 net of path) | 25 of 30 | 924.4 |

So **the trimmed mean is the one to ship**: 70% of the gain, and robustness indistinguishable
from the median on the failure mode the median exists for.

Wired as `imagery.REDUCERS` / `annual_composite(reducer=...)` / `compose --reducer`, with the
default left at "median" and `run_compose` inheriting an AOI's existing reducer, exactly as
for the resampling change and for the same reason: a model calibrated on medians and scored
on means is a domain shift. Every existing AOI -- Pakistan, Germany, France, Nigeria, Zambia
-- inherits "median". Shipping it nationally means recompositing, which
costs roughly 2 TB of transfer per country, so it
is free for the next country and expensive for the existing ones.

**Two more noise reductions, and they stack.** Weighting each 10 m pixel by the fraction of
the footprint covering it -- instead of `rasterize`'s all-or-nothing pixel-centre test, which
gives about half of VIDA footprints zero pixels and a representative-point fallback -- is
worth **+0.0113 within size band** on its own (25 of 30 folds, p = 0.0001). Combined with the
trimmed mean it reaches **+0.0305 raw, +0.0207 net of the path effect**, against +0.0215
predicted by adding them: additive to within noise, because they attack different noise
sources.

**SHIPPED 2026-09-20, and it is the only part of this section that costs nothing.** The
reducer and the frame count both need a country recomposited; area weighting is a read-side
change to `roofclf` and needs no new imagery at all, so it was promoted to the default
(`roofclf.AREA_WEIGHTED_ZONAL`, `roofclf.area_weighted_zonal_mean`, applied in BOTH
`building_table` and `score_buildings_national`, with `--no-area-weighted` on
`roof-classifier` and `roofclf-score-national` reproducing every earlier figure).

**The shipped version is not the experimental code, so it was re-measured rather than
carried over.** Two things had to change first, neither of which shows up in an interior
quadrat:

  * *The nodata mask.* The experiment tested `np.isfinite`, right for a NaN-masked scene
    stack and wrong for a composite window, where fill is 0.0. Unmasked, a cell-edge fill
    pixel enters the weighted mean as genuine near-zero reflectance, and PV is dark: that is
    the mechanism that once made **45.6% of every nationally flagged building** a cell-edge
    artefact. The shipped version applies the same all-bands-equal-fill test `zonal_mean_max`
    uses.
  * *The fallback.* A footprint with no subpixel of its own got zero weight and came back
    NaN, silently dropping **0.16 to 0.47% of buildings per quadrat** -- the smallest ones,
    i.e. the population this module exists for. The shipped version keeps `zonal_mean_max`'s
    value for those rows, so the scored population is unchanged by construction. 0.06 to 0.8%
    of buildings take that path.

Re-measured on all 30 quadrats, both arms on identical rows, no rows lost:

| Metric | Pixel-centre | Area-weighted | Delta | Folds better | Sign p | Wilcoxon p |
| --- | --- | --- | --- | --- | --- | --- |
| AUC | 0.8591 | 0.8682 | +0.0085 | 28 of 29 | 0.0000 | 0.0000 |
| **Within size band** | 0.8093 | 0.8193 | **+0.0119** | 24 of 29 | 0.0005 | 0.0017 |

and in the units the atlas consumes, at an identical precision of 0.500:

| Arm | Flagged | Precision | Recall |
| --- | --- | --- | --- |
| Pixel-centre | 21,904 | 0.500 | 0.6386 |
| **Area-weighted** | 22,580 | 0.500 | **0.6583** |

**+2.0 points of recall, 3.1% relative, for no imagery.** The shipped version slightly
exceeds the experimental +0.0113, which is the expected direction: it stopped dropping the
smallest buildings. Acceptance test: `scripts/verify_area_weighted_default.py`, result
`results/roofclf_area_weighted_default.json`.

**Pakistan was refitted on 2026-09-20** (30 quadrats, parcel label; pre-refit state kept at
`data/roofclf_PRE_areaweighted_20260920/`). Against the 2026-08-20 production fit:

| | 2026-08-20 | 2026-09-20 |
| --- | --- | --- |
| Buildings | 123,867 | 123,898 |
| Median fold AUC | 0.8574 | 0.8682 |
| Median within size band | 0.8206 | 0.8193 |
| Deployment threshold | 0.2515 | 0.2446 |
| Flagged at precision 0.500 | 21,580 | 22,580 |
| **Recall at precision 0.500** | 0.6292 | **0.6583** |

**The within-size line reads down and that is a difference of medians, not a regression.**
Two things changed between those summaries -- area weighting and the grid-snap read fix --
and neither summary is a paired comparison: different tables, different fold sets, and a
median of fold medians is not additive. Measured properly on identical rows the two are
**+0.0119** (24 of 29 folds, p = 0.0017) and **+0.0032** (18 of 29, p = 0.27) respectively;
the read-path figure reproduces the +0.0032 already recorded for it, and its own unpaired
medians move 0.8206 to 0.8092 while its paired delta is positive. This register has retracted
a claim to this exact trap once already ("the 0.8593 that made it look best was a difference
of medians"), so the paired test is the one to read. The deployment row is computed on pooled
out-of-fold scores rather than a median, which is why it moves unambiguously.

**The calibration and the national scoring must share one zonal convention**, and
`check_scoring_matches_calibration` now refuses a mismatched pair by name rather than by
coefficient hash. National rescoring was run the same day off this fit; the capacity chain
and the atlas are a separate, owner-gated step because they move the published headline.

**Frame count helps, weakly, and only through variance.** Full-year stacks (~36 scenes
against the dry-season 12) separate frame count from season by drawing a fixed random 12 out
of the SAME year stack, so the two differ only in N:

| Trimmed mean over | Within size band | Net of path |
| --- | --- | --- |
| 12 dry-season frames | +0.0200 | +0.0102 |
| 12 frames of the year | +0.0247 | +0.0149 |
| ~36 frames of the year | **+0.0295** | **+0.0197** |

**The frame-count effect is +0.0048 within size band for tripling N**, and the path effect
cancels in that comparison so it is clean. That is what 1/sqrt(N) predicts: three times the
frames cuts the standard error by 42%. So Google's 32-acquisition budget does transfer to
this problem -- through estimator variance, not through the shifted viewpoints its design
exploits -- and it costs three times the download, which against
roughly 2 TB of recompositing per country is a poor trade at national
scale. Note also that the full-year season mix is not itself harmful: at matched N = 12 the
year frames slightly outscore the dry-season ones, so a wider window is a viable way to reach
more frames if the bandwidth is ever there.

**The whole package, net of the path effect: about +0.026 AUC within size band**, from a
trimmed mean, area-weighted zonal means and more frames -- all of it noise reduction, none of
it new information, and none of it super-resolution.

**What it is worth to the PRODUCT, which is not AUC.** `run_roof_classifier` picks a
threshold targeting precision 0.5 on pooled out-of-fold scores, and `sub400_capacity` fits
its coverage ratio and area recall on the population that threshold flags. A ranking gain
that leaves that population unchanged changes no capacity figure, so the deployment step was
re-run for each variant:

| Variant | AUC | Flagged | Precision | Recall |
| --- | --- | --- | --- | --- |
| Baseline | 0.8601 | 21,592 | 0.500 | **0.6295** |
| Trimmed mean | 0.8771 | 23,148 | 0.500 | 0.6751 |
| Plus area-weighted zonal | 0.8810 | 23,382 | 0.500 | 0.6822 |
| Plus the full year's frames | 0.8851 | 23,794 | 0.500 | **0.6937** |

**At identical precision, recall goes 0.6295 to 0.6937: +6.4 points, or 10.2% more of the
true PV roofs captured.** That is the number to quote, because it is the population the
capacity chain is fitted on. The two free changes alone -- trimmed mean and area-weighted
zonal -- deliver +5.3 points of it; the remaining +1.1 costs three times the download.

### One threshold is already the right one (2026-09-20)

If the deployment threshold is what the capacity chain consumes, the obvious next lever is
the threshold itself. `run_roof_classifier` picks ONE cut targeting precision 0.5 on pooled
out-of-fold scores. One cut is recall-optimal only if the score means the same thing
everywhere, and this register has repeatedly found it does not: `rate_ratio` spans 0.2 to 5x
across quadrats, gradient boosting beat the linear model on per-quadrat rate error while
ranking worse, and no global monotone map recovered that gain. So: cut per stratum instead,
on the two stratifiers the capacity chain already uses, building-size band and quadrat
density. Every threshold is fitted on the OTHER quadrats' out-of-fold scores, the same
nesting the model itself uses, and every comparison is against a global cut RE-TUNED to
whatever precision the stratified rule actually reached, so a recall gain bought by dropping
precision cannot read as a gain.

**Equal precision in every stratum is much worse than one cut, and not marginally:**

| Rule | Flagged | Precision | Recall | Net of matched global | Quadrats better | Sign p |
| --- | --- | --- | --- | --- | --- | --- |
| One global cut | 21,199 | 0.5012 | **0.6195** | -- | -- | -- |
| Per size band | 20,180 | 0.5004 | 0.5889 | -0.0298 | 7 of 26 | 0.029 |
| Per density stratum | 19,074 | 0.5023 | 0.5586 | -0.0579 | 3 of 23 | 0.0005 |
| Per size and density | 19,029 | 0.4885 | 0.5420 | -0.0919 | 4 of 25 | 0.0009 |

The mechanism is that **equal AVERAGE precision is the wrong objective**. At a fixed pooled
precision the recall-maximising allocation equalises the MARGINAL precision -- the precision
of the last building admitted -- not the stratum's average. A stratum whose base rate is
3.6% (the 0-50 m² band, 50,502 of 123,867 buildings) has to be cut very deep before its
average precision reaches 0.5, and its recall collapses from 0.191 to 0.059 while the bands
that were already easy barely move.

**So the theoretically-correct version was run too**: recalibrate the score to a per-stratum
posterior with isotonic regression fitted on the training folds, then apply ONE global cut to
the recalibrated score, which equalises the margin by construction. This is not the
[monotone recalibration already rejected here](#aiming-at-the-aggregate-weighting-and-recalibration-2026-09-19) --
that map was global, and a per-stratum map is not monotone in the original score.

It wins pooled and dies paired. Per size band: recall 0.6392 at precision 0.4947 against the
matched global cut's 0.6260, so **+1.3 points pooled -- and a median per-quadrat difference
of exactly +0.0000, 12 of 24 quadrats better, sign test p = 1.00**. The pooled gain is a few
large quadrats, which is the same failure the register logged when 55 PV-dense German
municipalities read as an 18.2% error against a representative 33.4%. Recalibrating per
density stratum loses outright (-0.0482 net), and per size and density together loses
(-0.0110 net).

### The roof is its own control (2026-09-20)

Everything above works on ONE epoch, and the SNR budget says that is the binding
constraint: the noise limiting `roofclf` is roof-to-roof heterogeneity, 0.0431 reflectance,
20 to 40x the sensor noise, and the linear spectral limit on a single-epoch zonal mean is
essentially reached. Every intervention aimed at the MEASUREMENT -- L1C, 20 m sharpening,
spatial unmixing, single-image and multi-frame super-resolution, medoid compositing -- has
failed, which is exactly what that budget predicts.

There is one term that cancels roof-to-roof heterogeneity outright, and it is not spectral:
**the same roof, earlier.** Pakistan's rooftop boom is post-2022, so a 2019/20 dry-season
composite is a pre-installation look at most of today's arrays, and `current - 2019`
differences away everything about the roof that did not change. Thirty-one quadrat-clipped
scene stacks were pulled for 2019-11-01 to 2020-03-15 (6 to 12 frames, median 7, 223 MB
total) and reduced the SAME way as the current stack, so a difference cannot pick up a
reducer or a read-path change.

| Block | AUC | Within size band | vs baseline | Folds better | Sign p | Wilcoxon p |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline | 0.8574 | 0.8205 | -- | -- | -- | -- |
| **Plus the 2019 difference** | **0.8632** | **0.8388** | **+0.0234** | **25 of 29** | **0.0001** | **0.0002** |
| Plus a split-half difference (placebo) | 0.8551 | 0.8182 | -0.0009 | 14 of 29 | 1.00 | 0.70 |
| Plus the 2019 LEVELS, undifferenced | 0.8590 | 0.8294 | +0.0036 | 20 of 29 | 0.061 | 0.26 |
| Plus both differences | 0.8695 | 0.8392 | +0.0222 | 25 of 29 | 0.0001 | 0.008 |

**Measured against the shipped read path this is the largest single feature block in this
register**, and roughly what the entire noise-reduction package above is worth, from one
extra historical composite rather than a national recomposite. **That framing does not
survive its own control -- see "The two levers are not additive" below, which is the part to
read before acting on any of this.**

Three controls, all registered before measuring, and all of them matter:

**The placebo is exactly null.** Differencing the first half of the CURRENT dry-season stack
against its second half gives the same band count, the same features, the same imagery and
the same reduction, with no installation possible in between: -0.0009, 14 of 29 folds,
p = 1.00. So what helps is the EPOCH, not having two estimates of the same roof.

**The difference beats the levels, which is the L2 prior doing work.** For an unpenalised
linear model, adding the 2019 levels spans the same space as adding the differences and must
tie. Under L2 it does not, and it does not: +0.0036 (p = 0.061) against +0.0234. The
difference parameterisation is the one that encodes "the roof cancels", and encoding it is
worth 6x more than handing the model the same information unshaped.

**It is PV, not construction.** A building that did not exist in 2019, or was re-roofed, also
differences large, and VIDA footprints come from recent imagery so new construction is in
the layer. Two reads separate them (`scripts/epoch_difference_mechanism.py`):

  * *Sign.* PV modules are dark; bare ground turning into a roof is not. PV-bearing roofs
    darkened relative to PV-free ones by a median 0.0082 reflectance, **darker in 28 of 29
    quadrats, sign test p < 0.0001**.
  * *Magnitude.* Construction would live in the extreme tail of the difference. It does not:
    the top decile of `|d19_brightness|` has a LOWER PV base rate than the rest (0.130
    against 0.140), and the gain is in the bulk (+0.0165, 25 of 28 folds) not the tail
    (+0.0041, 12 of 19).

The fitted coefficients are also self-consistent with the static model rather than with a
generic change detector: the largest is `d19_b11` at +1.88, and `b11_mean` is the static
model's largest coefficient at +4.33. The block is reading "this roof moved TOWARDS the PV
spectral signature", not "this roof moved".

**In the units the atlas consumes** (the same deployment step
[the reducer package was priced in](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20)):
at an identical precision of 0.500 the flagged population goes 21,596 to 22,704 buildings
and **recall goes 0.6298 to 0.6621, +3.2 points, 5.1% relative**. For comparison the whole
noise-reduction package is +6.4 points, and that one needs the existing national imagery
recomposited; this one needs a second epoch alongside it.

**THE TWO LEVERS ARE NOT ADDITIVE, AND THIS IS THE RESULT THAT MATTERS FOR DEPLOYMENT.**
Everything above measures the epoch difference against the SHIPPED read path: a median
composite read through `CompositeIndex.read_window`. The noise-reduction package (trimmed
mean, area-weighted zonal means) replaces exactly that, and it was fitted on the same 30
quadrats. Re-running the whole ablation on the `trimzonal` table instead:

| Base | Baseline within size band | Plus the 2019 difference | Gain | Folds better | Sign p |
| --- | --- | --- | --- | --- | --- |
| Shipped read path | 0.8205 | 0.8388 | **+0.0234** | 25 of 29 | 0.0001 |
| Noise-reduced (`trimzonal`) | 0.8370 | 0.8510 | **+0.0047** | 20 of 28 | 0.036 |

**Four fifths of the epoch gain is already captured by the noise reduction.** It is still
there, still significant, and the placebo is still null on the better base (-0.0017, 10 of
29) -- but a project that ships the reducer package should expect well under +0.01, not
+0.023, from adding a second epoch on top.

**The old epoch was frame-starved, and it is still not saturated.** Those 2019/20 stacks
carry a median 7 frames against the current 12. Re-pulling them over a wider window
(2019-10-01 to 2020-04-30, `--max-items 24 --max-cloud 50`) more than doubles that to a
median 16, and on the same noise-reduced base the gain rises and sharpens:

| Old epoch | Median frames | Gain on `trimzonal` | Folds better | Sign p | Wilcoxon p |
| --- | --- | --- | --- | --- | --- |
| 2019-11-01 to 2020-03-15 | 7 | +0.0047 | 20 of 28 | 0.036 | 0.011 |
| **2019-10-01 to 2020-04-30, cap 24** | **16** | **+0.0067** | **23 of 29** | **0.002** | **0.0002** |

So the honest deployment number is +0.0067 and rising, not +0.0047, and the curve has not
flattened -- a deeper old epoch is the cheapest remaining way to improve this, since it
costs archive queries rather than a second national composite. One thing does change with
the cleaner old epoch: the undifferenced 2019 LEVELS catch up almost completely (+0.0063,
24 of 29, p = 0.0005 against the difference's +0.0067). The "the roof cancels" prior was
worth 6x on a noisy old epoch and is worth almost nothing on a clean one, which is what a
regularisation prior should do: it buys most where the data is weakest.

The two are not measuring the same thing mechanically -- one cleans the current estimate,
the other cancels the roof -- but they raise the same underlying quantity, the contrast
between panel and roof relative to the noise on it, and once the measurement is clean there
is less left for the difference to recover. The honest summary is that **this register has
found one large improvement available to `roofclf`, reachable two different ways, and not
two large improvements.** Best measured combination: `trimzonal` plus the 2019 difference at
0.8510 within size band against the shipped 0.8205, and the noise reduction is the cheaper
half of it.

**Caveats.** The 2019 arm carries a median 7 frames against the current 12, so the
difference is noisier on the old side than it needs to be; more 2019/20 scenes would likely
widen the gain rather than close it. Rule-1 labels are epoch-relative, so an array installed
between the mapping imagery and the composite is an unlabelled positive in both arms.
Deploying this nationally means a second epoch of imagery for the whole country, which is the
same cost, roughly 2 TB per country, as the reducer change -- but unlike
the reducer it buys new information rather than less noise, and it does not require
recompositing what already exists. Scripts: `scripts/compose_scene_stacks.py --window
2019-11-01:2020-03-15 --subdir stacks_2019`, `scripts/run_epoch_difference_ablation.py`.
Results: `results/roofclf_epoch_difference.json`, `results/roofclf_epoch_mechanism.json`.

### Most footprints are one pixel (2026-09-20)

Every spectral feature `roofclf` ships is a zonal MEAN over the footprint. That is the right
statistic only if a flagged roof is uniformly covered, and it is not: an array usually
occupies part of a roof, so the mean is a mixture of panel and roof in an unknown
proportion. This register's SNR budget says the roof half is the dominant noise term
(roof-to-roof heterogeneity 0.0431 reflectance, 20 to 40x the sensor noise) and that the
linear spectral limit ON THE MEAN is essentially reached. Order statistics are not on that
axis. They are a different summary of the same pixels, not a cleaner estimate of the same
summary, so the limit does not bind them.

Two hypotheses, registered before measuring. EXTREMES: the darkest pixel in a footprint
approximates the panel endmember, so min and max are less diluted than the mean, and this
should help MORE on larger footprints. SPREAD: a partially covered roof is internally
heterogeneous and a uniform one is not, so the within-footprint standard deviation is
direct evidence of partial cover. Both on four quantities (brightness, SPPI, SWIR/visible,
blue/red), both free -- the window is already read and rasterized. Plus the control that
matters here: the pixel COUNT alone, because a size proxy hiding inside either block would
look like a win.

| Block | AUC | Within size band | vs baseline | Folds better | Sign p |
| --- | --- | --- | --- | --- | --- |
| Baseline | 0.8591 | 0.8093 | -- | -- | -- |
| Plus pixel count (control) | 0.8579 | 0.8092 | -0.0015 | 11 of 29 | 0.265 |
| Plus extremes | 0.8579 | 0.8074 | -0.0006 | 12 of 29 | 0.458 |
| Plus spread | 0.8583 | 0.8080 | -0.0012 | 11 of 28 | 0.345 |
| Plus both | 0.8575 | 0.8086 | -0.0007 | 11 of 29 | 0.265 |

**Nothing, and the diagnostic is the point: 72.4% of the 123,898 buildings in these 30
quadrats resolve to a SINGLE 10 m pixel.** Median pixel count is 1 overall and 2 for a
PV-bearing roof. For three quarters of the population min, max and mean are the same number
and the standard deviation is exactly zero, so there is no within-footprint distribution to
read. Splitting each fold's AUC by pixel count confirms it is not merely diluted: on the
multi-pixel subset the blocks are still flat (spread +0.0009, 15 of 28 folds, p = 0.85;
extremes -0.0003, 13 of 28, p = 0.85), so the registered size-conditional prediction fails
on its own terms too.

**This bounds a whole class of ideas, not just this one.** Anything that needs structure
INSIDE a footprint -- texture, panel-versus-roof segmentation, within-roof unmixing, a
shape prior on the array -- has no substrate in three quarters of the population that
`roofclf` exists to cover. It also explains retrospectively why area-weighted zonal means
work (+0.0113 within size band, above): that change attacks the same fact from the other
side, fixing how a footprint reads a pixel it only PARTLY covers rather than trying to read
structure within one. Script: `scripts/run_dispersion_ablation.py`, feature block
`roofclf.DISPERSION_FEATURES`, result `results/roofclf_dispersion_baseline.json`.

**Verdict: one global threshold is already the right allocation, and the score is closer to
calibrated across size bands than the per-quadrat rate spread suggests.** Those are different
claims about the same model -- rate error is a level error within a quadrat, and what a
threshold needs is that the score ORDER the same way across strata, which it does. Nothing
changes in the pipeline. Script: `scripts/run_stratified_threshold.py`, result
`results/roofclf_stratified_threshold.json`.

Artifacts: `results/roofclf_preprocess_ablation.json`, `results/subpixel_shifts.json`,
`results/native_shifts.json`, `results/roofclf_gba_height.json`.

### Keeping more than the median composite (2026-09-19)

The composite reduces about twelve cloud-masked scenes to their per-pixel median
(`imagery.annual_composite`). A median is the maximum-robustness central estimator, so it
deletes the tail by construction, and the tail is where a specular surface at a fixed tilt
should put its information. The scenes are already downloaded and then discarded, so the
cheapest possible version of "use the time dimension" is to keep more of that distribution
and ask whether it helps.

`compose --stats` now writes a `temporal_stats` sidecar beside each composite: per-pixel
p10, p50, p90 and standard deviation for all ten bands, plus a valid-observation count.
No extra network traffic, which matters because this stage is bandwidth-bound. What
`roofclf` gets per building is the bright tail (p90 - p50, a free proxy for the glint that
otherwise needs bespoke per-target scene pulls), the dark tail (p50 - p10, which should
separate dark-and-static PV from dark-and-moving shadow), the temporal spread, and
`n_obs`, without which spread is unreadable: std = 0 means "stable" at twelve looks and
"one look" at one.

The measurement is a leave-one-quadrat-out ablation on the 30 production quadrats, and it
reproduces the shipped fit exactly (123,867 buildings, 17,150 positives, median fold AUC
0.8574, 0.8206 within size band, min fold 0.4964), so the block is the only variable.

| Feature block | AUC | Within size band |
| --- | --- | --- |
| Size only | 0.7441 | 0.5773 |
| Size + temporal | 0.7311 | 0.5868 |
| Median composite only | 0.8333 | -- |
| Size + spectral (shipped) | 0.8574 | 0.8206 |
| Shipped + temporal (compact, 6 columns) | 0.8579 | 0.8232 |
| Shipped + temporal (full, 31 columns) | 0.8576 | 0.8262 |

**It buys nothing.** Paired per fold, the compact block moves AUC by a median **+0.0003**
(IQR -0.0013 to +0.0016), improving **16 of 30 folds**, sign test p=0.57; within size band
+0.0006 (IQR -0.0018 to +0.0033), 16 of 30, p=0.71. Widening from 6 columns to 31 does not
rescue it, so the compact grouping is not what threw the signal away.

The `temporal_only` row is the part worth keeping, because it distinguishes "adds nothing
new" from "says nothing". On its own the block sits at 0.5868 within size band against a
0.5773 size-only baseline: a trace above chance, not nothing, but nothing that survives
having the median composite in the model. So the distribution's higher moments are close
to redundant with its centre for this task, at this resolution.

Two things make this a fair test rather than a plumbing failure. The sidecar stores its own
p50, and that band is **bit-identical to `composite_0.tif`'s median on 100% of valid
pixels**, so the temporal features and the existing reflectance features describe the same
twelve scenes and no epoch confound is possible. And the block has real dynamic range
rather than being flat: for B02 the median pixel spans 129 DN between p50 and p90, 183 DN
between p10 and p50, with a standard deviation of 148 DN, against roof reflectances of
order 1,000 to 3,000 DN.

The likeliest reason it fails is the same sensor ceiling that
[the 400 m² floor](#the-detection-floor-measured-against-sub-metre-truth-2026-09-12) and
[the French transfer result](results/france.md#earthpv-against-france-the-sub-400-m2-instrument-does-not-transfer)
keep returning: a sub-400 m² array is a minority of a 100 m² pixel, so whatever anisotropy
it has is diluted by a roof that does not share it, in every statistic equally. Twelve
dry-season scenes also give little specular opportunity, which is the ceiling
[glint](methods/glint.md) already documents from the other direction.

Kept behind flags (`compose --stats`, `roof-classifier --temporal-features`), off by
default, because re-measuring costs one afternoon and no retraining. Cost if it were ever
wanted nationally: about 4x the per-cell composite disk, roughly 215 GB for Pakistan's
4,473 cells. Raw numbers: `results/roofclf_temporal_ablation.csv` (median per block) and
`results/roofclf_temporal_ablation_folds.csv` (per fold, which is what the paired test
above is computed from).

### Temporal features for roofclf

Two candidate features were tested against the quadrats and neither was kept. **Epoch jump**,
the change in the same classifier's score between two imagery epochs, measured at 0.8736 to
0.8736 AUC in its probability form (exactly zero effect) and 0.8736 to 0.8608 in its cheaper
reflectance-delta form, with one quadrat failing outright. **Step change**, per-building
aggregation of the pixel-level time-series signal below, did not survive a within-size-band
control. An [older design note](issues/epoch-jump-recall-signal.md) proposed using the epoch
comparison as a recall *rescue* rather than a feature; that specific plumbing was never built,
and the measurement above is the reason it was not pursued.

### Retraining on known failures

Two retrains aimed at documented failure modes, both negative in an instructive way.

The **fraction-head quadrat-supervised retrain** beat the production checkpoint in 13 of 13
quadrats in-sample and collapsed the scale dispersion from 11.95x to 2.48x, which looks
decisive until the held-out quadrat comes back at 0.461 against an in-sample band of 1.878 to
3.684. A paired spatial block bootstrap puts the held-out AUC gain at -0.009 to +0.061,
one-sided p 0.062. One quadrat and 797 labelled pixels is the binding constraint, so more
holdout folds, not more analysis, is what would settle it.

The **roofclf hard-negative retrain** took the one concretely locatable confirmed false
positive on record (six very bright roofs that both detectors flag) and folded them in as
negatives. Six rows against 104,423 moved their own scores by 0.0001 to 0.003 and changed
nothing else. Oversampling them 20x, 100x and 500x does eventually suppress them, but
`median_fold_auc` falls 0.8824 to 0.8811 to 0.8726 to 0.839 on the way, so the model is
learning to distrust one tiny neighbourhood of feature space at the expense of everything
else. No factor tested threads that needle. The fix this actually recommends is mining more
examples of the same bright-roof pattern nationally, for which no roofclf-side mining tool
exists yet.

### SPPI alone as Germany's sub-400 estimator (2026-09-18)

Germany's published sub-400 m<sup>2</sup> half uses no classifier: it prices roof area in the
200-400 m<sup>2</sup> band at a register-fitted constant, because that beat both `roofclf` and
total roof area. The obvious thing left untried was the other detector. SPPI is a
zero-training spectral index, it is already computed for every scored German building, and it
is the corroborating half of Pakistan's AND-gate, so if any classifier were going to help
here it is the one that needs no labels.

It does not. All four estimators below were run through
`scripts/validate_sub400_against_mastr.py` on identical data, the same cells, the same
municipalities and the same five-fold cross-validation, with only the weighting changed:

| estimator | Gemeinden | median municipal error | best stratified | Spearman | slope |
| --- | --- | --- | --- | --- | --- |
| roof area only (published) | 10,589 | **31.2%** | 28.8% | 0.942 | 0.888 |
| SPPI percentile rank | 10,588 | 33.7% | 31.0% | 0.922 | 0.845 |
| roofclf probability | 10,005 | 36.8% | 34.9% | 0.855 | 0.333 |
| SPPI top decile | 10,209 | 49.9% | 48.8% | 0.824 | 0.498 |

Two formulations, because SPPI is a spectral index in roughly [-2.6, 0.07] rather than a
probability and cannot be multiplied in raw. **Percentile rank** weights each roof by where
its SPPI falls in the national distribution, the analogue of probability weighting.
**Top decile** credits only roofs above the 90th percentile, the analogue of thresholding and
the way SPPI is used in Pakistan's AND-gate.

The interesting half of the result is that SPPI ranks German roofs *better than the trained
classifier does*, on both error and slope, while needing no labels at all. The decisive half
is that neither beats doing nothing. This is the same finding as the roof-area baseline, from
a third direction: where PV is near-ubiquitous, capacity is close to proportional to roof area
by construction, so an instrument that concentrates credit on a subset discards more real
capacity than it correctly withholds. Thresholding is worst precisely because it discards the
most.

The baselines here read 31.2% and 36.8% where
[Germany's page](results/germany.md) records 35.4% and 48.4%, because the grid was rebuilt
without the building-density filter (4,871 cells against 4,657) after those were measured.
The ordering is unchanged and the within-run comparison is what the table is for.

**A NaN trap worth recording**, because it produced a confident wrong answer rather than an
error. The first top-decile run reported zero municipalities and zero capacity. 2,660 of
6.2M buildings, 0.043%, carry no SPPI value; `np.quantile` returns NaN if any input is NaN,
and `x >= NaN` is False for every row, so the threshold flagged nothing and the harness
dutifully reported zeros all the way through. The harness is now NaN-safe and logs how many
buildings lack a value.

### A sub-400 m² level without quadrats, from OSM and a past epoch (2026-10-20)

Countries whose only high-resolution imagery is years old cannot get Rule-1 quadrats (Box 17's
gate), and without quadrats they get no sub-400 m² figure at all. The classifier can be
borrowed, since ranking transfers; the level cannot, because the coverage ratio carries
precision and precision carries the local adoption rate. The idea tested here measured the
level from two things such a country still has (`earthpv.transfer_calibration`), as an
adjusted count, `pi = (f - FPR) / (TPR - FPR)` per roof-size bin:

- **TPR from OSM positives**: the detection rate among buildings carrying mapped PV anywhere
  in the country. Incomplete mapping is fine, since only the rate among them is used.
- **FPR from the past**: the flag rate of the same roofs in a pre-boom Sentinel-2 epoch,
  scored by the same model, as an upper bound on today's false-positive rate.

It was validated against Pakistan's 30 quadrats with no quadrat information at all: the
classifier from the other quadrats, positives from 8,584 OSM-mapped sub-400 m² roofs outside
every quadrat, negatives from composite_1 (2021-10 to 2022-01). Population: sub-400 m² roofs.

| Level from | Median error per quadrat | Pooled ratio | Spearman |
| --- | --- | --- | --- |
| Quadrats, leave-one-out (flagged roof area x ratio) | 35% | 1.00 | 0.92 |
| Quadrats, leave-one-out (roof area x constant, the null) | 54% | 0.98 | 0.90 |
| OSM TPR + 2021 FPR | 318% | **-3.71** | -0.48 |
| OSM TPR + 2021 FPR, epochs quantile-matched | 113% | -0.07 | -0.25 |
| OSM TPR + the TRUE current FPR (an oracle) | 46% | 1.26 | 0.96 |
| A strict threshold, no FPR correction (p >= 0.55) | 83% | 1.08 | 0.91 |
| 200 random flagged roofs reviewed yes/no, OSM TPR | 56% | 1.27 (90%: 1.09-1.47) | 0.93 |

**The past is not a negative set, and the reason is the classifier.** The same roofs flag
more often in 2021 than today (0.236 against 0.160, while today's true FPR is 0.093), so the
adjusted count goes negative. Matching the old epoch to today per band (median, median+IQR,
quantile) only makes the two flag rates equal (0.156 to 0.164 against 0.160), and the estimate
collapses to zero. The control that explains both: **roofclf's 2021 score predicts TODAY's
PV at AUC 0.832, against 0.870 for today's score** (0.848 once the epochs are matched), and
Pakistan had imported only 14% of today's panels by January 2022 (Ember). The classifier
recognises the kind of roof that adopts, not the panels on it, which is also why
[the epoch difference](#the-roof-is-its-own-control-2026-09-20) adds information but not much.
The same finding rules out the softer version of the idea, composing Sentinel-2 at an old
mapping epoch so a stale-imagery quadrat becomes Rule-1 again: the flagged set barely changes
between epochs, so such a quadrat would measure the old epoch's PV per flagged roof, which in
a boom country is several-fold below today's. That last step is inferred, not measured.

**The positives half works.** With the true FPR plugged in, OSM-derived TPR and array size
track the quadrats at Spearman 0.96. OSM positives are the easy ones (TPR 0.52-0.93 against
0.23-0.85 on quadrat PV; mean array 1.3-1.6x larger), and the two biases largely cancel, to
+26%. A yes/no review of random flagged roofs is the cheapest human input that supplies the
missing FPR (simulated at +27%, with 200 reviews holding the national total within about
15% of that), but each reviewed roof still needs recent imagery, which is the constraint
this started from.

**Nigeria**, the motivating case, and **India** (2026-10-22): does Pakistan's classifier
still rank PV roofs abroad? PU AUC on OSM-mapped sub-400 m² arrays against every other
sub-400 m² roof in the same cells (`scripts/transfer_calibration_pu_auc.py`; 90% intervals
from a cell-clustered bootstrap with negatives capped per cell):

| Country | Positives (cells) | PU AUC | Within size bins | Flag rate, positives / unlabelled |
| --- | --- | --- | --- | --- |
| Pakistan (own model, quadrats excluded) | 4,385 (133) | 0.930 (0.926-0.949) | 0.887-0.924 | 0.750 / 0.049 |
| India | 498 (148) | **0.778** (0.758-0.847) | 0.690-0.807 | 0.504 / 0.079 |
| Nigeria | 60 (25) | 0.661 (0.555-0.783) | 0.628-0.833 | 0.367 / 0.115 |

**Nigeria's first figure, 0.902 on 357 positives, was an artefact**, and so was India's
first, 0.673 on 47,911. The script labelled every footprint touched by any non-ground OSM
polygon, and VIDA traces a park's panel rows as buildings, so a large array or a park
mistagged rooftop turned into hundreds of "PV roofs" that were not the target population.
Positives now come only from arrays under 400 m², and footprints touching a larger PV
polygon are dropped from both classes; Pakistan, whose mapped rooftop PV is mostly small,
barely moves (0.934 -> 0.930), which is why the original rule looked sound. **The ranking
transfers to India only partly**: well above chance, well below Pakistan, and the mapped
Indian arrays are not smaller than Pakistan's (OSM sub-400 m² median 74.8 m² against 75.4),
so this is not France's sub-pixel regime. The level cannot be borrowed either way (above),
so neither country gets a sub-400 m² half: India needs its own Rule-1 quadrats (eight
sampled candidates are in `data/labels/india/candidate_quadrats/`), which would also
measure the borrowed model properly and allow a refit. Scored cells:
`data/roofclf_transfer/{nigeria,india}/prob`.

A side finding: composite_1 carries no BOA offset (scenes before baseline 04.00, 2022-01-25)
while composite_0 carries +1000 DN; each layer's own darkest 0.5% sits 730 to 860 DN apart in
every band (median over 60 cells). `roofclf.epoch_feature_frame(dn_offset=)` harmonizes it;
see open question 10 ("Growth as a product") for what it means for the growth atlas, and
for the 2026-10-22 finding that the offset differs by cell. Scripts:
`scripts/transfer_calibration_pakistan_check.py`, `scripts/transfer_calibration_followups.py`,
`scripts/transfer_calibration_pu_auc.py`. Results: `results/transfer_calibration/`.

### AlphaEarth embeddings: propensity, not panels (2026-10-22)

Google's Satellite Embedding dataset (AlphaEarth Foundations v2.1, CC-BY-4.0) gives every
10 m pixel a 64-number, unit-length summary of one calendar year of Sentinel-2, Landsat,
Sentinel-1 and other inputs, from 2017. It is the cheapest new input available: no training
and no GPU, and the Source Cooperative mirror (`tge-labs/aef`, anonymous S3) needs no Earth
Engine account. Each building got the area-weighted mean of the 64 channels over its
footprint, with the same `preprocess.coverage_matrix` weights the shipped Sentinel-2 features
use. Production 30-quadrat table, leave-one-quadrat-out, paired per fold against the shipped
model. Every variant was declared in the script before measuring; the harness reproduces the
shipped model exactly (0.8682 AUC, recall 0.658 at precision 0.5).

| Block | AUC | Within size band | vs baseline | Folds better | Sign p | Recall at precision 0.5 | Rate error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (shipped) | 0.8682 | 0.8194 | -- | -- | -- | 0.658 | 0.0286 |
| **Plus AEF 2025 (primary)** | 0.8682 | 0.8214 | +0.0032 | 18 of 29 | 0.26 | 0.642 | 0.0346 |
| Plus AEF 2024 | 0.8675 | 0.8220 | +0.0050 | 19 of 29 | 0.14 | 0.673 | 0.0372 |
| Plus AEF 2021, pre-boom control | 0.8741 | 0.8241 | +0.0047 | 20 of 29 | 0.061 | 0.691 | 0.0292 |
| Plus AEF 2025 and its change since 2021 | 0.8673 | 0.8295 | +0.0066 | 21 of 29 | 0.024 | 0.672 | 0.0264 |
| Plus AEF 2025 over a 70 m box, not the footprint | 0.8701 | 0.8182 | -0.0007 | 14 of 29 | 1.00 | 0.608 | 0.0384 |
| Size plus AEF 2025, no Sentinel-2 block | 0.7475 | 0.6424 | -0.1691 | 1 of 29 | < 0.001 | 0.030 | 0.0354 |
| Gradient boosting, plus AEF 2025 against without | 0.8517 | 0.7908 | +0.0012 | 16 of 29 | 0.71 | 0.647 | 0.0292 |

**The primary comparison is null.** -0.0003 AUC (14 of 29 folds, p = 1.00), +0.0032 within
size band (p = 0.26), and the two quantities the product consumes both get worse: recall at
the deployment precision falls 0.658 to 0.642 (quadrat bootstrap 95%: -0.066 to +0.034) and
the median per-quadrat adoption-rate error rises 0.0286 to 0.0346. A non-linear head does not
change that (+0.0012 within size band for gradient boosting).

**The pre-boom control explains the rest.** Pakistan had imported 14% of today's panels by
January 2022, so a 2021 embedding cannot see most mapped arrays; it scores at least as well
as 2025 (2025 against 2021: -0.0016 within size band, 12 of 29 folds; recall -0.049, 95%
-0.092 to -0.021). The one block that clears a sign test, 2025 plus the change since 2021, is
2021 plus 2025 in a linear model, and against the 2021 levels alone it adds nothing (+0.0016,
18 of 29, p = 0.26; Wilcoxon p = 0.13 against baseline). The direct check agrees: between
2021 and 2025 the embedding of a footprint that gained PV moved exactly as far as one that
did not (median cosine 0.9607 against 0.9604). What the embedding carries is the kind of roof
and neighbourhood that adopts, which is what [roofclf's own 2021
score](#a-sub-400-m2-level-without-quadrats-from-osm-and-a-past-epoch-2026-10-20) already
showed the Sentinel-2 block carries.

**It cannot replace the Sentinel-2 block.** Size plus the embedding reaches 0.6424 within size
band against 0.8194 for size plus reflectance, and flags almost nothing at precision 0.5. The
embedding is spatially smooth at roof scale: a footprint's mean embedding sits at cosine 0.992
from the mean over the 70 m box around it, so for a median 68 m2 Pakistani footprint it
mostly describes the block. The footprint is still marginally more informative than the box
(+0.0029 within size band, 22 of 29, p = 0.008), but neither beats the baseline.

**Large arrays are visible, small ones are not** (`scripts/aef_pixel_change_check.py`). On
the AEF grid, pixels at least 75% covered by mapped PV moved further 2021 to 2025 than
PV-free roof pixels more than 50 m from any PV (pooled AUC 0.653). That is carried by the
industrial quadrats (Multan, Rahim Yar Khan, Sanghar, SITE and the Karachi coast, 0.78 to
0.82); in the residential Islamabad and Lahore quadrats PV pixels moved LESS than distant
roofs (0.30 to 0.49), where new construction dominates the change. Roof pixels within 20 m of
PV moved less than distant ones (0.43), so the change does not smear into neighbours. An
annual AEF change map might corroborate large arrays or ground-mount, which is a separate
question from roofclf and was not tested.

Closed for roofclf. Scripts: `scripts/run_aef_embedding_ablation.py`,
`scripts/aef_pixel_change_check.py`. Results: `results/roofclf_aef_embedding.json` and
`_folds.csv`, `results/roofclf_aef_pixel_change.json`. Embedding windows for the 30 quadrats
(2021, 2024, 2025) are cached under `/home/tobi/earthpv_data/aef/`.

### AlphaEarth change finds unmapped ground-mount (2026-10-22)

The [roofclf test](#alphaearth-embeddings-propensity-not-panels-2026-10-22) closed the
embedding for small roofs but left one lead: pixels under large mapped arrays do move
between years. The place that could use it is the ground-mount precision table.
`pakistan_candidate_precision.yaml` sets `p_unmapped = 0.0` in every ground bin, so every
segmentation detection off a roof with no OSM feature within 100 m (about 4,300 of 5,200) is
booked as false, because nothing independent had ever looked at them.

**Data.** Scattered objects are unaffordable from the COG mirror (one band block per read,
~38 MB per object-year), so this reads the Source Cooperative Zarr mosaic
(`tge-labs/aef-mosaic`) by HTTP range request, ~2.5 MB per 256 x 256 chunk
(`scripts/aef_mosaic.py`, no new dependency; it matches the COG values at Multan at median
cosine 0.997). 2,215 chunks per year, 2017, 2021 and 2025.

**Populations** (`scripts/aef_large_array_change.py`, declared and seeded): every candidate
with OSM within 100 m (real), every rooftop candidate without, a size-proportional random
1,000 of the 4,326 unmapped ground ones, and 500 per placement of the OSM arrays >= 400 m2
that no candidate is within 100 m of (missed). Controls: each ground object's own polygon
displaced 300 to 1,200 m, and two PV-free VIDA roofs >= 400 m2 within 2 km for each rooftop
one (contaminated by unmapped PV, so rooftop AUCs are lower bounds). Scores: raw change
`1 - cos(e2017, e2025)`, and two logistic models fitted real against controls with
1-degree cells held out, one on the change vector alone (`learned`) and one adding the 2025
levels (`learned_level`).

| Real against controls, AUC | Raw change | Learned, change only | Learned, change and levels |
| --- | --- | --- | --- |
| Ground candidates (876) | 0.718 | 0.964 | 0.990 |
| Rooftop candidates (1,126) | 0.624 | 0.884 | 0.918 |
| Ground arrays segmentation missed (500) | 0.594 | 0.879 | 0.941 |
| Rooftop arrays segmentation missed (500) | 0.610 | 0.824 | 0.855 |

The direction of change carries the signal, not its size: raw change is weak, a model of
which way an embedding moves when an array goes in is strong, from 0.83 below 500 m2 to 0.98
at 5,000 to 50,000 m2 for ground. At the controls' 5% false-positive rate the change-only
model recovers 54% of the ground arrays segmentation missed and 40% of the rooftop ones.
That rate is against the land around them, not against look-alikes, so this is a
corroborating score for an existing candidate set, not a detector.

**The unmapped real share.** A threshold mixture (`pi = (P_unmapped - P_controls) / (P_real -
P_controls)`) puts it at 0.19 (1,000-5,000 m2), 0.29 (5,000-50,000) and 0.13 (> 50,000) on
the change-only score, about zero below 1,000 m2. That assumes a false positive changes like
the land around it, so it was checked by a **blind review** (`scripts/aef_render_review_tiles.py`):
60 shuffled Esri World Imagery panels under random codes, verdicts written before the key
was opened.

| Stratum (score above or below the controls' 95th percentile) | PV | No PV | Unsure |
| --- | --- | --- | --- |
| Mapped arrays, a check on the reviewer | 6 | 0 | 0 |
| Displaced controls | 0 | 6 | 0 |
| Unmapped, above | 7 | 12 | 5 |
| Unmapped, below | 1 | 23 | 0 |

The assumption fails, in the expected direction: the twelve false positives above threshold
are motorways, riverbeds, dark rock, forest, an open-pit mine and a factory yard, which score
higher than random land. Weighted back by stratum (31% of unmapped ground candidates >=
1,000 m2 sit above), **the real share is 0.12 to 0.18** (unsure counted as no, then yes),
below the mixture but far from 0.0. The review was a check on the method, by Claude from Esri
imagery; it is not a calibration, and the strata were drawn on `learned_level`.

Two leads came from the review and are post hoc, on 43 decided objects with 8 PV, so they
are recorded, not adopted. **The change-only score separates them far better** (AUC 0.975
against 0.857 with levels, 0.750 for raw change): forest, rock and mountain are static, and
only levels let them look like a solar park. **And timing separates the rest**: 63% of real
ground arrays changed mostly after 2021 against 39% of controls, and 75% of the reviewed
unmapped PV did, while the motorways, rivers, mine and yard changed mostly before.

**What it would mean, not applied.** At the table's current recall values, a ground
`p_unmapped` of 0.12 to 0.18 in the bins >= 1,000 m2 adds very roughly 0.44 to 0.66 GWp to
segmentation's ground estimate (1,135.6 MWp). Re-deriving that YAML is an owner decision and
interacts with the pending same-placement recall fix
([two errors that were cancelling](methods/mastr-validation.md#two-errors-that-were-cancelling)),
which pushes the other way. The next step is a real
review: `scripts/aef_ground_review_sample.py` has drawn 120 unmapped ground candidates, 40
per tercile of the change-only score, each with its Esri capture date (81 of 120 from 2025
or later), into `results/aef_ground_review/review.geojson` for JOSM.

Results: `results/aef_large_array_change.json` (and `_scores.csv`, `_population.parquet`),
`results/aef_ground_review/`. Embedding chunks are cached under
`/home/tobi/earthpv_data/aef/mosaic_chunks/` (16.6 GB).

### AlphaEarth against segmentation: a different detector, not a better one (2026-10-22)

**The owner's review settles the ground-mount share.** The 120 unmapped ground candidates of
`results/aef_ground_review/review.geojson` were reviewed in JOSM on Esri imagery and every
validated array mapped into OSM; `scripts/aef_review_from_osm.py` reads the verdicts back
(two agreeing Overpass answers, data base checked to postdate the edits). 67 solar features
are new since the July snapshot. Weighted back by tercile of the change-only score, the real
share of unmapped ground candidates is **0.26 under the precision table's own 100 m match
convention and 0.13 if the new feature must touch the candidate** (0.27 and 0.14 at >= 1,000
m2; undecidable old-imagery candidates excluded). Per tercile, strict: high 10 of 29, mid 1
of 23, low 0 of 35. The change score ranks these verdicts at AUC 0.84 (0.89 strict); raw
change at 0.53. Claude's blind review had said 0.12 to 0.18, i.e. it was applying the strict
rule. Either way the table's 0.0 is measurably too low; at its current recall values 0.14 to
0.27 is very roughly +0.5 to +1.0 GWp of ground-mount. Not applied.

**Wall to wall** (`scripts/aef_vs_segmentation.py --national-negatives`). A per-pixel logistic
over the frozen embedding (2025 levels and the change since 2017, positives from mapped
arrays >= 400 m2, negatives from around them and from 60 random national cells, never within
2 km of an evaluation area), against the production candidate set, on 20 uniformly random
density cells, 20 random PV-rich cells and the Rule-1 quadrats. The first run drew negatives
only around known PV and fired 300 to 1,300 times per 1,000 km2 of ordinary land; random-land
negatives fixed that, which is the difference between a usable and an unusable detector here.

| At tau 0.99 (declared: the first AEF threshold whose random-land burden is below segmentation's) | Segmentation | AlphaEarth |
| --- | --- | --- |
| Random cells: unmapped detections per 1,000 km2 | 8.5 | 5.7 |
| PV-rich cells: precision, mapped lower bound | 0.755 | 0.606 |
| PV-rich cells: precision with the reviewed share of unmapped | 0.83-0.88 | 0.65-0.70 |
| PV-rich cells: recall, ground / rooftop | 0.68 / 0.43 | 0.47 / 0.48 |
| Quadrats, exhaustive: precision | 0.952 | 0.969 |
| Quadrats: recall, ground / rooftop | 0.63 / 0.35 | 0.59 / 0.51 |

The reviewed share comes from a second blind review mixing 72 unmapped detections from both
instruments (`scripts/aef_vs_seg_review.py`): in the PV-rich cells 7 of 24 of segmentation's
were PV against 3 of 24 of AlphaEarth's, so the precision gap is not an artefact of OSM having
been mapped from segmentation's leads.

**What it adds is different arrays.** Arrays found by AlphaEarth and missed by segmentation
lift union recall from 0.35 to 0.60 for rooftop and from 0.63 to 0.81 for ground in the
quadrats, where its additions are 94% real; in the PV-rich cells from 0.43 to 0.63 and 0.68 to
0.76, where they are about 0.4 real. The gain sits at 400 to 5,000 m2 (quadrats: 0.31 to 0.47
at 400 to 1,000 m2, 0.56 to 0.83 at 1,000 to 5,000 m2). Its false positives are landscape
change, roads, rivers, mines, construction, where segmentation's are spectral look-alikes.

**Verdict: not a replacement and not a third capacity instrument; two roles.** A precision
corroborator for segmentation's unmapped candidates, calibrated on the owner's review, and a
leads generator for the human-validation workflow, aimed at urban and industrial cells. Its
newest year is calendar 2025, so it cannot see the newest arrays, and a national wall-to-wall
pass is ~0.5 TB from the Zarr mosaic, or a server-side job on Earth Engine.

Results: `results/aef_ground_review/owner_review_summary.json`, `owner_verdicts.csv`;
`results/aef_vs_segmentation_natneg.csv` (and the first run without random-land negatives,
`aef_vs_segmentation.csv`); `results/aef_vs_seg_review/`.

### The capacity chain is a quantification problem (2026-10-22)

A sweep of the levers this register had not yet tried, on the 30 production quadrats with the
same paired leave-one-quadrat-out design as above. Every block is scored three ways: ranking
(AUC within roof-size band), recall at the precision-0.5 deployment threshold, and the error
on each held-out quadrat's true PV area when it is priced the way the capacity chain prices it.
The harness recomputes the shipped band means from the composites and matches the production
table exactly before adding anything (`scripts/roofclf_untapped_extract.py`,
`scripts/roofclf_untapped_ablation.py`; `results/roofclf_untapped.json` and `_pass2.json`).

**The classifier: nothing new ships.**

| Block | Within size band vs shipped | Folds better | Verdict |
| --- | --- | --- | --- |
| Footprint weights convolved with a Gaussian PSF, sigma 0.4 / 0.65 / 1.0 px | +0.0005 / -0.0022 / -0.0144 | 19 / 11 / 7 of 29 | rejected: the area weights already fit |
| Footprint buffered 1 / 2 / 4 m before area weighting | +0.0002 / -0.0012 / -0.0105 | 15 / 12 / 6 | rejected |
| VIDA micro-context: counts within 25-100 m, nearest neighbour, relative size, built-up share | -0.0049 | 10 | rejected |
| The ten nearest buildings' mean features (a spatial lag) | -0.0010 | 13 | rejected |
| Spectral features x log roof area; all 45 pairwise band indices | -0.0003; -0.0002 | 14; 14 | rejected |
| L2 0.01 / 100 / 1,000 | -0.0009 / -0.0046 / -0.0263 | 7 / 9 / 7 | the shipped L2 = 1 stands |
| Equal training weight per quadrat | -0.0011 | 8 | rejected |
| Train without positives under 10 m<sup>2</sup> of PV; without negatives within 5 m of a positive | -0.0009; +0.0002 | 4; 15 | rejected |
| Yard block; segmentation and fraction rasters (re-measured on the current fit) | +0.0004; +0.0002 | 16; 16 | still rejected |
| Mean logit of the linear model and gradient boosting | +0.0003 | 16 | recall +1.4 points (95% 0.2 to 4.0), nothing else |
| Difference against composite_1 (2021-10 to 2022-01), per-window median match | +0.0024 | 20 (p = 0.061) | partial, below |

**A second epoch is already on disk for Pakistan.** composite_1 exists for 4,467 of 4,473
cells, so the download [the epoch-difference result](#the-roof-is-its-own-control-2026-09-20)
priced at a national recomposite is not needed here. Its difference is the one positive block
above, and on the capacity metric it helps thresholded pricing (median error 0.457 to 0.367,
20 of 29 quadrats, p = 0.061) but not probability-weighted pricing (19 of 29, p = 0.26), so it
is not deployed. Two cautions came with it. composite_1's radiometric scale differs by cell:
the 122 cells built on 2026-07-05, which hold 24 of the 30 quadrats, already sit on
composite_0's scale, so the documented flat +1000 DN offset makes them 0.1 too bright, and the
version using it scores worse (+0.0014). And the 2021 epoch alone reaches 0.7956 within size
band against 0.8194, the propensity [already recorded](#a-sub-400-m2-level-without-quadrats-from-osm-and-a-past-epoch-2026-10-20).

**Gradient boosting, priced end to end.** [The model-class test](#the-model-class-ranking-and-calibration-disagree-2026-09-19)
left open whether its better per-quadrat adoption rate survives the capacity chain. It does
not: per-quadrat PV-area error 0.409 against 0.457 thresholded (12 of 29 quadrats closer,
p = 0.46), and 0.245 against 0.242 probability-weighted.

**The lever is the aggregation.** The capacity chain counts a flagged roof in full and an
unflagged one not at all, then rescales by how that count behaved in the quadrats. Rebuilt in
the chain's own structure and held out one quadrat at a time
(`scripts/roofclf_soft_capacity_check.py`, `results/roofclf_soft_capacity.json`), median error
on true sub-400 m<sup>2</sup> PV area:

| Pricing, same scores | Median error | IQR | Pooled ratio |
| --- | --- | --- | --- |
| No classifier (roof area x ratio) | 0.518 | 0.23-1.84 | 1.085 |
| Flagged roof area (published) | 0.386 | 0.16-0.83 | 1.017 |
| Probability-weighted roof area | 0.094 | 0.07-0.67 | 0.998 |

Probability weighting is closer in 20 of 29 quadrats (Wilcoxon p = 0.0035), and 18 to 23 of
29 for four other scores and the roof-only label; the flagged version does not beat the
null at the median (16 of 29). The mechanism is the sparse end: below 300 bldg/km<sup>2</sup>
the mean score matches the true adoption rate (0.020 against 0.020) while only 0.2-0.3% of
roofs cross the threshold, so the flagged version books 12% of the mapped PV there and the
weighted one 92%. Through the real chain this moved Pakistan's Best estimate from 24,438 to
34,589 MWp, most of it in cells of 100-1,000 bldg/km<sup>2</sup>, where calibration is
thinnest, so it shipped opt-in (`--weighting probability`) with thresholding as the default.

**Adopted 2026-10-25** (owner decision): probability weighting is now the default of both
capacity commands, and the published Pakistan atlas uses it. Best estimate 24,438.3 to
34,588.8 MWp (90% 29,308-41,736); sub-400 m<sup>2</sup> roofclf 13,262.6 to 24,206.3, the
&ge; 400 m<sup>2</sup> replacement 8,256.7 to 7,503.2; the roofclf-AND-SPPI floor stays
thresholded by design, so Verified is unchanged at 6,994.1 MWp. 80% of the +10.2 GWp lands
in cells of 100-1,000 bldg/km<sup>2</sup>, and against the independent rooftop-solar
reference the geography agrees better (Spearman 0.868 to 0.882; 0.773 to 0.861 on hexagons
where this project is non-zero). A `--weighting threshold` rerun the same day reproduced the
previous page exactly. The thresholded count stays available as `--weighting threshold`.
Measured on the quadrats but not in sparse national cells:
[roofclf](methods/roofclf.md#count-every-roof-by-its-score) lists what it trusts and the two
measurements that would revert it.

**Estimators built for prior shift fail.** Treating the capacity chain as the quantification
problem it is, the standard estimators for a population whose base rate differs from training
were tried on the same scores (`scripts/roofclf_quantification.py`): EM prior adjustment
(Saerens et al. 2002), adjusted counts by TPR and FPR, and their probabilistic version. All
three reach a median error near 1.0, collapsing most quadrats to zero. Their assumption is
that only the base rate differs between quadrats while the score distribution within each
class stays put, and these quadrats differ in roof stock as well.

**Temporal unmixing on a full-year stack is dropped from the open list.** Its best measured
gain was +0.0015 within size band in the most dynamic quadrats, and this sweep puts the
binding error in the aggregation, not in another thousandth of ranking.

### A finer token grid: THOR at 8 px against TerraMind (2026-10-24)

TerraMind's patch embedding is fixed at 16 px, so at 10 m every token is 160 m across and a
400 m<sup>2</sup> array is 1/64 of one. ESA and IBM's comparison of TerraMind and THOR
(arXiv 2607.18504) found patch size and decoder explain more variance than which model is used,
with compact minority classes gaining most from small patches. THOR (ESA Phi-lab and NR,
Apache-2.0) accepts any patch size, so the test was whether a finer grid recovers the rooftop
arrays of 400-5,000 m<sup>2</sup> that segmentation misses.

**Design.** Three THOR-Tiny runs on v14's corpus with v14's recipe (loss, learning rate,
schedule, patience, neck tail, UNet decoder), so v14 itself is the baseline and was not
retrained. THOR tokenises each GSD group separately, which needed a control that matches
TerraMind's grid band for band:

| Run | 10 m group (B02-B04, B08) | 20 m group (B05-B07, B8A, B11, B12) | Tokens | Train cost per batch of 8 |
| --- | --- | --- | --- | --- |
| v14 (TerraMind-Tiny) | 160 m | 160 m | 196 | 274 ms |
| THOR ps16 | 160 m | 320 m | 245 | 133 ms |
| THOR ps16m (matched grid) | 160 m | 160 m | 392 | 182 ms |
| THOR ps8 | 80 m | 160 m | 980 | 614 ms |

Scored by `scripts/compare_backbones.py` on every AOI's own `val` chips: the six holdouts of
the training corpus plus five countries none of the models saw (Poland, Vietnam, India,
Morocco, Egypt). Recall is per installation, paired on the same (chip, installation) and tested
with an exact McNemar. Each THOR model is also compared at its own lowest threshold whose pooled
pixel precision reaches v14's at the production 0.3, because a model that marks more pixels
finds more installations: a 50-step smoke model scored recall 0.97 against v14's 0.75 at pixel
IoU 0.02.

**Result: no pooled recall gain.** At matched precision, all 11 AOIs pooled:

| | v14 | THOR ps16m | THOR ps8 |
| --- | --- | --- | --- |
| Rooftop 400-5,000 m<sup>2</sup> recall (n = 4,633) | 0.574 | 0.573 (p = 0.97) | 0.585 (p = 0.08) |
| Ground >= 400 m<sup>2</sup> recall (n = 10,722) | 0.933 | 0.924 (p < 0.001) | 0.928 (p = 0.005) |
| Pixel precision | 0.733 | 0.776 | 0.782 |
| Pixel IoU | 0.633 | 0.645 | 0.656 |

On the matched grid THOR ties TerraMind, and halving the 10 m group's token adds +1.2 points of
rooftop recall over it (+496/-441 installations, p = 0.08). The ps16 run with 320 m SWIR tokens
lost in every AOI but Morocco (rooftop 0.29 against 0.57): coarse SWIR tokens cost far more than finer visible
tokens gain, the same band ranking roofclf's coefficients show. What the finer grid does buy is
outline: pixel precision +5 points and IoU +2.3 over v14, consistent at both saved epochs and in
9 of 11 AOIs, which matters to an area-based capacity estimate more than to installation recall.

**The regional effects are mostly selection noise.** ps8 against ps16m is +18 points on French
rooftops and +18 on Pakistani ones, but -9 on South African and -15 on German (54
installations). Within v14's own run, the second-best checkpoint (epoch 49, val mIoU 0.805
against 0.811) has pooled rooftop recall 0.621 against the shipped epoch 41's 0.565, +9 points
in South Africa, at pixel precision 0.717 against 0.736. So one run and one selected epoch per
model cannot resolve a few points either way. The France gain is the one that held at both
saved epochs of both runs (0.57 and 0.54 against 0.42 and 0.43).

**Verdict: not adopted.** A finer grid does not recover the missed rooftop arrays at a level
one run can show, at 2.2 times v14's training cost per batch (614 against 274 ms) and three
times THOR ps16's inference cost per window (45 against 14 ms).
4 px was not run: it does not fit at batch 8 on the GTX 1060, an estimated 5 s per batch puts a
run at 8-12 days, and the ps8 over ps16m increment it would extend is +1.2 points. Two leads
came out of it:

- **Checkpoint selection.** val/mIoU is dominated by large ground plants' pixels and is a poor
  selector of rooftop recall. A selection rule on held-out installation recall, from a split
  that is not the holdout, or averaging the last epochs' weights, is untested and free.
- **Pascal attention, and it applies to production.** On the GTX 1060 PyTorch's default SDPA
  kernel (memory-efficient) is about 15 times slower in fp16 than the math kernel (269 against
  18 ms per layer at 980 tokens). TerraMind calls the same SDPA: forcing the math kernel takes
  TerraMind-Tiny from 275 to 97 ms per training batch of 8, with logits within 0.003 and 99.9%
  of pixels unchanged. **Applied to training 2026-10-24** (`earthpv.attention`; a 50-step
  smoke run 17 against 36 s). Not to TerraMind inference, which runs one window at a time
  and gains only 17% (25 against 29 ms per window), while 0.03% of a raster's pixels move by
  1-2 uint8 levels (7 of 51,120 detected pixels crossed 0.3 on six South African cells):
  every published raster stays reproducible byte for byte instead.

Code: `src/earthpv/thor_backbone.py` (THOR from a `third_party/` checkout, input
standardisation from `scripts/chip_band_stats.py`, compile disabled and the math kernel forced
on pre-Volta GPUs), configs `configs/thor_pv_ps{16,16m,8}_south_africa.yaml`, runner
`scripts/run_backbone_compare.sh`. `infer` uses a stride of 102 for tokens finer than 16 px,
since 104 is a multiple of 8. Results: `results/backbone_compare/thor16_vs_v14/`,
`thor8_vs_v14_lowthr/`, `thor16m_thor8_vs_v14/`, `epoch_noise/`.

### OlmoEarth embeddings: ahead in Pakistan, behind in South Africa (2026-10-25)

Ai2's OlmoEarth v1.3 annual embeddings (OlmoEarth-v1.3-Base over a calendar year of
Sentinel-1, Sentinel-2 and Landsat; 128 dimensions, int8, 10 m on each UTM zone's grid;
released 2026-10-22 on Source Cooperative) went through
[the AlphaEarth head-to-head](#alphaearth-against-segmentation-a-different-detector-not-a-better-one-2026-10-22)
unchanged: the same evaluation areas, truth, negatives, logistic probe and thresholds, so the
embedding is the only thing that differs. One deviation was forced: OlmoEarth covers 2017-2022
for only part of Pakistan (zone 43 from 2017, Multan's zone 42 from 2022, Quetta from 2023),
so change is measured from 2023 for both embeddings, and AlphaEarth was re-run on that
baseline. That costs AlphaEarth little (PV-rich recall 0.44 against 0.48 from 2017, quadrats
0.52 against 0.54).

**Operating points.** The declared rule (the first threshold whose random-land burden falls
below segmentation's 8.5 unmapped detections per 1,000 km<sup>2</sup>) picks tau 0.99 for
AlphaEarth and 0.995 for OlmoEarth's 64-dimension Matryoshka prefix. The full 128 dimensions
never get below it (15.1 at 0.995, the highest threshold tested), so they have no declared
point and are shown at 0.995 for reference.

| | Segmentation | AlphaEarth | OlmoEarth 64-d | OlmoEarth 128-d |
| --- | --- | --- | --- | --- |
| Random cells: unmapped detections per 1,000 km<sup>2</sup> | 8.5 | 5.7 | 6.1 | 15.1 |
| Random cells: of those, PV in Claude's blind review | 2-5 of 12 | 1-4 of 12 | 7-11 of 13 | not reviewed |
| Random cells: of those, PV in the owner's blind review | not reviewed | not reviewed | 10-12 of 13 | not reviewed |
| PV-rich cells: precision, mapped lower bound | 0.755 | 0.679 | 0.745 | 0.660 |
| PV-rich cells: precision with Claude's reviewed share | 0.84-0.88 | 0.71-0.73 | 0.85-0.86 | not reviewed |
| PV-rich cells: precision with the owner's reviewed share | 0.86-1.00 | 0.73-0.89 | 0.85-0.98 | not reviewed |
| PV-rich cells: recall, ground / rooftop | 0.68 / 0.43 | 0.46 / 0.40 | 0.83 / 0.67 | 0.92 / 0.82 |
| Quadrats, exhaustive: precision | 0.952 | 0.971 | 0.959 | 0.941 |
| Quadrats: recall, ground / rooftop | 0.63 / 0.35 | 0.53 / 0.51 | 0.92 / 0.65 | 0.99 / 0.69 |
| Quadrats: rooftop arrays a detection overlaps | 0.12 | 0.34 | 0.53 | 0.59 |

AlphaEarth is the 2023 baseline throughout except its random-cell review, which is the earlier
review of the 2017 baseline. **At the same false-alarm budget OlmoEarth 64-d matches
segmentation's precision and finds far more arrays**: quadrat rooftop recall 0.65 against 0.35,
PV-rich ground 0.83 against 0.68. Segmentation adds almost nothing on top of it (the union
reaches 0.65 rooftop and 0.95 ground in the quadrats), where AlphaEarth's union with
segmentation reached 0.60 and 0.81. In the quadrats 51 arrays are found by OlmoEarth and by
neither of the other two, against 6 found only by AlphaEarth. On random land its unmapped
detections are mostly real: in Claude's review 7 of 13 are clearly PV and 4 more are unsure,
so its false alarms are 0.9-2.8 per 1,000 km<sup>2</sup> against segmentation's 5.0-7.1; the
owner's review puts OlmoEarth's at 0.5-1.4 (segmentation's random-cell detections were not in
the owner's sample).

**Checked against four ways it could be an artefact:**

- **Loose matching.** A truth array counts as found when a detection lies within 100 m, which
  rewards blobs painted over built-up land. It does not here. OlmoEarth 64-d covers 0.24% of
  the PV-rich cells' land against segmentation's 0.35%, 80% of its detected area lies on mapped
  PV (segmentation 84%), and requiring overlap instead of proximity keeps the ranking: quadrat
  rooftop 0.53 against 0.12 for segmentation and 0.34 for AlphaEarth, as tabled.
- **Pixel leakage.** Training tiles touching a 0.02-degree buffer around any evaluation area are
  skipped, the rule AlphaEarth used.
- **OSM labels in pretraining.** OlmoEarth's pretraining decodes 30 rasterised OSM layers (as
  targets only; inference sees imagery alone), among them `power_plant`, i.e. every `power=plant`
  outline including solar parks, and `building`. Its training tiles were also chosen from 120 OSM
  categories that include solar plants. So part of its plant-outline recall may be exposure to
  these very labels: quadrat plant outlines are overlapped at 0.69 against segmentation's 0.22.
  Solar `power=generator` was never a target, and rooftop generators still go from 0.12 to 0.53
  in the quadrats, so the rooftop gain cannot come from it.
- **The reviewer.** The 61 panels (`scripts/olmoearth_vs_seg_review.py`, blind and mixed) were
  judged twice, by Claude and then by the owner (`scripts/build_review_page.py`). Fresh draws of
  segmentation and AlphaEarth read in Claude's review as its earlier review did (5 PV and 3
  unsure of 12 against 7 and 4 of 24; 1 and 1 of 12 against 3 and 1 of 24), so the instruments
  were read alike. The two reviewers never disagree about PV: every panel Claude called PV the
  owner did too, plus four more. They differ on the rest: of the 29 panels Claude called not
  PV, the owner marked 22 unsure. So the owner's lower ends match Claude's (OlmoEarth 0.85,
  segmentation 0.86 in the PV-rich cells) and the upper ends are wider. In the owner's review
  OlmoEarth's PV-rich detections are 10 PV, 12 unsure and 2 not PV of 24, segmentation's 5, 7
  and 0 of 12, AlphaEarth's 2, 6 and 4 of 12; on random land OlmoEarth's are 10, 2 and 1 of 13.

Plausible reasons, untested: a year of monthly multi-sensor input against one dry-season
median, and the Sentinel-2 grid itself rather than AlphaEarth's resampled lat/lon grid.

**The repeat in South Africa reverses it.** `scripts/olmoearth_vs_segmentation_country.py` ran
the same 64-d probe, recipe and operating-point rule against v14's candidates, with the PV-rich
cells drawn from the Western Cape, segmentation's val holdout, and the probe barred from that
region too, so neither instrument trained there: 20 random national cells and 20 of the 78
holdout cells holding two or more mapped arrays (the country has no quadrats). The rule again
picks tau 0.995. Both Claude and the owner reviewed the 96 blind panels; they agree on 78.

| | Segmentation (v14) | OlmoEarth 64-d |
| --- | --- | --- |
| Random cells: unmapped detections per 1,000 km<sup>2</sup> | 19.3 | 15.2 |
| Random cells: of 24 unmapped, PV in Claude's review | 1-6 | 1-5 |
| Random cells: of 24 unmapped, PV in the owner's review | 2 | 1-2 |
| PV-rich holdout cells: precision, mapped lower bound | 0.287 | 0.314 |
| PV-rich holdout cells: precision with Claude's reviewed share | 0.50-0.55 | 0.49-0.54 |
| PV-rich holdout cells: precision with the owner's reviewed share | 0.53 | 0.54 |
| PV-rich holdout cells: recall, all / rooftop / ground | 0.43 / 0.42 / 0.52 | 0.22 / 0.22 / 0.20 |

Precision ties again, at half the recall. OlmoEarth matches segmentation's recall only at tau
0.98 (0.44), at twice its random-land burden (37.3), and adds little in union (0.43 to 0.49).
Both instruments are far less precise than in Pakistan: the reviewed false alarms are mostly
roofs without panels, fields and sheds, plus ten electrical substations, all of them
OlmoEarth's. `power_substation` is one of OlmoEarth's pretraining OSM targets beside
`power_plant`, which may be why a probe trained on PV lands on them. As a corroborator it still
separates: segmentation candidates it confirms are mapped at 0.47, the rest at 0.26.

**Local training data does not explain it.** In Pakistan both instruments trained on labels
from around the evaluated cells (the probe outside a 0.02-degree buffer); in South Africa
neither did. A second run (`--train-in-holdout`) adds the 759 Western Cape training tiles
outside that buffer to the first run's 2,500 and national negatives, drawn again from the same
seed, with segmentation still held out. The rule then picks tau 0.99, and the probe's recall in
the holdout cells moves from 0.22 to 0.26 (rooftop 0.24, against segmentation's 0.42), its
mapped lower bound from 0.314 to 0.244. At every fixed tau its recall is slightly lower than
without the local tiles. So the gap to Pakistan is the country (its arrays, roofs and
confusers), not missing local labels.

**Verdict: a corroborator worth knowing about, not a detector to adopt.**

- **It does not transfer.** In South Africa a pixel logistic on the frozen embedding finds half
  of what segmentation finds at the same precision, even with labels from the evaluated
  region, and it brings its own false alarm.
- **The licence.** The OlmoEarth Artifact License forbids military and extractive uses,
  requires those restrictions to travel with distributed derivatives, and requires citing Ai2.
  Detections derived from it cannot go into the ODbL atlas or the Apache-2.0 model without an
  owner decision on how the terms combine. Leads that only point mappers at imagery are the
  least entangled use.
- **Cost.** At 64 dimensions and two years it is 1.1 MB per km<sup>2</sup>: about 1 TB for
  Pakistan, about 0.5 TB for the building-populated cells. That is roughly a day per 0.5 TB
  with nothing else on the link; this run fetched 49 GB in 4.5 hours beside a national compose.
- **One probe.** Only a pixel logistic regression on frozen embeddings was measured, and
  nationally change is available only from 2023.

In Pakistan, as a corroborator, it confirms 238 of segmentation's 290 PV-rich candidates, at a mapped
precision of 0.815, against 0.481 for the 52 it does not. AlphaEarth confirmed 134, at 0.836
against 0.686, so OlmoEarth separates segmentation's real candidates from its false ones better.

Code: `scripts/olmoearth_mosaic.py` (Zarr v3 shard reader over range requests, no new
dependency), `scripts/olmoearth_vs_segmentation.py`, `scripts/olmoearth_vs_seg_review.py`,
runner `scripts/run_olmoearth_compare.sh`; `scripts/aef_vs_segmentation.py --base-year 2023`.
Results: `results/olmoearth_vs_segmentation.csv` (with `_unions.csv` and `.json`),
`results/aef_vs_segmentation_natneg_base2023.csv`, `results/olmoearth_vs_seg_review/` (the
owner's verdicts in `summary_owner.json` and `blind_review_joined_owner.csv`, Claude's in
`summary.json` and `claude_verdicts.csv`). South Africa: `scripts/olmoearth_vs_segmentation_country.py`
(`--review`, `--join`), runner `scripts/run_olmoearth_country.sh`;
`results/olmoearth_vs_segmentation_south_africa.csv` (with `_unions.csv` and `.json`; the
second run beside it with `_holdout_trained`) and
`results/olmoearth_vs_seg_review_south_africa/` (the owner's verdicts in
`summary_verdicts.json`, Claude's in `claude_verdicts.csv`;
the owner's review page is `blind/review.html`, from `scripts/build_review_page.py`).

### One segmentation model for every country? v18 pooled (2026-10-30)

Every localized checkpoint is v5's corpus plus ONE country, so no model had seen more than one of
Poland, India, Vietnam, Egypt, Morocco, Yemen, Nigeria and Zambia, and Germany's chips came from
14 MGRS tiles. v18 pools them: v16's corpus row for row, each of those eight countries' train
chips repeated up to 8 times towards about 7,000 rows, and 7,205 German chips cut from the
national compose outside the 14 tiles (69,364 rows, 64,967 train; provenance in
`data/chips/combined_pooled_v18/corpus.json`). The recipe is v16's unchanged: one run, best
val/mIoU 0.8191 at epoch 18, early-stopped after epoch 26.

**Scored against v14 at matched precision.** `scripts/compare_backbones.py` on 14 holdouts,
paired McNemar per installation. Its first pass could not match: v18's pixel precision at its
lowest scored threshold (0.790 at 0.2) was already above v14's at production (0.755 at 0.3), so
its "matched" row was still a more conservative model. The re-score
(`results/backbone_compare/v18_pooled_vs_v14_lowthr/`) adds thresholds down to 0.0003. Pooled
over the six matching AOIs, v18 reaches v14's precision at 0.01 (0.764), its epoch 23 at 0.3
(0.758). Over all 14 holdouts:

| Checkpoint (threshold) | >= 400 m<sup>2</sup> | Rooftop 400-5,000 m<sup>2</sup> | Ground >= 400 m<sup>2</sup> | Pixel IoU (6 AOIs) |
| --- | --- | --- | --- | --- |
| v14 (0.3) | 0.816 | 0.573 | 0.916 | 0.622 |
| v18 epoch 18 (0.01) | 0.783 (+256/-790) | 0.474 (+144/-609) | 0.910 (+108/-177) | 0.590 |
| v18 epoch 23 (0.3) | 0.787 (+219/-688) | 0.492 (+137/-517) | 0.908 (+79/-167) | 0.615 |

Every row is p < 1e-4 against v14. v18 at epoch 18 never reaches v14's pixel recall at any
threshold (0.739 at 0.0003 against 0.780 at 0.3): this is not only a shifted operating point.

**Where it loses, matched to v14's own precision in each region:**

- **South Africa** (4,700 installations): rooftop 0.48 (epoch 18) and 0.53 (epoch 23) against
  0.62, 333 and 212 rooftop arrays lost net; ground 0.945 against 0.950.
- **France** (2,217): rooftop 0.37 and 0.31 against 0.42; ground 0.56 and 0.58 against 0.66.
- **Poland** (4,334): rooftop 0.53 against 0.64 but not matched, since v14 is far less precise
  there (0.69) than v18 at any threshold. Poland's own v15 makes the same trade (79 of 154
  rooftop arrays against v14's 98, `results/release_model_benchmark.csv`). Ground up to +0.8
  points.
- **Egypt** (23): 13 (epoch 18) and 6 (epoch 23) against 1, the one clear win, on v18's own
  training data.
- Germany, Pakistan (both holdouts), Punjab, Gujarat, India, Vietnam, Morocco, Zambia and Yemen:
  no significant difference, except two small losses (German ground, 7 of 399 at epoch 18;
  `pakistan_fresh`, 11 net of 314 at epoch 23).

So on the seven holdouts v14 never trained on and v18 did (India, Poland, Vietnam, Morocco,
Egypt, Yemen, Zambia), v18 wins one, and v14 transfers as well as v18 does with home data.

**Why, as far as one run shows.** The losses sit in the two largest holdouts, South Africa and
France, which both corpora contain and whose share v18 halved (South Africa 7,092 of 30,458
train rows in v14, 23%, and of 64,967 in v18, 11%). Early stopping on pooled val/mIoU ended v18 at
about 19 passes over each South African chip against v14's 42, and epoch 23 is better than
epoch 18 on South African rooftops (0.54 against 0.47 at 0.3) at the same val/mIoU (0.8188
against 0.8191). Some of the gap may therefore be dilution and under-training rather than
harmful labels. Two harmful-label candidates are untested: the German national chips (OSM holds
about 3.6% of Germany's rooftop units, so unmapped roofs train as background) and Yemen's 233
chips repeated 8 times (labels segmentation does not find at all). `last.ckpt` is epoch 23;
epochs 24 to 26 were not saved.

**Verdict: rejected as trained.** v18 replaces neither the released v14 nor any country's
checkpoint. What would separate the explanations: v18 trained on to v14's epoch count without
early stopping (resume from `last.ckpt`, about 11 GPU hours); v18 as a starting point for one
country's fine-tune; and a run without the German national chips and the Yemen repeats.

### Feeding TerraMind the input it was pretrained on: v21 (2026-10-30)

TerraMind was pretrained on Sentinel-2 L2A standardised per band with fixed statistics, but
TerraTorch 1.2.8's TerraMind ViT backbones (`terramind_v1_tiny` and its siblings) do not apply
them; only its generation and TiM builders do. Every segmentation checkpoint up to v20 was fed
reflectance (DN / 10000), so each band's spread was 5 to 8 times narrower than in pretraining.
TiM variants were not an alternative: they refuse a band subset and need 12 bands, where the
composites have 10.

**The probe said it mattered.** A frozen-feature probe on v14's corpus (logistic regression on
the four encoder layers the neck selects, one prediction per 16 px token, 1,487 training and
754 held-out chips) measured what the pretrained encoder can read before any fine-tuning:

| Encoder input | Held-out token average precision |
| --- | --- |
| DN / 10000 (every checkpoint so far) | 0.469 |
| TerraMind's own standardisation of raw DN | 0.737 |
| The same, 1,000 DN BOA offset removed first | 0.696 |
| The corpus's own statistics (what `thor_backbone` applies) | 0.452 |
| Randomly initialised weights, DN / 10000 and standardised | 0.231, 0.259 |

It improved in all six training AOIs (France 0.115 to 0.553, South Africa 0.426 to 0.718).

**The test.** v21 is v14 with one change: `backbone: earthpv_terramind`, which standardises each
band with TerraMind's statistics inside the model. Same pretrained weights, bands, neck,
decoder, loss, learning rate (1e-4, constant), patience and corpus
(`data/chips/combined_south_africa`). It was scored as THOR was
([above](#a-finer-token-grid-thor-at-8-px-against-terramind-2026-10-24)): 11 holdouts, paired
McNemar per installation, each checkpoint at its own threshold reaching v14's pooled pixel
precision (0.755 over the six training AOIs). Since one selected epoch moves rooftop recall by
several points, both of v21's saved epochs were scored against both of v14's.

**v21 converges twice as fast.** Its best val/mIoU, 0.8132 at epoch 20, is above v14's 0.8109
at epoch 41, and early stopping ended it after epoch 28 against v14's 49.

**It does not find more installations.** All 11 AOIs pooled, at matched precision:

| | v14 epoch 41 (shipped) | v14 epoch 49 | v21 epoch 20 | v21 epoch 27 |
| --- | --- | --- | --- | --- |
| Threshold | 0.3 | 0.8 | 0.5 | 0.1 |
| Rooftop 400-5,000 m<sup>2</sup> recall (n = 4,634) | 0.574 | 0.610 (p < 0.001) | 0.575 (+317/-312, p = 0.87) | 0.576 (p = 0.67) |
| Ground >= 400 m<sup>2</sup> recall (n = 10,725) | 0.933 | 0.929 (p = 0.003) | 0.926 (+75/-142, p < 0.001) | 0.925 (p < 0.001) |
| Pixel precision | 0.733 | 0.760 | 0.754 | 0.763 |
| Pixel IoU | 0.633 | 0.644 | 0.650 | 0.654 |

v14 epoch 49 does not quite reach the target at the highest scored threshold (0.754 at 0.8).
The pixel IoU gain comes mostly from Morocco, where the shipped epoch alone is imprecise (0.68
against 0.91 to 0.96 for the other three).

**The regional moves are mostly epoch noise.** v21 gains rooftop arrays in South Africa (0.66
and 0.65 against 0.62, p < 0.002) and Punjab (0.69 and 0.71 against 0.66) and loses ground
plants in Poland (0.960 against 0.970), but v14's own epoch 49 makes all three moves, each by
more (South Africa 0.69, Punjab 0.71, Poland 0.955). The one move that is v21's own,
at both saved epochs, is a loss in **France**: rooftop 0.35 and 0.38 against 0.42 (+63/-165,
p < 0.001), ground 0.62 and 0.60 against 0.66, where v14 epoch 49 differs from epoch 41 by
about one point either way. Elsewhere the differences are small: Pakistan's ground plants rise
at both v21 epochs (0.81 against 0.77) as they do at v14 epoch 49, German ground falls by 7 of
399 at epoch 27 only (p = 0.02), and Gujarat, Vietnam, India, Morocco and Egypt show none.

**Verdict: rejected as a model change.** The probe measured a frozen encoder. Fine-tuning every
layer at 1e-4 lets the encoder adapt to whatever scale it is fed, and here it adapts fully;
the input only shortens the way there. v21 replaces neither the released v14 nor any country's
checkpoint, and no published number changes. The standardisation could still matter where the
pretrained features have to carry more: with a lower encoder learning rate, a frozen encoder,
or a larger backbone fine-tuned briefly. That is untested, and worth trying only together with
a learning-rate schedule (constant 1e-4 with early stopping is the recipe every checkpoint
used). The faster convergence is real but small in hours: 20 fewer epochs at about 9 minutes
each on the GTX 1060, so v21 trained in 4.5 hours.

Code: `src/earthpv/terramind_backbone.py` (`earthpv_terramind`: the statistics as buffers, in
the units the model receives, so they travel with the checkpoint and `datamodule`, `infer` and
`evaluate` are unchanged; every existing checkpoint loads and predicts exactly as before),
config `configs/terramind_pv_v21_tmnorm_south_africa.yaml`, runner
`scripts/run_tmnorm_compare.sh`. Checkpoints in
`/home/tobi/earthpv_data/models/v21_tmnorm_south_africa/`. Results:
`results/backbone_compare/v21_tmnorm_vs_v14/`.

## The partial result worth watching

### Time-series step detection below the floor

At a median installation area near 50 m², the trained model reads 0.000 probability on 99.8%
of true footprints and glint validates zero of 1,021. Static appearance is exhausted. But
*appearance in time* is a different signal: a panel installed in 2023 is a step change in a
dense per-pixel Sentinel-2 series, even if no single scene shows it.

`scripts/pv_step_signal.py` removes common-mode atmosphere against reference pixels, guards
co-registration by phase correlation, learns the PV installation change vector spectrally
rather than assuming a fixed index, deseasonalises with annual harmonics and per-orbit
offsets, and scans for the best breakpoint per pixel.

**The good part:** Area under the ROC curve of 0.875 and 0.74 on held-out halves, against
0.50 for the model on the same footprints. That is the first non-zero discrimination anyone
here has achieved below 500 m².

**The part that failed:** Converting that into a city-scale unmapped-capacity number was
**rejected by its own control**. The method's estimate of unmapped area per built-up pixel sat
inside the false-area floor measured on two PV-free cropland control cubes, so nothing in its
totals block is quotable as capacity. What survives is the ranking: step-leads are defensible
as a lead ordering.

Two landmines are documented for anyone continuing: a propensity confound (the households
that install panels differ systematically from those that do not, in ways visible from space)
and duplicated Sentinel-2 baseline products that silently double-count dates.

## Deeper write-ups

These pages hold the full tables and derivations behind the rows above. Each one carries a
status banner stating where it now stands relative to the current pipeline, because several of
them were written before the thing they describe was replaced.

| Write-up | Subject |
| --- | --- |
| [Calibration boxes](issues/pakistan-calibration-boxes.md) | The running log of every ground-truth area, how each was mapped and what it changed |
| [roofclf national deployment and temporal features](issues/roofclf-national-deployment-and-temporal-features.md) | The first national scoring run, and the epoch-jump and step-change feature tests |
| [roofclf cell-edge false positives](issues/roofclf-cell-edge-false-positives.md) | Two compounding bugs that made 45.6% of national flags artifacts, and both fixes |
| [Quadrat-supervised fraction retrain](issues/quadrat-supervision-fraction-retrain.md) | The in-sample win, the holdout that did not support it, and the block bootstrap |
| [Fraction-head hard-negative retrain](issues/fraction-head-hard-negative-retrain.md) | A regime-specific win: better on large arrays, worse on dense small rooftops |
| [SPPI spectral index evaluation](issues/sppi-spectral-index-evaluation.md) | What SPPI can and cannot do, and why it is used only as a second opinion |
| [Boom-window stacking](issues/boom-window-stacking-experiment.md) | Why the 2021-versus-current retrain is inconclusive rather than negative |
| [Standard-pose matched filter](issues/standard-pose-matched-filter.md) | Assessed against real pose data and not recommended |
| [Glint PSF and matched filtering](issues/glint-psf-matched-filter.md) | The measured Sentinel-2 glint PSF, why filtering on it loses to the aperture statistic, and the verified-negative false-spike rate |
| [Glint spike-rate estimator](issues/glint-spike-rate-density-estimator.md) | Glint as a statistical density estimator, and the floor it hits |
| [Glint tile-batched coverage](issues/glint-tile-batched-coverage.md) | The 22x speedup, and the silent scene-loss bug it uncovered |
| [Glint-validated training labels](issues/glint-validated-training-labels.md) | A proposal to feed corroborated detections back as labels |
| [Quadrats as training data](issues/quadrats-as-training-data.md) | The proposal that became `roofclf` |
| [Calibration imagery dating](issues/calibration-imagery-dating.md) | Why ground-truth completeness is relative to an imagery date, and what closing that costs |
