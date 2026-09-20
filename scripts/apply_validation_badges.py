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

import json

from earthpv.atlas import (CELL_COLS_EVIDENCE, CELL_COLS_GROWTH,
                           CELL_COLS_GROWTH_EVIDENCE, derive_validation_score,
                           download_section_html, header_logo_html,
                           validation_badge_html, write_cell_geoparquet)

# A published page predates `cell_cols`, so the CSV export has no header to write. Recover
# it from the column count, which identifies the schema unambiguously across these atlases.
CELL_SCHEMAS = {len(c): c for c in (CELL_COLS_EVIDENCE, CELL_COLS_GROWTH_EVIDENCE,
                                    CELL_COLS_GROWTH)}

PUBLISHED = Path("docs/assets/interactive")

# (published name, AOI, canonical source).
#
# **Stamping only the docs/ copy is not enough, and that was a real bug.** Most of these
# pages are SYNCED into docs/assets/interactive/ from results/ or data/ by
# build_docs_figures.py's INTERACTIVE list, so a `pixi run docs-figures` copies the
# unstamped original straight over the stamped copy and the badge silently disappears --
# which is exactly what happened to France, Germany and Zambia. Stamp the SOURCE, and the
# docs copy as well for the pages that have no separate source.
PAGES = [
    # canonical in docs/ (no results/ original -- see the atlas module's own note)
    ("pakistan_evidence_atlas.html", "pakistan", None),
    ("gujarat_pv_atlas.html", "gujarat", None),
    # synced from elsewhere: the source is what must carry the stamp
    ("germany_pv_evidence_atlas.html", "germany",
     Path("data/predictions/germany/density/germany_pv_evidence_atlas.html")),
    ("france_pv_evidence_atlas.html", "france",
     Path("results/france_pv_evidence_atlas.html")),
    ("france_pv_comparison_atlas.html", "france",
     Path("results/france_pv_comparison_atlas.html")),
    ("zambia_pv_evidence_atlas.html", "zambia",
     Path("results/zambia_pv_evidence_atlas.html")),
    ("pakistan_growth_atlas.html", "pakistan",
     Path("results/pakistan_pv_growth_atlas.html")),
]

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
# The strapline at the very top ("EarthPV - Sentinel-2 - OpenStreetMap - ..."), replaced by
# the logo mark.
EYEBROW = re.compile(r'\s*<(p|div) class="eyebrow">.*?</\1>\n?', re.S)
OLD_LOGO = re.compile(r'\s*<style>\.brandmark.*?</style><div class="brandmark".*?</div>\n?',
                      re.S)
# Matched ONLY between its own comment markers. An earlier version anchored on
# `<section class="sec" id="downloads">` and ended at the next `</script>`, which collided
# with the data-release Downloads section the evidence template already carries and
# swallowed 44 KB of every page, including the main render script. Never anchor a
# destructive regex on markup you do not own.
OLD_DOWNLOAD = re.compile(
    r'\s*<!-- earthpv:cellcsv:start -->.*?<!-- earthpv:cellcsv:end -->\n?', re.S)
PV_JSON = re.compile(r'(<script id="pv" type="application/json">)(.*?)(</script>)', re.S)
# The out-of-domain extrapolation was dropped from the published atlas in August 2026, so
# this legend toggle points at an overlay no page still draws. wireKeyToggles already skips
# a missing button, so removing the markup is safe.
EXTRAP_KEY = re.compile(
    r'\n\s*<button type="button" class="extended-key key-toggle" id="extendedKey".*?</button>',
    re.S)


# The dev-note and the lede are the only things stamping deliberately DELETES, and together
# they are a couple of kilobytes. Anything bigger means a regex ate page content.
MAX_SHRINK_BYTES = 6000


