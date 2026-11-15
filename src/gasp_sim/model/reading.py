"""Reading habits: which messages a member reads at a consultation (``reading_habit``).

A member sees only the messages of the team channel (with their sender), never the
consultations of colleagues who read without writing. Their reading habit decides which
of the messages published before the consultation they read; everything the member
perceives from the channel comes from these messages (ODD 7.3, step 6 decision D3).

Three components:

- ``recent`` (default): the messages of the last ``hours``;
- ``unread``: every message published since the member's previous consultation, at most
  ``max_hours`` old if set;
- ``last_messages``: the ``messages`` most recent ones, never older than ``max_hours``.
  The age limit is required: without it, a channel silent for days would look as lively
  as its last messages.

Version 1 gives the same habit to the whole team; habits that differ between members
come with heterogeneous rhythms. Habits do not depend on personality.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field

from gasp_sim.config.base import ComponentParameters, Hours
from gasp_sim.core.clock import TimeGrid
from gasp_sim.core.deferred import LogEntry
from gasp_sim.model._time import ticks_of
from gasp_sim.registry import Component, ExtensionPoint, Registry

__all__ = [
    "READING_HABIT",
    "LastMessagesHabit",
    "LastMessagesParameters",
    "Reading",
    "ReadingHabit",
    "RecentHabit",
    "RecentParameters",
    "UnreadHabit",
    "UnreadParameters",
    "register_reading_habits",
]


@dataclass(frozen=True, slots=True)
class Reading[T]:
    """What a member read at one consultation.

    Attributes
    ----------
    entries : sequence of LogEntry
        The messages read, oldest first.
    start_tick : int
        First tick covered by the reading; the reading covers ``[start_tick, tick)``.
    """

    entries: Sequence[LogEntry[T]]
    start_tick: int


@runtime_checkable
class ReadingHabit(Protocol):
    """Chooses the messages a member reads at a consultation (``reading_habit``)."""

    def read[T](
        self,
        visible: Sequence[LogEntry[T]],
        *,
        tick: int,
        previous: int | None,
        grid: TimeGrid,
    ) -> Reading[T]:
        """Return what the member reads.

        Parameters
        ----------
        visible : sequence of LogEntry
            Messages published before ``tick``, oldest first.
        tick : int
            Tick of the consultation.
        previous : int or None
            Tick of the member's previous consultation, if any.
        grid : TimeGrid
            Time grid of the run.
        """

    def window_ticks(self, grid: TimeGrid) -> int | None:
        """Return the longest time a member looks back, in ticks, if it is fixed.

        Used to warn when it is shorter than the time between two consultations.
        """


#: Extension point of the reading habits.
READING_HABIT: ExtensionPoint[ReadingHabit] = ExtensionPoint(
    "reading_habit",
    ReadingHabit,
    summary="Which messages of the team channel a member reads at a consultation.",
)


class RecentParameters(ComponentParameters):
    """Read the messages of the last hours."""

    hours: Annotated[Hours, Field(gt=0)] = Field(
        default=0.5, description="How far back a member reads, in working hours."
    )


class UnreadParameters(ComponentParameters):
    """Read every message published since one's previous consultation."""

    max_hours: Annotated[Hours, Field(gt=0)] | None = Field(
        default=None,
        description="If set, messages older than this are not read, in working hours.",
    )


class LastMessagesParameters(ComponentParameters):
    """Read the most recent messages, up to a number and an age."""

    messages: int = Field(default=20, ge=1, description="Largest number of messages read.")
    max_hours: Annotated[Hours, Field(gt=0)] = Field(
        description="Messages older than this are not read, in working hours (required)."
    )


def _since[T](visible: Sequence[LogEntry[T]], start: int) -> Sequence[LogEntry[T]]:
    """Return the entries of ticks at or after ``start`` (``visible`` is in tick order)."""
    return visible[bisect.bisect_left(visible, start, key=lambda entry: entry.tick) :]


@dataclass(frozen=True, slots=True)
class RecentHabit:
    """Read the messages of the last ``hours``."""

    hours: float

    def window_ticks(self, grid: TimeGrid) -> int:
        """Return the window in ticks."""
        return ticks_of(self.hours, grid)

    def read[T](
        self,
        visible: Sequence[LogEntry[T]],
        *,
        tick: int,
        previous: int | None,
        grid: TimeGrid,
    ) -> Reading[T]:
        """Return the messages of the window ending at ``tick``."""
        start = max(0, tick - self.window_ticks(grid))
        return Reading(_since(visible, start), start)


@dataclass(frozen=True, slots=True)
class UnreadHabit:
    """Read everything since the previous consultation (since the start of the run first)."""

    max_hours: float | None

    def window_ticks(self, grid: TimeGrid) -> int | None:
        """Return the age limit in ticks, if any."""
        if self.max_hours is None:
            return None
        return ticks_of(self.max_hours, grid)

    def read[T](
        self,
        visible: Sequence[LogEntry[T]],
        *,
        tick: int,
        previous: int | None,
        grid: TimeGrid,
    ) -> Reading[T]:
        """Return the messages published since the previous consultation."""
        # Messages written during the previous consultation were not visible then.
        start = previous if previous is not None else 0
        limit = self.window_ticks(grid)
        if limit is not None:
            start = max(start, tick - limit)
        return Reading(_since(visible, start), start)


@dataclass(frozen=True, slots=True)
class LastMessagesHabit:
    """Read the ``messages`` most recent messages, none older than ``max_hours``."""

    messages: int
    max_hours: float

    def window_ticks(self, grid: TimeGrid) -> int:
        """Return the age limit in ticks."""
        return ticks_of(self.max_hours, grid)

    def read[T](
        self,
        visible: Sequence[LogEntry[T]],
        *,
        tick: int,
        previous: int | None,
        grid: TimeGrid,
    ) -> Reading[T]:
        """Return the most recent messages within the age limit.

        The reading covers the whole age limit, or only back to the oldest message read
        when the number of messages is reached.
        """
        start = max(0, tick - self.window_ticks(grid))
        entries = _since(visible, start)
        if len(entries) > self.messages:
            entries = entries[len(entries) - self.messages :]
            start = entries[0].tick
        return Reading(entries, start)


def _recent(parameters: RecentParameters) -> RecentHabit:
    return RecentHabit(parameters.hours)


def _unread(parameters: UnreadParameters) -> UnreadHabit:
    return UnreadHabit(parameters.max_hours)


def _last_messages(parameters: LastMessagesParameters) -> LastMessagesHabit:
    return LastMessagesHabit(parameters.messages, parameters.max_hours)


def register_reading_habits(registry: Registry) -> None:
    """Add the extension point and its built-in components to ``registry``."""
    registry.add_extension_point(READING_HABIT)
    registry.register(READING_HABIT, Component("recent", RecentParameters, _recent))
    registry.register(READING_HABIT, Component("unread", UnreadParameters, _unread))
    registry.register(
        READING_HABIT, Component("last_messages", LastMessagesParameters, _last_messages)
    )
