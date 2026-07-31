"""National PV dashboard: a thin tabbed shell combining several already-self-contained
HTML pages (the sub-400 m2 capacity bracket atlas, a glint panel-pose survey, or
whatever else exists for a given country) into one page.

Each source page is its own document with its own `:root` CSS-variable palette,
theme toggle, and `prefers-color-scheme` handling -- merging their markup into one
DOM would collide on those variable names and require rewriting working, independently
maintained templates. Instead this composes them as lazy-loaded `<iframe>`s behind a
tab strip, so every panel keeps working exactly as it does standalone, and the shell
itself stays generic across countries.

The output is a **self-contained bundle directory**, not a single file:
`<out_dir>/index.html` (the tab shell) plus one copy of each panel's source HTML at
`<out_dir>/<panel.key>.html`. Copying avoids relative-path arithmetic across the
different locations panels are checked into (`results/<aoi>_..._atlas.html` vs
`results/glint_validation_<aoi>/...`) and across the different location the whole
bundle is later synced to for the docs site (`docs/assets/interactive/<aoi>_
dashboard/`) -- the bundle is relocatable as a unit with no broken links either way.

Per-AOI panel lists live in `configs/aoi.yaml` under a `dashboard:` block (see
`earthpv dashboard --help`); this module only knows how to assemble whatever list
it is given, which is what makes it reusable for a country that has not been
onboarded yet -- add the config once its underlying atlas/survey pages exist, no
code change here.
"""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

TEMPLATE = Path(__file__).parent / "templates" / "national_dashboard.html"


@dataclass(frozen=True)
class DashboardPanel:
    key: str        # becomes "<key>.html" inside the bundle; also the iframe's lazy-load src
    label: str      # tab button headline
    sublabel: str   # tab button caption, shown small under the headline
    src: Path       # source HTML file to copy into the bundle
    note: str = ""  # one-line caption shown under the tab strip while this panel is active


def _default_lede(title: str, panels: list[DashboardPanel]) -> str:
    labels = [p.label for p in panels]
    if len(labels) == 1:
        joined = labels[0]
    else:
        joined = ", ".join(labels[:-1]) + " and " + labels[-1]
    return (
        f"{len(panels)} independently-built views of {title}'s solar footprint, combined "
        f"in one place: {joined}. Switch tabs above; each is the same standalone page "
        "documented elsewhere on this site."
    )


def build_national_dashboard(
    aoi: str, title: str, panels: list[DashboardPanel],
    out_dir: Path | None = None, lede: str | None = None,
) -> Path:
    """Assemble the bundle directory and return the path to its `index.html`.

    `out_dir` defaults to `results/<aoi>_pv_dashboard/`. Re-running overwrites the
    bundle in place (copies + the shell are cheap to regenerate), so this is safe to
    call every time a panel's source page is rebuilt.
    """
    if not panels:
        raise ValueError(f"build_national_dashboard({aoi!r}): panels list is empty")

    out_dir = Path(out_dir) if out_dir else Path("results") / f"{aoi}_pv_dashboard"
    out_dir.mkdir(parents=True, exist_ok=True)

    tabs_html = []
    frames_html = []
    for panel in panels:
        src = Path(panel.src)
        if not src.exists():
            raise FileNotFoundError(
                f"dashboard panel {panel.key!r} for {aoi!r}: source file not found: {src}"
            )
        (out_dir / f"{panel.key}.html").write_bytes(src.read_bytes())

        tabs_html.append(
            f'      <button class="tab" type="button" aria-pressed="false">\n'
            f'        <span class="tt1">{html.escape(panel.label)}</span>'
            f'<span class="tt2">{html.escape(panel.sublabel)}</span>\n'
            f'      </button>'
        )
        frames_html.append(
            f'    <div class="panel-frame">\n'
            f'      <iframe data-src="{html.escape(panel.key)}.html" '
            f'title="{html.escape(panel.label)}"></iframe>\n'
            f'    </div>'
        )

    page = TEMPLATE.read_text()
    for key, value in {
        "__PAGE_TITLE__": f"{title} National PV Dashboard",
        "__H1__": f"{title}: national PV overview",
        "__LEDE_HTML__": html.escape(lede if lede is not None else _default_lede(title, panels)),
        "__TABS_HTML__": "\n".join(tabs_html),
        "__IFRAMES_HTML__": "\n".join(frames_html),
        "__NOTES_JSON__": json.dumps([p.note for p in panels]),
    }.items():
        page = page.replace(key, value)

    out = out_dir / "index.html"
    out.write_text(page)
    print(f"national dashboard for {aoi}: {len(panels)} panel(s) -> {out}")
    return out
