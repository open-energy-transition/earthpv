#!/usr/bin/env python
"""Move published evidence atlases onto the current template without rebuilding them.

A template change used to reach the published pages in one of two ways: re-run
`earthpv atlas` for every country, which needs each country's full `data/` tree on disk and
re-reads inputs that may have moved since publication, so figures can change when only the
presentation was meant to; or hand-apply the same string edit to eleven pages, which is how
the Ember ceiling shipped (9fb3a29) and stops working the moment a change is larger than a
string.

This does neither. Every value the builder substituted into a page is recovered by
aligning the page against the template it was built from (`--old-template`, a git revision
or a file), checked by substituting it straight back and comparing the result to the page,
and then substituted into the current template. The data block, the badge, the prose and
the download section move across byte for byte, so **no figure can change**. Placeholders
the old template did not have are computed fresh from configuration only
(`__LAYERS_JSON__`, from `configs/atlas/<aoi>.yaml`; `__AOI_KEY__`, the AOI itself), never
from pipeline output.

    pixi run python scripts/retemplate_atlas.py docs/assets/interactive/*evidence_atlas.html
    pixi run python scripts/retemplate_atlas.py PAGE --old-template 9fb3a29 --dry-run

`--old-template` defaults to HEAD's copy of the template, i.e. the one the committed pages
were built from, which is right while the template change itself is still uncommitted.
Once it is committed, pass the revision the pages were last built from.

Alignment tolerates whitespace differences (a sync step that dropped a blank line), and
refuses a page whose round trip does not reproduce it, rather than guess.

`--new-template` (a git revision or a file) fills a template other than the working tree's,
so an uncommitted edit to it that is not ready to ship stays out of the pages.

`--refresh-prose REV` also rewrites the two prose blocks the builder writes from a page's
own numbers, `__CONFIDENCE_HTML__` and `__COMPOSITION_NOTE__`, with the current
`atlas._confidence_html` / `atlas._composition_note`. Their inputs are read back from the
page's data block and `configs/atlas/<aoi>.yaml`, and are trusted only if `atlas.py` at REV
(the builder the pages were made with) turns them into exactly the prose the page carries; a
page that fails that check keeps its prose and is reported. The figures are rounded to 0.1 in
the data block, so a value ending in .5 is tried just below and just above it.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path("src/earthpv/templates/pv_evidence_atlas.html")
PLACEHOLDER = re.compile(r"(__[A-Z0-9_]+__)")


def read_old_template(spec: str) -> str:
    if Path(spec).is_file():
        return Path(spec).read_text()
    return subprocess.run(["git", "show", f"{spec}:{TEMPLATE.as_posix()}"], cwd=ROOT,
                          check=True, capture_output=True, text=True).stdout


def _literal_pattern(literal: str) -> re.Pattern:
    """`literal` as a regex in which every run of whitespace matches any run, or none."""
    parts = re.split(r"\s+", literal)
    return re.compile(r"\s*".join(re.escape(p) for p in parts))


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def extract(template: str, page: str) -> dict[str, str]:
    """Recover each placeholder's value from a page built from `template`."""
    parts = PLACEHOLDER.split(template)
    literals, keys = parts[0::2], parts[1::2]
    m = _literal_pattern(literals[0]).match(page)
    if not m:
        raise ValueError("the page does not start the way the old template does")
    pos, values = m.end(), {}
    for key, nxt in zip(keys, literals[1:]):
        if not nxt.strip():
            raise ValueError(f"{key} is followed directly by another placeholder; "
                             "the template cannot be split unambiguously there")
        hit = _literal_pattern(nxt).search(page, pos)
        if not hit:
            raise ValueError(f"could not find the template text after {key}")
        value = page[pos:hit.start()]
        if key in values and _norm(values[key]) != _norm(value):
            raise ValueError(f"{key} has two different values in one page")
        values.setdefault(key, value)
        pos = hit.end()
    if page[pos:].strip():
        raise ValueError(f"{len(page) - pos} characters after the template's end")
    # The round trip: the old template filled with these values must BE the page.
    rebuilt = template
    for key, value in values.items():
        rebuilt = rebuilt.replace(key, value)
    if _norm(rebuilt) != _norm(page):
        raise ValueError("re-substituting the recovered values does not reproduce the page")
    return values


PROSE_KEYS = ("__CONFIDENCE_HTML__", "__COMPOSITION_NOTE__")


