"""Fail if an atlas template loses a feature, or gains a placeholder nothing substitutes.

Both failures are silent without this. A template that drops `__VALIDATION_BADGE__` simply
stops showing the calibration stamp on every atlas built afterwards, and nobody notices
until someone looks at a page. A template that GAINS a placeholder the builder does not
provide ships the literal `__NAME__` to readers. `atlas._assert_no_placeholders` catches the
second at build time, which is too late for a country whose atlas is rebuilt monthly; this
catches both in CI.

    pixi run python scripts/check_atlas_templates.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "src" / "earthpv" / "templates"
ATLAS = ROOT / "src" / "earthpv" / "atlas.py"

# What each SHIPPING template must carry. Anything absent here is not checked, so a
# template that is not published does not have to grow features it has no use for.
REQUIRED = {
    "pv_evidence_atlas.html": [
        ("__HEADER_LOGO__", "the EarthPV mark at the top"),
        ("__VALIDATION_BADGE__", "the calibration score stamp"),
        ("__DOWNLOAD_SECTION__", "the per-cell CSV and GeoParquet downloads"),
        ("comp-sizes", "the installation-size bands under the composition bar"),
        ('id="pv"', "the embedded per-cell data the downloads are built from"),
    ],
    "pv_growth_evidence_atlas.html": [
        ("__HEADER_LOGO__", "the EarthPV mark at the top"),
        ("__VALIDATION_BADGE__", "the calibration score stamp"),
        ("__DOWNLOAD_SECTION__", "the per-cell downloads"),
    ],
    "pv_atlas.html": [
        ("__HEADER_LOGO__", "the EarthPV mark at the top"),
        ("__VALIDATION_BADGE__", "the calibration score stamp"),
        ("__DOWNLOAD_SECTION__", "the per-cell downloads"),
    ],
}


def provided_keys(src: str) -> dict[str, set[str]]:
    """Placeholder keys each builder substitutes, keyed by the template constant it reads."""
    out: dict[str, set[str]] = {}
    lines = src.split("\n")
    for i, line in enumerate(lines):
        m = re.search(r"html = (\w+)\.read_text\(\)", line)
        if not m:
            continue
        const = m.group(1)
        keys = set()
        for l in lines[i:i + 200]:
            keys.update(re.findall(r'"(__[A-Z0-9_]+__)"\s*:', l))
            if re.match(r"^\s{4}\w", l) and "html" not in l and keys:
                break
        out.setdefault(const, set()).update(keys)
    return out


def const_for(template: str, src: str) -> str | None:
    m = re.search(r'(\w+TEMPLATE)\s*=\s*Path\(__file__\).*?"' + re.escape(template) + '"', src)
    return m.group(1) if m else None


def main() -> int:
    src = ATLAS.read_text()
    provided = provided_keys(src)
    problems: list[str] = []

    for name, wants in REQUIRED.items():
        path = TPL / name
        if not path.exists():
            problems.append(f"{name}: template is missing entirely")
            continue
        text = path.read_text()
        for token, why in wants:
            if token not in text:
                problems.append(f"{name}: lost {token} ({why})")

    # every placeholder a template uses must be substituted by the builder that reads it
    for path in sorted(TPL.glob("*.html")):
        tokens = set(re.findall(r"__[A-Z0-9_]+__", path.read_text()))
        if not tokens:
            continue
        const = const_for(path.name, src)
        if const is None:
            continue                      # template not wired to a builder; nothing to check
        have = provided.get(const, set())
        for t in sorted(tokens - have):
            problems.append(
                f"{path.name}: uses {t} but {const}'s builder never substitutes it, so the "
                f"literal text would ship to readers")

    if problems:
        print("Atlas template check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"atlas templates: {len(REQUIRED)} checked, all features present and every "
          f"placeholder substituted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
