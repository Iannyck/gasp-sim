"""Event queue for future events and synchronous notification bus.

The engine distinguishes two kinds of events (ADR-0011):

- **Scheduled events** happen at a known future tick (an agent's next consultation, the
  proxy's next evaluation, the end of a task). They wait in an :class:`EventQueue`, which
  releases them tick by tick in a total, deterministic order.
- **Notifications** report something that has just happened (a message was published).
  They are delivered at once, through an :class:`EventBus`, to the components that
  subscribed to them, such as the output recorder.

Ordering of the queue: by tick, then by priority (lower values first), then by order of
scheduling. The engine attaches no meaning to priorities; the model defines them
(ODD §3).

Examples
--------
>>> queue = EventQueue[str]()
>>> _ = queue.schedule("consultation", tick=2, priority=1)
>>> _ = queue.schedule("proxy evaluation", tick=2, priority=0)
>>> [scheduled.event for scheduled in queue.pop_due(0)]
[]
>>> [scheduled.event for scheduled in queue.pop_due(2)]
['proxy evaluation', 'consultation']
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["EventBus", "EventHandle", "EventQueue", "ScheduledEvent", "Subscription"]


# --------------------------------------------------------------------------- queue


@dataclass(frozen=True, slots=True)
class EventHandle:
    """Immutable identifier of a scheduled event, used to cancel it.

    Attributes
    ----------
    tick : int
        Tick at which the event is scheduled.
    priority : int
        Priority of the event within its tick (lower values first).
    sequence : int
        Order of scheduling within the queue; breaks ties between equal priorities.
    """

    tick: int
    priority: int
    sequence: int
    _owner: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ScheduledEvent[E]:
    """An event released by the queue, with its scheduling information.

    Attributes
    ----------
    handle : EventHandle
        Identifier returned when the event was scheduled.
    event : E
        The event itself, as given to :meth:`EventQueue.schedule`.
    """

    handle: EventHandle
    event: E

    @property
    def tick(self) -> int:
        """Tick at which the event was scheduled."""
        return self.handle.tick

    @property
    def priority(self) -> int:
        """Priority of the event within its tick."""
        return self.handle.priority


class EventQueue[E]:
    """Queue of events scheduled for future ticks.

    Events are released by :meth:`pop_due`, one tick at a time, ordered by priority
    (lower values first) and then by order of scheduling. Only future events can be
    scheduled: once a tick has been released, nothing can be scheduled for it or for an
    earlier tick (ADR-0011).

    Cancellation is lazy: a cancelled event stays in the internal heap but is never
    released, and is not counted by ``len()``.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, int, E]] = []
        self._pending: set[int] = set()
        self._sequence = itertools.count()
        self._current_tick: int | None = None
        self._token = object()

    def __len__(self) -> int:
        """Return the number of scheduled events that are not cancelled."""
        return len(self._pending)

    @property
    def current_tick(self) -> int | None:
        """Last tick released by :meth:`pop_due`, or ``None`` before the first release."""
        return self._current_tick

    def schedule(self, event: E, tick: int, *, priority: int = 0) -> EventHandle:
        """Schedule ``event`` for a future tick.

        Parameters
        ----------
        event : E
            Event to release at ``tick``.
        tick : int
            Non-negative tick, strictly after the last released tick.
        priority : int, optional
            Order within the tick; lower values are released first (default 0).

        Returns
        -------
        EventHandle
            Identifier that can be passed to :meth:`cancel`.

        Raises
        ------
        ValueError
            If ``tick`` is not a non-negative integer, is not in the future, or if
            ``priority`` is not an integer.
        """
        _check_int(tick, "tick", minimum=0)
        _check_int(priority, "priority")
        if self._current_tick is not None and tick <= self._current_tick:
            raise ValueError(
                f"Cannot schedule an event at tick {tick}: tick {self._current_tick} has "
                f"already been released; only later ticks can be scheduled."
            )
        sequence = next(self._sequence)
        heapq.heappush(self._heap, (tick, priority, sequence, event))
        self._pending.add(sequence)
        return EventHandle(tick, priority, sequence, self._token)

    def cancel(self, handle: EventHandle) -> bool:
        """Cancel a scheduled event.

        Parameters
        ----------
        handle : EventHandle
            Identifier returned by :meth:`schedule` on this queue.

        Returns
        -------
        bool
            ``True`` if the event was pending and is now cancelled; ``False`` if it had
            already been released or cancelled.

        Raises
        ------
        ValueError
            If the handle was issued by another queue.
        """
        if handle._owner is not self._token:
            raise ValueError("This handle was issued by another event queue.")
        if handle.sequence in self._pending:
            self._pending.remove(handle.sequence)
            return True
        return False

    def peek_tick(self) -> int | None:
        """Return the tick of the next pending event, or ``None`` if there is none."""
        self._discard_cancelled_head()
        return self._heap[0][0] if self._heap else None

    def pop_due(self, tick: int) -> list[ScheduledEvent[E]]:
        """Release every pending event scheduled for ``tick``, in order.

        Parameters
        ----------
        tick : int
            Tick to release. It must be later than the last released tick, and no
            pending event may be scheduled before it (it would otherwise be skipped).

        Returns
        -------
        list of ScheduledEvent
            Events scheduled for ``tick``, ordered by priority then order of scheduling.
            Cancelled events are left out.

        Raises
        ------
        ValueError
            If ``tick`` is not a non-negative integer, has already been released, or if
            a pending event is scheduled before it.
        """
        _check_int(tick, "tick", minimum=0)
        if self._current_tick is not None and tick <= self._current_tick:
            raise ValueError(
                f"Tick {tick} cannot be released: tick {self._current_tick} has already "
                f"been released."
            )
        next_tick = self.peek_tick()
        if next_tick is not None and next_tick < tick:
            raise ValueError(
                f"Cannot release tick {tick}: an event is still pending at tick "
                f"{next_tick} and would be skipped."
            )
        self._current_tick = tick
        released: list[ScheduledEvent[E]] = []
        while self._heap and self._heap[0][0] == tick:
            event_tick, priority, sequence, event = heapq.heappop(self._heap)
            if sequence not in self._pending:
                continue
            self._pending.remove(sequence)
            handle = EventHandle(event_tick, priority, sequence, self._token)
            released.append(ScheduledEvent(handle, event))
        return released

    def _discard_cancelled_head(self) -> None:
        """Drop cancelled events from the top of the heap."""
        while self._heap and self._heap[0][2] not in self._pending:
            heapq.heappop(self._heap)


