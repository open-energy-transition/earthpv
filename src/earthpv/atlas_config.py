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
      # used: false = registered and declared, but no figure on the page uses it yet
      - {name: Al Wehdah, stem: al_wehdah_priority_calib_1km, status: rule1, used: false}
    confidence:                            # the "How confident should you be in this?" text
      ground_truth: "<p>...</p>"           # replaces the default ground-truth paragraph
      caveats: ["<b>...</b> ..."]          # extra <li>s under "what's outside the range"
      corroboration: "<p>...</p>"          # independent, non-satellite cross-checks
    layers:                                # extra map layers, listed under "More layers"
      - name: Transmission lines           # required; shown in the layer list and legend
        type: geojson                      # geojson | raster
        path: data/external/lines.geojson  # geojson: embedded into the page at build time
        # url: https://...                 # or fetched by the reader's browser (needs CORS);
        #                                  # raster: a {z}/{x}/{y} tile URL, or a WMS GetMap
        #                                  # URL with {bbox-epsg-3857} as its bbox
        attribution: "&copy; source"       # shown on the map and in exported PNGs
        color: "#9aa4b1"                   # geojson only; default: the page's --user colour
        visible: false                     # default false: the capacity map stays the subject
        opacity: 0.8                       # 0-1; default 1 (geojson), 0.75 (raster)
        minzoom: 0                         # raster only, optional
        maxzoom: 18
    validation:                            # the calibration tier, when it is a judgement
      score: silver                        # gold | silver | bronze; beats the derived tier
      note: "Register-checked above 400&nbsp;m&sup2;"   # replaces the badge's sub-line
    start_here: yafi_pv2_calib_1km         # the candidate to map first, drawn as a star

`start_here` names a candidate (`candidate_quadrats/<stem>_candidate.geojson`) when which
one to map first is a judgement. `scripts/publish_calibration_areas.py` ranks it first and
stars it, on any atlas; without it only a Bronze atlas gets a star, its first by rule. Once
the box is registered the star moves on to the next in the ranking by itself.

`validation` exists for the cases `atlas.derive_validation_score` cannot judge from files on
disk: Germany has a calibrated small-installation half, which would make it Gold, but that
half fails its own register check, so the owner placed it at Silver (2026-10-22). An
explicit `--validation-score` on `earthpv atlas` still wins over this.

`status` is the quadrat's completeness declaration, not something code can derive:
"rule1" = every visible panel mapped (so its no-PV buildings are trustworthy negatives),
"corroborated" = a visual pass supports the count without asserting completeness,
"suspect" = needs re-verification. See `docs/methods/calibration-quadrats.md`.

`used` (default true) says whether the page's figures draw on the area. A box is drawn on
the map either way, but the confidence section only claims ground truth for boxes in use:
Yemen's first area (2026-10-23) was registered before any classifier was fitted to it, and
the default prose would otherwise have told readers the page's accuracy checks rested on it.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path("configs/atlas")

_TOP_KEYS = {"title", "composition_page", "cities", "calibration_boxes", "confidence", "layers",
             "validation", "start_here"}
_VALIDATION_KEYS = {"score", "note"}
_SCORES = {"gold", "silver", "bronze"}
_CONFIDENCE_KEYS = {"ground_truth", "caveats", "corroboration"}
_BOX_KEYS = {"name", "stem", "status", "used"}
_BOX_STATUS = {"rule1", "corroborated", "suspect"}
_LAYER_KEYS = {"name", "type", "path", "url", "attribution", "color", "visible", "opacity",
               "minzoom", "maxzoom"}
_LAYER_TYPES = {"geojson", "raster"}


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
    layers: tuple = ()
    validation_score: str = ""
    validation_note: str = ""
    start_here: str = ""

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
        used = entry.get("used", True)
        if not isinstance(used, bool):
            _fail(aoi, f"calibration box {entry['stem']!r}: `used` must be true or false")
        out.append({"name": str(entry["name"]), "stem": str(entry["stem"]),
                    "status": status, "used": used})
    stems = [b["stem"] for b in out]
    dupes = sorted({s for s in stems if stems.count(s) > 1})
    if dupes:
        _fail(aoi, f"calibration box stem(s) listed twice: {dupes}")
    return tuple(out)


