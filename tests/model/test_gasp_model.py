"""Tests of the GASP model in the control condition (step 6.1, ODD sections 3 and 7)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from gasp_sim.api import RandomStreams, StreamMode, TimeGrid
from gasp_sim.model.climate import ClimateRule, EmaRule
from gasp_sim.model.distributions import ConstantDistribution, UniformDistribution
from gasp_sim.model.expression import LogisticProbability, SpeakerView
from gasp_sim.model.model import STREAMS, GaspModel
from gasp_sim.model.observations import AgentDescribed, ClimateUpdated, Consulted, MessagePosted
from gasp_sim.model.perception import IndividualMemoryPerception, SharedPerception
from gasp_sim.model.reading import RecentHabit
from gasp_sim.model.rhythms import SynchronousRhythm

OBSERVATIONS = (AgentDescribed, Consulted, MessagePosted, ClimateUpdated)


def make(**overrides: Any) -> GaspModel:
    settings: dict[str, Any] = {
        "team_size": 8,
        "seed": 42,
        "safety": UniformDistribution(0.0, 1.0),
        "rhythm": SynchronousRhythm(0.5),
        "reading": RecentHabit(0.5),
        "perception": SharedPerception(),
        "climate_rule": EmaRule(0.5),
        "expression": LogisticProbability(-0.5, 2.0, 2.0),
    }
    settings.update(overrides)
    return GaspModel(**settings)


def run(model: GaspModel, ticks: int) -> list[object]:
    seen: list[object] = []
    for kind in OBSERVATIONS:
        model.simulation.bus.subscribe(kind, seen.append)
    model.simulation.run(ticks)
    return seen


def of[T](kind: type[T], seen: Sequence[object]) -> list[T]:
    return [item for item in seen if isinstance(item, kind)]


# --------------------------------------------------------------------------- team


def test_members_are_described_at_the_first_tick() -> None:
    seen = run(make(), 1)
    agents = of(AgentDescribed, seen)
    assert [agent.agent for agent in agents] == list(range(8))
    assert all(agent.tick == 0 and agent.initial_impression is None for agent in agents)
    streams = RandomStreams(seed=42, specs=STREAMS)
    expected = [float(streams.agent("traits", agent).random()) for agent in range(8)]
    assert [agent.psychological_safety for agent in agents] == expected


def test_draws_of_safety_do_not_depend_on_the_other_components() -> None:
    safeties = [
        [agent.psychological_safety for agent in of(AgentDescribed, run(model, 1))]
        for model in (
            make(),
            make(perception=IndividualMemoryPerception(0.5, 0.1, None)),
            make(expression=LogisticProbability(0.0, 1.0, 1.0)),
        )
    ]
    assert safeties[0] == safeties[1] == safeties[2]


def test_initial_impressions_with_individual_memory() -> None:
    model = make(perception=IndividualMemoryPerception(0.5, 0.1, None))
    impressions = [agent.initial_impression for agent in of(AgentDescribed, run(model, 1))]
    streams = RandomStreams(seed=42, specs=STREAMS)
    expected = [
        IndividualMemoryPerception(0.5, 0.1, None).initial_impression(
            streams.agent("perception", agent)
        )
        for agent in range(8)
    ]
    assert impressions == expected


# --------------------------------------------------------------------------- consultations


def test_every_member_consults_every_30_minutes() -> None:
    consulted = of(Consulted, run(make(), 2 * 96))
    assert len(consulted) == 8 * 16 * 2
    assert {item.tick for item in consulted} == set(range(0, 192, 6))


def test_first_consultation_has_nothing_to_read() -> None:
    first = of(Consulted, run(make(), 1))
    assert all(item.messages_read == 0 and item.read_minutes == 0 for item in first)
    assert all(item.observed_participation is None for item in first)


def test_members_read_the_previous_round_but_not_their_own_tick() -> None:
    seen = run(make(), 7)
    round_zero = [item.sender for item in of(MessagePosted, seen) if item.tick == 0]
    assert round_zero, "seed 42 must produce messages at the first round"
    for item in of(Consulted, seen):
        if item.tick != 6:
            continue
        assert item.messages_read == len(round_zero)
        assert item.read_minutes == 30
        others = set(round_zero) - {item.agent}
        assert item.observed_participation == pytest.approx(len(others) / 7)


def test_reading_windows_continue_across_days() -> None:
    seen = run(make(), 97)
    last_round = [item for item in of(MessagePosted, seen) if item.tick == 90]
    morning = [item for item in of(Consulted, seen) if item.tick == 96]
    assert len(morning) == 8
    assert all(item.messages_read == len(last_round) for item in morning)


def test_decisions_follow_equation_1_of_the_article() -> None:
    seen = run(make(), 3 * 96)
    streams = RandomStreams(seed=42, specs=STREAMS)
    safety = {item.agent: item.psychological_safety for item in of(AgentDescribed, seen)}
    expression = LogisticProbability(-0.5, 2.0, 2.0)
    for item in of(Consulted, seen):
        expected = expression.probability(SpeakerView(safety[item.agent], item.perceived_climate))
        assert item.probability == pytest.approx(expected)
        draw = float(streams.agent("speech", item.agent).random())
        assert item.spoke == (draw <= item.probability)
    messages = of(MessagePosted, seen)
    assert len(messages) == sum(item.spoke for item in of(Consulted, seen))
    assert [message.message for message in messages] == list(range(len(messages)))
    assert {message.message_type for message in messages} == {"generic"}


# --------------------------------------------------------------------------- climate


def test_climate_follows_the_participation_of_the_team() -> None:
    seen = run(make(), 2 * 96)
    updates = of(ClimateUpdated, seen)
    assert [update.tick for update in updates] == list(range(0, 192, 6))
    rule = EmaRule(0.5)
    climate = 0.5
    for update in updates:
        writers = {
            m.sender for m in of(MessagePosted, seen) if update.tick - 6 < m.tick <= update.tick
        }
        assert update.participation == pytest.approx(len(writers) / 8)
        # Every update covers 30 minutes: the first one covers the participation window.
        climate = rule.update(climate, update.participation, 0.5)
        assert update.climate == pytest.approx(climate)


def test_shared_perception_sees_the_climate_before_the_update_of_the_tick() -> None:
    seen = run(make(), 13)
    updates = {update.tick: update.climate for update in of(ClimateUpdated, seen)}
    for item in of(Consulted, seen):
        expected = 0.5 if item.tick == 0 else updates[item.tick - 6]
        assert item.perceived_climate == pytest.approx(expected)


def test_individual_memory_updates_impressions_with_what_members_read() -> None:
    perception = IndividualMemoryPerception(0.5, 0.1, None)
    seen = run(make(perception=perception), 13)
    impressions = {item.agent: item.initial_impression for item in of(AgentDescribed, seen)}
    rule = EmaRule(0.5)
    for item in sorted(of(Consulted, seen), key=lambda consulted: consulted.tick):
        impression = impressions[item.agent]
        assert impression is not None
        if item.tick > 0:
            assert item.observed_participation is not None
            impression = rule.update(impression, item.observed_participation, 0.5)
        assert item.perceived_climate == pytest.approx(impression)
        impressions[item.agent] = impression


def test_no_climate_update_without_consultation() -> None:
    model = make(rhythm=SynchronousRhythm(4.0))
    updates = of(ClimateUpdated, run(model, 96))
    assert [update.tick for update in updates] == [0, 48]


# --------------------------------------------------------------------------- runs


def test_same_seed_gives_the_same_run() -> None:
    assert run(make(), 2 * 96) == run(make(), 2 * 96)
    assert run(make(), 96) != run(make(seed=43), 96)


def test_single_stream_mode_runs() -> None:
    seen = run(make(mode=StreamMode.SINGLE), 96)
    assert len(of(Consulted, seen)) == 128


def test_other_time_grids() -> None:
    model = make(grid=TimeGrid(tick_minutes=10, day_minutes=450), rhythm=SynchronousRhythm(1.0))
    seen = run(model, 45)
    assert len(of(Consulted, seen)) == 8 * 8  # 7.5 h: consultations at 0, 1… 7 h


def test_the_model_runs_in_the_article_setting_without_proxy() -> None:
    """Smoke test of the 'article' setting; its outcome is explored, not asserted."""
    seen = run(make(), 600)
    assert len(of(ClimateUpdated, seen)) == 100


# --------------------------------------------------------------------------- errors


@dataclass(frozen=True)
class Fixed:
    """A component that returns a fixed value whatever it is asked."""

    value: Any

    def probability(self, speaker: SpeakerView) -> float:
        return float(self.value)

    def update(self, value: float, participation: float, elapsed_hours: float) -> float:
        return float(self.value)

    def draw(self, rng: np.random.Generator) -> float:
        return float(self.value)

    def consultations_of_day(self, agent: int, grid: TimeGrid, rng: object) -> Sequence[int]:
        return [self.value]

    def period_ticks(self, grid: TimeGrid) -> int:
        return 6


@pytest.mark.parametrize(
    ("overrides", "ticks", "message"),
    [
        ({"expression": Fixed(1.2)}, 1, "probability of speaking of member 0 must be"),
        ({"expression": Fixed(float("nan"))}, 1, "probability of speaking of member 0 must be"),
        ({"climate_rule": Fixed(-0.1)}, 1, "The climate must be a number in"),
        ({"rhythm": Fixed(96)}, 1, "gave tick 96 for member 0"),
    ],
)
def test_components_out_of_range_stop_the_run(
    overrides: dict[str, Any], ticks: int, message: str
) -> None:
    model = make(**overrides)
    with pytest.raises(ValueError, match=message):
        model.simulation.run(ticks)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"team_size": 1}, "team_size must be at least 2"),
        ({"initial_climate": 1.5}, "initial_climate must be a number in"),
        ({"participation_window_hours": 0.01}, "at least one tick"),
        ({"safety": ConstantDistribution(2.0)}, "psychological safety must be a number in"),
        ({"safety": Fixed(-1)}, "psychological safety must be a number in"),
    ],
)
def test_invalid_settings(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make(**overrides)


def test_climate_rule_protocol_is_respected() -> None:
    rule: ClimateRule = EmaRule(1.0)
    assert 0 <= rule.update(0.2, 0.9, 0.5) <= 1


def test_a_member_speaks_when_the_draw_equals_the_probability() -> None:
    """Equation 1 of the article: Voice = 1 if r <= P_speak."""
    first_draw = float(RandomStreams(seed=42, specs=STREAMS).agent("speech", 0).random())
    seen = run(make(expression=Fixed(first_draw)), 1)
    [first] = [item for item in of(Consulted, seen) if item.agent == 0]
    assert first.probability == first_draw
    assert first.spoke
