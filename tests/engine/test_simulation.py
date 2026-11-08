"""Tests of the simulation loop, the phases and the step context (ADR-0012)."""

from dataclasses import dataclass

import pytest

from gasp_sim.core.clock import TimeGrid
from gasp_sim.core.context import StepContext
from gasp_sim.core.deferred import DeferredLog
from gasp_sim.core.phases import FunctionPhase, Phase
from gasp_sim.core.rng import RandomStreams, StreamScope, StreamSpec
from gasp_sim.core.simulation import (
    DayStarted,
    Simulation,
    SimulationFailedError,
    StepCompleted,
)

SPECS = [StreamSpec("speech", 0, StreamScope.AGENT)]

# A small grid keeps day boundaries close: 4 ticks of 30 minutes per working day.
SMALL_GRID = TimeGrid(tick_minutes=30, day_minutes=120)


def streams(seed: int = 1) -> RandomStreams:
    return RandomStreams(seed=seed, specs=SPECS)


@dataclass(frozen=True)
class Consultation:
    agent: int


@dataclass(frozen=True)
class ProxyEvaluation:
    pass


class Recorder:
    """Phase that records what it sees, to check order and context."""

    def __init__(self, name: str, trace: list[tuple[str, int]]) -> None:
        self._name = name
        self._trace = trace

    @property
    def name(self) -> str:
        return self._name

    def run(self, context: StepContext) -> None:
        self._trace.append((self._name, context.tick))


# --------------------------------------------------------------------------- loop


def test_phases_run_in_order_at_every_tick() -> None:
    trace: list[tuple[str, int]] = []
    simulation = Simulation(
        phases=[Recorder("proxy", trace), Recorder("work", trace), Recorder("talk", trace)],
        streams=streams(),
    )
    simulation.run(2)
    assert trace == [
        ("proxy", 0),
        ("work", 0),
        ("talk", 0),
        ("proxy", 1),
        ("work", 1),
        ("talk", 1),
    ]
    assert simulation.next_tick == 2


def test_step_returns_the_executed_tick() -> None:
    simulation = Simulation(phases=[], streams=streams())
    assert [simulation.step() for _ in range(3)] == [0, 1, 2]


def test_context_describes_the_current_tick() -> None:
    seen: list[tuple[int, int, int, bool]] = []

    def look(context: StepContext) -> None:
        seen.append((context.tick, context.day, context.tick_of_day, context.is_day_start))
        assert context.grid == SMALL_GRID

    simulation = Simulation(
        phases=[FunctionPhase("look", look)], streams=streams(), grid=SMALL_GRID
    )
    simulation.run(6)
    assert seen == [
        (0, 0, 0, True),
        (1, 0, 1, False),
        (2, 0, 2, False),
        (3, 0, 3, False),
        (4, 1, 0, True),
        (5, 1, 1, False),
    ]


def test_run_rejects_invalid_counts() -> None:
    simulation = Simulation(phases=[], streams=streams())
    for ticks in (-1, 1.5, True):
        with pytest.raises(ValueError, match="ticks"):
            simulation.run(ticks)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- events


def test_released_events_reach_the_phases_in_queue_order() -> None:
    received: list[tuple[int, object]] = []

    def collect(context: StepContext) -> None:
        received.extend((context.tick, event) for event in context.events)

    simulation = Simulation(phases=[FunctionPhase("collect", collect)], streams=streams())
    simulation.schedule(Consultation(2), at=1, priority=1)
    simulation.schedule(ProxyEvaluation(), at=1, priority=0)
    simulation.schedule(Consultation(1), at=1, priority=1)
    simulation.schedule(Consultation(3), at=3)
    simulation.run(4)
    assert received == [
        (1, ProxyEvaluation()),
        (1, Consultation(2)),
        (1, Consultation(1)),
        (3, Consultation(3)),
    ]
    assert simulation.pending_events == 0


def test_phases_pick_their_own_events_by_type() -> None:
    consultations: list[Consultation] = []
    evaluations: list[ProxyEvaluation] = []
    simulation = Simulation(
        phases=[
            FunctionPhase("proxy", lambda c: evaluations.extend(c.events_of_type(ProxyEvaluation))),
            FunctionPhase("talk", lambda c: consultations.extend(c.events_of_type(Consultation))),
        ],
        streams=streams(),
    )
    simulation.schedule(Consultation(1), at=0)
    simulation.schedule(ProxyEvaluation(), at=0)
    simulation.step()
    assert consultations == [Consultation(1)]
    assert evaluations == [ProxyEvaluation()]


