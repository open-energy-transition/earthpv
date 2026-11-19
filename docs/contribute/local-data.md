# Share a local dataset

Most countries already count some of their solar, and a person who knows the country often
knows where. Finding that count is stage 5 of the [mapping flywheel](index.md), and it needs
nothing but a browser. Useful sources include:

- a national or regional **register** of PV installations, or a grid operator's list of
  connections;
- figures from the **statistics office, energy ministry or regulator**, best of all per
  province or district;
- a utility's **net-metering** or subsidy records;
- a **published study**, thesis or report with its own estimate, or local mapping of solar
  or rooftops.

## What happens to it

Each one is read for what it actually counts (registered or installed, AC or DC, rooftop or
ground, above which size, as of which date) and for its licence, then drawn beside the
estimate in the atlas's *Against official and published figures* section, nationally and
per province. It is never used to score the map, because none of them is ground truth for
it: a register counts what is registered, a study what its own method sees.

A register that is legally complete and geolocated can go further and calibrate the
estimate, as Germany's [MaStR](../methods/mastr-validation.md) does for its small
installations; France's [ODRE register](../methods/france-validation.md) measured how much
capacity a square metre of panel carries. That is one of the two ways a country reaches
Gold ([quality levels](index.md#how-a-country-moves-up)); complete
[calibration areas](calibration-areas.md) are the other.

## Point us to it

[Open an issue](https://github.com/open-energy-transition/earthpv/issues/new) with a link,
its licence, the date it refers to, and what it counts if you know. A dataset we may only
read, not reuse, is still worth a comparison.

An LLM assistant is good at this part: finding a country's register or statistics, reading a
report in another language, turning a PDF table into a spreadsheet and working out what a
figure counts. India's register was fetched and read this way. Check what it tells you
against the source before you send it.
