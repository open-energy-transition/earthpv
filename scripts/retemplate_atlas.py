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
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
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
    ap.add_argument("--aoi", help="AOI for a single page whose name does not carry it")
    ap.add_argument("--dry-run", action="store_true", help="check every page, write none")
    args = ap.parse_args()

    os.chdir(ROOT)  # configs/atlas/ and layer `path`s are repository-relative
    sys.path.insert(0, str(ROOT / "src"))
    from earthpv import atlas

    old = read_old_template(args.old_template)
    new = TEMPLATE.read_text()
    new_keys = set(PLACEHOLDER.findall(new))
    failed = 0
    for page in args.pages:
        try:
            values = extract(old, page.read_text())
            aoi = args.aoi or aoi_of(page)
            fresh = {"__LAYERS_JSON__": lambda: atlas.map_layers_json(aoi),
                     "__AOI_KEY__": lambda: aoi}
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
        print(f"  {'checked' if args.dry_run else 'wrote'} {page} [{aoi}]{note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