def test_phases_schedule_future_events() -> None:
    received: list[tuple[int, Consultation]] = []

    def consult(context: StepContext) -> None:
        for event in context.events_of_type(Consultation):
            received.append((context.tick, event))
            context.schedule_in(event, 2)

    simulation = Simulation(phases=[FunctionPhase("consult", consult)], streams=streams())
    simulation.schedule(Consultation(7), at=0)
    simulation.run(5)
    assert [tick for tick, _ in received] == [0, 2, 4]


def test_scheduling_for_the_current_tick_fails_the_simulation() -> None:
    def bad(context: StepContext) -> None:
        context.schedule(Consultation(1), at=context.tick)

    simulation = Simulation(phases=[FunctionPhase("bad", bad)], streams=streams())
    with pytest.raises(ValueError, match="only later ticks"):
        simulation.step()
    assert simulation.failed


def test_schedule_in_requires_a_positive_delay() -> None:
    errors: list[str] = []

    def check(context: StepContext) -> None:
        for delay in (0, -1, 1.0):
            try:
                context.schedule_in(Consultation(1), delay)  # type: ignore[arg-type]
            except ValueError as error:
                errors.append(str(error))

    Simulation(phases=[FunctionPhase("check", check)], streams=streams()).step()
    assert len(errors) == 3
    assert all("delay" in error for error in errors)


def test_phases_can_cancel_scheduled_events() -> None:
    received: list[object] = []

    def phase(context: StepContext) -> None:
        received.extend(context.events)
        if context.tick == 0:
            handle = context.schedule(Consultation(1), at=2)
            assert context.cancel(handle) is True

    simulation = Simulation(phases=[FunctionPhase("p", phase)], streams=streams())
    simulation.run(3)
    assert received == []


# --------------------------------------------------------------------------- notifications


def test_day_start_is_published_first_and_can_schedule_for_the_same_tick() -> None:
    order: list[str] = []
    simulation = Simulation(
        phases=[
            FunctionPhase(
                "talk",
                lambda c: order.extend(f"consult@{c.tick}" for _ in c.events_of_type(Consultation)),
            )
        ],
        streams=streams(),
        grid=SMALL_GRID,
    )

    def on_day_start(event: DayStarted) -> None:
        order.append(f"day{event.day}@{event.tick}")
        # A work rhythm resets in the morning: first consultation at the start of the day.
        simulation.schedule(Consultation(0), at=event.tick)

    simulation.bus.subscribe(DayStarted, on_day_start)
    simulation.run(9)
    assert order == [
        "day0@0",
        "consult@0",
        "day1@4",
        "consult@4",
        "day2@8",
        "consult@8",
    ]


def test_step_completed_is_published_after_logs_are_committed() -> None:
    channel = DeferredLog[str]("channel")
    completed: list[tuple[int, int, int]] = []

    def on_completed(event: StepCompleted) -> None:
        completed.append((event.tick, event.day, len(channel.visible)))

    simulation = Simulation(
        phases=[FunctionPhase("post", lambda c: channel.append(f"m{c.tick}"))],
        streams=streams(),
        grid=SMALL_GRID,
        logs=[channel],
    )
    simulation.bus.subscribe(StepCompleted, on_completed)
    simulation.run(5)
    assert completed == [(0, 0, 1), (1, 0, 2), (2, 0, 3), (3, 0, 4), (4, 1, 5)]


def test_phases_can_publish_notifications() -> None:
    seen: list[object] = []
    simulation = Simulation(
        phases=[FunctionPhase("announce", lambda c: c.publish(("message", c.tick)))],
        streams=streams(),
    )
    simulation.bus.subscribe(tuple, seen.append)
    simulation.run(2)
    assert seen == [("message", 0), ("message", 1)]


# --------------------------------------------------------------------------- synchronous perception


