"""Property-based tests of the simulation loop (ADR-0012)."""

from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from gasp_sim.core.clock import TimeGrid
from gasp_sim.core.context import StepContext
from gasp_sim.core.deferred import DeferredLog
from gasp_sim.core.phases import FunctionPhase
from gasp_sim.core.rng import RandomStreams
from gasp_sim.core.simulation import DayStarted, Simulation

grids = st.sampled_from(
    [
        TimeGrid(),
        TimeGrid(tick_minutes=30, day_minutes=120),
        TimeGrid(tick_minutes=60, day_minutes=60),
        TimeGrid(tick_minutes=15, day_minutes=450),
    ]
)


@dataclass(frozen=True)
class Ping:
    ident: int


@given(grid=grids, ticks=st.integers(min_value=0, max_value=400))
def test_day_starts_are_published_exactly_at_day_boundaries(grid: TimeGrid, ticks: int) -> None:
    starts: list[tuple[int, int]] = []
    simulation = Simulation(phases=[], streams=RandomStreams(seed=0, specs=[]), grid=grid)
    simulation.bus.subscribe(DayStarted, lambda event: starts.append((event.day, event.tick)))
    simulation.run(ticks)
    expected = [
        (tick // grid.ticks_per_day, tick)
        for tick in range(ticks)
        if tick % grid.ticks_per_day == 0
    ]
    assert starts == expected


@given(
    plan=st.lists(
        st.tuples(st.integers(min_value=0, max_value=30), st.integers(min_value=1, max_value=10)),
        max_size=40,
    )
)
def test_events_scheduled_by_phases_arrive_exactly_at_their_tick(
    plan: list[tuple[int, int]],
) -> None:
    """Each (tick, delay) entry: at ``tick``, a phase schedules a ping ``delay`` ticks later."""
    expected: list[tuple[int, int]] = []
    received: list[tuple[int, int]] = []

    def act(context: StepContext) -> None:
        for event in context.events_of_type(Ping):
            received.append((context.tick, event.ident))
        for ident, (when, delay) in enumerate(plan):
            if when == context.tick:
                context.schedule_in(Ping(ident), delay)

    # Within a tick, events come out in scheduling order: by the tick at which they were
    # scheduled, then by their position in the plan.
    order = sorted(range(len(plan)), key=lambda i: (plan[i][0] + plan[i][1], plan[i][0], i))
    expected.extend((plan[i][0] + plan[i][1], i) for i in order)

    simulation = Simulation(
        phases=[FunctionPhase("act", act)], streams=RandomStreams(seed=0, specs=[])
    )
    simulation.run(45)
    assert received == expected
    assert simulation.pending_events == 0


@given(posts=st.lists(st.integers(min_value=0, max_value=3), max_size=30))
def test_nothing_appended_during_a_tick_is_visible_in_that_tick(posts: list[int]) -> None:
    """``posts[t]`` messages are appended at tick ``t``; check what is visible at each tick."""
    log = DeferredLog[int]("channel")
    visible_counts: list[int] = []

    def phase(context: StepContext) -> None:
        visible_counts.append(len(log.visible))
        for _ in range(posts[context.tick]):
            log.append(context.tick)
        assert all(entry.tick < context.tick for entry in log.visible)

    simulation = Simulation(
        phases=[FunctionPhase("post", phase)],
        streams=RandomStreams(seed=0, specs=[]),
        logs=[log],
    )
    simulation.run(len(posts))
    assert visible_counts == [sum(posts[:tick]) for tick in range(len(posts))]
    assert len(log.visible) == sum(posts)
