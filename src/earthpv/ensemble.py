"""Combines sar.py/sppi.py/worldcover.py into one false-positive check, prioritizing
keeping real PV over catching every false positive.

Measured 2026-08-02, same joint population as the individual modules (2,426 OSM-
confirmed real PV, 701 confirmed FP -- vegetation-cycle-refuted + epoch-persistent --
plus the 21 desert/mountain false positives flagged by hand this session):

**Naive voting fails.** "Any one instrument flags it" (OR) costs 22.6% of real PV to
catch 67.3% of confirmed FP -- worse cost than any single instrument. "At least 2 of 3
agree" cuts cost to 3.7%, but the three instruments barely overlap on the desert/
mountain class specifically -- it catches 0/21 of those, throwing away WorldCover's
entire reason for existing. Requiring agreement between instruments that are
*complementary* (each catches a different failure mode) rather than *redundant*
defeats the purpose of combining them.

**What works: gate WorldCover's veto behind SPPI, don't vote them.** WorldCover alone
costs 15.8% of real PV (mostly legitimate ground-mount arrays sited on bare land, see
`worldcover.py`) to catch 76% (16/21) of the desert/mountain class. Restricted to
JUST the candidates WorldCover flags, SPPI's AUC rises to 0.868 (vs. 0.79
unconditionally) -- real ground-mount-on-bare-land reads SPPI ~0.004 (mildly
PV-like), natural bare terrain reads ~-0.068 (clearly not) -- because this is exactly
the "arid ground" regime SPPI's own header calls its weakest, and conditioning on
WorldCover's bare flag isolates precisely the population where that weakness is
concentrated and correctable. S1 does NOT help in this gated regime (AUC 0.48,
chance -- the same mountain-layover mismatch documented in `sar.py`), so it is not
part of this combination; use `--s1-composites-dir` separately if S1 coverage exists.

    veto = WorldCover flags (bare/snow/water) AND SPPI < DEFAULT_SPPI_RESCUE_MIN

Threshold curve (real cost / desert-mountain catch out of 21), all measured on the
same population as above -- pick the point that matches how much real PV you can
afford to lose:

    rescue_min   overall real cost   catch within WC-flagged   catch of the 21
    0.00 (default)   7.3%            85.7%                     11/21
    0.02             11.8%           92.9%                     14/21
    0.05             14.7%           96.4%                     (not separately measured)
    -inf (= plain WorldCover, no rescue) 15.8%   100%           16/21

The default (0.00) roughly halves WorldCover's real-PV cost while keeping most of its
catch power -- explicitly the "don't lose too many true positives" choice. Raise
`sppi_rescue_min` toward 0.05 if catching more of the desert/mountain class matters
more than the added cost.
"""

from __future__ import annotations

import numpy as np

DEFAULT_SPPI_RESCUE_MIN = 0.0


def combined_bare_terrain_veto(
    geoms, aoi: str, cfg: dict, settings, sppi_rescue_min: float = DEFAULT_SPPI_RESCUE_MIN,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`(is_veto, wc_class, sppi_score)`.

    `is_veto` is only True where WorldCover has coverage AND flags bare/snow/water
    AND SPPI also reads non-PV-like (< `sppi_rescue_min`) -- absence of coverage in
    either instrument never vetoes (same contract as every other check in this
    project). Needs no extra data beyond this AOI's own composites plus a WorldCover
    fetch (network, Planetary Computer, no login).
    """
    from earthpv import sppi as sppi_mod
    from earthpv import worldcover

    wc_class, wc_veto = worldcover.candidate_worldcover_veto(geoms)
    sp = sppi_mod.candidate_sppi(geoms, aoi, cfg, settings)
    rescued = np.isfinite(sp) & (sp >= sppi_rescue_min)
    is_veto = wc_veto & ~rescued
    return is_veto, wc_class, sp
