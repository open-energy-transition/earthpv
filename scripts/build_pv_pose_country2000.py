"""Build results/glint_validation_pakistan/pv_pose_country2000.html -- the fitted-
orientation polar plot, tilt/azimuth histograms, and validation-rate strip chart.

Output path and filename are unchanged from the original 2000-target country-scale
study (kept for stability -- `scripts/build_docs_figures.py` and `docs/results/
pv-pose.md` both point at it), but the SOURCE is now `pakistan_combined_summary.csv`
(2026-08-14): the original 2,000 size-stratified targets plus 401 more from a targeted
random top-up of the latitude bands/provinces `scripts/glint_pose_by_region.py` found
too thin to trust (`scripts/glint_orientation_region_topup.py`,
`docs/methods/glint.md`). Same fetch mechanism, same date range, so the two pulls are
directly poolable -- this page's fitted-tilt/azimuth population is now the full 2,401,
not just the original 2,000.

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
            "plus a 2026-08-14 targeted random top-up of 401 more targets concentrated "
            "in the latitude bands/provinces a regional re-cut found too thin to trust)"
        ),
        data_note="(2,401-target country study: 2,000 size-stratified + 401 targeted regional top-up, chunked tile-batch pull)",
    )


if __name__ == "__main__":
    main()
