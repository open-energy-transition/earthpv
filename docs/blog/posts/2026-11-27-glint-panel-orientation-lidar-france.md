---
date: 2026-11-27
slug: glint-panel-orientation-lidar-france
authors:
  - tobias-augspurger
categories:
  - Announcements
---

# Panel orientation from space: a first independent check against LiDAR

What are the tilt and azimuth angles of a solar farm? And when does it generate the most
electricity? A first independent check against IGN LiDAR in France finds an average gap of
1.5° in tilt and 5° in azimuth between the LiDAR and the panel orientations EarthPV reads
from solar glint in Sentinel-2 imagery.

<!-- more -->

At Open Energy Transition we have developed a new method to estimate solar panel
orientation from space, and we made the data open. Now independent researchers in France
have started to validate it, showing very promising first results.

<figure>
  <video controls muted playsinline preload="metadata" width="480"
         style="max-width: 100%; height: auto;"
         poster="../../assets/videos/earthpv_glint_france_year.jpg">
    <source src="../../assets/videos/earthpv_glint_france_year.mp4" type="video/mp4">
    Your browser cannot play this video.
    <a href="../../assets/videos/earthpv_glint_france_year.mp4">Download it (MP4, 1.8 MB)</a>.
  </video>
  <figcaption>
    <strong>Solar glints across France.</strong> Every glint the France survey recorded
    from October 2025 to October 2026, flashing on its date: 8,231 glints from 1,801 of the
    6,337 installations of 1,000 m² or more mapped in OpenStreetMap. 1,277 of them have a
    fitted panel tilt and orientation. Contains modified Copernicus Sentinel data 2025 to
    2026; © OpenStreetMap contributors; geoBoundaries.
  </figcaption>
</figure>

## The LiDAR check

Mohamed Ennhiri, PhD student at CNRS, laboratoire LOCIE, has used IGN LiDAR data to
validate our solar glint orientations across France, with success. His research is part of
his PhD within the DOLMEN project, supervised by Alessia Boccalatte, Stéphan Plassart and
Martin Thebault.

Their initial findings for France indicate an average gap of **1.5° for tilt and 5° for
azimuth** between solar glint and LiDAR. Given the limited time I could invest in the
initial implementation, it will be interesting to see how much this group will be able to
improve the new method.

## How a flash becomes an orientation

A glass-fronted panel is partly a mirror. Sentinel-2 passes over at roughly the same time
each morning, so a fixed panel reflects the Sun into the satellite only on the dates when
its tilt and facing happen to line the two up. The set of dates on which an installation
flashes therefore points to a single panel orientation.

<figure>
  <video controls muted playsinline preload="metadata" width="480"
         style="max-width: 100%; height: auto;"
         poster="../../assets/videos/earthpv_glint_park_provence.jpg">
    <source src="../../assets/videos/earthpv_glint_park_provence.mp4" type="video/mp4">
    Your browser cannot play this video.
    <a href="../../assets/videos/earthpv_glint_park_provence.mp4">Download it (MP4, 5.5 MB)</a>.
  </video>
  <figcaption>
    <strong>A flash of sunlight.</strong> One solar park in Provence in every clear
    Sentinel-2 image from October 2025 to September 2026, shown as delivered. Most images
    show nothing; in late spring and early summer the panels flash at around six times
    their usual near-infrared brightness. The polar plot marks the panel pose that would
    mirror the Sun into the satellite on each date; the flashes fit a tilt of 12.9° facing
    146° (south-east). Contains modified Copernicus Sentinel data 2025 to 2026; outline
    © OpenStreetMap contributors.
  </figcaption>
</figure>

The method, its sensitivity by installation size and the full survey numbers are in
[Panel pose from solar glint](../../results/pv-pose.md) and
[Solar glint](../../methods/glint.md).

## Why this matters for the energy transition

Knowing where solar installations are located and how much capacity they have is not
enough. Their orientation determines when they produce the most electricity. Better
information about panel orientation means:

1. More accurate hourly solar generation models
2. Better electricity grid and storage planning
3. Improved integration of renewable energy into electricity systems

Ultimately, this can support smarter decisions to accelerate power-sector decarbonisation.

## What glint cannot see

The method has limitations. Not all orientations produce observable reflections. With
Sentinel-2, the method works mainly for east-, south-east- and south-facing installations
in the Northern Hemisphere. Clouds, small installations and tracking systems introduce
further challenges. Solar glint is therefore a complementary source of information, not a
universal solution (see
[What glint is and is not good for](../../results/pv-pose.md#what-glint-is-and-is-not-good-for)).

## The data

The panel orientations we have already collected sit on the country atlases, in each
page's panel orientation section:
[France](../../atlas-france.md), [Pakistan](../../atlas.md) and
[India](../../atlas-india.md). More about EarthPV is in the [overview](../../overview.md).

## Get in touch

Interested in collaborating on, supporting or using EarthPV? Interested in building your
own PV atlas on your own PC ([here is how](../../contribute/new-atlas.md))? Get in touch,
through an [issue](https://github.com/open-energy-transition/earthpv/issues) or
[Open Energy Transition](https://openenergytransition.org), and help us build a global,
open dataset and method for mapping the spread of PV revolutions around the world.
