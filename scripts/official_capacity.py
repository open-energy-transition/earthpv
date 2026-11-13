"""Official and published PV capacity figures each evidence atlas is compared against.

**Why.** An atlas's Best estimate is a satellite count, and a reader's first question is how
it compares with the figures they already know: a national register, the statistics office,
or a published estimate. Each atlas draws its own total and its own per-province figures
next to those, in the "Against other figures" section, alongside the panels its country
imported from China (Ember, `scripts/ember_import_ceiling.py`).

**None of them is ground truth for this map.** A register counts what is registered (and
often AC for large plants), a statistics office what reaches it, a published estimate what
its own method sees; each entry's `scope` says which. The page shows the figures side by
side and never scores the atlas against them.

Two kinds of entry:

- **From a register on disk** (`REGISTERS`): Germany's MaStR per Land at its commissioning
  cutoff, France's ODRE register per region at the year-end vintage after the imagery,
  India's MNRE state-wise register for the imagery's centre month
  (`scripts/validate_india_mnre.py`), Poland's URE installation list summed by
  voivodeship (`URE_WORKBOOK`, downloaded from `URE_URL`), and Texas's utility-scale plants
  from EIA-860M summed by county (`EIA860M_WORKBOOK`, from `EIA860M_URL`). A register whose
  input is not on disk keeps the entry the YAML already has.
- **From a cited document** (`PUBLISHED`): typed in from the source, which `url` names, and
  checked against a fresh download of it (2026-10-29). Where a country publishes nothing
  national, IRENA's Renewable Capacity Statistics stand in, with IRENA's own flag for
  whether the figure came from an official source, an unofficial one or its own estimate.

The vintage picked is the one nearest the end of the atlas's imagery window.

Region keys are the atlas's own province names (geoBoundaries or Overture ADM1, quirks
included); `atlas.official_capacity` refuses a key the page does not have.

    python scripts/official_capacity.py     # rewrites configs/external/official_capacity.yaml
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "configs" / "external" / "official_capacity.yaml"

# Hand-entered from the cited document. `mw` is the national figure the page draws,
# `range` its stated uncertainty where it has one, `regions` keyed by the atlas's names.
PUBLISHED: dict[str, list[dict]] = {
    "belgium": [{
        "id": "elia",
        "name": "Elia",
        "title": "Photovoltaic power production estimation and forecast on Belgian grid (ods032)",
        "publisher": "Elia",
        "kind": "statistics",
        "url": "https://opendata.elia.be/explore/dataset/ods032/",
        "as_of": "2026-09-30",
        # `monitoredcapacity` at 2026-09-30 10:00 UTC, queried from Elia's open-data API on
        # 2026-11-09; the three regions sum to the national figure. ods032 ends on 2026-10-26
        # (ods209 continues it, without the Flanders and Wallonia rows).
        "mw": 12128.3,
        "scope": "The solar capacity Elia, the transmission system operator, monitors for its "
                 "generation estimates on 30 September 2026, the last day of the imagery "
                 "window. Elia's dataset gives it in MW and does not say whether that is panel "
                 "(DC) or inverter (AC) capacity.",
        "regions": {
            "Vlaams Gewest": 8713.8,
            "Wallonne Gewest": 3083.1,
            "Brussels Hoofdstedelijk": 331.4,
        },
    }],
    "denmark": [{
        "id": "ens",
        "name": "Energistyrelsen",
        "title": "Solcelleudbygningen i Danmark pr. 3. kvartal 2026",
        "publisher": "Energistyrelsen (Danish Energy Agency)",
        "kind": "register",
        "url": "https://ens.dk/media/8490/download",
        "as_of": "2026-09-30",
        # "Pr. 30. september 2026 er der registreret 175.455 nettilsluttede solcelleanlæg
        # svarende til ca. 5.468 MW" (Tabel 1, from the agency's master data register,
        # extracted 2026-10-01), in the quarterly note of 2 October 2026, downloaded
        # 2026-11-12. Of it 3,164 MW is 83 plants without subsidy or self-consumption (the
        # large parks), 1,128 MW self-consumption systems, 238 MW tendered plants and 938 MW
        # earlier support schemes. No regional figures.
        "mw": 5468.0,
        "scope": "Grid-connected solar PV registered on 30 September 2026, the last day of the "
                 "imagery window, from the energy agency's master data register: every "
                 "installation, household rooftops included. 3.2 GW of it is 83 large plants "
                 "without subsidy or self-consumption. Given in MW, without saying whether "
                 "panel (DC) or inverter (AC) capacity.",
    }],
    "italy": [{
        "id": "gse",
        "name": "GSE",
        "title": "Solare Fotovoltaico, Rapporto Statistico 2025",
        "publisher": "Gestore dei Servizi Energetici",
        "kind": "statistics",
        "url": "https://www.gse.it/documenti_site/Documenti%20GSE/Rapporti%20statistici/"
               "Solare%20Fotovoltaico%20-%20Rapporto%20Statistico%202025.pdf",
        "as_of": "2025-12-31",
        # "Potenza Installata (MW)", 2025, per region (page 14 of the October 2026 report,
        # downloaded 2026-11-12), summed into this page's five ADM1 macro-regions (ISTAT's
        # ripartizioni; Trentino-Alto Adige is the two provinces); the regions round to
        # 43,688 against the national 43,687. Of the national figure 14,296 MW is
        # ground-mounted (33%). The latest year-end, nine months before the imagery window
        # ends; Italy installed 6,520 MW in 2025.
        "mw": 43687.0,
        "scope": "Installed panel (DC) capacity at the end of 2025 from the energy services "
                 "operator's statistical report: every installation in operation, household "
                 "rooftops included; 14.3 GW of it is ground-mounted.",
        "regions": {
            "Nord-Ovest": 9695.0,
            "Nord-Est": 10769.0,
            "Centro": 8326.0,
            "Sud": 9115.0,
            "Isole": 5783.0,
        },
    }],
    "luxembourg": [{
        "id": "ilr",
        "name": "ILR",
        "title": "Statistiques du marché électricité 2025",
        "publisher": "Institut Luxembourgeois de Régulation",
        "kind": "statistics",
        "url": "https://www.ilr.lu/wp-content/uploads/publication/"
               "ILR_infographie_statistiques-marches_electricite_20260625-1.pdf",
        "as_of": "2025-12-31",
        # "Puissance installée par source d'énergie", Photovoltaïque 746,35 MW (+35.8% on
        # 2024), in the regulator's June 2026 infographic (CC BY 4.0), downloaded 2026-11-11;
        # the latest year-end, nine months before the imagery window ends. No canton figures.
        "mw": 746.35,
        "scope": "Installed solar PV at the end of 2025 from the energy regulator's market "
                 "statistics: every installation connected to the grid, household rooftops "
                 "included. Given in MW, without saying whether panel (DC) or inverter (AC) "
                 "capacity.",
    }],
    "netherlands": [{
        "id": "cbs",
        "name": "CBS",
        "title": "Zonnestroom; vermogen en vermogensklasse, bedrijven en woningen, regio (85005NED)",
        "publisher": "Centraal Bureau voor de Statistiek",
        "kind": "statistics",
        "url": "https://www.cbs.nl/nl-nl/cijfers/detail/85005NED",
        "as_of": "2025-12-31",
        # `OpgesteldVermogenVanZonnepanelen` for all sectors and dwellings (E007161), 2025,
        # status "nader voorlopig", from CBS's OData API on 2026-11-10 (table modified
        # 2026-06-12); the latest year, nine months before the imagery window ends. Of the
        # national figure 6,222.2 MWp is large ground-mounted, 10,564.4 large rooftop and
        # 12,639.9 small (up to 15 kWp). 445.9 MWp has no province, so the twelve sum to
        # 28,980.6.
        "mw": 29426.5,
        "scope": "Installed panel (DC) capacity at the end of 2025 from the statistics office, "
                 "provisional: every installation, household rooftops included. 12.6 GWp of it "
                 "is systems of 15 kWp or less and 6.2 GWp large ground-mounted; 446 MWp is "
                 "not assigned to a province.",
        "regions": {
            "Groningen": 1984.0,
            "Fryslân": 1470.7,
            "Drenthe": 1816.1,
            "Overijssel": 2395.5,
            "Flevoland": 1350.2,
            "Gelderland": 3918.7,
            "Utrecht": 1576.9,
            "Noord-Holland": 2662.0,
            "Zuid-Holland": 3464.7,
            "Zeeland": 1121.1,
            "Noord-Brabant": 4998.1,
            "Limburg": 2222.6,
        },
    }],
    "portugal": [{
        "id": "dgeg",
        "name": "DGEG",
        "title": "Estatísticas rápidas das renováveis, n.º 262, setembro de 2026",
        "publisher": "Direção-Geral de Energia e Geologia",
        "kind": "statistics",
        "url": "https://www.dgeg.gov.pt/pt/estatistica/energia/publicacoes/"
               "estatisticas-rapidas-das-renovaveis/",
        "as_of": "2026-09-30",
        # "Potência instalada", Fotovoltaica, column 2026 (to September, provisional), in the
        # bulletin's workbook dgeg-arr-q-2026-09.xlsx, downloaded 2026-11-10: 3,936 MW
        # conventional, 2,626 self-consumption (UPAC), 649 small production (UPP), 167
        # micro/mini and 18 concentrating. Its regions are NUTS II, which the districts on
        # this page do not nest in, so no regions.
        "mw": 7396.0,
        "scope": "Installed solar PV at the end of September 2026, the last month of the "
                 "imagery window, from the energy directorate's monthly renewables bulletin "
                 "(provisional): power plants, 2.6 GW of self-consumption units, small "
                 "production units and micro and mini generation. Given in MW, without saying "
                 "whether panel (DC) or inverter (AC) capacity.",
    }],
    "spain": [{
        "id": "ree",
        "name": "REE",
        "title": "El sistema eléctrico español en 2025",
        "publisher": "Red Eléctrica",
        "kind": "statistics",
        "url": "https://www.ree.es/sites/default/files/2026-03/1103_NP_ISE_2025.pdf",
        "as_of": "2025-12-31",
        # "Casi 50 GW": 33.1% of the 150.8 GW mix that includes self-consumption, as the note
        # puts it. REE's data API returned 500s for installed capacity on 2026-11-08 and its
        # regional notes give no capacity total for the largest PV regions, so no provinces.
        "mw": 49900.0,
        "scope": "National solar PV at the end of 2025 from the grid operator's annual system "
                 "report: 33.1% of a 150.8 GW generation mix, self-consumption included.",
    }],
    "pakistan": [{
        "id": "transitionzero",
        "name": "TransitionZero",
        "title": "Shedding light on Pakistan's distributed solar revolution",
        "publisher": "TransitionZero and PRIED",
        "kind": "estimate",
        "url": "https://www.transitionzero.org/"
               "shedding-light-on-pakistans-distributed-solar-revolution",
        "as_of": "2025-10",
        # 27.53 GW distributed (+/- 18.2%: 22.57-32.49 GW) plus 1.5 GW of utility-scale
        # plants from TZ-SAM, "around 29 GW" in the source; the range carries the
        # distributed figure's own +/- 18.2% and the utility-scale 1.5 GW unchanged.
        "mw": 29030.0,
        "range": [24070.0, 33990.0],
        "scope": "Satellite-sampling estimate: 27.53 GW of distributed rooftop and ground PV "
                 "(range 22.57 to 32.49 GW) from 0.3 m imagery of sampled areas extrapolated "
                 "nationally, plus 1.5 GW of utility-scale plants from TZ-SAM.",
        "regions": {
            "Punjab": 15700.0,
            "Khyber Pakhtunkhwa": 6160.0,
            "Sindh": 3500.0,
            "Islamabad Capital Territory": 610.0,
            "Azad Kashmir": 540.0,
            "Balochistan": 910.0,
            "Gilgit-Baltistan": 120.0,
        },
        "regions_scope": "Distributed PV only: the 1.5 GW of utility-scale plants is not "
                         "split by province, so the provinces sum to 27.53 GW.",
    }],
    "south_africa": [{
        "id": "ntcsa",
        "name": "NTCSA (Eskom)",
        "title": "Weekly System Status Report, 2026 week 43",
        "publisher": "National Transmission Company South Africa",
        "kind": "estimate",
        "url": "https://www.ntcsa.co.za/wp-content/uploads/2026/10/"
               "Weekly_System_Status_Report_2026_w43.pdf",
        "as_of": "2026-09",
        # 2,780.2 MW of PV contracted with NTCSA (installed capacity, week 43) plus the
        # Sept-26 row of "Estimated Rooftop PV" (9,430.1 MW), the end of the imagery window.
        "mw": 12210.3,
        "scope": "2,780.2 MW of utility-scale PV contracted with NTCSA plus 9,430.1 MW of "
                 "'estimated rooftop PV', Eskom's demand-side estimate of every PV installation "
                 "without an NTCSA contract, rooftop and ground-mounted. The report marks its "
                 "values as unverified and not yet official.",
        "regions": {
            "Eastern Cape": 797.1, "Free State": 650.2, "Gauteng": 3055.7,
            "KwaZulu-Natal": 1375.1, "Limpopo": 579.7, "Mpumalanga": 704.9,
            "Nothern Cape": 758.4, "North West": 681.2, "Western Cape": 827.8,
        },
        "regions_scope": "Estimated rooftop and other uncontracted PV only: the 2,780.2 MW of "
                         "contracted utility-scale PV is not split by province.",
    }],
    "poland": [{
        "id": "are",
        "name": "ARE",
        "title": "Energetyka w liczbach: moc osiągalna, OZE - fotowoltaika",
        "publisher": "Agencja Rynku Energii",
        "kind": "statistics",
        "url": "https://www.are.waw.pl/badania-statystyczne/energetyka-w-liczbach",
        "as_of": "2026-08",
        "mw": 27105.5,
        "scope": "National PV capacity at the end of August 2026 from the energy statistics "
                 "agency's monthly series; its size implies it includes the prosumer "
                 "microinstallations URE's list leaves out (about 13.7 GW).",
    }],
    "texas": [{
        "id": "eia_epm",
        "name": "EIA",
        "title": "Electric Power Monthly, table 6.2.B: net summer capacity using primarily "
                 "renewable energy sources, by state, August 2026",
        "publisher": "U.S. Energy Information Administration",
        "kind": "statistics",
        "url": "https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_6_02_b",
        "as_of": "2026-08-31",
        # Texas, August 2026 (downloaded 2026-11-13, data/external/eia/
        # epm_table_6_02_b_2026-08.html): utility-scale solar PV 33,670.9 MW net summer
        # capacity, estimated small-scale PV 3,529.6 MW, estimated total solar PV 37,200.5 MW;
        # solar thermal 0. The month nearest the end of the imagery window (September 2026)
        # the table had published.
        "mw": 37200.5,
        "scope": "All solar PV in Texas at the end of August 2026, a month before the imagery "
                 "window ends: 33.7 GW of utility-scale plants (net summer capacity, an "
                 "inverter (AC) rating) and EIA's estimate of 3.5 GW of small-scale systems "
                 "below 1 MW, household rooftops included.",
    }],
    "turkiye": [{
        "id": "teias",
        "name": "TEİAŞ",
        "title": "Türkiye Elektrik Üretim-İletim İstatistikleri 2025, table 9",
        "publisher": "Türkiye Elektrik İletim A.Ş.",
        "kind": "statistics",
        "url": "https://www.teias.gov.tr/turkiye-elektrik-uretim-iletim-istatistikleri",
        "as_of": "2025-12-31",
        "mw": 25926.7,
        "scope": "National installed solar capacity at the end of 2025 from the transmission "
                 "operator's annual statistics, licensed and unlicensed plants.",
    }],
}

IRENA_URL = ("https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2026/Mar/"
             "IRENA_DAT_RE_Capacity_Statistics_2026.pdf")
IRENA_FLAG = {"o": "from an official national source", "u": "from an unofficial source "
              "(industry or press)", "e": "IRENA's own estimate"}
# AOI -> (year-end, MW, IRENA's flag), solar photovoltaic, 2026 edition. Only for countries
# with no national figure above: where one exists, it is the comparison.
IRENA = {
    "egypt": ("2025", 3247.0, "o"), "morocco": ("2025", 546.0, "e"),
    "namibia": ("2025", 389.0, "e"), "nigeria": ("2025", 285.0, "e"),
    "vietnam": ("2025", 19252.0, "u"), "yemen": ("2025", 456.0, "u"),
    "zambia": ("2025", 328.0, "e"),
}


def irena(year: str, mw: float, flag: str) -> dict:
    return {
        "id": "irena",
        "name": "IRENA",
        "title": "Renewable Capacity Statistics 2026, solar photovoltaic",
        "publisher": "International Renewable Energy Agency",
        "kind": "statistics",
        "url": IRENA_URL,
        "as_of": f"{year}-12-31",
        "mw": mw,
        "scope": f"National on- and off-grid solar PV at the end of {year}, {IRENA_FLAG[flag]}. "
                 "No national register or statistic was found for this country.",
    }

# MaStR Land code (first two digits of the AGS) -> the atlas's Overture region name.
GERMAN_LAENDER = {
    "01": "Schleswig-Holstein", "02": "Hamburg", "03": "Niedersachsen", "04": "Bremen",
    "05": "Nordrhein-Westfalen", "06": "Hessen", "07": "Rheinland-Pfalz",
    "08": "Baden-Württemberg", "09": "Bayern", "10": "Saarland", "11": "Berlin",
    "12": "Brandenburg", "13": "Mecklenburg-Vorpommern", "14": "Sachsen",
    "15": "Sachsen-Anhalt", "16": "Thüringen",
}
# The France atlas covers metropolitan France; ODRE's overseas regions are not on it.
FRANCE_VINTAGE = "311224"  # 2024-12-31, the first year-end after the 2024 imagery window
FRANCE_OVERSEAS = {"La Réunion", "Guadeloupe", "Martinique", "Guyane", "Mayotte"}


def germany_mastr() -> dict | None:
    import pandas as pd

    gem = REPO / "data" / "calibration" / "mastr_gemeinden.parquet"
    meta = REPO / "data" / "calibration" / "mastr_meta.json"
    if not gem.exists() or not meta.exists():
        return None
    g = pd.read_parquet(gem)
    g["mw"] = (g["kw_rooftop"] + g["kw_ground"]) / 1e3
    by_land = g.groupby(g["ags"].str[:2])["mw"].sum()
    unknown = set(by_land.index) - set(GERMAN_LAENDER)
    if unknown:
        raise SystemExit(f"MaStR: Land codes with no name: {sorted(unknown)}")
    cutoff = json.loads(meta.read_text())["cutoff"]
    return {
        "id": "mastr",
        "name": "MaStR register",
        "title": "Marktstammdatenregister, rooftop and ground-mounted PV",
        "publisher": "Bundesnetzagentur",
        "kind": "register",
        "url": "https://www.marktstammdatenregister.de/MaStR/Datendownload",
        "as_of": cutoff,
        "mw": round(float(g["mw"].sum()), 1),
        "scope": "Every registered building-mounted and ground-mounted PV unit commissioned "
                 f"by {cutoff}, module capacity. Registration is mandatory for grid-connected "
                 "PV; plug-in balcony units are not included.",
        "regions": {GERMAN_LAENDER[k]: round(float(v), 1) for k, v in by_land.items()},
    }


def france_odre() -> dict | None:
    import pandas as pd

    path = REPO / "data" / "register" / f"odre_solaire_{FRANCE_VINTAGE}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=";", low_memory=False)
    df = df[df["technologie"].astype(str).str.startswith("Photo")]
    df["mw"] = pd.to_numeric(df["puismaxinstallee"], errors="coerce") / 1e3
    by_region = df.groupby("region")["mw"].sum()
    by_region = by_region[~by_region.index.isin(FRANCE_OVERSEAS)]
    as_of = f"20{FRANCE_VINTAGE[4:]}-{FRANCE_VINTAGE[2:4]}-{FRANCE_VINTAGE[:2]}"
    return {
        "id": "odre",
        "name": "ODRE register",
        "title": "Registre national des installations de production d'électricité, "
                 f"vintage {as_of}",
        "publisher": "ODRE (RTE, Enedis and the distribution operators)",
        "kind": "register",
        "url": "https://odre.opendatasoft.com/explore/dataset/"
               "registre-national-installation-production-stockage-electricite-agrege-"
               f"{FRANCE_VINTAGE}/",
        "as_of": as_of,
        "mw": round(float(by_region.sum()), 1),
        "scope": "Every grid-connected PV installation in metropolitan France at the year-end "
                 "after the imagery, installations below 36 kW as per-commune aggregates; "
                 "overseas regions left out.",
        "regions": {k: round(float(v), 1) for k, v in by_region.items()},
    }


def india_mnre() -> dict | None:
    import pandas as pd

    d = REPO / "results" / "india_mnre_validation"
    paths = [d / "comparison_by_state.csv", d / "summary.json", d / "mnre_source.json"]
    if not all(p.exists() for p in paths):
        return None
    states = pd.read_csv(paths[0])
    summary = json.loads(paths[1].read_text())
    source = json.loads(paths[2].read_text())
    month = summary["register_month"]
    return {
        "id": "mnre",
        "name": "MNRE register",
        "title": "MNRE state-wise installed solar capacity (via MoSPI eSankhyiki)",
        "publisher": "Ministry of New and Renewable Energy",
        "kind": "register",
        "url": source["url"],
        "as_of": month,
        "mw": round(float(summary["register_all_india_row"]["total"]), 1),
        "scope": "Ground-mounted, rooftop, hybrid and off-grid/KUSUM solar at the end of "
                 f"{month}, the centre of the imagery window. Utility-scale plants are "
                 "usually reported in AC, below their module capacity.",
        "regions": {r["name"]: round(float(r["total"]), 1) for _, r in states.iterrows()},
    }


URE_URL = "https://www.ure.gov.pl/download/9/16535/MAPAOZEna30092026nastroneURE.xlsx"
URE_WORKBOOK = REPO / "data" / "external" / "ure" / "MAPAOZEna30092026nastroneURE.xlsx"
# URE's lower-case Polish voivodeship -> the atlas's geoBoundaries name.
VOIVODESHIPS = {
    "dolnośląskie": "Lower Silesian Voivodeship",
    "kujawsko-pomorskie": "Kuyavian-Pomeranian Voivodeship",
    "lubelskie": "Lublin Voivodeship", "lubuskie": "Lubusz Voivodeship",
    "łódzkie": "Łódź Voivodeship", "małopolskie": "Lesser Poland Voivodeship",
    "mazowieckie": "Masovian Voivodeship", "opolskie": "Opole Voivodeship",
    "podkarpackie": "Subcarpathian Voivodeship", "podlaskie": "Podlaskie Voivodeship",
    "pomorskie": "Pomeranian Voivodeship", "śląskie": "Silesian Voivodeship",
    "świętokrzyskie": "Świętokrzyskie Voivodeship",
    "warmińsko-mazurskie": "Warmian-Masurian Voivodeship",
    "wielkopolskie": "Greater Poland Voivodeship",
    "zachodniopomorskie": "West Pomeranian Voivodeship",
}


def xlsx_rows(path: Path):
    """The first sheet of an .xlsx as {column letter: text} dicts, stdlib only (no
    environment here carries openpyxl)."""
    import re
    import xml.etree.ElementTree as ET
    import zipfile

    m = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(m + "t"))
                  for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(m + "si")]
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(m + "row"):
        out = {}
        for c in row.findall(m + "c"):
            v = c.find(m + "v")
            if c.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(m + "t"))
            elif v is None:
                continue
            else:
                val = shared[int(v.text)] if c.get("t") == "s" else v.text
            out[re.match(r"[A-Z]+", c.get("r")).group()] = val
        yield out


def poland_ure() -> dict | None:
    if not URE_WORKBOOK.exists():
        return None
    rows = list(xlsx_rows(URE_WORKBOOK))
    head = rows[0]
    if not (head.get("D", "").startswith("Województwo") and head.get("G", "").startswith("Moc")
            and head.get("H") == "Rodzaj OZE"):
        raise SystemExit(f"URE: unexpected header {head}")
    by_voi: dict[str, float] = {}
    for r in rows[1:]:
        if r.get("H") == "PVA":  # elektrownia fotowoltaiczna
            name = VOIVODESHIPS[r["D"].strip()]
            by_voi[name] = by_voi.get(name, 0.0) + float(r["G"])
    return {
        "id": "ure",
        "name": "URE register",
        "title": "Instalacje odnawialnych źródeł energii, stan na 30 września 2026 r.",
        "publisher": "Urząd Regulacji Energetyki",
        "kind": "register",
        "url": URE_URL,
        "as_of": "2026-09-30",
        "mw": round(sum(by_voi.values()), 1),
        "scope": "Every PV installation above microinstallation size (over 50 kW) in the energy "
                 "regulator's list, summed by voivodeship; prosumer microinstallations are not "
                 "in it.",
        "regions": {k: round(v, 1) for k, v in sorted(by_voi.items())},
        "regions_scope": "Installations above 50 kW only, so the bulk of rooftop PV, about "
                         "13.7 GW of prosumer microinstallations nationally (ARE), is outside "
                         "these figures.",
    }


EIA860M_URL = ("https://www.eia.gov/electricity/data/eia860m/xls/september_generator2026.xlsx")
EIA860M_WORKBOOK = REPO / "data" / "external" / "eia" / "september_generator2026.xlsx"


def texas_eia860m() -> dict | None:
    """Texas's utility-scale PV per county from EIA-860M, the monthly inventory of every
    operating generator of 1 MW and up, as of September 2026 (the last month of the imagery
    window). Nameplate (AC) capacity summed by EIA's own county name, which matches the
    page's county names (geoBoundaries ADM2) one for one; counties without a plant are left
    out, and so is a county the page does not draw (no imaged cell, so no region row in the
    density run's `regions.geoparquet`), which `atlas.official_capacity` would refuse; the
    state total keeps it and `regions_scope` names it. The `Operating` sheet is the
    workbook's first."""
    if not EIA860M_WORKBOOK.exists():
        return None
    rows = list(xlsx_rows(EIA860M_WORKBOOK))
    head = next((i for i, r in enumerate(rows[:10]) if r.get("A") == "Entity ID"), None)
    if head is None or rows[head].get("G") != "Plant State" or rows[head].get("H") != "County" \
            or not rows[head].get("M", "").startswith("Nameplate Capacity") \
            or rows[head].get("P") != "Technology":
        raise SystemExit(f"EIA-860M: unexpected header {rows[head] if head is not None else None}")
    by_county: dict[str, float] = {}
    for r in rows[head + 1:]:
        if r.get("G") == "TX" and r.get("P") == "Solar Photovoltaic":
            by_county[r["H"].strip()] = by_county.get(r["H"].strip(), 0.0) + float(r["M"])
    regions_path = REPO / "data" / "predictions" / "texas" / "density" / "regions.geoparquet"
    off_page: dict[str, float] = {}
    if regions_path.exists():
        import pyarrow.parquet as pq

        on_page = set(pq.read_table(regions_path, columns=["name"]).column("name").to_pylist())
        off_page = {k: v for k, v in by_county.items() if k not in on_page}
    scope = ("Utility-scale plants of 1 MW and up only, in the counties that have one; rooftop "
             "systems are outside these figures.")
    if off_page:
        scope += (" Not drawn here: " + ", ".join(
            f"{k} County ({v:,.0f} MW)" for k, v in sorted(off_page.items()))
            + ", where no cell was imaged.")
    return {
        "id": "eia860m",
        "name": "EIA-860M",
        "title": "Preliminary Monthly Electric Generator Inventory, September 2026",
        "publisher": "U.S. Energy Information Administration",
        "kind": "register",
        "url": EIA860M_URL,
        "as_of": "2026-09-30",
        "mw": round(sum(by_county.values()), 1),
        "scope": "Every operating utility-scale solar PV generator in Texas (1 MW and up) at "
                 "the end of September 2026, the last month of the imagery window, at "
                 "nameplate inverter (AC) capacity; systems below 1 MW are not in it. Where "
                 "EIA reports it, the panel (DC) capacity of the same plants is about 29% "
                 "higher.",
        "regions": {k: round(v, 1) for k, v in sorted(by_county.items()) if k not in off_page},
        "regions_scope": scope,
    }


REGISTERS = {"germany": germany_mastr, "france": france_odre, "india": india_mnre,
             "poland": poland_ure, "texas": texas_eia860m}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()

    old = (yaml.safe_load(a.out.read_text()) or {}).get("aois", {}) if a.out.exists() else {}
    out: dict[str, list[dict]] = {}
    for aoi in sorted(set(PUBLISHED) | set(REGISTERS) | set(IRENA) | set(old)):
        # A national total first, then a register that only covers part of the fleet (URE,
        # EIA-860M).
        entries = list(PUBLISHED.get(aoi, []))
        if aoi in REGISTERS:
            reg = REGISTERS[aoi]()
            if reg is None:
                reg = [e for e in old.get(aoi, []) if e.get("kind") == "register"]
                print(f"  {aoi}: register input not on disk, keeping {len(reg)} existing entry")
            else:
                reg = [reg]
            entries = entries + reg if aoi in ("poland", "texas") else reg + entries
        if aoi in IRENA:
            entries.append(irena(*IRENA[aoi]))
        if entries:
            out[aoi] = entries
        for e in entries:
            n = len(e.get("regions") or {})
            print(f"  {aoi:13s} {e['name']:22s} {e['as_of']:10s} {e['mw']:12,.0f} MW  {n} regions")

    doc = {
        "note": "Figures each evidence atlas draws beside its own in 'Against other figures'. "
                "None is ground truth for the atlas: `scope` says what each counts.",
        "retrieved": datetime.date.today().isoformat(),
        "aois": out,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("# Written by scripts/official_capacity.py; do not edit by hand.\n"
                     + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
