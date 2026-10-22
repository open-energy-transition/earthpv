"""Build results/glint_validation_pakistan/pv_pose_country2000.html -- the fitted-
orientation polar plot, tilt/azimuth histograms, and validation-rate strip chart.

Output path and filename are unchanged from the original 2000-target country-scale
study (kept for stability -- `scripts/build_docs_figures.py` and `docs/results/
pv-pose.md` both point at it), but the SOURCE is now `pakistan_combined_summary.csv`:
the original 2,000 size-stratified targets plus two targeted random top-ups of the
latitude bands/provinces `scripts/glint_pose_by_region.py` found too thin to trust (401
from `scripts/glint_orientation_region_topup.py`, 2026-08-14, and 442 from
`scripts/glint_orientation_region_topup2.py`, merged the same night). Same fetch
mechanism, same date range, so the three pulls are directly poolable: 2,843 targets.

Rebuilt 2026-10-22 after the duplicate-acquisition fix (`glint.one_row_per_acquisition`,
applied inside `annotate_spikes`). Overlapping MGRS tiles deliver copies of one
acquisition, and a glint seen in two copies had counted as two consistent dates: 10 of
the 346 fits rested on that and are gone (336). The page had last been built at 2,401
targets, before the second top-up was merged, so it also gains those 442 targets now.

Thin wrapper around `earthpv.pose.build_pose_survey_page`, which holds the reusable
template and rendering logic (pulled out 2026-07-31 as part of the national-dashboard
library, so a second country's survey doesn't need its own copy of this script).

Usage: .pixi/envs/default/bin/python scripts/build_pv_pose_country2000.py
"""
from __future__ import annotations

from pathlib import Path

from earthpv.pose import build_pose_survey_page

SUMMARY = Path("data/glint/pakistan_combined_summary.csv")
OUT = Path("results/glint_validation_pakistan/pv_pose_country2000.html")


def main() -> None:
    build_pose_survey_page(
        SUMMARY, OUT, country="Pakistan",
        history_note=(
            "(a 4x-larger, chunked-tile-batch re-run of the original 500-target study, "
            "plus two targeted random top-ups, 843 targets in all, concentrated in the "
            "latitude bands/provinces a regional re-cut found too thin to trust)"
        ),
        data_note=("(2,843-target country study: 2,000 size-stratified + 401 + 442 targeted "
                   "regional top-up, chunked tile-batch pull; tile copies of one acquisition "
                   "counted once since 2026-10-22)"),
    )


if __name__ == "__main__":
    main()
