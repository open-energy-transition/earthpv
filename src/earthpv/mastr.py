"""German Marktstammdatenregister (MaStR) rooftop-PV capacity, aggregated per
municipality (Gemeindeschluessel/AGS), for calibrating the PV-fraction density model.

MaStR registration is legally mandatory for grid-connected PV, so per-municipality
rooftop capacity is close to complete — the calibration target `calibrate.py` needs.
Acquired via `open-mastr` (bulk Gesamtdatenexport -> local sqlite), not the SOAP API,
so no account/API key is required. Runs entirely in the default (no-torch) env.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# `ArtDerSolaranlage` values covering panels mounted on/at a building. NOTE: `Lage` (the
# field originally targeted here) is entirely NULL in this MaStR export — verified
# against the actual sqlite; ArtDerSolaranlage is the populated field that carries this
# distinction instead. "Steckerfertige Solaranlage (sog. Balkonkraftwerk)" (balcony/
# plug-in PV) is its own category here and is excluded: ~1.5M units but ~1.6 GWp total,
# a few hundred watts each and invisible at 10 m GSD.
ROOFTOP_ART = ["Gebäudesolaranlage"]
GROUND_ART = ["Freiflächensolaranlage"]
ROOFTOP_KWP_CAP = 100.0  # kw_rooftop_le100: check the fit is not dominated by large industrial roofs


def download_mastr(refresh: bool = False) -> Path:
    """Downloads (once) the official Gesamtdatenexport via open-mastr and parses the
    solar tables into a local sqlite db. Multi-GB, network+CPU heavy, takes hours;
    open-mastr itself skips work that's already done unless `refresh`."""
    from open_mastr import Mastr

    db = Mastr()
    db.download(data=["solar"], update_date="today" if refresh else None)
    log.info("open-mastr solar tables ready at %s", db.engine.url)
    return Path(str(db.engine.url).replace("sqlite:///", ""))


def aggregate_gemeinden(sqlite_path: Path, cutoff: str = "2025-09-30") -> pd.DataFrame:
    """Rooftop/ground PV capacity (kW) per 8-digit Gemeindeschluessel (AGS), restricted
    to units commissioned by `cutoff` (the training composite's imagery window end) and
    still in operation (or decommissioned after it) — units that never appear in the
    imagery must not appear in the calibration target either."""
    import sqlalchemy as sa

    engine = sa.create_engine(f"sqlite:///{sqlite_path}")
    query = """
        SELECT "Gemeindeschluessel" AS ags, "ArtDerSolaranlage" AS art,
               "Bruttoleistung" AS kw, "EinheitBetriebsstatus" AS status,
               "Inbetriebnahmedatum" AS commissioned,
               "DatumEndgueltigeStilllegung" AS decommissioned
        FROM solar_extended
        WHERE "Inbetriebnahmedatum" <= :cutoff
    """
    df = pd.read_sql(sa.text(query), engine, params={"cutoff": cutoff})
    active = (df.status == "In Betrieb") | (
        df.decommissioned.notna() & (df.decommissioned > cutoff)
    )
    df = df[active & df.ags.notna() & df.kw.notna()].copy()

    is_rooftop = df.art.isin(ROOFTOP_ART)
    is_ground = df.art.isin(GROUND_ART)
    df["kw_rooftop"] = df.kw.where(is_rooftop, 0.0)
    df["kw_rooftop_le100"] = df.kw.where(is_rooftop & (df.kw <= ROOFTOP_KWP_CAP), 0.0)
    df["kw_ground"] = df.kw.where(is_ground, 0.0)

    agg = df.groupby("ags", as_index=False).agg(
        kw_rooftop=("kw_rooftop", "sum"),
        kw_rooftop_le100=("kw_rooftop_le100", "sum"),
        kw_ground=("kw_ground", "sum"),
        n_units=("kw", "size"),
    )
    log.info(
        "Aggregated %d gemeinden: total rooftop %.1f GWp, ground %.1f GWp (cutoff %s)",
        len(agg), agg.kw_rooftop.sum() / 1e6, agg.kw_ground.sum() / 1e6, cutoff,
    )
    return agg


def run_mastr(
    out_dir: Path = Path("data/calibration"), cutoff: str = "2025-09-30", refresh: bool = False,
) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sqlite_path = download_mastr(refresh=refresh)
    agg = aggregate_gemeinden(sqlite_path, cutoff=cutoff)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "mastr_gemeinden.parquet"
    agg.to_parquet(out_path)
    (out_dir / "mastr_meta.json").write_text(json.dumps({
        "cutoff": cutoff,
        "n_gemeinden": len(agg),
        "total_kw_rooftop": float(agg.kw_rooftop.sum()),
        "total_kw_rooftop_le100": float(agg.kw_rooftop_le100.sum()),
        "total_kw_ground": float(agg.kw_ground.sum()),
        "rooftop_art": ROOFTOP_ART,
        "ground_art": GROUND_ART,
    }, indent=2))
    log.info("Wrote %s", out_path)
    return out_path
