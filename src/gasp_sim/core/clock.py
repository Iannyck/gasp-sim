"""Simulation clock and conversion of durations to ticks.

Simulated time is a sequence of integer ticks of fixed length (5 minutes by default)
covering working time only: a working day (8 hours by default) is a whole number of
ticks, and nights and weekends are skipped (ADR-0003, ADR-0007).

Durations are given in hours in the configuration and converted to ticks here, with two
rules (ADR-0007, ADR-0010):

- :meth:`TimeGrid.hours_to_ticks` rounds to the nearest tick, halves up, and emits a
  :class:`DurationRoundingWarning` whenever rounding changes the value;
- :meth:`TimeGrid.hours_to_ticks_exact` refuses durations that are not a whole number of
  ticks; it is meant for rhythm periods and offsets.

Examples
--------
>>> grid = TimeGrid()
>>> grid.ticks_per_day
96
>>> grid.hours_to_ticks(0.5)
6
>>> grid.day_of(100), grid.tick_of_day(100)
(1, 4)
"""

from __future__ import annotations

import math
import numbers
import warnings
from dataclasses import dataclass

__all__ = ["Clock", "DurationRoundingWarning", "TimeGrid"]

#: Relative tolerance under which a duration counts as a whole number of ticks. It absorbs
#: floating-point noise (0.1 h is not exactly representable) without hiding real rounding.
_TOLERANCE = 1e-9


class DurationRoundingWarning(UserWarning):
    """Warning emitted when a duration is rounded to a whole number of ticks."""


@dataclass(frozen=True, slots=True)
class TimeGrid:
    """Length of a tick and of a working day.

    Parameters
    ----------
    tick_minutes : int, optional
        Length of a tick in minutes (default 5).
    day_minutes : int, optional
        Length of a working day in minutes (default 480, that is 8 hours). Must be a
        multiple of ``tick_minutes``.

    Raises
    ------
    ValueError
        If a length is not a positive integer, or if the working day is not a whole
        number of ticks.
    """

    tick_minutes: int = 5
    day_minutes: int = 480

    def __post_init__(self) -> None:
        """Validate the lengths."""
        for field_name in ("tick_minutes", "day_minutes"):
            value: object = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer, got {value!r}.")
        if self.day_minutes % self.tick_minutes != 0:
            raise ValueError(
                f"The working day ({self.day_minutes} min) must be a whole number of "
                f"{self.tick_minutes}-minute ticks."
            )

    @property
    def ticks_per_day(self) -> int:
        """Number of ticks in a working day."""
        return self.day_minutes // self.tick_minutes

    @property
    def tick_hours(self) -> float:
        """Length of a tick in hours."""
        return self.tick_minutes / 60

    def ticks_to_hours(self, ticks: int) -> float:
        """Convert a number of ticks to working hours.

        Parameters
        ----------
        ticks : int
            Non-negative number of ticks.

        Returns
        -------
        float
            Duration in hours.
        """
        _check_tick(ticks, "ticks")
        return ticks * self.tick_minutes / 60

    def hours_to_ticks(self, hours: float, *, name: str = "duration") -> int:
        """Convert a duration in hours to ticks, rounding to the nearest tick.

        Halves are rounded up. A :class:`DurationRoundingWarning` is emitted whenever the
        duration is not a whole number of ticks.

        Parameters
        ----------
        hours : float
            Finite, non-negative duration in hours.
        name : str, optional
            Name of the duration, used in messages (for example ``"silence_threshold"``).

        Returns
        -------
        int
            Number of ticks.

        Raises
        ------
        TypeError
            If ``hours`` is not a real number.
        ValueError
            If ``hours`` is negative, infinite or NaN.
        """
        exact = self._exact_ticks(hours, name)
        whole = _as_whole(exact)
        if whole is not None:
            return whole
        ticks = math.floor(exact + 0.5)
        warnings.warn(
            f"{name}: {float(hours):g} h is not a whole number of {self.tick_minutes}-minute "
            f"ticks; rounded to {ticks} ticks ({self.ticks_to_hours(ticks):g} h).",
            DurationRoundingWarning,
            stacklevel=2,
        )
        return ticks

    def hours_to_ticks_exact(self, hours: float, *, name: str = "duration") -> int:
        """Convert a duration in hours to ticks, refusing any rounding.

        Meant for rhythm periods and offsets, which must be whole numbers of ticks
        (ADR-0007).

        Parameters
        ----------
        hours : float
            Finite, non-negative duration in hours.
        name : str, optional
            Name of the duration, used in messages.

        Returns
        -------
        int
            Number of ticks.

        Raises
        ------
        TypeError
            If ``hours`` is not a real number.
        ValueError
            If ``hours`` is negative, infinite, NaN or not a whole number of ticks.
        """
        whole = _as_whole(self._exact_ticks(hours, name))
        if whole is None:
            raise ValueError(
                f"{name}: {float(hours):g} h is not a whole number of "
                f"{self.tick_minutes}-minute ticks."
            )
        return whole

    def day_of(self, tick: int) -> int:
        """Return the working day (starting at 0) that contains ``tick``."""
        _check_tick(tick, "tick")
        return tick // self.ticks_per_day

    def tick_of_day(self, tick: int) -> int:
        """Return the position of ``tick`` within its working day (starting at 0)."""
        _check_tick(tick, "tick")
        return tick % self.ticks_per_day

    def is_day_start(self, tick: int) -> bool:
        """Return whether ``tick`` is the first tick of a working day."""
        return self.tick_of_day(tick) == 0

    def _exact_ticks(self, hours: float, name: str) -> float:
        """Validate ``hours`` and return the exact, possibly fractional, number of ticks."""
        value: object = hours
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            raise TypeError(f"{name} must be a number of hours, got {value!r}.")
        hours_value = float(value)
        if not math.isfinite(hours_value) or hours_value < 0:
            raise ValueError(
                f"{name} must be a finite, non-negative number of hours, got {value!r}."
            )
        return hours_value * 60 / self.tick_minutes


