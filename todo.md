1. Estimate density per village and validated routhly using JOSM and a unit sized bounding box as polygon for the size of the density estimation.
2. Check glint against skyfield.

3. Rename to SentiPV
5. ~~Replace detected polygons for already mapped OSM data with the OSM polygon.~~
   DONE 2026-07-29 — `postprocess.replace_with_osm_geometry`, on by default
   (`--osm-replace`). Ran on pakistan: 2,022/6,566 candidates (30.8%) now carry the real
   OSM footprint; oversize-flagged count dropped 233 -> 149. Note: replacement geometry
   is only as current as the OSM mapper's own imagery (`osm_match_timestamp` now
   captured for auditability, not filtering) — acquiring fresher ground truth for stale
   matches is future work. See `docs/issues/osm-replacement-and-sppi-capacity.md`.
6. Glint: Level-1C is generally preferable, together with the saturation-quality mask
7. Before you start: find the mappers --> Train the mappers
8. Glint examples improvement.
9. Make labeled data another layer.
10. Show glint more on the landing of all pages.
11. Remove pose mirrow
12. ~~Expand glint by and Test: https://www.sciencedirect.com/science/article/pii/S1569843226000804~~
    TESTED 2026-07-29 (SPPI index, He et al. 2026) — see
    `docs/issues/sppi-spectral-index-evaluation.md` (per-building signal, complementary
    to our detectors) and `docs/issues/osm-replacement-and-sppi-capacity.md` (building-
    scoped capacity-contribution attempt: works for 7/9 quadrats at precision-targeted
    threshold, median precision 0.524, but NOT safe nationally yet — still 10.5%
    precision in the arid quadrat and the pooled threshold doesn't transfer to Mardan).
    Not adopted for detection or capacity; `earthpv.sppi` module + `scripts/sppi_capacity
    _validation.py` kept for the next quadrat batch.
13. Validate assumption that large scale follows small scale. 
14. Show improvements of label counts. How many more labels are take for Pakistan for the recall statistics?
15. Plot glint gallery to validate and check for clouds. 
16. Improve building dataset.
17. Consider the distance between polygons for the evaluation.
18. Load calibration polygons/labels into JOSM for validation.
19. Try nightlights as national density regime proxy.
20. Validate false postives for >500m² with SPPI. 