def builder_at(rev: str):
    """`earthpv.atlas` as it was at git revision `rev`, loaded beside the current one."""
    src = subprocess.run(["git", "show", f"{rev}:src/earthpv/atlas.py"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    path = Path(tempfile.mkdtemp()) / "atlas_at_rev.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("earthpv_atlas_at_rev", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rounding_candidates(v: float) -> list[float]:
    """Values the builder may have held for a figure stored rounded to 0.1."""
    return [v - 0.04, v + 0.04] if round(v * 10) % 10 == 5 else [v]


def prose(builder, cfg, data: dict, total_best: float, ci: list) -> dict[str, str]:
    """The two prose blocks `builder` writes for a page with this data block."""
    t = data["totals"]
    u = t["uncertainty"]
    kw = dict(
        total_best=total_best, best_ci=ci,
        has_extrapolation=int(t.get("n_extended_cells") or 0) > 0,
        has_quadrat_bootstrap=bool(u.get("coverage_bootstrap")),
        n_calib_boxes=t["n_calib_boxes"], n_calib_rule1=t["n_calib_rule1"],
        ground_interval=u.get("small_ground_interval", ""),
        roofclf_probability="probability" in (t.get("roofclf_weighting") or {}).values(),
        kwp_module_ci90=u.get("kwp_module_ci90"), kwp_land_ci90=u.get("kwp_land_ci90"),
        n_coverage_boot=next((b.get("n_boot") for b in (u.get("coverage_bootstrap") or {}).values()
                              if b.get("n_boot")), None),
    )
    accepted = inspect.signature(builder._confidence_html).parameters
    return {
        "__CONFIDENCE_HTML__": builder._confidence_html(
            cfg, **{k: v for k, v in kw.items() if k in accepted}),
        "__COMPOSITION_NOTE__": builder._composition_note(
            cfg, u["components"], u.get("best_floor_offset_mwp", 0.0), total_best),
    }


def refreshed_prose(old_builder, new_builder, cfg, values: dict) -> dict[str, str] | None:
    """New prose for a page, or None when the old builder cannot reproduce its current prose."""
    data = json.loads(values["__PV_DATA_JSON__"])
    t = data["totals"]
    best, (lo, hi) = t["mwp_best"], t["uncertainty"]["mwp_best_ci"]
    for b, ci_lo, ci_hi in itertools.product(*map(_rounding_candidates, (best, lo, hi))):
        old = prose(old_builder, cfg, data, b, [ci_lo, ci_hi])
        if all(_norm(old[k]) == _norm(values[k]) for k in PROSE_KEYS):
            return prose(new_builder, cfg, data, b, [ci_lo, ci_hi])
    return None


def aoi_of(page: Path) -> str:
    m = re.match(r"(.+?)_(?:pv_)?evidence_atlas\.html$", page.name)
    if not m:
        raise ValueError(f"cannot tell the AOI from {page.name}; pass --aoi")
    return m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", nargs="+", type=Path)
    ap.add_argument("--old-template", default="HEAD",
                    help="git revision (or a file) of the template the pages were built from")
    ap.add_argument("--new-template",
                    help="git revision (or a file) of the template to fill; default the working tree's")
    ap.add_argument("--refresh-prose", metavar="REV",
                    help="rewrite the confidence and composition prose with the current builder, "
                         "checked against atlas.py at REV (the builder the pages were made with)")
    ap.add_argument("--aoi", help="AOI for a single page whose name does not carry it")
    ap.add_argument("--dry-run", action="store_true", help="check every page, write none")
    args = ap.parse_args()

    os.chdir(ROOT)  # configs/atlas/ and layer `path`s are repository-relative
    sys.path.insert(0, str(ROOT / "src"))
    from earthpv import atlas, atlas_config

    old = read_old_template(args.old_template)
    new = read_old_template(args.new_template) if args.new_template else TEMPLATE.read_text()
    old_builder = builder_at(args.refresh_prose) if args.refresh_prose else None
    new_keys = set(PLACEHOLDER.findall(new))
    failed = 0
    for page in args.pages:
        try:
            values = extract(old, page.read_text())
            aoi = args.aoi or aoi_of(page)
            fresh = {"__LAYERS_JSON__": lambda: atlas.map_layers_json(aoi),
                     "__AOI_KEY__": lambda: aoi}
            prose_note = ""
            if old_builder is not None:
                new_prose = refreshed_prose(old_builder, atlas, atlas_config.load(aoi), values)
                if new_prose is None:
                    prose_note = " (prose kept: the old builder does not reproduce it)"
                else:
                    values = {**values, **new_prose}
                    prose_note = " (prose refreshed)"
            html = new
            for key in sorted(new_keys):
                if key in values:
                    value = values[key]
                elif key in fresh:
                    value = fresh[key]()
                else:
                    raise ValueError(f"the new template needs {key}, which the old page does not "
                                     "carry and this script cannot compute; rebuild with "
                                     "`earthpv atlas` instead")
                html = html.replace(key, value)
            html = atlas._assert_no_placeholders(html, page.name)
        except Exception as err:  # noqa: BLE001 - report every page, then fail
            failed += 1
            print(f"  FAIL {page}: {err}")
            continue
        dropped = sorted(set(values) - new_keys)
        note = f" (dropped {', '.join(dropped)})" if dropped else ""
        if not args.dry_run:
            page.write_text(html)
        print(f"  {'checked' if args.dry_run else 'wrote'} {page} [{aoi}]{note}{prose_note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
