"""Tests of the configuration of the GASP model: defaults, presets, checks (step 6.1)."""

import textwrap
from pathlib import Path

import pytest

from gasp_sim.api import GASP, ConfigError, config_json_schema, parse_config
from gasp_sim.experiment.gasp import check_windows
from gasp_sim.model.config import GaspConfig, default_registry


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "run.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_defaults() -> None:
    loaded = parse_config("seed: 1\ndays: 1\n", GaspConfig, default_registry())
    resolved = loaded.resolved()
    assert resolved["team_size"] == 8
    assert resolved["psychological_safety"] == {"type": "uniform", "low": 0.0, "high": 1.0}
    assert resolved["rhythm"] == {"type": "synchronous", "period_hours": 0.5}
    assert resolved["reading"] == {"type": "recent", "hours": 0.5}
    assert resolved["perception"] == {
        "type": "individual_memory",
        "initial_mean": 0.5,
        "initial_sd": 0.1,
        "inertia_hours": None,
    }
    assert resolved["initial_climate"] == 0.5
    assert resolved["participation_window_hours"] == 0.5
    assert resolved["climate_rule"] == {"type": "ema", "inertia_hours": 16.0}
    assert resolved["expression"] == {
        "type": "logistic",
        "intercept": -0.5,
        "safety_weight": 2.0,
        "climate_weight": 2.0,
    }


def test_article_preset() -> None:
    loaded = parse_config("preset: article\nseed: 1\n", GaspConfig, default_registry())
    config = loaded.config
    assert (config.hours, config.days, config.run_ticks()) == (50, None, 600)
    resolved = loaded.resolved()
    assert resolved["perception"] == {"type": "shared"}
    assert resolved["climate_rule"] == {"type": "ema", "inertia_hours": 0.5}
    assert loaded.warnings == ()


def test_article_threshold_preset() -> None:
    loaded = parse_config("preset: article_threshold\nseed: 1\n", GaspConfig, default_registry())
    assert loaded.resolved()["climate_rule"] == {
        "type": "threshold",
        "threshold": 0.5,
        "rate_per_hour": 0.1,
    }
    assert loaded.config.hours == 50


def test_a_file_can_change_the_length_of_a_preset_in_either_unit() -> None:
    registry = default_registry()
    in_days = parse_config("preset: article\nseed: 1\ndays: 3\n", GaspConfig, registry)
    assert (in_days.config.days, in_days.config.hours) == (3, None)
    in_hours = parse_config("preset: article\nseed: 1\nhours: 10\n", GaspConfig, registry)
    assert in_hours.config.hours == 10


def test_parameters_are_checked() -> None:
    text = """\
        seed: 1
        days: 1
        team_size: 2
        psychological_safety: {type: beta, mean: 0.5, sd: 0.6}
        expression: {type: linear}
        climate_rule: {type: ema, inertia_hours: 0}
        """
    with pytest.raises(ConfigError) as caught:
        parse_config(textwrap.dedent(text), GaspConfig, default_registry())
    errors = [str(issue) for issue in caught.value.errors]
    assert "team_size: must be at least 3 (got 2)" in errors
    assert any(error.startswith("psychological_safety: sd must be smaller") for error in errors)
    assert any(error.startswith("expression → intercept: required setting") for error in errors)
    assert "climate_rule → inertia_hours: must be greater than 0 (got 0)" in errors


def test_windows_shorter_than_the_consultation_period_are_warned_about(tmp_path: Path) -> None:
    text = """\
        seed: 1
        days: 1
        rhythm: {type: synchronous, period_hours: 1}
        participation_window_hours: 0.5
        reading: {type: recent, hours: 0.25}
        """
    loaded = GASP.load(write(tmp_path, text))
    assert [str(issue) for issue in loaded.warnings] == [
        "participation_window_hours: the participation window (0.5 h) is shorter than the "
        "time between two consultations (1 h): it will often be empty, that is a "
        "participation of 0",
        "reading: the reading window (0.25 h) is shorter than the time between two "
        "consultations (1 h): it will often be empty, that is a participation of 0",
    ]


def test_windows_without_fixed_length_are_not_checked() -> None:
    loaded = parse_config(
        "seed: 1\ndays: 1\nreading: {type: unread}\n", GaspConfig, default_registry()
    )
    assert check_windows(loaded) == []


def test_rounded_windows_are_warned_about_once(tmp_path: Path) -> None:
    loaded = GASP.load(write(tmp_path, "seed: 1\ndays: 1\nparticipation_window_hours: 0.52\n"))
    assert [str(issue) for issue in loaded.warnings] == [
        "participation_window_hours: 0.52 h is not a whole number of 5-minute ticks; rounded "
        "to 6 ticks (0.5 h)"
    ]


def test_json_schema_lists_every_component() -> None:
    schema = config_json_schema(GaspConfig, default_registry())
    assert set(schema["properties"]["perception"]["discriminator"]["mapping"]) == {
        "shared",
        "individual_memory",
    }
    ema = schema["$defs"]["ClimateRuleEma"]["properties"]["inertia_hours"]
    assert "half of the former value" in ema["description"]
