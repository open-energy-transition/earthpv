"""Write every docs/atlas*.md page from one table, grouped into calibration tiers.

The PV Atlas pages are full-bleed wrappers around each country's interactive evidence
atlas, with a country switcher on top (the pages hide the left navigation, so the
switcher is the only way across). Writing them by hand meant adding a switcher line to
every page for every new country. This writes them all, so a new country is one row in
ATLASES.

**Tiers, by calibration status** (owner request 2026-10-19). A page's tier is read from
the calibration badge its own atlas carries (`atlas.VALIDATION_TIERS`, set by
`derive_validation_score` or `--validation-score` when the atlas is built), so the switcher,
the navigation and the badge on the map cannot disagree:

- **Gold**: installations above and below the 400 m2 floor, the small half calibrated on
  areas mapped panel by panel (Pakistan). Germany's register-calibrated half would qualify
  on paper, but fails its own register check, so it is Silver (`configs/atlas/germany.yaml`).
- **Silver**: 400 m2 and up only, validated against local hand-mapped ground truth; no
  calibrated estimate below the floor.
- **Bronze**: 400 m2 and up only, with no local calibration.

Silver and Bronze pages open with a warning that smaller installations are missing, what a
reader can do about it, and links into the Contribute Data section (docs/contribute/).

    python scripts/build_atlas_pages.py          # rewrites docs/atlas*.md
    python scripts/build_atlas_pages.py --nav    # also prints the mkdocs.yml nav block
    # Paste only the PV Atlas block over the old one: other nav sections may follow it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

TIERS = {
    "gold": ("Gold", "Installations above and below the 400 m2 floor, calibrated on ground truth or a register"),
    "silver": ("Silver", "400 m2 and up only, validated against local ground truth"),
    "bronze": ("Bronze", "400 m2 and up only, not yet calibrated"),
}

# (page stem, country, interactive file, iframe title, country-specific warning line)
ATLASES = [
    ("atlas", "Pakistan", "pakistan_evidence_atlas.html",
     "Pakistan PV evidence atlas: best estimate by 0.1-degree cell", ""),
    ("atlas-germany", "Germany", "germany_pv_evidence_atlas.html", None, ""),
    ("atlas-france", "France", "france_pv_evidence_atlas.html", None,
     "A French household array is about 20 m&sup2;, a fifth of a Sentinel-2 pixel, so "
     "every figure here is a floor."),
    ("atlas-egypt", "Egypt", "egypt_pv_evidence_atlas.html", None, ""),
    ("atlas-india", "India", "india_pv_evidence_atlas.html", None, ""),
    ("atlas-morocco", "Morocco", "morocco_pv_evidence_atlas.html", None, ""),
    ("atlas-nigeria", "Nigeria", "nigeria_pv_evidence_atlas.html", None, ""),
    ("atlas-poland", "Poland", "poland_pv_evidence_atlas.html", None, ""),
    ("atlas-south-africa", "South Africa", "south_africa_pv_evidence_atlas.html", None, ""),
    ("atlas-vietnam", "Vietnam", "vietnam_pv_evidence_atlas.html", None, ""),
    ("atlas-yemen", "Yemen", "yemen_pv_evidence_atlas.html", None, ""),
    ("atlas-zambia", "Zambia", "zambia_pv_evidence_atlas.html", None, ""),
]


def tier_of(html: str) -> str:
    """The tier the atlas's own calibration badge shows."""
    import re

    text = (DOCS / "assets" / "interactive" / html).read_text()
    m = re.search(r'class="vscore-tier">(Gold|Silver|Bronze)<', text)
    if not m:
        raise SystemExit(f"{html}: no calibration badge found; rebuild the atlas first")
    return m.group(1).lower()

