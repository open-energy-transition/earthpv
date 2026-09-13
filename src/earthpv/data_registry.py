"""The curated registry of PV labels, registers and roof-context datasets by country.

`docs/assets/registry/earthpv_training_data_registry.csv` lists 90 datasets across 51 countries:
open training labels, national installation registers, aggregate statistics and building/roof
layers. It exists so that extending earthpv to a new country starts from "what does this
country already publish" rather than from a blank OSM pull.

**The registry records what a source IS, not what earthpv should do with it.** Its
`recommended_earthpv_use` column is prose written per dataset. `classify_role` turns the two
structured columns that matter -- whether PV presence is actually confirmed, and whether the
records carry geometry -- into one of five roles that map onto concrete pipeline stages, so a
user can filter to "things I can train on" without reading ninety prose cells.

The five roles, and why the distinction is load-bearing:

* `train_positives` -- confirmed PV with geometry. The only category that can supply Gold or
  Silver segmentation/roofclf labels directly.
* `roof_context` -- building footprints or roof-potential layers with NO PV label. These are
  the roof universe and the source of reliable negatives; treating a roof-potential figure as
  installed PV is the single most common way to misread this table.
* `calibration_only` -- counts or capacity by administrative area, no geometry. Usable for
  per-region calibration and completeness checks, never as training labels.
* `pseudo_labels` -- model-derived detections. Bronze supervision and active-learning pools;
  agreement with them is not validation.
* `access_required` -- a register that exists but whose record-level export is restricted or
  not public. A partnership lead, not a download.

`earthpv data-sources` is the CLI front door.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

REGISTRY_PATH = Path("docs/assets/registry/earthpv_training_data_registry.csv")

ROLES = ("train_positives", "roof_context", "pseudo_labels", "calibration_only",
         "access_required")

ROLE_NEXT_STEP = {
    "train_positives": (
        "Clip to an AOI, dissolve overlapping geometry (labels.dissolve_overlapping), then "
        "`earthpv labels --aoi <aoi>` and `earthpv chips --aoi <aoi>`. If the records are "
        "points rather than polygons, they are Silver: match them to building footprints "
        "first and verify a sample against imagery."),
    "roof_context": (
        "Use as the building layer (`buildings.py`) and for roofclf negatives. Roof POTENTIAL "
        "is not installed PV -- never label these as positives."),
    "pseudo_labels": (
        "Bronze only. Use for active-learning candidate pools and completeness comparisons; "
        "verify a sample before any retrain, and never report agreement with them as "
        "validation."),
    "calibration_only": (
        "No geometry, so no training. Compare against `density`/atlas output per region the "
        "way `validate-mastr` and `validate-france` do, and use for adoption priors and "
        "sampling allocation."),
    "access_required": (
        "Treat as a partnership lead. Ask for privacy-safe coordinates or building "
        "identifiers plus an operational-status field; that is what turns it into "
        "`train_positives`."),
}

_AGGREGATE_HINTS = ("aggregate", "counts", "statistics", "district-wise", "by postcode",
                    "time series", "number of")
_MODEL_HINTS = ("model-derived", "predicted", "bronze")
_RESTRICTED_HINTS = ("not public", "not openly exposed", "restricted", "bulk export",
                     "not located", "partnership")
# Anything that puts a record on the map. If one of these is present the row is locatable,
# whatever aggregate-sounding words sit next to it.
_GEOMETRY_HINTS = ("polygon", "point", "mask", "geometry", "shapefile", "raster", "footprint",
                   "latitude", "coordinate", "image", "location", "geojson", "geospatial")


def classify_role(row: pd.Series) -> str:
    """Map one registry row onto a pipeline role. Derived only from the recorded fields."""
    conf = str(row.get("confirmed_pv_presence_label", "")).strip().lower()
    geom = str(row.get("label_or_geometry", "")).strip().lower()
    stype = str(row.get("source_type", "")).strip().lower()
    access = str(row.get("license_or_access", "")).strip().lower()

    # Model-derived is checked FIRST: several rows say "No; model detections should be
    # treated as Bronze" and the bare "no" rule would file them as roof context, losing the
    # fact that they are PV detections at all.
    if any(h in conf for h in _MODEL_HINTS) and "mixed" not in conf:
        return "pseudo_labels"
    # "aggregate" wins over a leading "no": several rows read "No direct building label;
    # aggregate confirmed installations", which is calibration data, not a roof layer.
    if "aggregate" in conf or "no direct installation geometry" in conf:
        return "calibration_only"
    if conf.startswith("no") or "potential only" in conf or "roof potential" in conf:
        return "roof_context"
    if any(h in conf for h in _RESTRICTED_HINTS) or any(h in access for h in _RESTRICTED_HINTS):
        return "access_required"
    # Aggregate-shaped records carry no geometry to train on whatever the label says -- but
    # only when nothing in the description actually locates anything. Several annotated-imagery
    # datasets mention panel "counts" alongside real geometry, and an over-eager hint match
    # filed them as calibration-only.
    if any(h in geom for h in _AGGREGATE_HINTS) and not any(h in geom for h in _GEOMETRY_HINTS):
        return "calibration_only"
    if "building footprint" in geom and "pv" not in geom and "solar" not in geom:
        return "roof_context"
    if conf.startswith(("yes", "likely", "potentially", "partial", "mixed", "administrative")):
        return "train_positives"
    if "training dataset" in stype:
        return "train_positives"
    return "calibration_only"


def load_registry(path: Path | str = REGISTRY_PATH) -> pd.DataFrame:
    """The registry with an added `earthpv_role` column, sorted by priority then country."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found -- the registry ships with the repo under docs/assets/registry/")
    # utf-8-sig: the sheet export carries a BOM, which otherwise lands in the first header.
    d = pd.read_csv(p, encoding="utf-8-sig")
    d.columns = [c.strip() for c in d.columns]
    d["earthpv_role"] = d.apply(classify_role, axis=1)
    rank = {"A+": 0, "A": 1, "A (partnership)": 1, "A (access dependent)": 1, "A-": 2,
            "B+": 3, "B": 4, "B-": 5, "C+": 6, "C": 7}
    d["_rank"] = d.priority.map(lambda v: rank.get(str(v).strip(), 9))
    return d.sort_values(["_rank", "country", "dataset_name"]).drop(columns="_rank")


def filter_registry(d: pd.DataFrame, country: str | None = None,
                    continent: str | None = None, role: str | None = None,
                    min_priority: str | None = None) -> pd.DataFrame:
    """Case-insensitive substring filters, so `--country korea` finds South Korea."""
    out = d
    if country:
        out = out[out.country.str.contains(country, case=False, na=False)]
    if continent:
        out = out[out.continent.str.contains(continent, case=False, na=False)]
    if role:
        out = out[out.earthpv_role == role]
    if min_priority:
        rank = {"A+": 0, "A": 1, "A-": 2, "B+": 3, "B": 4, "B-": 5, "C+": 6, "C": 7}
        cap = rank.get(min_priority.strip(), 9)
        out = out[out.priority.map(lambda v: rank.get(str(v).strip()[:2].strip(), 9)) <= cap]
    return out
