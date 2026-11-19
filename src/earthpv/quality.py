"""The quality checklist on every evidence atlas (owner, 2026-11-19): which of the pipeline's
checks a country has passed, which are under way and which are still open, so a reader sees
what stands behind the figures and what the badge is waiting for.

Sixteen checks in five stages, in the order a country goes through them: detection from
space, ground truth from the map, checks by people, the installations below 400 m2, and
checks independent of the model. Each carries the quality level that needs it
(`docs/atlas-quality-levels.md`, `scripts/build_atlas_pages.CRITERIA`), or none where it is a
step towards one (the two review pages) or context (official figures).

Every status is read from something on record, never typed: the page's own data block
(`totals`), the country's atlas config (`validation` declarations), its calibration table,
the review pages' verdicts (`results/<aoi>_{oversize,large}_review/review.csv`), the
checkpoint decision (`results/<aoi>_checkpoint_decision.json`), the plausibility check
(`<density>/plausibility.csv`), the rooftop classifier's random-cell log and the glint
coverage (`results/glint_coverage/<aoi>.json`, scripts/glint_coverage.py). Where no file
holds the answer (how the five countries run before the held-out rule got their model), the
country's config says it under `quality: {<check>: {status, note}}`, which replaces the
derived row. Because verdicts and declarations change without a rebuild,
scripts/patch_atlas_leads.py and scripts/retemplate_atlas.py recompute the checklist every
time they touch a page.

Statuses: `done`; `warn` (done, with flags a reader should know about); `partial` (under
way); `todo` (not yet); `na` (does not apply, left out of the count).
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
from pathlib import Path

from earthpv import atlas_config

TIERS = ("bronze", "silver", "gold")
TIER_NAME = {"bronze": "Bronze", "silver": "Silver", "gold": "Gold"}
STATUS_TEXT = {"done": "Done", "warn": "Done, with flags", "partial": "In progress",
               "todo": "Not yet", "na": "Does not apply"}
STAGES = (
    ("detection", "Detection from space"),
    ("map", "Ground truth from the map"),
    ("people", "Checked by people"),
    ("small", "Installations below 400 m&sup2;"),
    ("independent", "Independent checks"),
)
# id: (stage, label, the level that needs it). The ids are the keys of a config's `quality`
# block (atlas_config.QUALITY_CHECKS lists the same ids).
CHECKS = {
    "model": ("detection", "Model trained on the local map", "bronze"),
    "imagery": ("detection", "Imagery over every populated cell", "bronze"),
    "precision": ("detection", "Model outlines priced by measured precision", "bronze"),
    "plausibility": ("detection", "Plausibility check on every region", "bronze"),
    "osm": ("map", "Hand-mapped solar counted once", "bronze"),
    "ground_truth": ("map", "Local ground truth", "silver"),
    "leads": ("map", "Mapping leads drawn up", "bronze"),
    "blobs": ("people", "Very large outlines judged (solar farm review)", None),
    "large_review": ("people", "Large installations judged (review page)", None),
    "leads_mapped": ("people", "A third of the large leads checked", "silver"),
    "retrained": ("people", "Model retrained on the checked leads", "silver"),
    "small": ("small", "Installations below 400 m&sup2; estimated", "gold"),
    "small_holds": ("small", "That estimate holds up against ground truth", "gold"),
    "roofclf_checked": ("small", "Rooftop estimate checked by people", "gold"),
    "glint": ("independent", "Solar glint measured on the large installations", "gold"),
    "official": ("independent", "Set beside official figures", None),
}
assert set(CHECKS) == set(atlas_config.QUALITY_CHECKS)

LEVELS_URL = "https://open-energy-transition.github.io/earthpv/atlas-quality-levels/"
HELP_URL = "https://open-energy-transition.github.io/earthpv/contribute/"
# The random-cell log of the rooftop classifier (docs/methods/roofclf-national-validation.md);
# Pakistan's predates the per-country name.
ROOFCLF_LOG = {"pakistan": Path("results/roofclf_random_validation_log.csv")}
BADGE = re.compile(r'class="vscore vscore--([a-z]+)"[^>]*?(?:data-earned="([a-z]+)")?>')


def _n(x) -> str:
    return f"{int(x):,}"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{_n(n)} {one if n == 1 else (many or one + 's')}"


def _date(iso: str | None) -> str:
    """'2026-10-25' -> '25 October 2026'; anything else unchanged."""
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return html.escape(str(iso or ""))
    return f"{d.day} {d:%B %Y}"


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", s)).strip()


def _review(aoi: str, kind: str) -> dict | None:
    """Verdict counts of a review page: `kind` oversize (solar farm review, above the merge
    cap) or large (10,000 m2 up to the cap). None when the country has no page."""
    p = Path("results") / f"{aoi}_{kind}_review" / "review.csv"
    if not p.exists():
        return None
    with p.open(newline="") as f:
        verdicts = [(r.get("verdict") or "").strip() for r in csv.DictReader(f)]
    return {"queue": len(verdicts), "pv": verdicts.count("pv"),
            "not_pv": verdicts.count("not_pv"), "unsure": verdicts.count("unsure")}


def _review_row(r: dict | None, unjudged: str) -> tuple[str, str]:
    if r is None:
        return "todo", "No review page on record for this run yet."
    q, pv, no, uns = r["queue"], r["pv"], r["not_pv"], r["unsure"]
    if q == 0:
        return "na", "The model drew no outline of this size."
    judged = pv + no
    split = f"{_n(pv)} solar, {_n(no)} not solar" + (f", {_n(uns)} unsure" if uns else "")
    if judged == q:
        return "done", f"All {_n(q)} judged: {split}."
    if judged:
        return "partial", f"{_n(judged)} of {_n(q)} judged ({split}). {unjudged}"
    return "todo", f"None of the {_n(q)} judged yet. {unjudged}"


def _model(aoi: str) -> tuple[str, str]:
    p = Path("results") / f"{aoi}_checkpoint_decision.json"
    if not p.exists():
        return "todo", "No record of how this page's model was chosen."
    d = json.loads(p.read_text())
    s, reason, winner = d.get("scores") or {}, d.get("reason") or "", d.get("winner")

    def found(key):
        m = s.get(key) or {}
        m = m.get("matched") or m
        return m.get("detected_ge500"), m.get("installations_ge500")

    (dl, n), (dv, _) = found("local"), found("v5")
    if winner in ("local", "v5") and None not in (dl, dv, n):
        counts = (f"in a region held out from training it found {_n(dl if winner == 'local' else dv)} "
                  f"of {_n(n)} mapped installations of 500 m&sup2; and up, against "
                  f"{_n(dv if winner == 'local' else dl)} for the "
                  f"{'general' if winner == 'local' else 'localized'} model")
        if winner == "v5":
            return "done", (f"A general model, kept over one trained on the solar mapped here: "
                            f"{counts}.")
        if "pixel IoU differs" in reason:
            return "done", (f"Trained on the solar mapped here: {counts}, a tie it won on how "
                            "closely its outlines match the mapped ones.")
        if "tie goes to the localized" in reason:
            return "done", f"Trained on the solar mapped here: {counts}, a tie, which goes to it."
        return "done", f"Trained on the solar mapped here and kept: {counts}."
    return "done", "Trained on the solar mapped here, and chosen on its mapped installations."


def _calibration_table(aoi: str) -> dict:
    p = Path("configs/calibration") / f"{aoi}_candidate_precision.yaml"
    if not p.exists():
        return {}
    import yaml

    try:
        return yaml.safe_load(p.read_text()) or {}
    except Exception:  # noqa: BLE001 - a malformed table must not break the page
        return {}


def _plausibility(density_dir: Path | None, rooftop: bool) -> tuple[str, str]:
    p = Path(density_dir) / "plausibility.csv" if density_dir else None
    if p is None or not p.exists():
        return "todo", "No record of the check for this page's run."
    with p.open(newline="") as f:
        status = [(r.get("status") or "").strip() for r in csv.DictReader(f)]
    n, fail, sus = len(status), status.count("fail"), status.count("suspect")
    if n == 0:
        return "todo", "The run has no regions to check."
    if not fail and not sus:
        return "done", (f"All {_n(n)} regions pass: no implausible share of ground-mounted "
                        "capacity, no single cell carrying a region.")
    flagged = " and ".join(x for x in (f"{_n(fail)} fail" if fail else "",
                                       f"{_n(sus)} look suspect" if sus else "") if x)
    return "warn", (f"{_n(n - fail - sus)} of {_n(n)} regions pass; {flagged}, on a high share "
                    "of ground-mounted capacity or one cell carrying a region"
                    + ("" if rooftop else ": with no rooftop estimate below 400 m&sup2;, "
                       "most rooftop capacity is missing from the share") + ".")


def _roofclf_log(aoi: str) -> tuple[int, int] | None:
    p = ROOFCLF_LOG.get(aoi, Path("results") / f"{aoi}_roofclf_random_validation_log.csv")
    if not p.exists():
        return None
    with p.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return len(rows), sum(1 for r in rows if (r.get("n_real") or "").strip())


def checklist(aoi: str, totals: dict, shown: str, earned: str,
              density_dir: Path | None = None) -> list[dict]:
    """The checks for one page: dicts of id, stage, label, tier, status, detail (HTML)."""
    from earthpv import atlas

    cfg = atlas_config.load(aoi)
    T = totals or {}
    table = _calibration_table(aoi)
    leads = T.get("leads") or {}
    blob_r, large_r = _review(aoi, "oversize"), _review(aoi, "large")
    rooftop = bool((T.get("small_rooftop_status") or {}).get("measured"))
    ground = bool((T.get("small_ground_status") or {}).get("measured"))
    rows = {}

    rows["model"] = _model(aoi)

    proc, country = T.get("n_cells_processed"), T.get("n_cells_country")
    med = (T.get("imagery_dates") or {}).get("median")
    if proc:
        rows["imagery"] = ("done", (
            f"{_n(proc)} of the {_n(country or proc)} cells of 0.1&deg; inside the border imaged"
            + (f", the median scene taken on {_date(med)}" if med else "")
            + ". The cells left out, hatched on the map, hold too few buildings and no "
              "mapped solar."))
    else:
        rows["imagery"] = ("todo", "No record of the imaged cells.")

    rn = int(table.get("recall_reference_n") or 0)
    if not table:
        rows["precision"] = ("todo", "No calibration table for this run.")
    elif rn:
        rows["precision"] = ("done", (
            "Each size and placement class is priced by the share of the model's outlines "
            f"that turned out real, with recall measured on {_n(rn)} mapped installations."))
    else:
        rows["precision"] = ("warn", (
            "Each size and placement class is priced by the share of the model's outlines "
            "that turned out real, but with no recall reference, so the model's figure is a "
            "floor."))

    rows["plausibility"] = _plausibility(density_dir, rooftop)

    osm_n = T.get("osm_n")
    as_of = (T.get("polygons") or {}).get("osm_as_of") or leads.get("osm_as_of")
    rows["osm"] = (("done", f"{_n(osm_n)} solar installations from OpenStreetMap"
                    + (f", as of {_date(as_of)}" if as_of else "")
                    + ", dissolved so a plant and the panels mapped inside it count once.")
                   if osm_n is not None else ("todo", "No hand-mapped solar on record."))

    # Areas in use where the config lists them (India's two are registered, not used), else
    # the page's own count.
    rule1 = (sum(1 for b in cfg.calibration_boxes if b["status"] == "rule1" and b["used"])
             if cfg.calibration_boxes else int(T.get("n_calib_rule1") or 0))
    boxes = len(cfg.calibration_boxes) or int(T.get("n_calib_boxes") or 0)
    gt = []
    if rn:
        gt.append(f"{_n(rn)} mapped installations as the model's recall reference")
    if rule1:
        gt.append(f"{_plural(rule1, 'calibration area')} mapped completely and in use")
    if gt:
        rows["ground_truth"] = ("done", "; ".join(gt).capitalize() + ".")
    elif earned in ("silver", "gold") and cfg.validation_note:
        rows["ground_truth"] = ("done", _strip_tags(cfg.validation_note))
    elif boxes:
        rows["ground_truth"] = ("partial", (
            f"{_plural(boxes, 'calibration area')} registered; none is declared complete and "
            "in use yet."))
    else:
        rows["ground_truth"] = ("todo", (
            "No calibration area mapped completely, and no recall reference yet."))

    # Mappers are offered only the leads a person judged solar (owner, 2026-11-19); the
    # model's other leads are drawn up for the review pages, counted here, never linked.
    if leads:
        nb = (leads.get("blobs") or {}).get("n", 0)
        nc = (leads.get("confirmed") or {}).get("n", 0)
        rows["leads"] = ("done", (
            f"{_n(leads.get('n', 0))} leads" + (f" and {_n(nb)} very large outlines" if nb else "")
            + " that OpenStreetMap does not have"
            + (f" as of {_date(leads.get('osm_as_of'))}" if leads.get("osm_as_of") else "")
            + ". Mappers get only those a person has judged solar: "
            + (f"{_n(nc)} so far, in the download below." if nc else "none yet.")))
    else:
        rows["leads"] = ("todo", "No leads drawn up yet.")

    rows["blobs"] = _review_row(blob_r, "One not yet judged counts only once it is mapped.")
    rows["large_review"] = _review_row(
        large_r, "One not yet judged is priced by the measured share of real outlines of its "
                 "size.")

    lr = atlas.leads_retrained(aoi)
    if lr["mapped"]:
        bs = lr["blobs_share"]
        rows["leads_mapped"] = ("done", (
            f"Recorded on {_date(lr['date'])}: {lr['share']:.0%} of the leads"
            + (f" and {bs:.0%} of the very large outlines" if bs != lr["share"]
               else " and of the very large outlines")
            + f" of the {_date(lr['leads'])} lead file."))
    else:
        # The share counts the leads of 1 ha and up and the blobs (owner, 2026-11-19): exactly
        # the outlines of the two review pages, so their verdicts are the progress.
        seen = [f"{_n(r['pv'] + r['not_pv'])} of {_n(r['queue'])} {what} "
                f"({100 * (r['pv'] + r['not_pv']) // r['queue']}%)"   # down: 99%, not 100%
                for r, what in ((blob_r, "very large outlines"), (large_r, "large installations"))
                if r and r["queue"] and r["pv"] + r["not_pv"]]
        need = ("Not recorded yet. Needed: a verdict, mapped in OpenStreetMap or judged not "
                f"solar, on a third of the leads of {atlas.LEAD_RULE_MIN_M2 / 1e4:g} ha and up "
                "and of the very large outlines, the outlines of the two review pages.")
        rows["leads_mapped"] = (("partial", f"{need} On the review pages so far: "
                                 f"{' and '.join(seen)}.") if seen else ("todo", need))
    if lr["retrained"]:
        rows["retrained"] = ("done", f"{html.escape(lr['model'])}, recorded on {_date(lr['date'])}.")
    elif lr["mapped"]:
        rows["retrained"] = ("todo", "The leads are checked; the retrain on them is still to come.")
    else:
        rows["retrained"] = ("todo", "Comes once the leads are checked.")

    if rooftop and ground:
        rows["small"] = ("done", "Rooftop and farm arrays below 400 m&sup2; are estimated.")
    elif rooftop or ground:
        have, lack = (("Rooftops", "farm arrays") if rooftop else ("Farm arrays", "rooftops"))
        rows["small"] = ("partial", f"{have} below 400 m&sup2; are estimated; {lack} below "
                                    "400 m&sup2; are not measured.")
    else:
        rows["small"] = ("todo", (
            "Not measured: nothing below 400 m&sup2; is estimated yet. Calibration areas "
            "mapped panel by panel, or a register, are what would price it."))

    if earned == "gold":
        rows["small_holds"] = ("done", "Judged to hold up, by the owner.")
    elif rooftop or ground:
        rows["small_holds"] = ("todo", (
            "Not yet judged against its own ground truth: each mapped area left out in turn, "
            "or a register's local totals."))
    else:
        rows["small_holds"] = ("todo", "Needs an estimate below 400 m&sup2; first.")

    log = _roofclf_log(aoi)
    if earned == "gold":
        rows["roofclf_checked"] = ("done", "Random cells and point data checked by people.")
    elif not rooftop:
        rows["roofclf_checked"] = ("todo", "Needs a rooftop estimate below 400 m&sup2; first.")
    elif log and log[1]:
        # Reviewed cells only: the log also lists draws for models that were never published.
        rows["roofclf_checked"] = ("partial", (
            f"{_plural(log[1], 'cell')} drawn at random reviewed on imagery; the inspection of "
            "every building's score as points is not recorded yet."))
    else:
        rows["roofclf_checked"] = ("todo", (
            "No cell drawn at random has been reviewed on imagery yet, and the inspection of "
            "every building's score as points is not recorded either."))

    g = atlas.glint_surveyed(aoi)
    cov_p = Path("results") / "glint_coverage" / f"{aoi}.json"
    cov = json.loads(cov_p.read_text()) if cov_p.exists() else None
    if g["met"]:
        rows["glint"] = ("done", (
            f"{_n(g['measured'])} of the {_n(g['eligible'])} installations of 1 ha and up "
            f"mapped in OpenStreetMap measured ({_n(g['required'])} needed), recorded on "
            f"{_date(g['date'])}."))
    elif cov:
        m, e, r = cov["measured"], cov["eligible"], cov["required"]
        rows["glint"] = ("partial", (
            f"{_n(m)} of the {_n(e)} installations of 1 ha and up mapped in OpenStreetMap "
            f"measured, {_n(r)} needed: "
            + ("enough, not yet recorded." if cov.get("met") else "more to measure.")))
    else:
        rows["glint"] = ("todo", "No glint survey of the large installations yet.")

    refs = T.get("references") or []
    if isinstance(refs, list) and refs:
        names = []
        for r in refs:
            nm = html.escape(str(r.get("name") or r.get("publisher") or ""))
            if nm and nm not in names:
                names.append(nm)
        regional = any(r.get("regions") for r in refs)
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        rows["official"] = ("done", (
            f"Drawn beside {listed}" + (", nationally and by region" if regional else "")
            + "; never used to tune or score the estimate."))
    else:
        rows["official"] = ("todo", "No official or published figure found to set beside it.")

    # What no file records, the country's config says (`quality` in configs/atlas/<aoi>.yaml).
    for cid, status, note in cfg.quality:
        rows[cid] = (status, note)

    return [{"id": cid, "stage": stage, "label": label, "tier": tier,
             "status": rows[cid][0], "detail": rows[cid][1]}
            for cid, (stage, label, tier) in CHECKS.items()]


def summary(items: list[dict], shown: str) -> str:
    """One sentence: the level shown, how many checks are done, what the next level needs."""
    counted = [c for c in items if c["status"] != "na"]
    done = sum(c["status"] in ("done", "warn") for c in counted)
    under = sum(c["status"] == "partial" for c in counted)
    out = (f"<b>This atlas shows {TIER_NAME.get(shown, shown.title())}.</b> "
           f"{_n(done)} of {_n(len(counted))} checks done"
           + (f", {_n(under)} under way" if under else "") + ".")
    for tier in TIERS[TIERS.index(shown) + 1:] if shown in TIERS else ():
        open_ = [c["label"] for c in items if c["tier"] == tier
                 and c["status"] not in ("done", "warn", "na")]
        if open_:
            first = open_[0][0].lower() + open_[0][1:]
            rest = [s[0].lower() + s[1:] for s in open_[1:]]
            listed = first if not rest else ", ".join([first, *rest[:-1]]) + " and " + rest[-1]
            out += f" {TIER_NAME[tier]} still needs: {listed}."
            break
    return out


def checklist_html(aoi: str, totals: dict, badge_html: str,
                   density_dir: Path | None = None, today: str | None = None) -> str:
    """The checklist section's body, from the page's `totals` and its badge (the tier shown,
    and the tier earned where the badge shows a lower one)."""
    m = BADGE.search(badge_html or "")
    shown = m.group(1) if m else "bronze"
    earned = (m.group(2) or m.group(1)) if m else shown
    items = checklist(aoi, totals, shown, earned, density_dir)
    today = today or dt.date.today().isoformat()
    parts = [f'<p class="qa-sum">{summary(items, shown)}</p>', '<div class="qa-grid">']
    for stage, title in STAGES:
        rows = [c for c in items if c["stage"] == stage]
        parts.append(f'<div class="qa-stage"><div class="qa-h">{title}</div><ul class="qa-list">')
        for c in rows:
            tier = (f'<span class="qa-tier qa-tier--{c["tier"]}" title="Needed for '
                    f'{TIER_NAME[c["tier"]]}">{TIER_NAME[c["tier"]]}</span>'
                    if c["tier"] else "")
            parts.append(
                f'<li class="qa-row qa--{c["status"]}" data-check="{c["id"]}">'
                '<span class="qa-ic" aria-hidden="true"></span>'
                f'<div class="qa-main"><div class="qa-lb">{c["label"]}{tier}</div>'
                f'<div class="qa-dt">{c["detail"]}</div></div>'
                f'<span class="qa-st">{STATUS_TEXT[c["status"]]}</span></li>')
        parts.append("</ul></div>")
    parts.append("</div>")
    parts.append(
        f'<p class="qa-foot">As of {_date(today)}. A tag names the level that needs a check; '
        f'<a href="{LEVELS_URL}" target="_blank" rel="noopener">what the levels mean</a> &middot; '
        f'<a href="{HELP_URL}" target="_blank" rel="noopener">how to help</a>.</p>')
    return "\n".join(parts)
