"""Stamp the EarthPV Validation Score badge into already-published atlas pages.

The badge reaches new atlases through the templates, but a page only picks it up when it
is REGENERATED, and regenerating a country's atlas recomputes its published numbers and
needs that country's data on disk. This stamps the badge into the HTML instead: no
recomputation, no data required, and idempotent, so it is safe to re-run and harmless once
a page has been regenerated properly.

    pixi run python scripts/apply_validation_badges.py            # report only
    pixi run python scripts/apply_validation_badges.py --write
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from earthpv.atlas import derive_validation_score, validation_badge_html

PUBLISHED = Path("docs/assets/interactive")

# Which AOI a published page belongs to. Anything not listed is skipped rather than guessed.
PAGE_AOI = {
    "pakistan_evidence_atlas.html": "pakistan",
    "germany_pv_evidence_atlas.html": "germany",
    "france_pv_evidence_atlas.html": "france",
    "zambia_pv_evidence_atlas.html": "zambia",
    "gujarat_pv_atlas.html": "gujarat",
    "pakistan_growth_atlas.html": "pakistan",
    "france_pv_comparison_atlas.html": "france",
}

# Explicit tiers, because the derivation reads the CURRENT state of data/ and a page
# published months ago should carry the score its evidence earned, not whatever happens to
# be on this machine today. Germany is the judgement case the --validation-score flag
# exists for: its sub-400 half is calibrated from the MaStR register rather than from
# mapped quadrats, and its Best estimate still fails its own register check.
SCORES = {
    "pakistan": "gold",     # 30 Rule-1 mapped areas, calibrated sub-400 half
    "germany": "gold",      # sub-400 half, register-calibrated; see note above
    "france": "silver",     # 14 hand-mapped communes, no calibrated sub-400 half
    "zambia": "bronze",     # segmentation only, no local ground truth
    "gujarat": "bronze",    # segmentation only, no calibration quadrats
}

DEV_NOTE = re.compile(
    r'<p class="dev-note"><b>Active development\.</b>.*?</p>\n?', re.S)
AFTER_H1 = re.compile(r'(<h1>[^<]*</h1>\n)')
# An already-stamped badge, so a design change can be re-applied instead of skipped.
OLD_BADGE = re.compile(r'\s*<style>\s*(?:header \{ position: relative; \}\s*)?\.vscore.*?'
                       r'</(?:a|div)>\n?', re.S)
# The long intro paragraph these pages carry under the title. The evidence atlases lost
# their equivalent when the "Active development" note went; this is the same block on the
# atlases that never had that note.
LEDE = re.compile(r'\s*<p class="lede">.*?</p>\n?', re.S)


def stamp(path: Path, score: str, drop_lede: bool = True) -> tuple[bool, str]:
    html = path.read_text()
    before = html
    html = OLD_BADGE.sub("\n", html)          # re-stampable
    if drop_lede:
        html = LEDE.sub("\n", html)
    badge = validation_badge_html(score)
    note = "re-stamped" if before != html and "vscore" in before else "stamped"
    if DEV_NOTE.search(html):
        path.write_text(DEV_NOTE.sub(f"    {badge}\n", html, count=1))
        return True, f"{note}, replaced the dev-note"
    m = AFTER_H1.search(html)
    if not m:
        return False, "no dev-note and no <h1> to anchor to"
    path.write_text(html[:m.end()] + f"    {badge}\n" + html[m.end():])
    return True, f"{note} after the <h1>"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="apply; otherwise report only")
    args = ap.parse_args()
    for name in sorted(PAGE_AOI):
        path = PUBLISHED / name
        if not path.exists():
            print(f"{name:46} missing, skipped")
            continue
        aoi = PAGE_AOI[name]
        score = SCORES.get(aoi) or derive_validation_score(aoi, False)
        if not args.write:
            state = "would re-stamp" if "vscore" in path.read_text() else "would stamp"
            print(f"{name:46} {aoi:9} {score:7} {state}")
            continue
        changed, why = stamp(path, score)
        print(f"{name:46} {aoi:9} {score:7} {'OK  ' if changed else 'skip'} {why}")


if __name__ == "__main__":
    main()
