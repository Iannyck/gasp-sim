"""Tests of the configuration of the toy chatter example (examples/toy_chatter/config.py)."""

import textwrap
from pathlib import Path

import pytest

from examples.toy_chatter import run
from examples.toy_chatter.config import (
    CONFIG_DIR,
    SPEAKING_RULE,
    ToyConfig,
    build,
    default_registry,
    load,
)
from examples.toy_chatter.model import ConstantRule, FeedbackRule, ToyChatter, ToyParameters
from gasp_sim.api import ConfigError, StreamMode, TimeGrid, config_json_schema


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "toy.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_default_file_reproduces_the_reference_run() -> None:
    """The configured model gives exactly the run of the model built in code (step 3)."""
    loaded = load(CONFIG_DIR / "default.yaml")
    model = build(loaded)
    model.run_days(loaded.config.days)
    reference = ToyChatter(ToyParameters(), seed=42)
    reference.run_days(5)
    assert model.decisions == reference.decisions
    summary = model.summary()
    assert (summary.consultations, summary.messages) == (400, 272)
    assert summary.mean_participation == pytest.approx(0.68)


def test_build_passes_every_setting_to_the_model(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
        seed: 3
        days: 1
        stream_mode: single
        time: {tick_minutes: 15, day_hours: 7.5}
        n_agents: 4
        consultation_period_hours: 0.75
        window_hours: 2.0
        speaking_rule: {type: constant, probability: 0.6}
        """,
    )
    model = build(load(path))
    assert model.parameters == ToyParameters(
        n_agents=4, consultation_period_hours=0.75, window_hours=2.0
    )
    assert model.rule == ConstantRule(probability=0.6)
    assert model.grid == TimeGrid(tick_minutes=15, day_minutes=450)
    assert model.streams.mode is StreamMode.SINGLE
    assert model.period == 3


def test_preset_file() -> None:
    loaded = load(CONFIG_DIR / "no_feedback.yaml")
    assert loaded.config.preset == "no_feedback"
    assert build(loaded).rule == ConstantRule(probability=0.5)


def test_plugin_file() -> None:
    loaded = load(CONFIG_DIR / "with_plugin.yaml")
    rule = build(loaded).rule
    assert type(rule).__name__ == "ThresholdRule"
    assert rule.probability_for(0.39) == 0.2
    assert rule.probability_for(0.4) == 0.6
    assert loaded.registry.component_source(SPEAKING_RULE, "threshold") == (
        "plugin 'examples.toy_chatter.extra_rules'"
    )


def test_rounded_window_is_reported_once(tmp_path: Path) -> None:
    path = write(tmp_path, "seed: 1\ndays: 1\nwindow_hours: 1.03\n")
    loaded = load(path)
    assert [str(issue) for issue in loaded.warnings] == [
        "window_hours: 1.03 h is not a whole number of 5-minute ticks; rounded to 12 ticks (1 h)"
    ]
    assert build(loaded).window == 12  # no second warning (pytest turns warnings into errors)


def test_invalid_file_lists_every_problem(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
        seed: 1
        days: 1
        n_agnets: 4
        consultation_period_hours: 0.1
        speaking_rule:
          type: feedback
          base_probability: 1.5
        """,
    )
    with pytest.raises(ConfigError) as caught:
        load(path)
    assert [str(issue) for issue in caught.value.errors] == [
        "speaking_rule → base_probability: must be at most 1 (got 1.5)",
        "n_agnets: unknown setting; did you mean 'n_agents'?",
        "consultation_period_hours: must be a whole number of 5-minute ticks (got 0.1)",
    ]


def test_registry_and_schema() -> None:
    registry = default_registry()
    assert registry.component_names(SPEAKING_RULE) == ("constant", "feedback")
    assert [preset.name for preset in registry.presets] == ["no_feedback"]
    schema = config_json_schema(ToyConfig, registry)
    assert set(schema["properties"]["speaking_rule"]["discriminator"]["mapping"]) == {
        "constant",
        "feedback",
    }
    assert load(CONFIG_DIR / "default.yaml", registry).registry is not registry


def test_default_rule_parameters_match_the_model_defaults(tmp_path: Path) -> None:
    loaded = load(write(tmp_path, "seed: 1\ndays: 1\nspeaking_rule: {type: feedback}\n"))
    assert build(loaded).rule == FeedbackRule()
    loaded = load(write(tmp_path, "seed: 1\ndays: 1\nspeaking_rule: {type: constant}\n"))
    assert build(loaded).rule == ConstantRule()


# --------------------------------------------------------------------------- run script


def test_run_script_prints_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main([]) == 0
    output = capsys.readouterr().out
    assert "no scientific value" in output
    assert "speaking rule: feedback (base_probability=0.3, feedback=0.4)" in output
    assert "consultations: 400" in output
    assert "mean participation per consultation round: 0.680" in output


def test_run_script_prints_the_resolved_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "seed: 1\ndays: 1\nwindow_hours: 1.03\n")
    assert run.main([str(path), "--resolved"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("# Resolved configuration")
    assert "speaking_rule:\n  type: feedback\n" in captured.out
    assert captured.err.startswith("warning: window_hours: 1.03 h")


def test_run_script_reports_invalid_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "seed: 1\n")
    assert run.main([str(path)]) == 1
    assert "days: required setting is missing" in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [["a.yaml", "b.yaml"], ["--other"]])
def test_run_script_usage(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(arguments) == 2
    assert capsys.readouterr().err.startswith("usage:")


def test_run_script_reads_the_command_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["run", str(CONFIG_DIR / "no_feedback.yaml")])
    assert run.main() == 0
    assert "speaking rule: constant (probability=0.5)" in capsys.readouterr().out
