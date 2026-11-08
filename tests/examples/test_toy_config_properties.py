"""Property-based tests of configuration loading, on the toy chatter schema."""

import warnings

import yaml
from hypothesis import given
from hypothesis import strategies as st

from examples.toy_chatter.config import ToyConfig, default_registry
from gasp_sim.api import ConfigError, parse_config

REGISTRY = default_registry()


def toy_text(
    seed: int,
    n_agents: int,
    period_ticks: int,
    window_hours: float,
    rule: str,
    probability: float,
    feedback: float,
) -> str:
    parameters = (
        {"probability": probability}
        if rule == "constant"
        else {"base_probability": probability, "feedback": feedback}
    )
    document = {
        "seed": seed,
        "days": 1,
        "n_agents": n_agents,
        "consultation_period_hours": period_ticks * 5 / 60,
        "window_hours": window_hours,
        "speaking_rule": {"type": rule, **parameters},
    }
    return yaml.safe_dump(document)


@given(
    seed=st.integers(min_value=0, max_value=2**63),
    n_agents=st.integers(min_value=1, max_value=50),
    period_ticks=st.integers(min_value=1, max_value=96),
    window_hours=st.floats(min_value=0.05, max_value=8.0),
    rule=st.sampled_from(["constant", "feedback"]),
    probability=st.floats(min_value=0.0, max_value=1.0),
    feedback=st.floats(min_value=0.0, max_value=2.0),
)
def test_resolved_configuration_loads_back_to_the_same_configuration(
    seed: int,
    n_agents: int,
    period_ticks: int,
    window_hours: float,
    rule: str,
    probability: float,
    feedback: float,
) -> None:
    text = toy_text(seed, n_agents, period_ticks, window_hours, rule, probability, feedback)
    loaded = parse_config(text, ToyConfig, REGISTRY)
    again = parse_config(loaded.to_yaml(), ToyConfig, REGISTRY)
    assert again.config == loaded.config
    assert again.warnings == loaded.warnings


@given(
    window_hours=st.floats(min_value=0.05, max_value=8.0),
    tick_minutes=st.sampled_from([1, 2, 5, 10, 15, 30]),
)
def test_a_window_is_reported_as_rounded_exactly_when_the_engine_would_warn(
    window_hours: float, tick_minutes: int
) -> None:
    text = yaml.safe_dump(
        {
            "seed": 1,
            "days": 1,
            "window_hours": window_hours,
            "consultation_period_hours": 1,
            "time": {"tick_minutes": tick_minutes},
        }
    )
    try:
        loaded = parse_config(text, ToyConfig, REGISTRY)
    except ConfigError as error:
        # Only possible for a window shorter than half a tick.
        assert window_hours * 60 < tick_minutes / 2, error
        return
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loaded.config.time.grid().hours_to_ticks(window_hours)
    assert len(loaded.warnings) == len(caught)
