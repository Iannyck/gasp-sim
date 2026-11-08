"""Example-based tests of the clock and duration conversion (gasp_sim.core.clock)."""

import math

import pytest

from gasp_sim.core.clock import Clock, DurationRoundingWarning, TimeGrid

# --------------------------------------------------------------------------- time grid


def test_default_grid_has_5_minute_ticks_and_96_ticks_per_day() -> None:
    grid = TimeGrid()
    assert grid.tick_minutes == 5
    assert grid.day_minutes == 480
    assert grid.ticks_per_day == 96
    assert grid.tick_hours == pytest.approx(5 / 60)


def test_custom_grid() -> None:
    grid = TimeGrid(tick_minutes=15, day_minutes=450)
    assert grid.ticks_per_day == 30


@pytest.mark.parametrize(
    ("tick_minutes", "day_minutes"),
    [(0, 480), (-5, 480), (5, 0), (2.5, 480), (True, 480), (7, 480)],
)
def test_invalid_grid_is_rejected(tick_minutes: int, day_minutes: int) -> None:
    with pytest.raises(ValueError):
        TimeGrid(tick_minutes=tick_minutes, day_minutes=day_minutes)


# --------------------------------------------------------------------------- conversion


@pytest.mark.parametrize(
    ("hours", "ticks"),
    [(0, 0), (0.5, 6), (1, 12), (2.25, 27), (8, 96), (0.25, 3), (1 / 12, 1)],
)
def test_whole_durations_convert_without_warning(hours: float, ticks: int) -> None:
    # Any warning would fail the test (pytest is configured with filterwarnings = error).
    assert TimeGrid().hours_to_ticks(hours) == ticks
    assert TimeGrid().hours_to_ticks_exact(hours) == ticks


def test_floating_point_noise_is_not_reported_as_rounding() -> None:
    hours = 0.1 + 0.2 + 0.2  # 0.5 h, not exactly representable after these additions
    assert TimeGrid().hours_to_ticks(hours) == 6


def test_rounding_warns_and_names_the_duration() -> None:
    with pytest.warns(DurationRoundingWarning, match=r"silence_threshold: 0\.1 h"):
        ticks = TimeGrid().hours_to_ticks(0.1, name="silence_threshold")  # 6 minutes
    assert ticks == 1


def test_halves_are_rounded_up() -> None:
    grid = TimeGrid(tick_minutes=60, day_minutes=480)
    with pytest.warns(DurationRoundingWarning):
        assert grid.hours_to_ticks(2.5) == 3
    with pytest.warns(DurationRoundingWarning):
        assert grid.hours_to_ticks(3.5) == 4


def test_exact_conversion_refuses_rounding() -> None:
    with pytest.raises(ValueError, match=r"rhythm_period: 0\.1 h is not a whole number"):
        TimeGrid().hours_to_ticks_exact(0.1, name="rhythm_period")


@pytest.mark.parametrize("hours", [-1, math.inf, math.nan])
def test_invalid_hours_are_rejected(hours: float) -> None:
    grid = TimeGrid()
    with pytest.raises(ValueError, match="finite, non-negative"):
        grid.hours_to_ticks(hours)
    with pytest.raises(ValueError, match="finite, non-negative"):
        grid.hours_to_ticks_exact(hours)


@pytest.mark.parametrize("hours", ["1", None, True])
def test_non_numeric_hours_are_rejected(hours: object) -> None:
    with pytest.raises(TypeError, match="number of hours"):
        TimeGrid().hours_to_ticks(hours)  # type: ignore[arg-type]


def test_ticks_to_hours() -> None:
    assert TimeGrid().ticks_to_hours(6) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        TimeGrid().ticks_to_hours(-1)


# --------------------------------------------------------------------------- days


def test_day_boundaries_with_default_grid() -> None:
    grid = TimeGrid()
    assert (grid.day_of(0), grid.tick_of_day(0), grid.is_day_start(0)) == (0, 0, True)
    assert (grid.day_of(95), grid.tick_of_day(95), grid.is_day_start(95)) == (0, 95, False)
    assert (grid.day_of(96), grid.tick_of_day(96), grid.is_day_start(96)) == (1, 0, True)
    assert (grid.day_of(100), grid.tick_of_day(100)) == (1, 4)


@pytest.mark.parametrize("tick", [-1, 1.0, True])
def test_invalid_tick_is_rejected(tick: object) -> None:
    with pytest.raises(ValueError, match="tick"):
        TimeGrid().day_of(tick)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- clock


def test_clock_starts_at_the_beginning_of_day_zero() -> None:
    clock = Clock()
    assert (clock.tick, clock.day, clock.tick_of_day, clock.is_day_start) == (0, 0, 0, True)
    assert clock.hours_elapsed == 0
    assert clock.grid == TimeGrid()


def test_clock_advances_into_the_next_day() -> None:
    clock = Clock()
    for _ in range(95):
        clock.advance()
    assert (clock.tick, clock.day, clock.is_day_start) == (95, 0, False)
    assert clock.advance() == 96
    assert (clock.day, clock.tick_of_day, clock.is_day_start) == (1, 0, True)
    assert clock.hours_elapsed == pytest.approx(8)


def test_clock_uses_a_custom_grid() -> None:
    clock = Clock(TimeGrid(tick_minutes=30, day_minutes=480))
    for _ in range(16):
        clock.advance()
    assert (clock.day, clock.is_day_start) == (1, True)
