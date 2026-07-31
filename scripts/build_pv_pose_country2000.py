"""Build results/glint_validation_pakistan/pv_pose_country2000.html -- the 2000-target
country-scale re-run of pv_pose_pakistan.html's fitted-orientation polar plot.

Thin wrapper around `earthpv.pose.build_pose_survey_page`, which holds the reusable
template and rendering logic (pulled out 2026-07-31 as part of the national-dashboard
library, so a second country's survey doesn't need its own copy of this script).

Usage: .pixi/envs/default/bin/python scripts/build_pv_pose_country2000.py
"""
from __future__ import annotations

from pathlib import Path

from earthpv.pose import build_pose_survey_page

SUMMARY = Path("data/glint/country2000_summary.csv")
OUT = Path("results/glint_validation_pakistan/pv_pose_country2000.html")


def main() -> None:
    build_pose_survey_page(
        SUMMARY, OUT, country="Pakistan",
        history_note="(a 4x-larger, chunked-tile-batch re-run of the original 500-target study)",
        data_note="(2000-target stratified country study, chunked tile-batch pull)",
    )


if __name__ == "__main__":
    main()
