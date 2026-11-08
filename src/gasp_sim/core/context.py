"""What a phase receives during one tick (ADR-0012).

A :class:`StepContext` gives a phase what it needs for the current tick, and nothing
more: the time, the random streams, the events released for this tick, and two actions,
scheduling a future event and publishing a notification. It does not give access to the
simulation itself, so a phase cannot, for instance, advance the clock. The model's own
state (agents, proxy, climate) lives in the model's objects.

A context is valid only during its tick: once the step is over, its actions raise.
"""

from __future__ import annotations

from gasp_sim.core.clock import TimeGrid
from gasp_sim.core.events import EventBus, EventHandle, EventQueue
from gasp_sim.core.rng import RandomStreams

__all__ = ["StepContext"]


class StepContext:
    """Context of one tick, given to every phase.

    Instances are created by :class:`~gasp_sim.core.simulation.Simulation`; models do
    not create them.

    Parameters
    ----------
    tick : int
        The tick being executed.
    grid : TimeGrid
        Tick and working-day lengths.
    streams : RandomStreams
        Named random streams of the run.
    events : tuple of object
        Events released for this tick, in queue order (priority, then order of
        scheduling).
    queue : EventQueue
        Queue used to schedule future events.
    bus : EventBus
        Bus used to publish notifications.
    """

    __slots__ = ("_bus", "_closed", "_events", "_grid", "_queue", "_streams", "_tick")

    def __init__(
        self,
        *,
        tick: int,
        grid: TimeGrid,
        streams: RandomStreams,
        events: tuple[object, ...],
        queue: EventQueue[object],
        bus: EventBus,
    ) -> None:
        self._tick = tick
        self._grid = grid
        self._streams = streams
        self._events = events
        self._queue = queue
        self._bus = bus
        self._closed = False

    @property
    def tick(self) -> int:
        """The tick being executed."""
        return self._tick

    @property
    def day(self) -> int:
        """Working day of the current tick, starting at 0."""
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
    def grid(self) -> TimeGrid:
        """Tick and working-day lengths, with conversions from hours."""
        return self._grid

    @property
    def streams(self) -> RandomStreams:
        """Named random streams of the run."""
        return self._streams

    @property
    def events(self) -> tuple[object, ...]:
        """Events released for this tick, in queue order."""
        return self._events

    def events_of_type[T](self, event_type: type[T]) -> list[T]:
        """Return the released events of exactly ``event_type``, in queue order."""
        return [event for event in self._events if type(event) is event_type]

    def schedule(self, event: object, *, at: int, priority: int = 0) -> EventHandle:
        """Schedule ``event`` for a later tick ``at``.

        Raises
        ------
        ValueError
            If ``at`` is not strictly after the current tick (ADR-0011).
        RuntimeError
            If the step of this context is over.
        """
        self._check_open()
        return self._queue.schedule(event, at, priority=priority)

    def schedule_in(self, event: object, delay: int, *, priority: int = 0) -> EventHandle:
        """Schedule ``event`` ``delay`` ticks after the current tick.

        Raises
        ------
        ValueError
            If ``delay`` is not a positive integer.
        RuntimeError
            If the step of this context is over.
        """
        delay_value: object = delay
        if not isinstance(delay_value, int) or isinstance(delay_value, bool) or delay < 1:
            raise ValueError(f"delay must be a positive integer, got {delay_value!r}.")
        return self.schedule(event, at=self._tick + delay, priority=priority)

    def cancel(self, handle: EventHandle) -> bool:
        """Cancel a scheduled event; see :meth:`EventQueue.cancel`."""
        self._check_open()
        return self._queue.cancel(handle)

    def publish(self, notification: object) -> None:
        """Publish a notification on the bus; it is delivered immediately."""
        self._check_open()
        self._bus.publish(notification)

    def _close(self) -> None:
        """Invalidate the context at the end of its step; called by the simulation."""
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"The step of tick {self._tick} is over; this context is closed.")
