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

Gold and Silver also need every mapping lead checked by a person (owner, 2026-10-31;
`atlas.leads_checked`) and the segmentation model retrained on mapped leads at least once
(owner, 2026-11-01; `atlas.leads_retrained`): one turn of the mapping flywheel. A page whose
calibration earns more than Bronze but lacks either shows Bronze, and its badge keeps the
earned tier as `data-earned`; its banner says what is missing (`atlas.lead_rule_gaps`).

Silver and Bronze pages open with a warning that smaller installations are missing, what a
reader can do about it, and links into the Contribute Data section (docs/contribute/).
`docs/atlas-quality-levels.md` lists every criterion and ends on the flywheel figure the
levels follow (`quality_page`); the switcher links it.

    python scripts/build_atlas_pages.py          # rewrites docs/atlas*.md
    python scripts/build_atlas_pages.py --nav    # also prints the mkdocs.yml nav block
    # Paste only the PV Atlas block over the old one: other nav sections may follow it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
sys.path.insert(0, str(REPO / "src"))

TIERS = {
    "gold": ("Gold", "Installations above and below the 400 m2 floor, calibrated on ground truth or a register"),
    "silver": ("Silver", "400 m2 and up only, validated against local ground truth; every "
               "mapping lead checked; model retrained on mapped leads"),
    "bronze": ("Bronze", "400 m2 and up only, not yet calibrated, or mapping leads not yet "
               "all checked, or model not yet retrained on them"),
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
    ("atlas-namibia", "Namibia", "namibia_pv_evidence_atlas.html", None, ""),
    ("atlas-nigeria", "Nigeria", "nigeria_pv_evidence_atlas.html", None, ""),
    ("atlas-poland", "Poland", "poland_pv_evidence_atlas.html", None, ""),
    ("atlas-south-africa", "South Africa", "south_africa_pv_evidence_atlas.html", None, ""),
    ("atlas-vietnam", "Vietnam", "vietnam_pv_evidence_atlas.html", None, ""),
    ("atlas-yemen", "Yemen", "yemen_pv_evidence_atlas.html", None, ""),
    ("atlas-zambia", "Zambia", "zambia_pv_evidence_atlas.html", None, ""),
]


def tier_of(html: str) -> str:
    """The tier the atlas's own calibration badge shows."""
    text = (DOCS / "assets" / "interactive" / html).read_text()
    m = re.search(r'class="vscore-tier">(Gold|Silver|Bronze)<', text)
    if not m:
        raise SystemExit(f"{html}: no calibration badge found; rebuild the atlas first")
    return m.group(1).lower()


def earned_of(html: str) -> str:
    """The tier the atlas's calibration evidence earned: its badge's `data-earned` when the
    badge shows a lower one because the leads are not all checked, else the shown tier."""
    text = (DOCS / "assets" / "interactive" / html).read_text()
    m = re.search(r'class="vscore vscore--[a-z]+"[^>]*?data-earned="([a-z]+)"', text)
    return m.group(1) if m else tier_of(html)


def aoi_of(html: str) -> str:
    """The AOI key behind an interactive file name (`pakistan_evidence_atlas.html` included)."""
    return re.sub(r"(_pv)?_evidence_atlas\.html$", "", html)