class Clock:
    """Current simulated time, as a tick on a :class:`TimeGrid`.

    The clock starts at tick 0, the first tick of working day 0, and only moves forward.

    Parameters
    ----------
    grid : TimeGrid, optional
        Tick and working-day lengths; the default grid (5-minute ticks, 8-hour days) if
        omitted.
    """

    def __init__(self, grid: TimeGrid | None = None) -> None:
        self._grid = grid if grid is not None else TimeGrid()
        self._tick = 0

    @property
    def grid(self) -> TimeGrid:
        """Tick and working-day lengths."""
        return self._grid

    @property
    def tick(self) -> int:
        """Current tick."""
        return self._tick

    @property
    def day(self) -> int:
        """Current working day, starting at 0."""
        return self._grid.day_of(self._tick)

    @property
    def tick_of_day(self) -> int:
        """Position of the current tick within its working day, starting at 0."""
        return self._grid.tick_of_day(self._tick)

    @property
    def is_day_start(self) -> bool:
        """Whether the current tick is the first tick of a working day."""
        return self._grid.is_day_start(self._tick)

    @property
    def hours_elapsed(self) -> float:
        """Working hours elapsed since tick 0."""
        return self._grid.ticks_to_hours(self._tick)

    def advance(self) -> int:
        """Move to the next tick and return it."""
        self._tick += 1
        return self._tick


def _as_whole(exact_ticks: float) -> int | None:
    """Return the integer equal to ``exact_ticks`` within tolerance, or ``None``."""
    candidate = round(exact_ticks)
    if abs(exact_ticks - candidate) <= _TOLERANCE * max(1.0, abs(exact_ticks)):
        return int(candidate)
    return None


def _check_tick(value: object, name: str) -> None:
    """Raise if ``value`` is not a non-negative integer."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}.")
