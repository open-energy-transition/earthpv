# National dashboards

A national dashboard combines everything a country has into one page: the capacity
atlas (large PV nationwide, plus the sub-400 m<sup>2</sup> bracket where it has been
checked) and, where a glint survey exists, the fitted panel-orientation plot. Each
tab is the exact same standalone page documented elsewhere on this site (see
[Capacity density](../methods/density.md) and
[Panel pose from glint](../results/pv-pose.md)); the dashboard is only a thin shell
that switches between them, so nothing here is a separate, independently-computed
number.

## Available today

| Country | | |
| --- | --- | --- |
| Pakistan | [Open dashboard](pakistan.md) | Capacity bracket + panel orientation (n=2000) |

Pakistan is the only country with both artifacts today. A country needs, at minimum,
a completed `density` run (see [Reproduce](../reproduce.md) and
[Scale to a new country](../scale.md)) before it has anything to show here; the panel
orientation tab additionally needs a country-scale glint survey, which is
[Sentinel-2 -- and time -- intensive](../methods/glint.md) and is not expected for
every country.

## Adding a country

This is generated, not hand-built, specifically so a second country does not mean
writing a new page: `earthpv dashboard --aoi <name>` reads a `dashboard:` block from
that AOI's entry in `configs/aoi.yaml` and combines whatever panels it lists into one
bundle under `results/<aoi>_pv_dashboard/`.

```yaml
# configs/aoi.yaml, under aois.<name>:
dashboard:
  title: Some Country
  panels:
    - key: capacity
      label: Capacity
      sublabel: Sub-400 m² bracket + large PV
      src: results/some_country_pv_sub400_bracket_atlas.html
      note: "One-line caption shown while this tab is active."
    # a `pose` panel is optional -- add it once a glint survey exists
```

Once the block exists:

```bash
pixi run earthpv dashboard --aoi <name>       # writes results/<name>_pv_dashboard/
pixi run docs-figures                          # syncs it into docs/assets/interactive/
```

then add a `docs/dashboards/<name>.md` page following `pakistan.md`'s shape (front
matter `hide: [navigation, toc]`, one `.embed.page-full-bleed` iframe) and a nav entry
in `mkdocs.yml`. The panel list, the shell template
(`src/earthpv/templates/national_dashboard.html`) and the composition code
(`src/earthpv/dashboard.py`) are all country-agnostic; only the config block and the
one markdown page are country-specific.
