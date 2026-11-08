"""Property-based tests of the clock and duration conversion (ADR-0007, ADR-0010)."""

import warnings

from hypothesis import given
from hypothesis import strategies as st

from gasp_sim.core.clock import Clock, DurationRoundingWarning, TimeGrid

# Grids whose working day is a whole number of ticks.
grids = st.sampled_from(
    [
        TimeGrid(),
        TimeGrid(tick_minutes=1, day_minutes=480),
        TimeGrid(tick_minutes=10, day_minutes=480),
        TimeGrid(tick_minutes=15, day_minutes=450),
        TimeGrid(tick_minutes=30, day_minutes=480),
        TimeGrid(tick_minutes=60, day_minutes=420),
    ]
)
hours_values = st.floats(min_value=0, max_value=10_000, allow_nan=False, allow_infinity=False)


@given(grid=grids, ticks=st.integers(min_value=0, max_value=10**6))
def test_whole_numbers_of_ticks_convert_exactly_and_silently(grid: TimeGrid, ticks: int) -> None:
    hours = ticks * grid.tick_minutes / 60
    # A rounding warning here would fail the test (filterwarnings = error).
    assert grid.hours_to_ticks(hours) == ticks
    assert grid.hours_to_ticks_exact(hours) == ticks


@given(grid=grids, hours=hours_values)
def test_rounding_error_is_at_most_half_a_tick(grid: TimeGrid, hours: float) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ticks = grid.hours_to_ticks(hours)
    exact = hours * 60 / grid.tick_minutes
    warned = any(issubclass(w.category, DurationRoundingWarning) for w in caught)

    assert abs(ticks - exact) <= 0.5 + 1e-9 * max(1.0, exact)
    if warned:
        # A warning means the duration really was changed.
        assert abs(ticks - exact) > 1e-9 * max(1.0, exact)
    else:
        # No warning means the conversion was exact (up to floating-point noise).
        assert abs(ticks - exact) <= 1e-9 * max(1.0, exact)


@given(grid=grids, tick=st.integers(min_value=0, max_value=10**8))
def test_day_decomposition_is_consistent(grid: TimeGrid, tick: int) -> None:
    day = grid.day_of(tick)
    position = grid.tick_of_day(tick)
    assert day * grid.ticks_per_day + position == tick
    assert 0 <= position < grid.ticks_per_day
    assert grid.is_day_start(tick) == (position == 0)


@given(grid=grids, steps=st.integers(min_value=0, max_value=2_000))
def test_clock_matches_the_grid_after_any_number_of_steps(grid: TimeGrid, steps: int) -> None:
    clock = Clock(grid)
    for _ in range(steps):
        clock.advance()
    assert clock.tick == steps
    assert clock.day == grid.day_of(steps)
    assert clock.is_day_start == grid.is_day_start(steps)
