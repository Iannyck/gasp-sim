"""Tests of the deferred logs (gasp_sim.core.deferred)."""

from collections.abc import Sequence

import pytest

from gasp_sim.core.deferred import DeferredLog, LogEntry


def items(entries: Sequence[LogEntry[str]]) -> list[str]:
    return [entry.item for entry in entries]


def test_entries_become_visible_after_the_tick_is_committed() -> None:
    log = DeferredLog[str]("channel")
    log._begin(0)
    log.append("a")
    log.append("b")
    assert items(log.staged) == ["a", "b"]
    assert items(log.visible) == []
    log._commit()
    assert list(log.visible) == [LogEntry(0, "a"), LogEntry(0, "b")]
    assert items(log.staged) == []


def test_entries_are_stamped_with_their_tick() -> None:
    log = DeferredLog[str]("channel")
    for tick, item in [(0, "a"), (3, "b"), (7, "c")]:
        log._begin(tick)
        log.append(item)
        log._commit()
    assert [(entry.tick, entry.item) for entry in log.visible] == [(0, "a"), (3, "b"), (7, "c")]


def test_visible_since_returns_a_time_window() -> None:
    log = DeferredLog[str]("channel")
    for tick, item in [(0, "a"), (2, "b"), (2, "c"), (5, "d")]:
        if log._open_tick != tick:
            if log._open_tick is not None:
                log._commit()
            log._begin(tick)
        log.append(item)
    log._commit()
    assert items(log.visible_since(0)) == ["a", "b", "c", "d"]
    assert items(log.visible_since(2)) == ["b", "c", "d"]
    assert items(log.visible_since(3)) == ["d"]
    assert items(log.visible_since(6)) == []


def test_appending_outside_a_tick_is_refused() -> None:
    log = DeferredLog[str]("channel")
    with pytest.raises(RuntimeError, match="outside a simulation step"):
        log.append("too early")
    log._begin(0)
    log._commit()
    with pytest.raises(RuntimeError, match="outside a simulation step"):
        log.append("between steps")


def test_ticks_must_be_opened_once_and_in_order() -> None:
    log = DeferredLog[str]("channel")
    with pytest.raises(RuntimeError, match="no tick is open"):
        log._commit()
    log._begin(4)
    with pytest.raises(RuntimeError, match="still open"):
        log._begin(5)
    log._commit()
    with pytest.raises(RuntimeError, match="does not follow"):
        log._begin(4)


@pytest.mark.parametrize("name", ["", None, 3])
def test_invalid_name_is_rejected(name: object) -> None:
    with pytest.raises(ValueError, match="name"):
        DeferredLog(name)  # type: ignore[arg-type]
