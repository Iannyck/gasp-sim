"""Consultation rhythms of the team members (extension point ``work_rhythm``, ODD 7.2).

A member reads and writes in the team channel only when they consult it; in between,
they work. Every morning the engine starts a new working day and each member's rhythm
starts again (ADR-0007, ADR-0013): the rhythm gives the consultations of that day.

Version 1 has one component, ``synchronous``: every member consults at the start of the
day and then every ``period_hours``, all at the same moments, as in the article.
Heterogeneous rhythms come later (ODD 7.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Protocol, runtime_checkable

import numpy as np
from pydantic import Field

from gasp_sim.config.base import ComponentParameters, ExactHours
from gasp_sim.core.clock import TimeGrid
from gasp_sim.registry import Component, ExtensionPoint, Registry

__all__ = [
    "WORK_RHYTHM",
    "SynchronousParameters",
    "SynchronousRhythm",
    "WorkRhythm",
    "register_rhythms",
]


@runtime_checkable
class WorkRhythm(Protocol):
    """Gives the consultations of a member during one working day (``work_rhythm``)."""

    def consultations_of_day(
        self, agent: int, grid: TimeGrid, rng: np.random.Generator
    ) -> Sequence[int]:
        """Return the ticks of the day, from 0, at which ``agent`` consults the channel.

        Parameters
        ----------
        agent : int
            The member, from 0.
        grid : TimeGrid
            Time grid of the run.
        rng : numpy.random.Generator
            The ``rhythm`` stream of the member, for rhythms with random parts.

        Returns
        -------
        sequence of int
            Increasing ticks within the day, each in ``[0, grid.ticks_per_day)``.
        """

    def period_ticks(self, grid: TimeGrid) -> int:
        """Return the usual time between two consultations of a member, in ticks.

        Used to warn when a time window of the configuration is shorter than it.
        """


#: Extension point of the consultation rhythms.
WORK_RHYTHM: ExtensionPoint[WorkRhythm] = ExtensionPoint(
    "work_rhythm",
    WorkRhythm,
    summary="When each member consults the team channel during a working day.",
)


class SynchronousParameters(ComponentParameters):
    """Everyone consults at the start of the day and then every period, all together."""

    period_hours: Annotated[ExactHours, Field(gt=0)] = Field(
        default=0.5,
        description="Time between two consultations, in hours; a whole number of ticks.",
    )


@dataclass(frozen=True, slots=True)
class SynchronousRhythm:
    """Consult at the start of the day and every ``period_hours``; no random draw."""

    period_hours: float

    def period_ticks(self, grid: TimeGrid) -> int:
        """Return the period in ticks."""
        return grid.hours_to_ticks_exact(self.period_hours, name="period_hours")

    def consultations_of_day(
        self, agent: int, grid: TimeGrid, rng: np.random.Generator
    ) -> Sequence[int]:
        """Return ``0, period, 2 * period…`` within the day."""
        return range(0, grid.ticks_per_day, self.period_ticks(grid))


def _synchronous(parameters: SynchronousParameters) -> SynchronousRhythm:
    return SynchronousRhythm(parameters.period_hours)


def register_rhythms(registry: Registry) -> None:
    """Add the extension point and its built-in components to ``registry``."""
    registry.add_extension_point(WORK_RHYTHM)
    registry.register(WORK_RHYTHM, Component("synchronous", SynchronousParameters, _synchronous))
