"""Tests of the command-line interface (ADR-0016)."""

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import gasp_sim
from examples.toy_chatter.config import ToyConfig, build, default_registry
from examples.toy_chatter.outputs import SUMMARIES, TABLES
from gasp_sim.api import (
    FunctionPhase,
    LoadedConfig,
    ModelDefinition,
    RandomStreams,
    Registry,
    RunSettings,
    Simulation,
    StepContext,
)
from gasp_sim.cli.main import app, make_app

TOY = ModelDefinition(
    name="toy chatter",
    schema=ToyConfig,
    registry=default_registry,
    build=lambda loaded: build(loaded).simulation,
    tables=TABLES,
    summaries=SUMMARIES,
    headline=(("run", "consultations"), ("run", "messages"), ("run", "mean_participation")),
)
CLI = make_app(lambda: TOY)
DEFAULT = Path("examples/toy_chatter/configs/default.yaml").resolve()


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


def invoke(arguments: list[str], application: typer.Typer = CLI) -> tuple[int, str, str]:
    result = CliRunner().invoke(application, arguments)
    return result.exit_code, result.stdout, result.stderr


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "run.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- general


def test_version() -> None:
    assert invoke(["--version"]) == (0, f"gasp-sim {gasp_sim.__version__}\n", "")


def test_help_lists_the_commands() -> None:
    code, output, _ = invoke(["--help"])
    assert code == 0
    assert "validate" in output
    assert "run" in output


@pytest.mark.parametrize("arguments", [["validate"], ["run"], ["frobnicate"], ["run", "--nope"]])
def test_mistyped_commands_exit_with_status_2(arguments: list[str]) -> None:
    assert invoke(arguments)[0] == 2


def test_the_default_model_is_not_available_yet(tmp_path: Path) -> None:
    for command in ("validate", "run"):
        code, _, errors = invoke([command, str(DEFAULT)], app)
        assert code == 1
        assert errors == "error: The GASP model is not available yet in this version.\n"


# --------------------------------------------------------------------------- validate


def test_validate_a_valid_file() -> None:
    assert invoke(["validate", str(DEFAULT)]) == (0, f"{DEFAULT}: valid configuration.\n", "")


def test_validate_prints_the_resolved_configuration_and_the_warnings(tmp_path: Path) -> None:
    code, output, errors = invoke(
        ["validate", str(write(tmp_path, "seed: 1\ndays: 1\nwindow_hours: 1.03\n")), "--resolved"]
    )
    assert code == 0
    assert output.startswith("# Resolved configuration")
    assert "speaking_rule:\n  type: feedback\n" in output
    assert errors.startswith("warning: window_hours: 1.03 h")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("seed: 1\n", "the length of the run is missing"),
        ("seed: 1\ndays: 1\nplugins: [missing.py]\n", "plugin file 'missing.py' not found"),
    ],
)
def test_validate_reports_invalid_files(tmp_path: Path, text: str, message: str) -> None:
    code, output, errors = invoke(["validate", str(write(tmp_path, text))])
    assert (code, output) == (1, "")
    assert errors.startswith("Invalid configuration")
    assert message in errors


def test_validate_reports_missing_files(tmp_path: Path) -> None:
    code, _, errors = invoke(["validate", str(tmp_path / "none.yaml")])
    assert code == 1
    assert "cannot read the file" in errors


# --------------------------------------------------------------------------- run


def test_run_records_in_results_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, output, errors = invoke(["run", str(DEFAULT), "--run-id", "toy-1"])
    assert (code, errors) == (0, "")
    assert output == (
        f"results: {Path('results') / 'toy-1'}\n"
        "  consultations: 400\n"
        "  messages: 272\n"
        "  mean_participation: 0.68\n"
    )
    manifest = json.loads((tmp_path / "results" / "toy-1" / "manifest.json").read_text("utf-8"))
    assert manifest["status"] == "completed"


def test_run_in_another_directory_with_the_default_identifier(tmp_path: Path) -> None:
    code, output, _ = invoke(["run", str(DEFAULT), "--output", str(tmp_path / "out")])
    assert code == 0
    [directory] = (tmp_path / "out").iterdir()
    assert directory.name.endswith("-seed42")
    assert output.startswith(f"results: {directory}\n")


def test_run_stops_on_invalid_files_without_creating_anything(tmp_path: Path) -> None:
    code, _, errors = invoke(
        ["run", str(write(tmp_path, "seed: 1\n")), "--output", str(tmp_path / "out")]
    )
    assert code == 1
    assert "the length of the run is missing" in errors
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("run_id", "message"),
    [("../escape", "error: Invalid run identifier"), ("taken", "error: [Errno 17]")],
)
def test_run_reports_unusable_run_identifiers(tmp_path: Path, run_id: str, message: str) -> None:
    (tmp_path / "taken").mkdir()
    code, _, errors = invoke(["run", str(DEFAULT), "--output", str(tmp_path), "--run-id", run_id])
    assert code == 1
    assert errors.startswith(message)


def test_run_reports_failures_and_partial_results(tmp_path: Path) -> None:
    failing = make_app(
        lambda: ModelDefinition(
            name="failing", schema=Plain, registry=Registry, build=failing_simulation
        )
    )
    path = write(tmp_path, "seed: 1\ndays: 1\n")
    code, _, errors = invoke(
        ["run", str(path), "--output", str(tmp_path), "--run-id", "broken"], failing
    )
    assert code == 1
    assert errors == (
        f"error: The run failed: ValueError: boom\npartial results: {tmp_path / 'broken'}\n"
    )


def test_run_without_headline_values(tmp_path: Path) -> None:
    quiet = make_app(
        lambda: ModelDefinition(
            name="quiet", schema=Plain, registry=Registry, build=failing_simulation
        )
    )
    path = write(tmp_path, "seed: 1\nhours: 0.25\n")
    code, output, _ = invoke(["run", str(path), "--output", str(tmp_path), "--run-id", "q"], quiet)
    assert (code, output) == (0, f"results: {tmp_path / 'q'}\n")


def test_run_shows_missing_headline_values(tmp_path: Path) -> None:
    class Silent:
        def observe(self, observation: object) -> None: ...

        def rows(self, period: object) -> list[object]:
            return []

    summaries = tuple(
        type(summary)(summary.name, summary.row, Silent, per=summary.per, description="x")
        for summary in SUMMARIES
    )
    silent = make_app(
        lambda: ModelDefinition(
            name="toy",
            schema=ToyConfig,
            registry=default_registry,
            build=TOY.build,
            summaries=summaries,
            headline=(("run", "messages"),),
        )
    )
    path = write(tmp_path, "seed: 1\nhours: 1\n")
    code, output, _ = invoke(["run", str(path), "--output", str(tmp_path), "--run-id", "q"], silent)
    assert (code, output) == (0, f"results: {tmp_path / 'q'}\n  messages: (none)\n")