WARNING = {
    "silver": (
        "<strong>Silver atlas: smaller installations are missing.</strong> Installations of "
        "about 400 m&sup2; (70 kWp) and up are validated against hand-mapped ground truth; "
        "below that, where household rooftops sit, there is no calibrated estimate. {extra}"
    ),
    "bronze": (
        "<strong>Bronze atlas: smaller installations are missing.</strong> Only mapped "
        "installations and arrays the model outlines, about 400 m&sup2; (70 kWp) and up, are "
        "counted, so read every figure as a floor."
    ),
}
# A country whose reason for its tier is not the generic one (its tier is set in
# configs/atlas/<aoi>.yaml `validation`). Replaces WARNING and HELP for that page.
# Kept short (owner request 2026-10-24: the banner at half its former length); the
# atlas's own confidence section carries the detail.
TIER_NOTE = {
    "Germany": (
        "<strong>Silver atlas: the small-installation estimate is not yet validated.</strong> "
        "Arrays of about 400 m&sup2; and up are checked against Germany's register (MaStR). "
        "The estimate below that misses the register's municipal totals by about half, and "
        "Best sits above the ~75 GWp registered: read the map as where capacity sits.",
        "<strong>You can help:</strong> a few areas mapped panel by panel would check the "
        "small-installation geography directly.",
    ),
    # Silver by the owner's decision (2026-10-23), kept 2026-10-24 when farm areas began
    # calibrating farm ground PV: household rooftops below 400 m2 are still unmeasured.
    "Yemen": (
        "<strong>Silver atlas: farm solar is calibrated, household rooftops are not.</strong> "
        "Installations of about 400 m&sup2; (70 kWp) and up are counted, plus small "
        "solar-irrigation arrays calibrated on hand-mapped farm areas. Small rooftop systems "
        "are not estimated yet, so read the rooftop figures as a floor.",
        "<strong>You can help:</strong> map every panel inside a hollow diamond. Building "
        "areas calibrate rooftops; farm areas widen the farm estimate.",
    ),
}
# What a reader can do about it: the Contribute Data section (docs/contribute/).
HELP = {
    "silver": (
        "<strong>You can help:</strong> small areas mapped completely, panel by panel, in "
        "OpenStreetMap are what an estimate of the smaller installations is fitted on."
    ),
    "bronze": (
        "<strong>You can change that:</strong> map every panel inside a hollow diamond on the "
        "map, starting with the <strong>&#9733; star</strong>. Six to ten complete areas start "
        "an estimate of {country}'s smaller installations."
    ),
}
CTA = (
    '<a class="atlas-tier-cta" href="../contribute/">Contribute data: map a calibration '
    'area &rarr;</a> <a class="atlas-tier-more" href="../contribute/id/">In the browser '
    '(iD)</a> <a class="atlas-tier-more" href="../contribute/josm/">With JOSM</a>'
)


def _href(stem: str) -> str:
    return f"../{stem}/"


def switcher(current: str) -> str:
    lines = ['<nav class="atlas-switch" aria-label="Choose a country atlas">',
             '  <span class="atlas-switch__label">Atlas</span>']
    for tier, (label, desc) in TIERS.items():
        lines.append(f'  <span class="atlas-switch__tier atlas-switch__tier--{tier}" '
                     f'title="{desc}">{label}</span>')
        for stem, country, html, *_ in ATLASES:
            if tier_of(html) != tier:
                continue
            if stem == current:
                lines.append(f'  <span aria-current="page">{country}</span>')
            else:
                lines.append(f'  <a href="{_href(stem)}">{country}</a>')
    lines.append("</nav>")
    return "\n".join(lines)


def page(stem: str, country: str, html: str, title: str | None, extra: str) -> str:
    tier = tier_of(html)
    title = title or f"{country} PV evidence atlas: verified and best estimate by 0.1-degree cell"
    parts = ["---", f'title: "EarthPV: {country}"', "hide:", "  - navigation", "  - toc",
             "---", "", '<div class="page-full-bleed" markdown>', switcher(stem)]
    if tier in WARNING:
        text = WARNING[tier].format(country=country, extra=extra).strip()
        help_ = HELP[tier].format(country=country)
        if country in TIER_NOTE:
            text, help_ = TIER_NOTE[country]
        parts.append(f'<div class="atlas-tier-alert atlas-tier-alert--{tier}" role="note">\n'
                     f"  <p>{text}</p>\n  <p>{help_}</p>\n  <p>{CTA}</p>\n</div>")
    # `allow="fullscreen"`: the atlas map has a fullscreen button, which a frame without
    # the permission silently disables. The local-network ones let the "Open in JOSM"
    # button reach JOSM's Remote Control on 127.0.0.1 under Chrome's Local Network Access
    # (named `local-network-access` from Chrome 142, `loopback-network` from 145). A
    # same-origin frame inherits them anyway; named so the page still works if the atlas
    # is ever served from another origin.
    parts.append(f'<iframe src="../assets/interactive/{html}" title="{title}" '
                 'allow="fullscreen; local-network-access; loopback-network"></iframe>')
    parts.append("</div>")
    return "\n".join(parts) + "\n"


def nav_block() -> str:
    out = ["  - PV Atlas:"]
    for tier, (label, _) in TIERS.items():
        out.append(f"      - {label}:")
        for stem, country, html, *_ in ATLASES:
            if tier_of(html) == tier:
                out.append(f"          - {country}: {stem}.md")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--nav", action="store_true", help="print the mkdocs.yml nav block")
    a = ap.parse_args()
    for row in ATLASES:
        (DOCS / f"{row[0]}.md").write_text(page(*row))
    print(f"wrote {len(ATLASES)} atlas pages")
    if a.nav:
        print(nav_block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
