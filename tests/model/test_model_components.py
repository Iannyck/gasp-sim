"""Tests of the built-in components of the GASP model (step 6.1)."""

import math
import statistics

import numpy as np
import pytest
from pydantic import ValidationError

from gasp_sim.api import ExtensionPoint, LogEntry, Registry, TimeGrid
from gasp_sim.model.climate import EmaParameters, EmaRule, ThresholdRule
from gasp_sim.model.config import default_registry
from gasp_sim.model.distributions import (
    BetaDistribution,
    BetaParameters,
    ConstantDistribution,
    UniformDistribution,
    UniformParameters,
    beta_sd_limit,
)
from gasp_sim.model.expression import (
    LinearParameters,
    LinearProbability,
    LogisticProbability,
    SpeakerView,
)
from gasp_sim.model.perception import (
    IndividualMemoryParameters,
    IndividualMemoryPerception,
    SharedPerception,
)
from gasp_sim.model.reading import LastMessagesHabit, RecentHabit, UnreadHabit
from gasp_sim.model.rhythms import SynchronousParameters, SynchronousRhythm

GRID = TimeGrid()


def rng(seed: int = 1) -> np.random.Generator:
    return np.random.default_rng(seed)


# --------------------------------------------------------------------------- registry


def test_every_extension_point_has_its_built_in_components() -> None:
    registry = default_registry()
    names = {
        point.name: registry.component_names(point)
        for point in registry.extension_points
        if isinstance(point, ExtensionPoint)
    }
    assert names == {
        "climate_perception": ("individual_memory", "shared"),
        "climate_rule": ("ema", "threshold"),
        "distribution": ("beta", "constant", "uniform"),
        "expression_probability": ("linear", "logistic"),
        "reading_habit": ("last_messages", "recent", "unread"),
        "work_rhythm": ("synchronous",),
    }
    assert [preset.name for preset in registry.presets] == ["article", "article_threshold"]


def test_registries_are_independent() -> None:
    assert default_registry() is not default_registry()
    assert isinstance(default_registry(), Registry)


# --------------------------------------------------------------------------- distributions


def test_uniform_distribution() -> None:
    values = [UniformDistribution(0.2, 0.4).draw(rng(seed)) for seed in range(200)]
    assert all(0.2 <= value <= 0.4 for value in values)
    assert UniformDistribution(0.3, 0.3).draw(rng()) == 0.3
    with pytest.raises(ValidationError, match=r"low \(0.6\) must not exceed high \(0.4\)"):
        UniformParameters(low=0.6, high=0.4)


def test_beta_distribution_has_the_requested_mean_and_spread() -> None:
    generator = rng(7)
    values = [BetaDistribution(0.6, 0.15).draw(generator) for _ in range(20_000)]
    assert statistics.fmean(values) == pytest.approx(0.6, abs=0.005)
    assert statistics.stdev(values) == pytest.approx(0.15, abs=0.005)
    assert all(0 <= value <= 1 for value in values)


def test_beta_without_spread_gives_the_mean_without_drawing() -> None:
    generator = rng()
    state = generator.bit_generator.state
    assert BetaDistribution(0.3, 0.0).draw(generator) == 0.3
    assert generator.bit_generator.state == state


def test_beta_spread_must_be_possible() -> None:
    assert beta_sd_limit(0.5) == 0.5
    assert beta_sd_limit(0.9) == pytest.approx(0.3)
    BetaParameters(mean=0.9, sd=0.29)
    with pytest.raises(ValidationError, match=r"sd must be smaller than 0.3 for a mean of 0.9"):
        BetaParameters(mean=0.9, sd=0.3)


def test_constant_distribution_does_not_draw() -> None:
    generator = rng()
    state = generator.bit_generator.state
    assert ConstantDistribution(0.4).draw(generator) == 0.4
    assert generator.bit_generator.state == state


# --------------------------------------------------------------------------- rhythms