def _guard_size(before: str, after: str, path: Path) -> None:
    lost = len(before) - len(after)
    if lost > MAX_SHRINK_BYTES:
        raise SystemExit(
            f"REFUSING to write {path}: stamping removed {lost:,} bytes, far more than the "
            f"dev-note and lede it is allowed to drop. A regex has eaten page content; "
            f"fix it rather than committing this."
        )


def add_downloads(html: str, aoi: str, out_path: Path) -> str:
    """Give an already-published page the per-cell CSV export.

    Two steps, because a page built before this feature has the data but not its column
    names: recover `cell_cols` from the width of the embedded rows, then append the
    section. Pages with no embedded `cells` (a comparison page, a registry) are left alone.
    """
    html = OLD_DOWNLOAD.sub("\n", html)      # re-appliable
    m = PV_JSON.search(html)
    if not m:
        return html
    try:
        data = json.loads(m.group(2))
    except ValueError:
        return html
    rows = data.get("cells") or []
    if not rows:
        return html
    if "cell_cols" not in data:
        cols = CELL_SCHEMAS.get(len(rows[0]))
        if not cols:
            return html          # unknown schema: better no CSV than a mislabelled one
        data["cell_cols"] = cols
        html = (html[:m.start()] + m.group(1)
                + json.dumps(data, separators=(",", ":")) + m.group(3) + html[m.end():])
    # GeoParquet is a real file, not something the browser can build, so write it beside
    # the page being stamped. Same stem, so the relative link resolves for the published
    # copy and for the source alike.
    pq = write_cell_geoparquet(rows, data.get("cell_cols") or [], out_path)
    foot = re.search(r'\n(\s*)<div class="foot"', html)
    section = "\n  " + download_section_html(aoi, pq.name if pq else "") + "\n"
    if foot:
        return html[:foot.start()] + section + html[foot.start() + 1:]
    return html + section


def stamp(path: Path, score: str, aoi: str = "atlas",
          drop_lede: bool = True) -> tuple[bool, str]:
    html = path.read_text()
    before = html
    html = OLD_BADGE.sub("\n", html)          # re-stampable
    html = OLD_LOGO.sub("\n", html)
    if drop_lede:
        html = LEDE.sub("\n", html)
    # Top strapline out, logo mark in. Anchored on the <h1> rather than on the eyebrow it
    # replaces, so a SECOND run -- where the eyebrow is already gone -- still re-inserts
    # the logo instead of quietly dropping it.
    html = EYEBROW.sub("\n", html, count=1)
    m_h1 = re.search(r'([ \t]*)<h1>', html)
    if m_h1:
        indent = m_h1.group(1)
        html = (html[:m_h1.start()] + f"{indent}{header_logo_html()}\n"
                + html[m_h1.start():])
    badge = validation_badge_html(score)
    note = "re-stamped" if before != html and "vscore" in before else "stamped"
    html = EXTRAP_KEY.sub("", html, count=1)
    html = add_downloads(html, aoi, path)
    if DEV_NOTE.search(html):
        out = DEV_NOTE.sub(f"    {badge}\n", html, count=1)
        _guard_size(before, out, path)
        path.write_text(out)
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
    for name, aoi, source in PAGES:
        score = SCORES.get(aoi) or derive_validation_score(aoi, False)
        # The source first, so a later docs-figures sync carries the stamp rather than
        # reverting it; then the published copy, so the site is right immediately.
        targets = [t for t in (source, PUBLISHED / name) if t and t.exists()]
        if not targets:
            print(f"{name:46} {aoi:9} {score:7} no source and no published copy, skipped")
            continue
        for path in targets:
            where = "source" if path is source else "docs  "
            if not args.write:
                state = "re-stamp" if "vscore" in path.read_text() else "stamp"
                print(f"{name:46} {aoi:9} {score:7} {where} would {state}")
                continue
            changed, why = stamp(path, score, aoi=aoi)
            print(f"{name:46} {aoi:9} {score:7} {where} "
                  f"{'OK  ' if changed else 'skip'} {why}")


if __name__ == "__main__":
    main()
