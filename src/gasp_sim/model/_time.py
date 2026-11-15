"""Conversion of configured durations to ticks during a run."""

from __future__ import annotations

import functools
import warnings

from gasp_sim.core.clock import DurationRoundingWarning, TimeGrid

__all__ = ["ticks_of"]


@functools.lru_cache(maxsize=256)
def ticks_of(hours: float, grid: TimeGrid) -> int:
    """Return ``hours`` in ticks of ``grid``, rounded to the nearest tick without warning.

    Durations of a configuration are checked, and their rounding reported, when the file
    is loaded (ADR-0014); components convert them again during the run without repeating
    the warning. Conversions are remembered, since components call this at every
    consultation.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DurationRoundingWarning)
        return grid.hours_to_ticks(hours)
