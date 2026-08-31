---
date: 2026-08-25
authors:
  - gabriel-kasmi
categories:
  - Perspectives
---

# A journey into rooftop solar mapping

A guest post by [Gabriel Kasmi](https://www.linkedin.com/in/gabriel-kasmi/),
creator of [DeepPVMapper](https://github.com/gabrielkasmi/deeppvmapper), on how a
PhD side-input became a mapping method, and how that method led to EarthPV.

<!-- more -->

## Meant to be an input

I started mapping rooftop solar at the end of 2020, as a PhD student between the
French transmission system operator, RTE, and PSL University in Paris. Back then,
it was supposed to be an input to improve the accuracy of the rooftop PV
forecasting models. Then the journey took an unexpected turn.

First, mapping rooftop PV systems required training data, and a mapping
algorithm. I didn't start from scratch and could rely on a crowdsourcing campaign
to collect ground truth data - this eventually led to the dataset BDAPPV,
published in early 2022. On the mapping side, I adapted Rausch et al.'s (2020)
pipeline to construct what would become DeepPVMapper.

After a little over six months (we were still in the pre-ChatGPT era), I had a
working algorithm. Then came the grind: mapping all of France. Running the
pipeline over the entirety of France meant preprocessing enormous volumes of
aerial imagery tiles, and it took an embarrassing number of crashed jobs to learn
exactly how much RAM a batch of tiles could quietly eat before the whole thing
died mid-run.

The figure below is what those months of grind actually looked like from the
inside: I must have re-run the script that generates it a countless number of
times, watching one more département shade in with each pass - until the mosaic
below, from Ille-et-Vilaine down to the Var, was finally complete. The map was
supposed to be an input to a more accurate forecasting model. It ended up being
the destination.

<!-- IMAGE PENDING: save Gabriel's France progress mosaic to
     docs/assets/blog/kasmi-france-pv-mosaic.png (create the folder), then
     uncomment the block below. mkdocs build --strict fails until the file exists.
![Progress mosaic of DeepPVMapper's rooftop PV detections across France, département by département, from Ille-et-Vilaine down to the Var.](../../assets/blog/kasmi-france-pv-mosaic.png)

/// caption
DeepPVMapper's rooftop PV detections filling in across France, one département per pass.
///
-->


## A map that says something

In the meantime, the PhD defense was over, and priorities regarding forecasting
models had shifted. I was left with a (now) robust mapping algorithm, and a map.
But what could I do with it?

The first use case came up when comparing the accuracy of the detections with
RTE's connection data. Most of the work consisted in comparing two different sources,
each with their own uncertainties. But how could I turn DeepPVMapper into a
reliable ground truth?

Answering that meant turning noisy, biased detections into something you could
actually compare against a registry. I adapted a Bayesian framework - borrowed
from how ecologists estimate true population sizes from imperfect survey counts -
to convert DeepPVMapper's raw detections into a posterior distribution over
installed capacity, département by département, correcting for the pipeline's own
measured precision and recall.

Nationally, the two independent sources - RTE's connection data and the corrected
remote-sensing estimate - converged to within 3%. That's a strong result on its
own: two methods sharing no input data landing on nearly the same national
number.

But the national total hid the more interesting story. Locally, the agreement
fell apart. Twenty-five départements showed capacity essentially invisible to
RTE's own connection data, and in the worst case, the registry covered only 39%
of the estimated fleet, missing 61% outright. Some of that gap had a clean
mechanism behind it: municipalities served by local distributors rather than the
national incumbent Enedis showed registry coverage roughly 40% lower, purely as
an artefact of a more fragmented reporting chain.

## A map that is useful

That result also planted a more uncomfortable question. In France, this exercise
was a nice-to-have: an independent check on a system that, overall, already
works. The audit found real gaps, but it was checking a foundation that was
already fairly solid.

The real bascule was realizing where this stops being a nice-to-have and becomes
a must-have. The Bayesian correction doesn't need a registry to compare against -
it needs a set of detections and a bounded validation sample. Which means the
method is, if anything, more useful exactly where a country has no reliable
estimate of installed capacity at all, not less.

That's the question that eventually led to EarthPV.

Pakistan is the case we picked first, and not by accident: official statistics
report roughly 6.8 GW of installed solar capacity, while independent estimates go
as high as 47 GW. That's not a rounding error - it's evidence that nobody
actually knows. The obstacle there isn't a lack of registries to audit against;
it's a lack of usable imagery in the first place, since most high-resolution
options are commercial, expensive and restrictively licensed. EarthPV exists to
solve that upstream problem: an open, reproducible pipeline for estimating
rooftop PV from Sentinel-2 imagery alone, an open geospatial foundation model,
and a verification loop with local OpenStreetMap mappers.

Put the two pieces together and the shape of what comes next is fairly clear. One
project learned how to turn imperfect detections into a calibrated,
uncertainty-aware capacity estimate. The other learned how to produce those
detections in places with no high-resolution imagery to fall back on. Neither is
the full answer on its own - but together, they point toward something that
didn't exist when I started in 2020: a grounded, open installed-capacity estimate
for rooftop solar, produced the same way regardless of whether the country in
question has good grid data or none at all.

What's missing isn't more work on the easy cases: better accuracy, finer models,
more characteristics, but a sense of direction toward what's actually hard.
That's what EarthPV is trying to be: a compass, not an answer.
