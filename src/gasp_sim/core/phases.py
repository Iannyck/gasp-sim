"""Phases: the ordered processes executed at every tick (ADR-0012).

A tick is a sequence of phases, run in a fixed order chosen by the model (for GASP, the
order of ODD §3: proxy, work, consultations, publication, climate, recording). Any object
with a ``name`` and a ``run(context)`` method is a phase; :class:`FunctionPhase` wraps a
plain function.

Examples
--------
>>> def work(context):
...     pass
>>> phase = FunctionPhase("work", work)
>>> phase.name
'work'
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from gasp_sim.core.context import StepContext

__all__ = ["FunctionPhase", "Phase"]


@runtime_checkable
class Phase(Protocol):
    """Interface of a phase.

    Attributes
    ----------
    name : str
        Unique name of the phase within a simulation, used in messages and records.
    """

    @property
    def name(self) -> str:
        """Unique name of the phase."""

    def run(self, context: StepContext) -> None:
        """Execute the phase for the tick described by ``context``."""


@dataclass(frozen=True, slots=True)
class FunctionPhase:
    """A phase defined by a plain function.

    Parameters
    ----------
    name : str
        Unique name of the phase.
    function : callable
        Called with the step context at every tick.
    """

    name: str
    function: Callable[[StepContext], None]

    def run(self, context: StepContext) -> None:
        """Call the wrapped function with ``context``."""
        self.function(context)