def test_entries_of_a_tick_are_seen_only_from_the_next_tick() -> None:
    channel = DeferredLog[str]("channel")
    perceived: list[tuple[int, str, list[str]]] = []

    def consult(context: StepContext) -> None:
        for agent in ("alice", "bob"):
            # Each agent sees only what was visible before this tick ...
            perceived.append((context.tick, agent, [e.item for e in channel.visible]))
            # ... and posts a message that the other cannot see during this tick.
            channel.append(f"{agent}@{context.tick}")

    def climate(context: StepContext) -> None:
        # End-of-tick processes can read what was posted during the tick.
        assert [e.item for e in channel.staged] == [f"alice@{context.tick}", f"bob@{context.tick}"]

    simulation = Simulation(
        phases=[FunctionPhase("consult", consult), FunctionPhase("climate", climate)],
        streams=streams(),
        logs=[channel],
    )
    simulation.run(2)
    assert perceived == [
        (0, "alice", []),
        (0, "bob", []),
        (1, "alice", ["alice@0", "bob@0"]),
        (1, "bob", ["alice@0", "bob@0"]),
    ]


# --------------------------------------------------------------------------- failures


def test_a_failing_phase_stops_the_simulation_for_good() -> None:
    calls: list[int] = []

    def fragile(context: StepContext) -> None:
        calls.append(context.tick)
        if context.tick == 1:
            raise RuntimeError("phase failed")

    simulation = Simulation(phases=[FunctionPhase("fragile", fragile)], streams=streams())
    simulation.step()
    with pytest.raises(RuntimeError, match="phase failed"):
        simulation.step()
    assert simulation.failed
    with pytest.raises(SimulationFailedError):
        simulation.step()
    assert calls == [0, 1]
    assert simulation.next_tick == 1


def test_a_failing_notification_handler_also_stops_the_simulation() -> None:
    simulation = Simulation(phases=[], streams=streams())

    def broken(event: DayStarted) -> None:
        raise RuntimeError("rhythm failed")

    simulation.bus.subscribe(DayStarted, broken)
    with pytest.raises(RuntimeError, match="rhythm failed"):
        simulation.step()
    assert simulation.failed
    with pytest.raises(SimulationFailedError):
        simulation.step()


def test_a_context_cannot_be_used_after_its_step() -> None:
    kept: list[StepContext] = []
    simulation = Simulation(phases=[FunctionPhase("keep", kept.append)], streams=streams())
    simulation.step()
    (context,) = kept
    with pytest.raises(RuntimeError, match="context is closed"):
        context.schedule(Consultation(1), at=5)
    with pytest.raises(RuntimeError, match="context is closed"):
        context.publish("late")


def test_phases_must_have_a_name_and_a_run_method() -> None:
    with pytest.raises(TypeError, match="not a phase"):
        Simulation(phases=[object()], streams=streams())  # type: ignore[list-item]


def test_phase_and_log_names_must_be_unique() -> None:
    with pytest.raises(ValueError, match="phases share the name 'a'"):
        Simulation(
            phases=[FunctionPhase("a", lambda c: None), FunctionPhase("a", lambda c: None)],
            streams=streams(),
        )
    with pytest.raises(ValueError, match="logs share the name 'x'"):
        Simulation(phases=[], streams=streams(), logs=[DeferredLog("x"), DeferredLog("x")])


def test_function_phase_satisfies_the_protocol() -> None:
    assert isinstance(FunctionPhase("p", lambda c: None), Phase)


def test_properties_expose_the_setup() -> None:
    log = DeferredLog[str]("channel")
    phase = FunctionPhase("p", lambda c: None)
    run_streams = streams()
    simulation = Simulation(phases=[phase], streams=run_streams, grid=SMALL_GRID, logs=[log])
    assert simulation.phases == (phase,)
    assert simulation.logs == (log,)
    assert simulation.streams is run_streams
    assert simulation.grid == SMALL_GRID
    assert not simulation.failed


# --------------------------------------------------------------------------- determinism


def run_toy(seed: int) -> list[tuple[int, int, float]]:
    """Agents draw from their own stream at each consultation; returns the trace."""
    trace: list[tuple[int, int, float]] = []

    def consult(context: StepContext) -> None:
        for event in context.events_of_type(Consultation):
            draw = float(context.streams.agent("speech", event.agent).random())
            trace.append((context.tick, event.agent, draw))
            context.schedule_in(event, 1 + event.agent)

    simulation = Simulation(phases=[FunctionPhase("consult", consult)], streams=streams(seed))
    for agent in range(3):
        simulation.schedule(Consultation(agent), at=0)
    simulation.run(20)
    return trace


def test_same_seed_gives_the_same_run() -> None:
    assert run_toy(42) == run_toy(42)
    assert run_toy(42) != run_toy(43)
