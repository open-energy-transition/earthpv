"""Self-tests for `scripts/publish_calibration_areas.py`, the public boundary files behind the
atlas's "Open in JOSM / iD" buttons.

They run the publisher on a synthetic labels tree, so the right answers are known in
advance: which areas are published as what kind, which are left out (already registered,
screened out, in the rejection register), that a boundary's local paths never reach the
public site, that coordinates stop at OSM's 7 decimals, and that a re-run removes what
left the set and rewrites nothing else.

Run with `pixi run -e default python -m pytest tests/ -q` (pytest is not currently a
declared dependency; these are written to also run as a plain script).
"""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "publish_calibration_areas", ROOT / "scripts" / "publish_calibration_areas.py")
pub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pub)


def _square(path: Path, lon: float, lat: float, props: dict) -> None:
    d = 0.009123456789  # more decimals than OSM keeps, so the rounding is visible
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}}]}))


def _tree(tmp: Path) -> dict:
    labels, configs, out, pages = tmp / "labels", tmp / "configs", tmp / "out", tmp / "pages"
    local = {"source_geojson": "/home/someone/drawn/a.geojson", "labels_file": "/data/x.parquet"}
    _square(labels / "a_calib_1km_boundary.geojson", 70.0, 30.0, {"location": "A District", "side_m": 1000.0, **local})
    _square(labels / "b_calib_1km_boundary.geojson", 71.0, 30.0, {"location": "B District"})
    cands = labels / "candidate_quadrats"
    _square(cands / "c_gap_calib_2km_candidate.geojson", 72.0, 30.0,
            {"location": "C District, Punjab, Pakistan", "side_m": 2000.0, "note": "screen only",
             "source_grid_density_bldg_km2": 61.5})
    _square(cands / "a_calib_1km_candidate.geojson", 70.0, 30.0, {})               # registered since
    _square(cands / "mardan_periurban_calib_2km_candidate.geojson", 73.0, 30.0, {})  # Box 18 reject
    _square(cands / "kasur_gap_calib_2km_candidate.geojson", 74.0, 30.0, {})       # in the register
    configs.mkdir()
    (configs / "pakistan.yaml").write_text(
        "calibration_boxes:\n  - {name: Area A, stem: a_calib_1km, status: rule1}\n")
    (configs / "testland.yaml").write_text("title: Testland\n")
    pages.mkdir()
    (pages / "nopeland_pv_evidence_atlas.html").write_text("")
    (out / "pakistan").mkdir(parents=True)
    (out / "pakistan" / "gone_calib_1km.geojson").write_text("{}")
    (out / "retired.geojson").write_text("{}")
    register = tmp / "rejected.csv"
    register.write_text("name,reason\nkasur_gap,imagery from 2019\n")
    return dict(labels=labels, configs=configs, out=out, pages=pages, register=register)


def _publish(t: dict) -> dict:
    pub.REJECT_REGISTER = t["register"]
    return pub.publish(t["labels"], t["configs"], t["out"], pages=t["pages"])


def test_kinds_and_exclusions():
    with tempfile.TemporaryDirectory() as d:
        t = _tree(Path(d))
        res = _publish(t)
        kinds = {f["id"]: f["properties"]["kind"] for f in res["pakistan"]}
        assert kinds == {"a_calib_1km": "calibration", "b_calib_1km": "unlisted",
                         "c_gap_calib_2km": "candidate"}, kinds
        a = next(f for f in res["pakistan"] if f["id"] == "a_calib_1km")["properties"]
        assert (a["name"], a["status"]) == ("Area A", "rule1")
        c = next(f for f in res["pakistan"] if f["id"] == "c_gap_calib_2km")["properties"]
        assert (c["name"], c["density_bldg_km2"], c["side_m"]) == ("C District", 61.5, 2000.0)


def test_public_files_are_safe_and_rounded():
    with tempfile.TemporaryDirectory() as d:
        t = _tree(Path(d))
        _publish(t)
        files = sorted(t["out"].rglob("*.geojson"))
        text = "".join(p.read_text() for p in files)
        assert "source_geojson" not in text and "/home/someone" not in text and "labels_file" not in text
        assert not re.search(r"\d\.\d{8,}", text), "coordinates must stop at 7 decimals"
        index = json.loads((t["out"] / "pakistan.geojson").read_text())
        assert index["earthpv"]["register_cmd"] == "python scripts/new_calibration_quadrat.py"
        for f in index["features"]:
            one = json.loads((t["out"] / "pakistan" / f"{f['id']}.geojson").read_text())["features"]
            assert len(one) == 1 and one[0] == f and f["properties"]["do_not_upload"]


def test_every_aoi_gets_an_index_and_stale_files_go():
    with tempfile.TemporaryDirectory() as d:
        t = _tree(Path(d))
        _publish(t)
        out = t["out"]
        for aoi in ("testland", "nopeland"):   # a config without areas; a page without a config
            doc = json.loads((out / f"{aoi}.geojson").read_text())
            assert doc["features"] == []
            assert doc["earthpv"]["register_cmd"] == f"python scripts/new_calibration_quadrat.py --aoi {aoi}"
        assert not (out / "pakistan" / "gone_calib_1km.geojson").exists()
        assert not (out / "retired.geojson").exists()
        before = {p: p.read_text() for p in out.rglob("*.geojson")}
        mtimes = {p: p.stat().st_mtime_ns for p in before}
        _publish(t)
        assert {p: p.read_text() for p in out.rglob("*.geojson")} == before
        assert {p: p.stat().st_mtime_ns for p in before} == mtimes, "an unchanged file was rewritten"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
