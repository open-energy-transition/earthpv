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
        ("__COMPOSITION_NOTE__", "the per-country composition sentence"),
        ('id="pv"', "the embedded per-cell data the downloads are built from"),
        ("__LAYERS_JSON__", "the per-country extra map layers (configs/atlas/<aoi>.yaml)"),
        ('class="dlbar"', "the PNG/SVG/CSV download buttons on each figure"),
        ("__AOI_KEY__", "the key the page fetches its published calibration areas by"),
        ("calib-hit", "the click target that opens a calibration area in JOSM or iD"),
        ("farm-dot", "the farm calibration area's own (green) marker, apart from building areas"),
        ('id="references"', "the comparison with official and published figures and Ember imports"),
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



# Every AOI whose atlas is published, and the display name a reader would recognise it by.
# A country's page must not name another country in its own prose -- the failure this check
# exists for shipped Pakistan's NEPRA corroboration on the German, French and Zambian
# atlases for weeks, and nothing in the build noticed.
PUBLISHED = {
    "pakistan_evidence_atlas.html": ("pakistan", "Pakistan"),
    "germany_pv_evidence_atlas.html": ("germany", "Germany"),
    "france_pv_evidence_atlas.html": ("france", "France"),
    "zambia_pv_evidence_atlas.html": ("zambia", "Zambia"),
    # Nigeria was published 2026-09-23 without an entry here, which left its page
    # unguarded; Vietnam and India are registered before their pages exist (a missing
    # page is skipped, so this is safe to land first).
    "nigeria_pv_evidence_atlas.html": ("nigeria", "Nigeria"),
    "vietnam_pv_evidence_atlas.html": ("vietnam", "Vietnam"),
    "india_pv_evidence_atlas.html": ("india", "India"),
    # The 2026-10-10 run, registered before the pages exist like Vietnam and India.
    "morocco_pv_evidence_atlas.html": ("morocco", "Morocco"),
    "egypt_pv_evidence_atlas.html": ("egypt", "Egypt"),
    "yemen_pv_evidence_atlas.html": ("yemen", "Yemen"),
    "south_africa_pv_evidence_atlas.html": ("south_africa", "South Africa"),
    # 2026-10-19, registered before its page exists.
    "poland_pv_evidence_atlas.html": ("poland", "Poland"),
    "namibia_pv_evidence_atlas.html": ("namibia", "Namibia"),
}


def _visible_text(html: str) -> str:
    """Body text only: scripts, styles and comments carry cross-country references on
    purpose (a JS comment explaining a label-collision fix cites Lahore and Karachi) and
    are not what a reader sees."""
    out = re.sub(r"(?s)<script.*?</script>", " ", html)
    out = re.sub(r"(?s)<style.*?</style>", " ", out)
    out = re.sub(r"(?s)<!--.*?-->", " ", out)
    return out


