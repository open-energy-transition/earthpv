"""One self-contained HTML page for judging a blind review folder by hand.

The blind reviews (`olmoearth_vs_seg_review.py`, `olmoearth_vs_segmentation_country.py
--review`, `aef_vs_seg_review.py`) write contact sheets of six panels and an empty
`blind/verdicts.csv`. This cuts the sheets back into panels and writes `blind/review.html`:
one panel at a time, PV / not PV / unsure (keys 1, 2, 3), a note, links that open the spot
in current satellite imagery, and an export of `verdicts.csv` in exactly the format the
joins read (`code,imagery_date,verdict,note`). Progress is kept in the browser between
sessions, and an exported CSV can be imported again to carry on elsewhere.

The page stays blind: from the key it takes only each panel's location, never which
instrument or set it came from.

    pixi run python scripts/build_review_page.py results/olmoearth_vs_seg_review_south_africa
"""

from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from PIL import Image

PANEL = 480
PAD_DEG = 0.001  # ~100 m around the outline for the editor links
KEY = "blind_key_DO_NOT_OPEN_BEFORE_VERDICTS.geojson"


def panels(blind: Path, n: int) -> list[Image.Image]:
    sheets = sorted(blind.glob("sheet_*.png"))
    out = []
    for i in range(n):
        s = Image.open(sheets[i // 6])
        j = i % 6
        out.append(s.crop(((j % 3) * PANEL, (j // 3) * PANEL,
                           (j % 3 + 1) * PANEL, (j // 3 + 1) * PANEL)).convert("RGB"))
    return out


def _jpeg(im: Image.Image) -> str:
    b = io.BytesIO()
    im.save(b, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def locations(review: Path) -> dict[str, dict]:
    """Code -> point and padded bounds, and nothing else from the key."""
    path = review / KEY
    if not path.exists():
        return {}
    k = gpd.read_file(path).to_crs(4326)
    out = {}
    for code, g in zip(k["code"], k.geometry):
        p = g.representative_point()
        w, s, e, n = g.bounds
        out[code] = {"lon": round(p.x, 6), "lat": round(p.y, 6),
                     "bbox": [round(w - PAD_DEG, 6), round(s - PAD_DEG, 6),
                              round(e + PAD_DEG, 6), round(n + PAD_DEG, 6)]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("review_dir", type=Path)
    args = ap.parse_args()
    blind = args.review_dir / "blind"
    v = pd.read_csv(blind / "verdicts.csv", dtype=str).fillna("")
    locs = locations(args.review_dir)
    items = [{"code": c, "date": d, "img": _jpeg(im), **locs.get(c, {})}
             for c, d, im in zip(v.code, v.imagery_date, panels(blind, len(v)))]
    out = write_page(blind / "review.html", args.review_dir.name, items)
    print(f"{len(items)} panels -> {out} ({out.stat().st_size / 1e6:.1f} MB)")


def write_page(out: Path, name: str, items: list[dict], guide: str | None = None) -> Path:
    """Write the review page for `items`, for any review, not only the blind folders.

    Each item needs `code` and `img` (a data URI, or a path relative to `out` so the images
    stay on disk beside the page), and may carry `date`, `date_label` (the caption under the
    image; default "Esri imagery <date>"), `lon`/`lat`/`bbox` for the imagery links. `guide`
    replaces the "How to judge" text (HTML); the default is the blind reviews' own. The
    export is `code,imagery_date,verdict,note` with verdicts `pv`, `no_pv`, `unsure`.
    (`scripts/oversize_review.py package` uses this for unmapped parks, 2026-10-29.)"""
    page = (TEMPLATE.replace("__NAME__", name)
            .replace("__GUIDE__", GUIDE if guide is None else guide)
            .replace("__ITEMS__", json.dumps(items).replace("</", "<\\/")))
    out.write_text(page)
    return out


GUIDE = r"""      <ul>
        <li><b>PV</b>: solar panels sit inside or touching the yellow outline. The outline may be
          larger or smaller than the array; it still counts.</li>
        <li><b>Not PV</b>: the outline covers something else (roofs, greenhouses, sheds, water,
          bare ground, shadow) and the imagery is recent enough to show panels if they were there.</li>
        <li><b>Unsure</b>: you cannot tell, for example the imagery is too blurred, a tile is
          missing, or the capture is from before 2025 and shows no panels (the detectors read
          2025-2026 imagery, so the array may be newer than the photo).</li>
      </ul>
      <p>The date on each panel is the Esri capture there. Newer imagery is often a click away:
        Google and Bing in the links. Keys: <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> judge and move on,
        <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step, <kbd>n</kbd> note, <kbd>Esc</kbd> leave the note.</p>
      <p>When done, export and save the file as <code>blind/verdicts.csv</code> in this folder
        (or pass it with <code>--verdicts</code>). Progress also stays in this browser.</p>"""


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blind PV Review</title>
<style>
:root {
  --bg: #f6f7f9; --panel: #ffffff; --ink: #1d2330; --muted: #5d6677; --line: #d9dde5;
  --pv: #1f8a5b; --no: #c0392b; --unsure: #b7791f; --todo: #c9ced8; --accent: #2563eb;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f131a; --panel: #171c25; --ink: #e6e9ef; --muted: #98a2b3; --line: #2a3140;
    --pv: #34c27f; --no: #ef6b5b; --unsure: #e2a83c; --todo: #3a4252; --accent: #6ea8ff;
  }
}
:root[data-theme="dark"] {
  --bg: #0f131a; --panel: #171c25; --ink: #e6e9ef; --muted: #98a2b3; --line: #2a3140;
  --pv: #34c27f; --no: #ef6b5b; --unsure: #e2a83c; --todo: #3a4252; --accent: #6ea8ff;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { position: sticky; top: 0; z-index: 2; background: var(--panel);
  border-bottom: 1px solid var(--line); padding: 10px 16px; display: flex; flex-wrap: wrap;
  gap: 8px 16px; align-items: center; }
header h1 { font-size: 16px; margin: 0; }
header .name { color: var(--muted); font-size: 13px; }
.progress { flex: 1 1 200px; display: flex; align-items: center; gap: 8px; min-width: 180px; }
.bar { flex: 1; height: 8px; background: var(--todo); border-radius: 4px; overflow: hidden; }
.bar > div { height: 100%; background: var(--accent); width: 0; }
button, .btn { font: inherit; border: 1px solid var(--line); background: var(--panel);
  color: var(--ink); border-radius: 6px; padding: 6px 12px; cursor: pointer; }
button:hover, .btn:hover { border-color: var(--accent); }
main { max-width: 1180px; margin: 0 auto; padding: 16px; display: grid;
  grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; }
@media (max-width: 860px) { main { grid-template-columns: 1fr; } }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px; }
.viewer img { width: 100%; max-width: 720px; aspect-ratio: 1; display: block; margin: 0 auto;
  border-radius: 6px; image-rendering: auto; background: #222; }
.meta { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px;
  margin: 10px 0 0; color: var(--muted); font-size: 14px; }
.meta b { color: var(--ink); font-size: 18px; }
.verdicts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 12px; }
.verdicts button { padding: 12px 6px; font-weight: 600; }
.verdicts button kbd { font: 12px ui-monospace, monospace; color: var(--muted); margin-right: 4px; }
.verdicts button.on[data-v="pv"] { background: var(--pv); border-color: var(--pv); color: #fff; }
.verdicts button.on[data-v="no_pv"] { background: var(--no); border-color: var(--no); color: #fff; }
.verdicts button.on[data-v="unsure"] { background: var(--unsure); border-color: var(--unsure); color: #fff; }
.verdicts button.on kbd { color: #fff; }
textarea { width: 100%; margin-top: 10px; min-height: 56px; font: inherit; color: var(--ink);
  background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 8px; }
.nav { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.links { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; font-size: 13px; }
.links a { color: var(--accent); text-decoration: none; border: 1px solid var(--line);
  border-radius: 999px; padding: 3px 10px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(52px, 1fr)); gap: 6px; }
.chip { font: 12px ui-monospace, monospace; padding: 6px 0; text-align: center;
  border-radius: 6px; border: 2px solid transparent; background: var(--todo); color: var(--ink); cursor: pointer; }
.chip.pv { background: var(--pv); color: #fff; }
.chip.no_pv { background: var(--no); color: #fff; }
.chip.unsure { background: var(--unsure); color: #fff; }
.chip.cur { border-color: var(--accent); }
.side h2 { font-size: 14px; margin: 0 0 8px; }
.side p, .side li { font-size: 13px; color: var(--muted); }
.side ul { padding-left: 18px; margin: 6px 0; }
.counts { display: flex; gap: 10px; font-size: 13px; margin: 8px 0; flex-wrap: wrap; }
.toast { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); background: var(--ink);
  color: var(--bg); padding: 8px 14px; border-radius: 6px; opacity: 0; transition: opacity .2s; }
.toast.show { opacity: 1; }
input[type=file] { display: none; }
</style>
</head>
<body>
<header>
  <h1>Blind PV review <span class="name">__NAME__</span></h1>
  <div class="progress"><div class="bar"><div id="bar"></div></div><span id="prog"></span></div>
  <button id="export" title="Download verdicts.csv">Export verdicts.csv</button>
  <label class="btn" title="Load a verdicts.csv exported earlier">Import<input id="import" type="file" accept=".csv"></label>
  <button id="theme" title="Toggle light or dark">Theme</button>
</header>
<main>
  <section class="card viewer">
    <img id="img" alt="">
    <div class="meta"><b id="code"></b><span id="date"></span></div>
    <div class="verdicts">
      <button data-v="pv"><kbd>1</kbd>PV</button>
      <button data-v="no_pv"><kbd>2</kbd>Not PV</button>
      <button data-v="unsure"><kbd>3</kbd>Unsure</button>
    </div>
    <textarea id="note" placeholder="Note (optional): what you see, e.g. 'greenhouses', 'panels on the roof beside it'"></textarea>
    <div class="nav">
      <button id="prev">&larr; Previous</button>
      <button id="next">Next &rarr;</button>
      <button id="nextTodo">Next unjudged</button>
      <button id="clear">Clear verdict</button>
    </div>
    <div class="links" id="links"></div>
  </section>
  <aside class="side">
    <div class="card">
      <h2>Panels</h2>
      <div class="counts" id="counts"></div>
      <div class="grid" id="grid"></div>
    </div>
    <div class="card" style="margin-top:16px">
      <h2>How to judge</h2>
__GUIDE__
    </div>
  </aside>
</main>
<div class="toast" id="toast"></div>
<script id="items" type="application/json">__ITEMS__</script>
<script>
(function () {
  const ITEMS = JSON.parse(document.getElementById("items").textContent);
  const STORE = "pvreview:__NAME__";
  const LABEL = { pv: "PV", no_pv: "Not PV", unsure: "Unsure" };
  let state = {};
  try { state = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch (e) { state = {}; }
  let cur = 0;
  const $ = (id) => document.getElementById(id);

  function save() { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }
  function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 1600); }

  function links(it) {
    if (it.lat === undefined) return "";
    const [w, s, e, n] = it.bbox;
    const L = [
      ["Google satellite", `https://www.google.com/maps/@${it.lat},${it.lon},180m/data=!3m1!1e3`],
      ["Bing aerial", `https://www.bing.com/maps?cp=${it.lat}~${it.lon}&lvl=19&style=a`],
      ["Esri Wayback", `https://livingatlas.arcgis.com/wayback/#mapCenter=${it.lon}%2C${it.lat}%2C18`],
      ["OpenStreetMap", `https://www.openstreetmap.org/#map=19/${it.lat}/${it.lon}`],
      ["JOSM", `http://127.0.0.1:8111/load_and_zoom?left=${w}&right=${e}&top=${n}&bottom=${s}`],
    ];
    return L.map(([t, u]) => `<a href="${u}" target="_blank" rel="noopener">${t}</a>`).join("");
  }

  function render() {
    const it = ITEMS[cur], v = state[it.code] || {};
    $("img").src = it.img; $("img").alt = "Panel " + it.code;
    $("code").textContent = `${it.code}  (${cur + 1} of ${ITEMS.length})`;
    $("date").textContent = it.date_label || ("Esri imagery " + (it.date || "unknown"));
    document.querySelectorAll(".verdicts button").forEach((b) =>
      b.classList.toggle("on", b.dataset.v === v.verdict));
    $("note").value = v.note || "";
    $("links").innerHTML = links(it);
    const done = ITEMS.filter((x) => state[x.code] && state[x.code].verdict).length;
    $("prog").textContent = `${done} / ${ITEMS.length} judged`;
    $("bar").style.width = (100 * done / ITEMS.length) + "%";
    const c = { pv: 0, no_pv: 0, unsure: 0 };
    ITEMS.forEach((x) => { const s = state[x.code]; if (s && c[s.verdict] !== undefined) c[s.verdict]++; });
    $("counts").innerHTML = Object.entries(c).map(([k, n]) => `<span>${LABEL[k]}: <b>${n}</b></span>`).join("");
    $("grid").innerHTML = ITEMS.map((x, i) => {
      const s = state[x.code] || {};
      return `<div class="chip ${s.verdict || ""} ${i === cur ? "cur" : ""}" data-i="${i}" title="${x.code}">${x.code}</div>`;
    }).join("");
  }

  function go(i) { cur = (i + ITEMS.length) % ITEMS.length; render(); }
  function nextTodo() {
    for (let k = 1; k <= ITEMS.length; k++) {
      const i = (cur + k) % ITEMS.length;
      if (!(state[ITEMS[i].code] && state[ITEMS[i].code].verdict)) return go(i);
    }
    toast("Every panel is judged. Export when ready.");
  }
  function judge(v) {
    const code = ITEMS[cur].code;
    state[code] = Object.assign({}, state[code], { verdict: v });
    save(); render(); nextTodo();
  }

  document.querySelectorAll(".verdicts button").forEach((b) =>
    b.addEventListener("click", () => judge(b.dataset.v)));
  $("note").addEventListener("input", (e) => {
    const code = ITEMS[cur].code;
    state[code] = Object.assign({}, state[code], { note: e.target.value }); save();
  });
  $("prev").onclick = () => go(cur - 1);
  $("next").onclick = () => go(cur + 1);
  $("nextTodo").onclick = nextTodo;
  $("clear").onclick = () => { const s = state[ITEMS[cur].code]; if (s) { delete s.verdict; save(); render(); } };
  $("grid").addEventListener("click", (e) => { const c = e.target.closest(".chip"); if (c) go(+c.dataset.i); });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "TEXTAREA") { if (e.key === "Escape") e.target.blur(); return; }
    if (e.key === "1") judge("pv");
    else if (e.key === "2") judge("no_pv");
    else if (e.key === "3") judge("unsure");
    else if (e.key === "ArrowLeft" || e.key === "k") go(cur - 1);
    else if (e.key === "ArrowRight" || e.key === "j") go(cur + 1);
    else if (e.key === "n") { e.preventDefault(); $("note").focus(); }
  });

  const q = (s) => /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  $("export").onclick = () => {
    const rows = ["code,imagery_date,verdict,note"].concat(ITEMS.map((x) => {
      const s = state[x.code] || {};
      return [x.code, x.date || "", s.verdict || "", (s.note || "").replace(/\r?\n/g, " ")].map(q).join(",");
    }));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.join("\n") + "\n"], { type: "text/csv" }));
    a.download = "verdicts.csv"; a.click();
    const open = ITEMS.filter((x) => !(state[x.code] && state[x.code].verdict)).length;
    toast(open ? `Exported; ${open} panels still unjudged` : "Exported all verdicts");
  };

  function parseCSV(text) {
    const rows = []; let row = [], f = "", inq = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (inq) { if (ch === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else inq = false; } else f += ch; }
      else if (ch === '"') inq = true;
      else if (ch === ",") { row.push(f); f = ""; }
      else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(f); rows.push(row); row = []; f = ""; }
      else f += ch;
    }
    if (f || row.length) { row.push(f); rows.push(row); }
    return rows;
  }
  $("import").addEventListener("change", (e) => {
    const file = e.target.files[0]; if (!file) return;
    file.text().then((t) => {
      const rows = parseCSV(t), h = rows.shift() || [];
      const ci = h.indexOf("code"), vi = h.indexOf("verdict"), ni = h.indexOf("note");
      if (ci < 0 || vi < 0) { toast("Not a verdicts.csv: needs code and verdict columns"); return; }
      let n = 0;
      rows.forEach((r) => {
        const code = r[ci], v = r[vi];
        if (!ITEMS.some((x) => x.code === code)) return;
        if (v && !LABEL[v]) return;
        state[code] = { verdict: v || undefined, note: ni >= 0 ? (r[ni] || "") : "" }; n++;
      });
      save(); render(); toast(`Imported ${n} rows`);
    });
    e.target.value = "";
  });

  $("theme").onclick = () => {
    const r = document.documentElement, dark = r.dataset.theme
      ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    r.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("pvreview:theme", r.dataset.theme); } catch (e) {}
  };
  try { const t = localStorage.getItem("pvreview:theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}

  render();
  if (state[ITEMS[0].code] && state[ITEMS[0].code].verdict) nextTodo();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