def totals_of(html: str) -> dict:
    """The page's own `totals` block."""
    text = (DOCS / "assets" / "interactive" / html).read_text()
    m = re.search(r'<script id="pv" type="application/json">(.*?)</script>', text, re.S)
    return json.loads(m.group(1)).get("totals", {}) if m else {}


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
# A page that earned Silver or Gold on its calibration but shows Bronze because its
# mapping leads are not all checked (owner rule, 2026-10-31) or its model has not yet been
# retrained on mapped leads (owner rule, 2026-11-01). EARNED_NOTE says, in one sentence,
# what the calibration does cover; the banner then names the missing pieces, keyed by
# `atlas.lead_rule_gaps`.
LEADS_WARNING = "<strong>{title}</strong> {earned_note} Silver and Gold also need {needs}."
LEADS_TITLE = {
    ("leads_checked", "leads_retrained"):
        "Bronze until its mapping leads are checked and the model is retrained on them.",
    ("leads_checked",): "Bronze until its mapping leads are checked.",
    ("leads_retrained",): "Bronze until the model is retrained on mapped leads.",
}
LEADS_NEED = {
    "leads_checked": "every lead in the country's lead file checked by a person ({n} places "
                     "the model found solar that OpenStreetMap does not have yet)",
    "leads_retrained": "the model retrained at least once on what people mapped from over "
                       "half of a lead file",
}
LEADS_HELP = (
    "<strong>You can help:</strong> download the lead file under <em>Download the data behind "
    "this atlas</em> and work through it on recent imagery, mapping every real installation. "
    "{then}"
)
LEADS_THEN = {
    True: "The model is retrained on what you map; once it is, and every lead has a verdict, "
          "the atlas shows {earned}.",
    False: "When every lead has a verdict the atlas shows {earned}.",
}
LEADS_CTA = (
    '<a class="atlas-tier-cta" href="../contribute/leads/">Map the leads with JOSM &rarr;</a> '
    '<a class="atlas-tier-more" href="../atlas-quality-levels/">What the levels mean</a>'
)
EARNED_NOTE = {
    "Germany": "Arrays of about 400 m&sup2; and up are checked against Germany's register "
               "(MaStR); the small-installation estimate below that is not yet validated.",
    "France": "Arrays of about 400 m&sup2; and up are checked against 14 communes mapped "
              "panel by panel; nothing below that is estimated.",
    "Yemen": "Installations of about 400 m&sup2; and up are counted, plus small "
             "solar-irrigation arrays calibrated on hand-mapped farm areas; small rooftop "
             "systems are not estimated.",
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
        rows = [r for r in ATLASES if tier_of(r[2]) == tier]
        if not rows:      # a level no country shows (Silver from 2026-10-31): no empty label
            continue
        lines.append(f'  <span class="atlas-switch__tier atlas-switch__tier--{tier}" '
                     f'title="{desc}">{label}</span>')
        for stem, country, html, *_ in rows:
            if stem == current:
                lines.append(f'  <span aria-current="page">{country}</span>')
            else:
                lines.append(f'  <a href="{_href(stem)}">{country}</a>')
    lines.append('  <a class="atlas-switch__about" href="../atlas-quality-levels/">'
                 'What the levels mean</a>')
    lines.append("</nav>")
    return "\n".join(lines)


def page(stem: str, country: str, html: str, title: str | None, extra: str) -> str:
    from earthpv import atlas

    tier = tier_of(html)
    title = title or f"{country} PV evidence atlas: verified and best estimate by 0.1-degree cell"
    parts = ["---", f'title: "EarthPV: {country}"', "hide:", "  - navigation", "  - toc",
             "---", "", '<div class="page-full-bleed" markdown>', switcher(stem)]
    earned = earned_of(html)
    if earned != tier:
        label = TIERS[earned][0]
        n = (totals_of(html).get("leads") or {}).get("n")
        gaps = tuple(atlas.lead_rule_gaps(aoi_of(html)))
        if not gaps:
            raise SystemExit(f"{html}: its badge shows {tier}, below the {earned} it earned, "
                             "but its config meets every lead rule; re-badge it first "
                             "(scripts/patch_atlas_leads.py)")
        needs = ", and ".join(LEADS_NEED[g].format(n=f"{n:,}" if n else "all") for g in gaps)
        text = LEADS_WARNING.format(
            title=LEADS_TITLE[gaps],
            earned_note=EARNED_NOTE.get(country, f"Its calibration meets {label}."),
            needs=needs)
        help_ = LEADS_HELP.format(
            then=LEADS_THEN["leads_retrained" in gaps].format(earned=label))
        parts.append(f'<div class="atlas-tier-alert atlas-tier-alert--{tier}" role="note">\n'
                     f"  <p>{text}</p>\n  <p>{help_}</p>\n  <p>{LEADS_CTA}</p>\n</div>")
    elif tier in WARNING:
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
    # The quality-levels page goes last: a section opens on its first page, and clicking
    # PV Atlas must land on the top-tier country's map, not on the criteria.
    out = ["  - PV Atlas:"]
    for tier, (label, _) in TIERS.items():
        rows = [r for r in ATLASES if tier_of(r[2]) == tier]
        if rows:          # mkdocs rejects a section with no pages
            out.append(f"      - {label}:")
            out += [f"          - {country}: {stem}.md" for stem, country, *_ in rows]
    out.append("      - Quality levels: atlas-quality-levels.md")
    return "\n".join(out)


# --------------------------------------------------------------------------------------
# docs/atlas-quality-levels.md: every criterion, and the flywheel the levels follow
# --------------------------------------------------------------------------------------
# Each criterion: (name, what it means, where it is set). The levels add up: Silver needs
# all of Bronze, Gold all of Silver. Keep in step with atlas.derive_validation_score,
# atlas.leads_checked, atlas.leads_retrained and the country-run rules in CLAUDE.md.
CRITERIA = {
    "bronze": [
        ("Model trained on the country's own map",
         "The segmentation model is fine-tuned on the country's own OpenStreetMap solar, and "
         "the shipped checkpoint is whichever of that local model and a general one finds "
         "more mapped installations in a held-out region chosen before training; a tie goes "
         "to the local model. Zambia, run before this rule, uses a general model.",
         "`scripts/pick_val_region.py`, `scripts/compare_local_vs_v5.py`"),
        ("Imagery over every populated cell",
         "A dry-season Sentinel-2 composite over every 0.1&deg; cell with at least 1,000 "
         "buildings, plus every cell holding mapped solar. Cells nobody imaged are hatched on the map, so "
         "bare land means imaged with nothing found.",
         "`earthpv compose`"),
        ("Hand-mapped solar counted once",
         "<em>Verified</em> is OpenStreetMap's own solar, clipped to the border and dissolved "
         "so a plant outline and the panels mapped inside it count once.",
         "`scripts/prepare_national_osm_solar.py`"),
        ("Model outlines priced by measured precision",
         "<em>Best</em> adds the model's outlines of about 400 m&sup2; and up, each weighted "
         "by the share of outlines of its size and placement that turned out to be real. "
         "Without a local recall reference this is a floor.",
         "`configs/calibration/<aoi>_candidate_precision.yaml`"),
        ("Plausibility gate",
         "Before publication each region's ground-mount to rooftop ratio and its "
         "single-cell concentration are checked; a failure is looked at and stated on the "
         "page.",
         "`earthpv check-density`"),
        ("Mapping leads published",
         "The model's outlines more than 100 m from any solar installation in "
         "OpenStreetMap, most promising first. Leads under 1,000 m&sup2; on ground steeper "
         "than 15&deg; are left out (shaded slopes and cliff edges read like panels); "
         "larger ones on steep ground stay, marked <code>steep_review</code>, because a "
         "solar farm can stand on a mountainside, unless the ground is steeper than 30&deg;, "
         "where a lead of any size is left out. France's audited lead release predates "
         "this rule.",
         "`scripts/release_leads.py`"),
    ],
    "silver": [
        ("Local ground truth",
         "The model's precision table is fitted against the country's own mapped "
         "installations as a recall reference, or the country has calibration areas in use "
         "where every visible panel is mapped (Rule 1).",
         "`atlas.derive_validation_score`"),
        ("Every mapping lead checked",
         "A person has looked at every lead in the country's current lead file on recent "
         "high-resolution imagery and mapped the real installations. The record names the "
         "lead file it covers, so a rebuilt file starts unchecked. Until the check is "
         "recorded the atlas shows Bronze, whatever its calibration earns.",
         "`validation.leads_checked` in `configs/atlas/<aoi>.yaml`"),
        ("Model retrained on mapped leads",
         "The mapping flywheel has turned at least once: people have worked through over "
         "half of the leads from the country's first model, mapping the real installations "
         "and judging the rest not solar, and the localized segmentation model has been "
         "trained a second time on the country's OpenStreetMap solar, now holding that "
         "mapping. Until this is recorded the atlas shows Bronze, whatever its calibration "
         "earns.",
         "`validation.retrained_on_leads` in `configs/atlas/<aoi>.yaml`"),
    ],
    "gold": [
        ("Installations below 400 m&sup2; calibrated",
         "An estimate below the 400 m&sup2; floor, where 10 m pixels cannot outline an "
         "array: the rooftop classifier priced by a coverage ratio fitted on calibration "
         "areas mapped panel by panel, its interval from resampling those areas, or a "
         "legally complete national register.",
         "`roofclf`, `sub400_capacity.py`"),
        ("The small-installation estimate holds up",
         "That estimate survives the check against its own ground truth: leaving each "
         "mapped area out in turn, or the register's municipal totals.",
         "owner judgement, `validation.score`"),
    ],
}
# The flywheel figure's alt text, as docs/how-it-works.md carries it (build_docs_figures.py
# draws the figure).
FLYWHEEL_ALT = (
    "The mapping flywheel: six numbered stations run clockwise round a ring with the "
    "OpenStreetMap logo at the hub. 1, detect from space with each country's TerraMind model "
    "and the small-installation classifiers. 2, publish the evidence atlas with mapping leads"
    " and areas to map. 3, people map the leads of 400 square metres and more. 4, people map "
    "calibration areas completely. 5, people investigate local datasets such as registers and"
    " official statistics. 6, retrain the model and recalibrate on what was mapped. Arrows "
    "from stations 3 and 4 carry mapped panels into OpenStreetMap, and arrows out of it carry"
    " them to the atlas as counted capacity and to retraining as labels. A dashed frame round"
    " the whole wheel marks an LLM assistant that helps at every station but never edits "
    "OpenStreetMap, declares an area complete or signs off a number."
)


def quality_page() -> str:
    # The owner removed the per-country standings table, the judgements and the code line
    # from the published page (67820b5, 2026-11-01): it lists the criteria only.
    out = ["---", 'title: "EarthPV: quality levels"', "---", "",
           "# Quality levels: Gold, Silver and Bronze", "",
           "Every country atlas carries a calibration badge in its corner: **Gold**, "
           "**Silver** or **Bronze**. It says how far the atlas's figures have been checked, "
           "against installations mapped by hand and by people looking at what the model "
           "found, not how much solar a country has. The levels add up: Silver needs everything Bronze asks for, and Gold "
           "everything Silver asks for. A country shows the highest level whose every "
           "criterion it meets.", ""]
    heads = {"bronze": "Bronze: every published atlas",
             "silver": "Silver: Bronze, plus local ground truth, checked leads and a "
                       "retrained model",
             "gold": "Gold: Silver, plus installations below 400 m&sup2;"}
    for tier in ("bronze", "silver", "gold"):
        out += [f"## {heads[tier]}", "", "| Criterion | What it means | Where it is set |",
                "| --- | --- | --- |"]
        out += [f"| **{n}** | {w} | {where} |" for n, w, where in CRITERIA[tier]]
        out.append("")
    out += ["## When a lead counts as checked", "",
            "A lead is checked when a person has looked at it on recent high-resolution "
            "imagery and either mapped the installation in OpenStreetMap or judged it not "
            "solar. Rooftop leads in towns and leads beside roads deserve the same look as "
            "the rest: dark asphalt junctions and shadows are the model's commonest false "
            "alarms. Leads marked <code>steep_review</code> need a look at the terrain as "
            "well. The [lead mapping guide](contribute/leads.md) walks through a lead file in "
            "JOSM. When every lead in a country's current file has a verdict, a maintainer "
            "records it as `validation.leads_checked` in the country's configuration, naming "
            "the file by its date.", "",
            "## When the model counts as retrained", "",
            "The first model a country gets is trained on whatever OpenStreetMap held when "
            "its atlas was first built, and its leads are the places it found solar that the "
            "map did not have. The model counts as retrained once people have worked through "
            "over half of that first lead file, and the localized model has been trained "
            "again on the country's OpenStreetMap solar, now holding what they mapped. A "
            "maintainer records it as `validation.retrained_on_leads`, naming the lead file "
            "and the new model. It needs doing once: unlike the lead check, it does not lapse "
            "when a new lead file is made. With both records in place the badge shows the "
            "level the calibration earns.", "",
            "## The levels follow the mapping flywheel", "",
            f"![{FLYWHEEL_ALT}](assets/figures/osm_ai_flywheel.svg#only-light)",
            f"![{FLYWHEEL_ALT}](assets/figures/osm_ai_flywheel.dark.svg#only-dark)", "",
            "The levels say how far a country has come round the "
            "[mapping flywheel](how-it-works.md#workflow), the loop in which the model and "
            "the people mapping solar in OpenStreetMap improve each other's work.", "",
            "- **Bronze: the wheel is set up.** A model trained on the country's own "
            "OpenStreetMap solar detects arrays from space (station 1), and the atlas is "
            "published with its mapping leads and the areas to map (station 2).",
            "- **Silver: the wheel has turned once.** People check every lead and map the "
            "real installations (station 3), and the model is retrained on what they mapped "
            "(station 6), so its next leads come from a model that has learned the country's "
            "own false alarms and missed arrays. The figures are checked against local "
            "ground truth: mapped installations, complete calibration areas (station 4) or a "
            "register (station 5).",
            "- **Gold: the wheel reaches below the floor.** Installations under 400 m&sup2; "
            "are too small for the model to outline, so no lead finds them. Calibration areas "
            "mapped panel by panel (station 4), or a legally complete register (station 5), "
            "are what the small-installation estimate is fitted on and checked against.", "",
            "Each further turn adds labels the model learns from and areas the estimates are "
            "fitted on, so a country moves up by being mapped. The lead check applies to each "
            "new lead file; the first retraining counts for good.",
            ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--nav", action="store_true", help="print the mkdocs.yml nav block")
    a = ap.parse_args()
    import os
    os.chdir(REPO)
    for row in ATLASES:
        (DOCS / f"{row[0]}.md").write_text(page(*row))
    (DOCS / "atlas-quality-levels.md").write_text(quality_page())
    print(f"wrote {len(ATLASES)} atlas pages and atlas-quality-levels.md")
    if a.nav:
        print(nav_block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