def test_synchronous_rhythm() -> None:
    rhythm = SynchronousRhythm(0.5)
    assert list(rhythm.consultations_of_day(3, GRID, rng())) == list(range(0, 96, 6))
    assert rhythm.period_ticks(GRID) == 6
    assert len(SynchronousRhythm(1.25).consultations_of_day(0, GRID, rng())) == 7
    with pytest.raises(ValidationError, match="greater than 0"):
        SynchronousParameters(period_hours=0)


# --------------------------------------------------------------------------- reading habits


def entries(*ticks: int) -> list[LogEntry[int]]:
    return [LogEntry(tick, index) for index, tick in enumerate(ticks)]


def test_recent_habit_reads_the_last_hours() -> None:
    visible = entries(0, 5, 6, 11)  # published before tick 12
    reading = RecentHabit(0.5).read(visible, tick=12, previous=6, grid=GRID)
    assert [entry.tick for entry in reading.entries] == [6, 11]
    assert reading.start_tick == 6
    at_start = RecentHabit(0.5).read([], tick=0, previous=None, grid=GRID)
    assert (list(at_start.entries), at_start.start_tick) == ([], 0)
    assert RecentHabit(0.5).window_ticks(GRID) == 6


def test_unread_habit_reads_since_the_previous_consultation() -> None:
    visible = entries(0, 3, 6, 9, 30)
    habit = UnreadHabit(None)
    reading = habit.read(visible, tick=36, previous=6, grid=GRID)
    assert [entry.tick for entry in reading.entries] == [6, 9, 30]
    assert reading.start_tick == 6
    first = habit.read(visible, tick=36, previous=None, grid=GRID)
    assert len(first.entries) == 5
    assert habit.window_ticks(GRID) is None
    capped = UnreadHabit(1.0).read(visible, tick=36, previous=0, grid=GRID)
    assert [entry.tick for entry in capped.entries] == [30]
    assert capped.start_tick == 24


def test_last_messages_reads_a_number_of_messages_within_an_age() -> None:
    visible = entries(0, 20, 21, 22, 23)
    habit = LastMessagesHabit(messages=2, max_hours=1.0)
    reading = habit.read(visible, tick=24, previous=None, grid=GRID)
    assert [entry.tick for entry in reading.entries] == [22, 23]
    assert reading.start_tick == 22
    few = LastMessagesHabit(messages=10, max_hours=1.0).read(
        visible, tick=24, previous=None, grid=GRID
    )
    assert [entry.tick for entry in few.entries] == [20, 21, 22, 23]
    assert few.start_tick == 12
    silent = habit.read(entries(0, 1), tick=100, previous=None, grid=GRID)
    assert (list(silent.entries), silent.start_tick) == ([], 88)


def test_rounded_windows_are_converted_without_warning() -> None:
    # 0.52 h is rounded to 6 ticks; the loader reports it, the component does not again.
    assert RecentHabit(0.52).window_ticks(GRID) == 6


# --------------------------------------------------------------------------- climate rules


def test_ema_replaces_half_of_the_value_after_one_inertia() -> None:
    rule = EmaRule(2.0)
    assert rule.update(0.0, 1.0, 2.0) == pytest.approx(0.5)
    assert rule.update(0.0, 1.0, 4.0) == pytest.approx(0.75)
    assert rule.update(0.4, 0.4, 3.0) == pytest.approx(0.4)
    # Two updates of one hour equal one update of two hours.
    assert rule.update(rule.update(0.0, 1.0, 1.0), 1.0, 1.0) == pytest.approx(0.5)


def test_ema_inertia_is_not_rounded_to_ticks() -> None:
    assert EmaParameters(inertia_hours=0.33).inertia_hours == 0.33
    assert EmaRule(0.33).update(0.0, 1.0, 0.5) == pytest.approx(1 - 2 ** (-0.5 / 0.33))
    with pytest.raises(ValidationError, match="greater than 0"):
        EmaParameters(inertia_hours=0)


def test_threshold_rule() -> None:
    rule = ThresholdRule(threshold=0.5, rate_per_hour=0.1)
    assert rule.update(0.5, 0.4, 2.0) == pytest.approx(0.3)
    assert rule.update(0.5, 0.5, 2.0) == pytest.approx(0.7)
    assert rule.update(0.05, 0.0, 1.0) == 0.0
    assert rule.update(0.95, 1.0, 1.0) == 1.0


