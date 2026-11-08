"""The simulation loop: one tick after another, in a fixed order (ADR-0012).

Each call to :meth:`Simulation.step` executes one tick ``t``:

1. every registered :class:`~gasp_sim.core.deferred.DeferredLog` is opened for ``t``;
2. if ``t`` is the first tick of a working day, a :class:`DayStarted` notification is
   published, then every *day-start phase* runs, in order, with its own
   :class:`~gasp_sim.core.context.StepContext`; no event of ``t`` has been released yet,
   so these phases (such as work rhythms) can still schedule events for ``t``
   (ADR-0007, ADR-0013);
3. the events scheduled for ``t`` are released from the queue, in order;
4. every phase runs, in order, with the same :class:`~gasp_sim.core.context.StepContext`;
5. every log is committed: entries appended during ``t`` become visible from ``t + 1``;
6. a :class:`StepCompleted` notification is published;
7. the clock advances to ``t + 1``.

If anything fails during a step, the error propagates and the simulation is marked as
failed: further steps raise :class:`SimulationFailedError`, so that no result is drawn
from an inconsistent state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from gasp_sim.core.clock import Clock, TimeGrid
from gasp_sim.core.context import StepContext
from gasp_sim.core.deferred import DeferredLog
from gasp_sim.core.events import EventBus, EventHandle, EventQueue
from gasp_sim.core.phases import Phase
from gasp_sim.core.rng import RandomStreams

__all__ = ["DayStarted", "Simulation", "SimulationFailedError", "StepCompleted"]


@dataclass(frozen=True, slots=True)
class DayStarted:
    """Notification published at the first tick of every working day.

    Attributes
    ----------
    day : int
        The working day that starts, from 0.
    tick : int
        Its first tick.
    """

    day: int
    tick: int


@dataclass(frozen=True, slots=True)
class StepCompleted:
    """Notification published at the end of every tick, after the logs are committed.

    Attributes
    ----------
    tick : int
        The tick that has just been executed.
    day : int
        Its working day.
    """

    tick: int
    day: int


class SimulationFailedError(RuntimeError):
    """Raised when stepping a simulation whose previous step failed."""


class Simulation:
    """Run phases tick after tick, with a clock, an event queue, a bus and logs.

    Parameters
    ----------
    phases : sequence of Phase
        Phases run at every tick, in this order.
    day_start_phases : sequence of Phase, optional
        Phases run only at the first tick of each working day, in this order, before the
        events of that tick are released (ADR-0013). Phase names must be unique across
        both sequences.
    streams : RandomStreams
        Named random streams of the run.
    grid : TimeGrid, optional
        Tick and working-day lengths; 5-minute ticks and 8-hour days if omitted.
    logs : sequence of DeferredLog, optional
        Logs opened and committed at every tick (delayed visibility).
    bus : EventBus, optional
        Notification bus; a new one if omitted. Subscribe to it before running to
        receive :class:`DayStarted` and :class:`StepCompleted`.

    Raises
    ------
    TypeError
        If a phase does not have a ``name`` and a ``run`` method.
    ValueError
        If two phases, or two logs, share a name.
    """

    def __init__(
        self,
        *,
        phases: Sequence[Phase],
        streams: RandomStreams,
        day_start_phases: Sequence[Phase] = (),
        grid: TimeGrid | None = None,
        logs: Sequence[DeferredLog[Any]] = (),
        bus: EventBus | None = None,
    ) -> None:
        self._phases = tuple(phases)
        self._day_start_phases = tuple(day_start_phases)
        _check_unique_phases(self._day_start_phases + self._phases)
        self._logs = tuple(logs)
        _check_unique_names([log.name for log in self._logs], "log")
        self._streams = streams
        self._clock = Clock(grid)
        self._queue: EventQueue[object] = EventQueue()
        self._bus = bus if bus is not None else EventBus()
        self._failed = False

    @property
    def phases(self) -> tuple[Phase, ...]:
        """Phases run at every tick, in order."""
        return self._phases

    @property
    def day_start_phases(self) -> tuple[Phase, ...]:
        """Phases run at the first tick of each working day, in order."""
        return self._day_start_phases

    @property
    def logs(self) -> tuple[DeferredLog[Any], ...]:
        """Logs committed at the end of every tick."""
        return self._logs

    @property
    def streams(self) -> RandomStreams:
        """Named random streams of the run."""
        return self._streams

    @property
    def grid(self) -> TimeGrid:
        """Tick and working-day lengths."""
        return self._clock.grid

    @property
    def bus(self) -> EventBus:
        """Notification bus."""
        return self._bus

    @property
    def next_tick(self) -> int:
        """Tick executed by the next call to :meth:`step` (also the number of ticks run)."""
        return self._clock.tick

    @property
    def failed(self) -> bool:
        """Whether a step has failed; a failed simulation cannot be resumed."""
        return self._failed

    @property
    def pending_events(self) -> int:
        """Number of scheduled events not yet released or cancelled."""
        return len(self._queue)

    def schedule(self, event: object, *, at: int, priority: int = 0) -> EventHandle:
        """Schedule ``event`` for tick ``at``, typically to set up a run before it starts.

        During a run, phases schedule through their :class:`StepContext` instead.

        Raises
        ------
        ValueError
            If ``at`` is not after the last executed tick (ADR-0011).
        """
        return self._queue.schedule(event, at, priority=priority)

    def step(self) -> int:
        """Execute one tick and return it.

        Raises
        ------
        SimulationFailedError
            If a previous step failed.
        """
        if self._failed:
            raise SimulationFailedError(
                "A previous step failed; this simulation cannot be resumed."
            )
        tick = self._clock.tick
        context: StepContext | None = None
        try:
            for log in self._logs:
                log._begin(tick)
            if self._clock.is_day_start:
                self._bus.publish(DayStarted(day=self._clock.day, tick=tick))
                context = self._new_context(tick, events=())
                for phase in self._day_start_phases:
                    phase.run(context)
                context._close()
            released = self._queue.pop_due(tick)
            context = self._new_context(
                tick, events=tuple(scheduled.event for scheduled in released)
            )
            for phase in self._phases:
                phase.run(context)
            for log in self._logs:
                log._commit()
            context._close()
            self._bus.publish(StepCompleted(tick=tick, day=self._clock.day))
            self._clock.advance()
        except BaseException:
            self._failed = True
            if context is not None:
                context._close()
            raise
        return tick

    def run_days(self, days: int) -> None:
        """Execute ``days`` working days, that is ``days`` times the ticks of a day.

        The count starts from the next tick: if the simulation is in the middle of a working
        day, ``run_days(1)`` ends in the middle of the next one, not at the end of the
        current one.

        Raises
        ------
        ValueError
            If ``days`` is not a non-negative integer.
        """
        days_value: object = days
        if not isinstance(days_value, int) or isinstance(days_value, bool) or days < 0:
            raise ValueError(f"days must be a non-negative integer, got {days_value!r}.")
        self.run(days * self._clock.grid.ticks_per_day)

    def run(self, ticks: int) -> None:
        """Execute ``ticks`` consecutive ticks.

        Raises
        ------
        ValueError
            If ``ticks`` is not a non-negative integer.
        """
        ticks_value: object = ticks
        if not isinstance(ticks_value, int) or isinstance(ticks_value, bool) or ticks < 0:
            raise ValueError(f"ticks must be a non-negative integer, got {ticks_value!r}.")
        for _ in range(ticks):
            self.step()

    def _new_context(self, tick: int, *, events: tuple[object, ...]) -> StepContext:
        """Create the context given to phases for ``tick``."""
        return StepContext(
            tick=tick,
            grid=self._clock.grid,
            streams=self._streams,
            events=events,
            queue=self._queue,
            bus=self._bus,
        )


def _check_unique_phases(phases: tuple[Phase, ...]) -> None:
    """Check that every phase has the expected interface and a unique name."""
    for phase in phases:
        phase_value: object = phase
        if not isinstance(phase_value, Phase):
            raise TypeError(
                f"{phase_value!r} is not a phase: it needs a 'name' and a 'run(context)' method."
            )
    _check_unique_names([phase.name for phase in phases], "phase")


def _check_unique_names(names: list[str], kind: str) -> None:
    """Raise if a name appears twice."""
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"Two {kind}s share the name {name!r}.")
        seen.add(name)
