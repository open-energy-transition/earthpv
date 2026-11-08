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
  areas mapped panel by panel or a register, and the rooftop classifier checked by people by
  random validation and point data inspection (owner, 2026-11-02). No country yet. A judgement
  set in `configs/atlas/<aoi>.yaml`, never derived from files on disk.
- **Silver**: 400 m2 and up validated against local hand-mapped ground truth; any estimate
  below the floor is not yet checked. Pakistan's and Germany's small halves stop here for
  that reason (Germany's fails its own register check; `configs/atlas/<aoi>.yaml`).
- **Bronze**: 400 m2 and up only, with no local calibration.

Gold and Silver also need the leads mapped in OpenStreetMap to localize the model (owner,
2026-11-01; `atlas.leads_retrained`): a third of a lead file's leads and of its very large
outlines with a verdict, and the segmentation model retrained on that mapping once, one turn
of the mapping flywheel. It replaced "every lead checked" (2026-10-31). A page whose
calibration earns more than Bronze but lacks it shows Bronze, and its badge keeps the earned
tier as `data-earned`; its banner says what is missing (`atlas.lead_rule_gaps`).

Silver and Bronze pages open with a banner of two short sentences saying what is not yet
calibrated or verified, and one link to where a reader can help in the Contribute Data
section (docs/contribute/; owner, 2026-11-06).
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
    "gold": ("Gold", "Installations above and below the 400 m2 floor, calibrated on ground "
             "truth or a register, with the rooftop classifier checked by people"),
    "silver": ("Silver", "400 m2 and up validated against local ground truth; leads mapped in "
               "OpenStreetMap to localize the model; any estimate below 400 m2 not yet checked"),
    "bronze": ("Bronze", "400 m2 and up only, not yet calibrated, or not yet enough leads "
               "mapped in OpenStreetMap to localize the model"),
}