def check_published_atlases(problems: list[str]) -> None:
    """No published atlas may name another country, or link another country's pages.

    A country's OWN `configs/atlas/<aoi>.yaml` is exempt: Germany's page compares its
    municipal error to Pakistan's on purpose, and France's explains why the classifier
    that carries Pakistan's estimate does not carry its own. That is a deliberate,
    reviewed comparison written for that page. What this checks is the text the BUILDER
    emits, which is the same strings for every country and therefore must name none.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from earthpv import atlas_config

    pub = ROOT / "docs" / "assets" / "interactive"
    others = {name: [o for k, (_, o) in PUBLISHED.items() if k != name]
              for name in PUBLISHED}
    for name, (aoi, _) in PUBLISHED.items():
        path = pub / name
        if not path.exists():
            continue                      # not every AOI is published in every checkout
        html = path.read_text()
        text = _visible_text(html)
        cfg = atlas_config.load(aoi, ROOT / "configs" / "atlas")
        for supplied in (cfg.ground_truth, cfg.corroboration, *cfg.caveats):
            text = text.replace(supplied, " ")
        for other in others[name]:
            if other in text:
                problems.append(
                    f"{name}: its visible text names {other}, which is another country's "
                    f"atlas. Country-specific prose belongs in configs/atlas/{aoi}.yaml.")
        # a link to another country's page is just as wrong, and survives in raw HTML
        for link_aoi in (a for k, (a, _) in PUBLISHED.items() if a != aoi):
            if f'href="{link_aoi}_' in html:
                problems.append(f"{name}: links to a {link_aoi} page "
                                f"(set `composition_page` in configs/atlas/{aoi}.yaml)")


def check_atlas_configs(problems: list[str]) -> None:
    """Every configs/atlas/*.yaml parses, and none of its prose was mangled by wrapping.

    A YAML folded scalar (`>-`) joins its lines with a space, so a line break placed mid
    word -- which `textwrap` will happily do on a hyphen -- ships as "recent- enough" to
    every reader of that page.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from earthpv import atlas_config

    for path in sorted((ROOT / "configs" / "atlas").glob("*.yaml")):
        try:
            cfg = atlas_config.load(path.stem, ROOT / "configs" / "atlas")
        except Exception as exc:                            # noqa: BLE001 - report, don't raise
            problems.append(f"configs/atlas/{path.name}: {exc}")
            continue
        prose = [cfg.ground_truth, cfg.corroboration, *cfg.caveats]
        for text in prose:
            m = re.search(r"[a-z]- [a-z]", text)
            if m:
                problems.append(
                    f"configs/atlas/{path.name}: a word is split across a folded line "
                    f"(...{text[max(0, m.start() - 30):m.end() + 30]}...)")


def check_calibration_areas(problems: list[str]) -> None:
    """The published boundary files the atlas's editor buttons load are complete and safe.

    They are committed output of `scripts/publish_calibration_areas.py`, which CI cannot
    re-run (data/ is gitignored), so a config box added without re-publishing would give
    a calibration area whose JOSM button imports nothing. Each file must also be one
    polygon carrying `do_not_upload`, the tag a mapper sees in JOSM on the boundary layer.
    """
    sys.path.insert(0, str(ROOT / "src"))
    import json

    from earthpv import atlas_config

    out = ROOT / "docs" / "assets" / "labels" / "calibration_areas"
    for path in sorted((ROOT / "configs" / "atlas").glob("*.yaml")):
        aoi = path.stem
        index = out / f"{aoi}.geojson"
        if not index.exists():
            problems.append(f"{index.relative_to(ROOT)} is missing; run `pixi run calib-publish`")
            continue
        feats = json.loads(index.read_text()).get("features", [])
        ids = {f["properties"]["id"] for f in feats}
        listed = {f["properties"]["id"] for f in feats if f["properties"].get("kind") == "calibration"}
        cfg = atlas_config.load(aoi, ROOT / "configs" / "atlas")
        for box in cfg.calibration_boxes:
            if box["stem"] not in listed:
                problems.append(f"{index.relative_to(ROOT)}: no published boundary for configured box "
                                f"{box['stem']!r}; run `pixi run calib-publish`")
        files = {p.stem for p in (out / aoi).glob("*.geojson")} if (out / aoi).is_dir() else set()
        for stem in sorted(files ^ ids):
            problems.append(f"calibration_areas/{aoi}: {stem!r} is in only one of the index and the "
                            "per-area files; run `pixi run calib-publish`")
        for stem in sorted(files & ids):
            one = json.loads((out / aoi / f"{stem}.geojson").read_text()).get("features", [])
            ok = (len(one) == 1 and one[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
                  and one[0]["properties"].get("do_not_upload") and one[0]["properties"]["id"] == stem)
            if not ok:
                problems.append(f"calibration_areas/{aoi}/{stem}.geojson: must be exactly one polygon "
                                "with its own id and a do_not_upload property")


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

    check_atlas_configs(problems)
    check_published_atlases(problems)
    check_calibration_areas(problems)

    if problems:
        print("Atlas template check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    n_cfg = len(list((ROOT / "configs" / "atlas").glob("*.yaml")))
    n_pub = sum(1 for n in PUBLISHED if (ROOT / "docs/assets/interactive" / n).exists())
    print(f"atlas templates: {len(REQUIRED)} checked, all features present and every "
          f"placeholder substituted; {n_cfg} AOI configs valid; {n_pub} published atlases "
          f"carry no other country's text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
