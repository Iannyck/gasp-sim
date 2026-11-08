"""Tests of the toy chatter example model (examples/toy_chatter)."""

import math
from collections import defaultdict

import pytest

from examples.toy_chatter import run
from examples.toy_chatter.model import ToyChatter, ToyParameters
from gasp_sim.api import StreamMode, TimeGrid

DEFAULT = ToyParameters()


def run_model(
    seed: int = 1,
    days: int = 2,
    parameters: ToyParameters = DEFAULT,
    mode: StreamMode = StreamMode.NAMED,
) -> ToyChatter:
    model = ToyChatter(parameters, seed=seed, mode=mode)
    model.run_days(days)
    return model


# --------------------------------------------------------------------------- reproducibility


def test_same_seed_gives_the_same_run() -> None:
    first, second = run_model(seed=5), run_model(seed=5)
    assert first.decisions == second.decisions
    assert first.participation == second.participation


def test_different_seeds_give_different_runs() -> None:
    assert run_model(seed=5).decisions != run_model(seed=6).decisions


# --------------------------------------------------------------------------- rhythms


def test_every_agent_consults_16_times_per_day_on_its_own_offset() -> None:
    model = run_model(days=3)
    period = model.period
    ticks_per_day = model.grid.ticks_per_day
    by_agent_and_day: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
    for decision in model.decisions:
        by_agent_and_day[(decision.agent, decision.tick // ticks_per_day)].append(decision.tick)

    assert period == 6
    for agent, offset in enumerate(model.offsets):
        assert 0 <= offset < period
        for day in range(3):
            ticks = by_agent_and_day[(agent, day)]
            start = day * ticks_per_day + offset
            assert ticks == list(range(start, start + 16 * period, period))


def test_rhythms_restart_every_morning_with_a_period_that_does_not_divide_the_day() -> None:
    # 45-minute period: 8-hour days do not hold a whole number of periods.
    model = run_model(days=2, parameters=ToyParameters(consultation_period_hours=0.75))
    ticks_per_day = model.grid.ticks_per_day
    for agent, offset in enumerate(model.offsets):
        ticks = [d.tick for d in model.decisions if d.agent == agent]
        assert ticks[0] == offset
        assert offset + ticks_per_day in ticks  # first consultation of day 1


def test_consultation_period_must_be_a_whole_number_of_ticks() -> None:
    with pytest.raises(ValueError, match="consultation_period_hours"):
        ToyChatter(ToyParameters(consultation_period_hours=0.1), seed=1)


# --------------------------------------------------------------------------- perception


def test_agents_consulting_at_the_same_tick_share_the_same_perception() -> None:
    """Synchronous perception: the probability does not depend on processing order."""
    model = run_model(days=2, parameters=ToyParameters(n_agents=6))
    by_tick: defaultdict[int, set[float]] = defaultdict(set)
    for decision in model.decisions:
        by_tick[decision.tick].add(decision.probability)
    assert all(len(probabilities) == 1 for probabilities in by_tick.values())


def test_probability_depends_only_on_messages_visible_before_the_tick() -> None:
    model = run_model(days=2)
    window = model.window
    for decision in model.decisions:
        recent_speakers = {
            entry.item.sender
            for entry in model.channel.visible
            if decision.tick - window <= entry.tick < decision.tick
        }
        assert decision.probability == pytest.approx(
            model.speaking_probability(len(recent_speakers))
        )


def test_participation_counts_the_speakers_of_each_round() -> None:
    model = run_model(days=1)
    for tick, share in model.participation:
        round_decisions = [d for d in model.decisions if d.tick == tick]
        assert share == pytest.approx(sum(d.spoke for d in round_decisions) / len(round_decisions))


# --------------------------------------------------------------------------- feedback


def test_without_feedback_the_probability_is_constant() -> None:
    model = run_model(parameters=ToyParameters(feedback=0.0))
    assert {decision.probability for decision in model.decisions} == {DEFAULT.base_probability}


def test_stronger_feedback_never_reduces_participation() -> None:
    """With common random numbers, raising the feedback can only add speakers.

    The same seed gives the same offsets and the same draw for every consultation, and the
    probability with feedback is never below the base probability.
    """
    for seed in range(5):
        low = run_model(seed=seed, parameters=ToyParameters(feedback=0.0))
        high = run_model(seed=seed, parameters=ToyParameters(feedback=0.6))
        for (tick_low, share_low), (tick_high, share_high) in zip(
            low.participation, high.participation, strict=True
        ):
            assert tick_low == tick_high
            assert share_high >= share_low
        assert high.summary().mean_participation > low.summary().mean_participation


# --------------------------------------------------------------------------- random-stream modes


def test_named_and_single_stream_modes_are_statistically_equivalent() -> None:
    """ADR-0002 verification: results must not depend on how draws are spread among streams.

    Runs are deterministic (fixed seeds), so this test cannot fail by chance from one run of
    the test suite to the next.
    """
    runs = 150
    named = [run_model(seed=s, days=1).summary().mean_participation for s in range(runs)]
    single = [
        run_model(seed=s, days=1, mode=StreamMode.SINGLE).summary().mean_participation
        for s in range(runs)
    ]

    def mean_and_variance(values: list[float]) -> tuple[float, float]:
        mean = sum(values) / len(values)
        return mean, sum((v - mean) ** 2 for v in values) / (len(values) - 1)

    mean_named, var_named = mean_and_variance(named)
    mean_single, var_single = mean_and_variance(single)
    standard_error = math.sqrt(var_named / runs + var_single / runs)
    # Welch z-statistic; |z| > 4 would indicate a real difference between the modes.
    assert abs(mean_named - mean_single) < 4 * standard_error
    assert named != single  # the modes really draw differently


# --------------------------------------------------------------------------- misc


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_agents": 0},
        {"base_probability": 1.5},
        {"base_probability": -0.1},
        {"feedback": -1.0},
        {"window_hours": 0.0},
        {"consultation_period_hours": math.inf},
    ],
)
def test_invalid_parameters_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        ToyParameters(**kwargs)  # type: ignore[arg-type]


def test_custom_grid() -> None:
    model = ToyChatter(DEFAULT, seed=1, grid=TimeGrid(tick_minutes=15, day_minutes=480))
    model.run_days(1)
    assert model.period == 2
    assert model.summary().consultations == DEFAULT.n_agents * 16


def test_run_script_prints_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    run.main(seed=3, days=1)
    output = capsys.readouterr().out
    assert "no scientific value" in output
    assert "mean participation" in output