def _parse_layers(aoi: str, raw) -> tuple:
    """Validate `layers:`. Files are only checked for existence here; `atlas` embeds them.

    A layer is configuration, not pipeline output: it never enters a capacity figure and
    the page lists it under "More layers", off by default unless `visible: true`.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        _fail(aoi, "`layers` must be a list of mappings")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            _fail(aoi, f"layer {entry!r} must be a mapping")
        name = entry.get("name")
        unknown = set(entry) - _LAYER_KEYS
        if unknown:
            _fail(aoi, f"layer {name!r} has unknown key(s) {sorted(unknown)}; "
                       f"expected {sorted(_LAYER_KEYS)}")
        if not name:
            _fail(aoi, f"layer {entry!r} needs a `name`")
        kind = entry.get("type", "geojson")
        if kind not in _LAYER_TYPES:
            _fail(aoi, f"layer {name!r} has type {kind!r}; expected one of {sorted(_LAYER_TYPES)}")
        path, url = entry.get("path"), entry.get("url")
        if kind == "geojson" and bool(path) == bool(url):
            _fail(aoi, f"geojson layer {name!r} needs exactly one of `path` or `url`")
        if kind == "raster":
            if path or not url:
                _fail(aoi, f"raster layer {name!r} needs a tile `url` and no `path`")
            if "{z}" not in url and "{bbox-epsg-3857}" not in url:
                _fail(aoi, f"raster layer {name!r}: url needs {{z}}/{{x}}/{{y}} or "
                           "{bbox-epsg-3857}")
        if url and not str(url).startswith(("https://", "http://")):
            _fail(aoi, f"layer {name!r}: url must be http(s)")
        if path and not Path(path).exists():
            _fail(aoi, f"layer {name!r}: {path} does not exist")
        color = entry.get("color")
        if color is not None and not (isinstance(color, str) and color.startswith("#")
                                      and len(color) in (4, 7)):
            _fail(aoi, f"layer {name!r}: color must be a #rgb or #rrggbb hex string")
        opacity = entry.get("opacity")
        if opacity is not None and not (isinstance(opacity, (int, float)) and 0 < opacity <= 1):
            _fail(aoi, f"layer {name!r}: opacity must be in (0, 1]")
        out.append({k: entry[k] for k in _LAYER_KEYS if k in entry} | {"type": kind})
    names = [layer["name"] for layer in out]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        _fail(aoi, f"layer name(s) listed twice: {dupes}")
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

    val = raw.get("validation") or {}
    if not isinstance(val, dict):
        _fail(aoi, "`validation` must be a mapping")
    unknown = set(val) - _VALIDATION_KEYS
    if unknown:
        _fail(aoi, f"unknown validation key(s) {sorted(unknown)}; "
                   f"expected {sorted(_VALIDATION_KEYS)}")
    score = str(val.get("score") or "").strip().lower()
    if score and score not in _SCORES:
        _fail(aoi, f"validation.score {score!r} is not one of {sorted(_SCORES)}")

    return AtlasConfig(
        aoi=aoi,
        title=str(raw.get("title") or default_title),
        composition_page=str(raw.get("composition_page") or ""),
        cities=_parse_cities(aoi, raw.get("cities")),
        calibration_boxes=_parse_boxes(aoi, raw.get("calibration_boxes")),
        ground_truth=str(conf.get("ground_truth") or "").strip(),
        caveats=tuple(c.strip() for c in caveats),
        corroboration=str(conf.get("corroboration") or "").strip(),
        layers=_parse_layers(aoi, raw.get("layers")),
        validation_score=score,
        validation_note=str(val.get("note") or "").strip(),
        start_here=str(raw.get("start_here") or "").strip(),
        path=path,
    )