# (page stem, country, interactive file, iframe title)
ATLASES = [
    ("atlas", "Pakistan", "pakistan_evidence_atlas.html",
     "Pakistan PV evidence atlas: best estimate by 0.1-degree cell"),
    ("atlas-germany", "Germany", "germany_pv_evidence_atlas.html", None),
    ("atlas-france", "France", "france_pv_evidence_atlas.html", None),
    ("atlas-egypt", "Egypt", "egypt_pv_evidence_atlas.html", None),
    ("atlas-india", "India", "india_pv_evidence_atlas.html", None),
    ("atlas-morocco", "Morocco", "morocco_pv_evidence_atlas.html", None),
    ("atlas-namibia", "Namibia", "namibia_pv_evidence_atlas.html", None),
    ("atlas-nigeria", "Nigeria", "nigeria_pv_evidence_atlas.html", None),
    ("atlas-poland", "Poland", "poland_pv_evidence_atlas.html", None),
    ("atlas-south-africa", "South Africa", "south_africa_pv_evidence_atlas.html", None),
    ("atlas-spain", "Spain", "spain_pv_evidence_atlas.html", None),
    ("atlas-turkiye", "Turkey", "turkiye_pv_evidence_atlas.html", None),
    ("atlas-vietnam", "Vietnam", "vietnam_pv_evidence_atlas.html", None),
    ("atlas-yemen", "Yemen", "yemen_pv_evidence_atlas.html", None),
    ("atlas-zambia", "Zambia", "zambia_pv_evidence_atlas.html", None),
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


# The banner on a Silver or Bronze page: two short sentences saying what is not yet
# calibrated or verified, then one link to where a reader can help (owner, 2026-11-06;
# it was three paragraphs). The atlas's own confidence section carries the detail.
WARNING = {
    "silver": (
        "<strong>This Silver atlas is not yet verified.</strong> Only arrays of about "
        "400 m&sup2; and up are checked against hand-mapped ground truth."
    ),
    "bronze": (
        "<strong>This Bronze atlas is not yet calibrated or verified.</strong> It counts only "
        "mapped installations and arrays of about 400 m&sup2; and up, so every figure is a "
        "floor."
    ),
}
# A country whose reason for its tier is not the generic one (its tier is set in
# configs/atlas/<aoi>.yaml `validation`). Replaces WARNING for that page.
TIER_NOTE = {
    # Silver by the owner's decision (2026-11-02): the small-installation estimate is
    # calibrated, but the checks Gold asks of the rooftop classifier are not done.
    "Pakistan": (
        "<strong>This Silver atlas is not yet verified.</strong> Its estimate below "
        "400 m&sup2; is calibrated, but nobody has checked it by hand yet."
    ),
    # Germany and Yemen show the leads banner below until they meet the lead rule; these
    # are their Silver banners after that.
    "Germany": (
        "<strong>This Silver atlas is not yet verified.</strong> Its estimate below "
        "400 m&sup2; misses Germany's register by about half, so read the map as where "
        "capacity sits."
    ),
    # Silver by the owner's decision (2026-10-23): household rooftops below 400 m2 are
    # still unmeasured.
    "Yemen": (
        "<strong>This Silver atlas is not yet verified.</strong> Farm solar is calibrated on "
        "hand-mapped areas, but small rooftop systems are not estimated yet."
    ),
}
# A page that earned Silver or Gold on its calibration but shows Bronze because not enough
# of its leads have been mapped in OpenStreetMap to localize the model (owner rule,
# 2026-11-01; it replaced "every lead checked"). SMALL_GAP says what its calibration leaves
# out; LEADS_NEED what the lead rule still asks, keyed by `atlas.lead_rule_gaps`.
LEADS_WARNING = "<strong>This Bronze atlas is not yet verified.</strong> {small}, and {needs}."
SMALL_GAP = {
    "Germany": "Its estimate below 400 m&sup2; is not validated",
    "France": "Nothing below 400 m&sup2; is estimated",
    "Yemen": "Small rooftop systems are not estimated",
}
LEADS_NEED = {
    ("leads_mapped", "leads_retrained"): "too few of its leads are mapped in OpenStreetMap",
    ("leads_retrained",): "the model is not yet retrained on the mapped leads",
}
# Where a reader can help: the Contribute Data section (docs/contribute/).
CTA = {
    "calibrate": '<a class="atlas-tier-cta" href="../contribute/">Contribute data: map a '
                 'calibration area &rarr;</a>',
    "leads": '<a class="atlas-tier-cta" href="../contribute/leads/">Contribute data: map the '
             'model\'s leads &rarr;</a>',
}

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


def banner(tier: str, text: str, cta: str) -> str:
    """The Silver/Bronze banner: two short sentences, then one link. A reader can close it
    (owner, 2026-11-06); docs/assets/javascripts/atlas-banner.js shows the button and
    remembers the choice, so without scripts the button stays hidden."""
    return (f'<div class="atlas-tier-alert atlas-tier-alert--{tier}" role="note">\n'
            f"  <p>{text}</p>\n  <p>{cta}</p>\n"
            '  <button class="atlas-tier-close" type="button" aria-label="Close this notice" '
            'title="Close" hidden>&times;</button>\n</div>')


def page(stem: str, country: str, html: str, title: str | None) -> str:
    from earthpv import atlas

    tier = tier_of(html)
    title = title or f"{country} PV evidence atlas: verified and best estimate by 0.1-degree cell"
    # `fit`: embed-theme.js sizes the frame to the whole atlas, so the page scrolls as one
    # and the switcher and tier banner scroll away above the map (owner, 2026-11-06)
    # instead of staying pinned over an atlas scrolling inside a viewport-high frame.
    parts = ["---", f'title: "EarthPV: {country}"', "hide:", "  - navigation", "  - toc",
             "---", "", '<div class="page-full-bleed fit" markdown>', switcher(stem)]
    earned = earned_of(html)
    if earned != tier:
        gaps = tuple(atlas.lead_rule_gaps(aoi_of(html)))
        if not gaps:
            raise SystemExit(f"{html}: its badge shows {tier}, below the {earned} it earned, "
                             "but its config meets every lead rule; re-badge it first "
                             "(scripts/patch_atlas_leads.py)")
        small = SMALL_GAP.get(country, f"It earned {TIERS[earned][0]} on its calibration")
        text = LEADS_WARNING.format(small=small, needs=LEADS_NEED[gaps])
        # Only mapping is a reader's to do; a model retrain is not.
        cta = CTA["leads" if "leads_mapped" in gaps else "calibrate"]
        parts.append(banner(tier, text, cta))
    elif tier in WARNING:
        parts.append(banner(tier, TIER_NOTE.get(country, WARNING[tier]), CTA["calibrate"]))
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
# atlas.leads_retrained, density.load_oversize_admission and the country-run rules in
# CLAUDE.md.
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
        ("Very large outlines counted only once checked",
         "An outline above 100,000 m&sup2; (10 ha) is a blob: 10 m pixels merge everything "
         "bright and touching into one shape, so it is as often a sheet of false alarms as a "
         "solar park the map does not have yet. A blob counts towards capacity only once it "
         "is mapped in OpenStreetMap or a person has judged it solar on the Sentinel-2 "
         "imagery the model saw; until then it is a lead in a file of its own.",
         "`density.load_oversize_admission`, `scripts/oversize_review.py`"),
        ("Plausibility gate",
         "Before publication each region's ground-mount to rooftop ratio and its "
         "single-cell concentration are checked; a failure is looked at and stated on the "
         "page.",
         "`earthpv check-density`"),
        ("Mapping leads published",
         "The model's outlines more than 100 m from any solar installation in "
         "OpenStreetMap, in two files: the leads, most promising first, and the very large "
         "outlines, largest first. Leads under 1,000 m&sup2; on ground steeper "
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
        ("Leads mapped to localize the model",
         "The mapping flywheel has turned at least once: people have checked about a third "
         "of a lead file's leads, working down from the top, and a third of its very large "
         "outlines, largest first, mapping the real installations in OpenStreetMap and "
         "judging the rest not solar; and the localized segmentation model has been trained "
         "again on the country's OpenStreetMap solar, now holding that mapping. Until this is "
         "recorded the atlas shows Bronze, whatever its calibration earns.",
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
        ("The rooftop classifier checked by people",
         "A person has checked the classifier's results on the national scoring behind the "
         "page, in two ways. <em>Random validation:</em> cells drawn at random from the whole "
         "country, away from the calibration areas, are reviewed on imagery and the real and "
         "false detections logged, because calibration areas are chosen on purpose and a "
         "classifier that does well there may not do well elsewhere. <em>Point data "
         "inspection:</em> the classifier's score for every building, exported as points, is "
         "looked through on a map for where it fires and where it stays silent. Until both "
         "are recorded the atlas shows Silver.",
         "`scripts/tile_roofclf_detections_geojson.py`, "
         "`results/roofclf_random_validation_log.csv`, `scripts/export_roofclf_points.py`; "
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
             "silver": "Silver: Bronze, plus local ground truth and leads mapped to "
                       "localize the model",
             "gold": "Gold: Silver, plus installations below 400 m&sup2;, checked by people"}
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
            "well. A very large outline is checked on the Sentinel-2 imagery the model saw as "
            "well as on recent high-resolution imagery, since a park built after the "
            "high-resolution capture shows only there; map the panels or the park's outline, "
            "not the blob. The [lead mapping guide](contribute/leads.md) walks through a lead "
            "file in JOSM.", "",
            "## How much to map: a third", "",
            "Mapping every lead does not pay: the real installations sit near the top of a "
            "lead file, which is sorted most promising first, and the bottom is mostly false "
            "alarms, above all among the small ones. Where people have worked through a lead "
            "file, the top third held more than two thirds of the leads they went on to map in "
            "Pakistan (385 of v3's 4,435 leads of July 2026) and nearly nine in ten in Yemen (246 of "
            "2,259 in a week of October 2026); below it only 2 to 4% of leads were real. In "
            "Germany, whose register locates every installation of 30 kW or more, the top "
            "third holds 46% of the leads with a registered unit inside. So a third of the "
            "leads, worked from the top, and a third of the very large outlines, largest "
            "first, give the model most of what a full pass would. A maintainer records it as "
            "`validation.retrained_on_leads`, naming the lead file, the shares checked and "
            "the model trained on the result. It needs doing once: it does not lapse when a "
            "new lead file is made.", "",
            "## The levels follow the mapping flywheel", "",
            f"![{FLYWHEEL_ALT}](assets/figures/osm_ai_flywheel.svg#only-light)",
            f"![{FLYWHEEL_ALT}](assets/figures/osm_ai_flywheel.dark.svg#only-dark)", "",
            "The levels say how far a country has come round the "
            "[mapping flywheel](how-it-works.md#workflow), the loop in which the model and "
            "the people mapping solar in OpenStreetMap improve each other's work.", "",
            "- **Bronze: the wheel is set up.** A model trained on the country's own "
            "OpenStreetMap solar detects arrays from space (station 1), and the atlas is "
            "published with its mapping leads and the areas to map (station 2).",
            "- **Silver: the wheel has turned once.** People check a third of the leads and "
            "map the real installations (station 3), and the model is retrained on what they mapped "
            "(station 6), so its next leads come from a model that has learned the country's "
            "own false alarms and missed arrays. The figures are checked against local "
            "ground truth: mapped installations, complete calibration areas (station 4) or a "
            "register (station 5).",
            "- **Gold: the wheel reaches below the floor.** Installations under 400 m&sup2; "
            "are too small for the model to outline, so no lead finds them. Calibration areas "
            "mapped panel by panel (station 4), or a legally complete register (station 5), "
            "are what the small-installation estimate is fitted on and checked against. People "
            "then check the rooftop classifier's results directly, on cells drawn at random and "
            "on its score for every building.", "",
            "Each further turn adds labels the model learns from and areas the estimates are "
            "fitted on, so a country moves up by being mapped. The first turn counts for good.",
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
    # The Electrify Earth globe at the site root is drawn from these same atlases.
    import build_landing_page

    build_landing_page.write()
    if a.nav:
        print(nav_block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
