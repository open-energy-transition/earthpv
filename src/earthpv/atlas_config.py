"""Per-AOI content for the evidence atlas, so one template serves every country.

**The Pakistan atlas is this project's reference page, and until 2026-09-20 it was also
literally the only country the shared template described.** Every atlas built from
`templates/pv_evidence_atlas.html` carried, in its own body text, Pakistan's NEPRA
net-metering register as "independent corroboration" of ITS headline figure, Pakistan's
measured 124 bldg/km2 domain-sparsity caveat, a link to Pakistan's composition page, and a
paragraph about the hand-picked calibration quadrats behind the small-panel instruments --
which for Germany, France and Zambia rendered as "All **0** quadrats ... were chosen by a
researcher". None of it failed a build, and none of it was visible from the Pakistan page
it was written for.

So everything that is true of one country and not another now lives here, in
`configs/atlas/<aoi>.yaml`, and the builder omits whatever a country has not supplied
rather than falling back on another country's text. A country with no config file at all
still gets a complete, honest page: the map, the tiers, the composition and the
country-neutral parts of the confidence section, minus the sections that would need local
evidence to write.

Schema (every key optional; an unknown key is an error, since a typo would otherwise
silently drop the section it was meant to fill):

    title: Pakistan                        # display name; default: the AOI, title-cased
    composition_page: pakistan_atlas_composition.html   # sibling page, linked if given
    cities:                                # map annotations, [name, lon, lat]
      - [Karachi, 67.01, 24.86]
    calibration_boxes:                     # exhaustively mapped ground-truth quadrats
      - {name: Lahore DHA Phase V, stem: lahore_calib_6p61km2, status: rule1}
    confidence:                            # the "How confident should you be in this?" text
      ground_truth: "<p>...</p>"           # replaces the default ground-truth paragraph
      caveats: ["<b>...</b> ..."]          # extra <li>s under "what's outside the range"
      corroboration: "<p>...</p>"          # independent, non-satellite cross-checks

`status` is the quadrat's completeness declaration, not something code can derive:
"rule1" = every visible panel mapped (so its no-PV buildings are trustworthy negatives),
"corroborated" = a visual pass supports the count without asserting completeness,
"suspect" = needs re-verification. See `docs/methods/calibration-quadrats.md`.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path("configs/atlas")

_TOP_KEYS = {"title", "composition_page", "cities", "calibration_boxes", "confidence"}
_CONFIDENCE_KEYS = {"ground_truth", "caveats", "corroboration"}
_BOX_KEYS = {"name", "stem", "status"}
_BOX_STATUS = {"rule1", "corroborated", "suspect"}


@dataclass(frozen=True)
class AtlasConfig:
    """What one country supplies to the shared atlas template."""

    aoi: str
    title: str
    composition_page: str = ""
    cities: tuple = ()
    calibration_boxes: tuple = ()
    ground_truth: str = ""
    caveats: tuple = ()
    corroboration: str = ""

    # Kept so a caller can tell "this country has no config" from "this country has a
    # config that supplies nothing", which read the same otherwise and mean different
    # things when a section comes out missing.
    path: Path | None = field(default=None, compare=False)


def _fail(aoi: str, msg: str) -> None:
    raise ValueError(f"configs/atlas/{aoi}.yaml: {msg}")


def _parse_cities(aoi: str, raw) -> tuple:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        _fail(aoi, "`cities` must be a list of [name, lon, lat]")
    out = []
    for entry in raw:
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            _fail(aoi, f"city {entry!r} must be [name, lon, lat]")
        name, lon, lat = entry
        try:
            lon, lat = float(lon), float(lat)
        except (TypeError, ValueError):
            _fail(aoi, f"city {name!r} has a non-numeric coordinate")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            _fail(aoi, f"city {name!r} is at {lon},{lat}, which is not a lon/lat pair")
        out.append([str(name), lon, lat])
    return tuple(out)


def _parse_boxes(aoi: str, raw) -> tuple:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        _fail(aoi, "`calibration_boxes` must be a list of {name, stem, status}")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            _fail(aoi, f"calibration box {entry!r} must be a mapping")
        unknown = set(entry) - _BOX_KEYS
        if unknown:
            _fail(aoi, f"calibration box {entry.get('stem')!r} has unknown key(s) "
                       f"{sorted(unknown)}; expected {sorted(_BOX_KEYS)}")
        if not entry.get("name") or not entry.get("stem"):
            _fail(aoi, f"calibration box {entry!r} needs both `name` and `stem`")
        status = entry.get("status", "corroborated")
        if status not in _BOX_STATUS:
            _fail(aoi, f"calibration box {entry['stem']!r} has status {status!r}; "
                       f"expected one of {sorted(_BOX_STATUS)}")
        out.append({"name": str(entry["name"]), "stem": str(entry["stem"]),
                    "status": status})
    stems = [b["stem"] for b in out]
    dupes = sorted({s for s in stems if stems.count(s) > 1})
    if dupes:
        _fail(aoi, f"calibration box stem(s) listed twice: {dupes}")
    return tuple(out)


@functools.lru_cache(maxsize=None)
def load(aoi: str, config_dir: Path = CONFIG_DIR) -> AtlasConfig:
    """Read `<config_dir>/<aoi>.yaml`, or return an empty config if there is none.

    A missing file is normal and not a warning: it is what a country looks like before
    anyone has written its page-specific content, and every section it would fill is
    optional by construction. A file that exists but cannot be parsed IS an error --
    silently serving a country the empty config is how the template came to ship another
    country's text in the first place.
    """
    default_title = aoi.replace("_", " ").title()
    path = Path(config_dir) / f"{aoi}.yaml"
    if not path.exists():
        return AtlasConfig(aoi=aoi, title=default_title)

    import yaml

    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        _fail(aoi, "top level must be a mapping")
    unknown = set(raw) - _TOP_KEYS
    if unknown:
        _fail(aoi, f"unknown key(s) {sorted(unknown)}; expected {sorted(_TOP_KEYS)}")

    conf = raw.get("confidence") or {}
    if not isinstance(conf, dict):
        _fail(aoi, "`confidence` must be a mapping")
    unknown = set(conf) - _CONFIDENCE_KEYS
    if unknown:
        _fail(aoi, f"unknown confidence key(s) {sorted(unknown)}; "
                   f"expected {sorted(_CONFIDENCE_KEYS)}")
    caveats = conf.get("caveats") or []
    if not isinstance(caveats, list) or any(not isinstance(c, str) for c in caveats):
        _fail(aoi, "`confidence.caveats` must be a list of HTML strings")

    return AtlasConfig(
        aoi=aoi,
        title=str(raw.get("title") or default_title),
        composition_page=str(raw.get("composition_page") or ""),
        cities=_parse_cities(aoi, raw.get("cities")),
        calibration_boxes=_parse_boxes(aoi, raw.get("calibration_boxes")),
        ground_truth=str(conf.get("ground_truth") or "").strip(),
        caveats=tuple(c.strip() for c in caveats),
        corroboration=str(conf.get("corroboration") or "").strip(),
        path=path,
    )
