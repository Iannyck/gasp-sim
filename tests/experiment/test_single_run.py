"""Tests of model definitions and single runs (ADR-0016)."""

import json
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import pytest

import gasp_sim.registry as registry_module
from examples.toy_chatter.config import ToyConfig, build, default_registry
from examples.toy_chatter.outputs import SUMMARIES, TABLES
from gasp_sim.api import (
    FunctionPhase,
    LoadedConfig,
    ModelDefinition,
    RandomStreams,
    Registry,
    RunFailedError,
    RunSettings,
    Simulation,
    StepContext,
    run_single,
)

HEADLINE = (("run", "consultations"), ("run", "messages"), ("run", "mean_participation"))

TOY = ModelDefinition(
    name="toy chatter",
    schema=ToyConfig,
    registry=default_registry,
    build=lambda loaded: build(loaded).simulation,
    tables=TABLES,
    summaries=SUMMARIES,
    headline=HEADLINE,
)


def write(tmp_path: Path, text: str, name: str = "run.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class Plain(RunSettings):
    """Settings of a model without components."""


def failing_simulation(loaded: LoadedConfig[Plain]) -> Simulation:
    def fail_at_three(context: StepContext) -> None:
        if context.tick == 3:
            raise ValueError("boom")

    return Simulation(
        phases=[FunctionPhase("fail", fail_at_three)],
        streams=RandomStreams(seed=loaded.config.seed, specs=()),
        grid=loaded.config.time.grid(),
    )


FAILING = ModelDefinition(name="failing", schema=Plain, registry=Registry, build=failing_simulation)


# --------------------------------------------------------------------------- definitions


def test_headline_values_must_be_columns_of_run_summaries() -> None:
    for headline in [(("run", "nothing"),), (("windows", "messages"),), (("other", "x"),)]:
        with pytest.raises(ValueError, match="not a column of a summary of the whole run"):
            ModelDefinition(
                name="toy",
                schema=ToyConfig,
                registry=default_registry,
                build=TOY.build,
                summaries=SUMMARIES,
                headline=headline,
            )


def test_load_uses_the_schema_and_the_registry_of_the_model(tmp_path: Path) -> None:
    loaded = TOY.load(write(tmp_path, "seed: 1\ndays: 1\nspeaking_rule: {type: constant}\n"))
    assert isinstance(loaded.config, ToyConfig)
    assert loaded.resolved()["speaking_rule"]["type"] == "constant"


def test_installed_plugins_are_loaded_from_the_group_of_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "toy_extra.py").write_text(
        "from examples.toy_chatter.extra_rules import register\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    points = [EntryPoint("extra", "toy_extra:register", "toy.plugins")]

    def select(*, group: str) -> list[EntryPoint]:
        return [point for point in points if point.group == group]

    monkeypatch.setattr(registry_module, "entry_points", select)
    with_group = ModelDefinition(
        name="toy",
        schema=ToyConfig,
        registry=default_registry,
        build=TOY.build,
        plugin_group="toy.plugins",
    )
    assert [plugin.kind for plugin in with_group.new_registry().plugins] == ["entry_point"]
    assert TOY.new_registry().plugins == ()


# --------------------------------------------------------------------------- runs


def test_run_single_records_the_run_and_returns_the_headline(tmp_path: Path) -> None:
    loaded = TOY.load(Path("examples/toy_chatter/configs/default.yaml"))
    result = run_single(TOY, loaded, tmp_path / "results", run_id="toy-1")
    assert result.run_id == "toy-1"
    assert result.path == tmp_path / "results" / "toy-1"
    assert result.headline == (
        ("consultations", 400),
        ("messages", 272),
        ("mean_participation", pytest.approx(0.68)),
    )
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["ticks_completed"] == 5 * 96


def test_run_single_runs_for_the_hours_of_the_configuration(tmp_path: Path) -> None:
    loaded = TOY.load(write(tmp_path, "seed: 3\nhours: 2.5\n"))
    result = run_single(TOY, loaded, tmp_path, run_id="short")
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ticks_completed"] == 30
    assert dict(result.headline)["consultations"] == 5 * 5  # 5 agents, every 30 minutes


def test_a_failed_run_is_reported_with_its_directory(tmp_path: Path) -> None:
    loaded = FAILING.load(write(tmp_path, "seed: 1\ndays: 1\n"))
    with pytest.raises(RunFailedError, match="The run failed: ValueError: boom") as caught:
        run_single(FAILING, loaded, tmp_path, run_id="broken")
    assert caught.value.path == tmp_path / "broken"
    assert isinstance(caught.value.__cause__, ValueError)
    manifest = json.loads((tmp_path / "broken" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"


def test_errors_before_the_run_starts_are_not_run_failures(tmp_path: Path) -> None:
    loaded = FAILING.load(write(tmp_path, "seed: 1\ndays: 1\n"))
    with pytest.raises(ValueError, match="Invalid run identifier"):
        run_single(FAILING, loaded, tmp_path, run_id="../escape")
    (tmp_path / "taken").mkdir()
    with pytest.raises(FileExistsError):
        run_single(FAILING, loaded, tmp_path, run_id="taken")


def test_headline_is_empty_when_the_run_summary_has_no_row(tmp_path: Path) -> None:
    class Silent:
        def observe(self, observation: object) -> None: ...

        def rows(self, period: Any) -> list[object]:
            return []

    summaries = tuple(
        type(summary)(summary.name, summary.row, Silent, per=summary.per, description="x")
        for summary in SUMMARIES
    )
    silent = ModelDefinition(
        name="toy",
        schema=ToyConfig,
        registry=default_registry,
        build=TOY.build,
        summaries=summaries,
        headline=(("run", "messages"),),
    )
    loaded = silent.load(write(tmp_path, "seed: 1\nhours: 1\n"))
    assert run_single(silent, loaded, tmp_path, run_id="quiet").headline == (("messages", None),)