# --------------------------------------------------------------------------- bus


@dataclass(frozen=True, slots=True)
class Subscription:
    """Immutable identifier of a subscription, used to unsubscribe.

    Attributes
    ----------
    event_type : type or None
        Type of notification delivered to the handler, or ``None`` for every
        notification.
    sequence : int
        Order of subscription; handlers are called in this order.
    """

    event_type: type[Any] | None
    sequence: int
    _handler: Callable[[Any], None] = field(repr=False, compare=False)
    _owner: object = field(repr=False, compare=False)


class EventBus:
    """Synchronous notification bus.

    A published notification is delivered immediately to every matching handler, in the
    order of subscription. A handler matches if it subscribed to the exact type of the
    notification (subclasses are not included) or to every notification. Errors raised
    by a handler are not caught: they propagate to the publisher, and the remaining
    handlers are not called (ADR-0011).

    Subscriptions made or cancelled while a notification is being delivered take effect
    from the next publication.
    """

    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []
        self._sequence = itertools.count()
        self._token = object()

    def subscribe[T](self, event_type: type[T], handler: Callable[[T], None]) -> Subscription:
        """Deliver notifications of exactly ``event_type`` to ``handler``.

        Parameters
        ----------
        event_type : type
            Type of notification to receive.
        handler : callable
            Called with each matching notification.

        Returns
        -------
        Subscription
            Identifier that can be passed to :meth:`unsubscribe`.
        """
        event_type_value: object = event_type
        if not isinstance(event_type_value, type):
            raise TypeError(f"event_type must be a class, got {event_type_value!r}.")
        return self._add(event_type, handler)

    def subscribe_all(self, handler: Callable[[object], None]) -> Subscription:
        """Deliver every notification to ``handler``.

        Parameters
        ----------
        handler : callable
            Called with each notification.

        Returns
        -------
        Subscription
            Identifier that can be passed to :meth:`unsubscribe`.
        """
        return self._add(None, handler)

    def unsubscribe(self, subscription: Subscription) -> bool:
        """Stop delivering notifications to a handler.

        Returns
        -------
        bool
            ``True`` if the subscription was active; ``False`` if it had already been
            cancelled.

        Raises
        ------
        ValueError
            If the subscription was issued by another bus.
        """
        if subscription._owner is not self._token:
            raise ValueError("This subscription was issued by another event bus.")
        for index, active in enumerate(self._subscriptions):
            if active.sequence == subscription.sequence:
                del self._subscriptions[index]
                return True
        return False

    def publish(self, event: object) -> None:
        """Deliver ``event`` to every matching handler, in the order of subscription."""
        for subscription in tuple(self._subscriptions):
            if subscription.event_type is None or type(event) is subscription.event_type:
                subscription._handler(event)

    def _add(self, event_type: type[Any] | None, handler: Callable[[Any], None]) -> Subscription:
        """Register a handler and return its subscription."""
        if not callable(handler):
            raise TypeError(f"handler must be callable, got {handler!r}.")
        subscription = Subscription(event_type, next(self._sequence), handler, self._token)
        self._subscriptions.append(subscription)
        return subscription


def _check_int(value: object, name: str, *, minimum: int | None = None) -> None:
    """Raise if ``value`` is not an integer (booleans excluded) at least ``minimum``."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, got {value!r}.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}.")