# --------------------------------------------------------------------------- perceptions

TEAM_RULE = EmaRule(2.0)


def test_shared_perception() -> None:
    perception = SharedPerception()
    assert perception.initial_impression(rng()) is None
    perceived = perception.perceive(
        None, team_climate=0.3, observed=0.9, elapsed_hours=0.5, rule=TEAM_RULE
    )
    assert (perceived.climate, perceived.impression) == (0.3, None)


def test_individual_memory_draws_an_impression_and_updates_it() -> None:
    perception = IndividualMemoryPerception(0.5, 0.1, None)
    impressions = [perception.initial_impression(rng(seed)) for seed in range(500)]
    assert statistics.fmean(i for i in impressions if i is not None) == pytest.approx(0.5, abs=0.02)
    first = perception.perceive(
        0.4, team_climate=0.9, observed=None, elapsed_hours=None, rule=TEAM_RULE
    )
    assert (first.climate, first.impression) == (0.4, 0.4)
    no_history = perception.perceive(
        0.4, team_climate=0.9, observed=1.0, elapsed_hours=None, rule=TEAM_RULE
    )
    assert no_history.climate == 0.4
    later = perception.perceive(
        0.4, team_climate=0.9, observed=1.0, elapsed_hours=2.0, rule=TEAM_RULE
    )
    assert later.climate == later.impression == pytest.approx(0.7)


def test_individual_memory_with_its_own_inertia() -> None:
    perception = IndividualMemoryPerception(0.5, 0.0, 0.5)
    assert perception.initial_impression(rng()) == 0.5
    threshold = ThresholdRule(0.5, 0.1)
    perceived = perception.perceive(
        0.0, team_climate=0.5, observed=1.0, elapsed_hours=0.5, rule=threshold
    )
    assert perceived.climate == pytest.approx(0.5)


def test_individual_memory_needs_an_impression() -> None:
    with pytest.raises(ValueError, match="needs the initial impression"):
        IndividualMemoryPerception(0.5, 0.1, None).perceive(
            None, team_climate=0.5, observed=0.5, elapsed_hours=1.0, rule=TEAM_RULE
        )


def test_individual_memory_parameters() -> None:
    assert IndividualMemoryParameters().initial_sd == 0.1
    with pytest.raises(ValidationError, match=r"initial_sd must be smaller than 0\.3"):
        IndividualMemoryParameters(initial_mean=0.1, initial_sd=0.31)


# --------------------------------------------------------------------------- expression


def test_logistic_probability_at_its_anchors() -> None:
    neutral = SpeakerView(psychological_safety=0.5, perceived_climate=0.5)
    assert LogisticProbability(0.0, 2.0, 2.0).probability(neutral) == 0.5
    default = LogisticProbability(-0.5, 2.0, 2.0)
    assert default.probability(neutral) == pytest.approx(1 / (1 + math.exp(0.5)))
    least, most = (SpeakerView(safety, 0.5) for safety in (0.0, 1.0))
    odds = [p / (1 - p) for p in (default.probability(least), default.probability(most))]
    assert odds[1] / odds[0] == pytest.approx(math.exp(2.0))
    silent, active = (SpeakerView(0.5, climate) for climate in (0.0, 1.0))
    assert default.probability(silent) < default.probability(neutral)
    assert default.probability(active) > default.probability(neutral)


def test_linear_probability_is_clipped() -> None:
    linear = LinearProbability(0.1, 0.5, 0.6)
    assert linear.probability(SpeakerView(0.2, 0.5)) == pytest.approx(0.5)
    assert linear.probability(SpeakerView(1.0, 1.0)) == 1.0
    assert LinearProbability(-0.5, 0.1, 0.1).probability(SpeakerView(0.0, 0.0)) == 0.0
    with pytest.raises(ValidationError, match="Field required"):
        LinearParameters()  # type: ignore[call-arg]
