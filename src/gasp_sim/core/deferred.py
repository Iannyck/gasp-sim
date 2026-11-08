"""Append-only logs whose entries become visible one tick after they are written.

A :class:`DeferredLog` implements synchronous perception (ADR-0007, ADR-0012): what is
appended during tick ``t`` is *staged* and becomes *visible* from tick ``t + 1``. Agents
consulting at the same tick therefore never see each other's entries of that tick, and
the order in which they are processed has no influence on what they perceive.

The simulation opens every registered log at the start of a tick and commits it at the
end; models only append and read.

Examples
--------
>>> log = DeferredLog[str]("team_channel")
>>> log._begin(0)
>>> log.append("hello")
>>> [entry.item for entry in log.staged], [entry.item for entry in log.visible]
(['hello'], [])
>>> log._commit()
>>> [(entry.tick, entry.item) for entry in log.visible]
[(0, 'hello')]
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["DeferredLog", "LogEntry"]


@dataclass(frozen=True, slots=True)
class LogEntry[T]:
    """One entry of a :class:`DeferredLog`.

    Attributes
    ----------
    tick : int
        Tick during which the entry was appended.
    item : T
        The appended item.
    """

    tick: int
    item: T


class DeferredLog[T]:
    """Append-only log with one-tick delayed visibility.

    Parameters
    ----------
    name : str
        Name of the log, used in messages (for example ``"team_channel"``).

    Notes
    -----
    The sequences returned by :attr:`visible` and :attr:`staged` are read-only views of
    internal storage: do not modify them.
    """

    def __init__(self, name: str) -> None:
        name_value: object = name
        if not isinstance(name_value, str) or not name_value:
            raise ValueError(f"Log name must be a non-empty string, got {name_value!r}.")
        self._name = name
        self._visible: list[LogEntry[T]] = []
        self._visible_ticks: list[int] = []
        self._staged: list[LogEntry[T]] = []
        self._open_tick: int | None = None
        self._last_tick: int | None = None

    @property
    def name(self) -> str:
        """Name of the log."""
        return self._name

    @property
    def visible(self) -> Sequence[LogEntry[T]]:
        """Entries appended before the current tick, oldest first."""
        return self._visible

    @property
    def staged(self) -> Sequence[LogEntry[T]]:
        """Entries appended during the current tick, in order of appending."""
        return self._staged

    def visible_since(self, tick: int) -> Sequence[LogEntry[T]]:
        """Return the visible entries appended at or after ``tick``.

        Useful for time windows, such as the silence window of a proxy.

        Parameters
        ----------
        tick : int
            First tick of the window.

        Returns
        -------
        sequence of LogEntry
            Visible entries with ``entry.tick >= tick``, oldest first.
        """
        start = bisect.bisect_left(self._visible_ticks, tick)
        return self._visible[start:]

    def append(self, item: T) -> None:
        """Append ``item``; it becomes visible from the next tick.

        Raises
        ------
        RuntimeError
            If called outside a tick (before the simulation starts or between steps).
        """
        if self._open_tick is None:
            raise RuntimeError(f"Cannot append to log {self._name!r} outside a simulation step.")
        self._staged.append(LogEntry(self._open_tick, item))

    def _begin(self, tick: int) -> None:
        """Open ``tick`` for appending; called by the simulation."""
        if self._open_tick is not None:
            raise RuntimeError(f"Log {self._name!r}: tick {self._open_tick} is still open.")
        if self._last_tick is not None and tick <= self._last_tick:
            raise RuntimeError(
                f"Log {self._name!r}: tick {tick} does not follow tick {self._last_tick}."
            )
        self._open_tick = tick

    def _commit(self) -> None:
        """Make the entries of the open tick visible; called by the simulation."""
        if self._open_tick is None:
            raise RuntimeError(f"Log {self._name!r}: no tick is open.")
        self._visible.extend(self._staged)
        self._visible_ticks.extend(entry.tick for entry in self._staged)
        self._staged.clear()
        self._last_tick = self._open_tick
        self._open_tick = None
