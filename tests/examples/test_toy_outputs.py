"""Tests of the recorded outputs of the toy chatter example (examples/toy_chatter/outputs.py)."""

import csv
import json
import textwrap
from pathlib import Path

import pytest

from examples.toy_chatter import run
from examples.toy_chatter.config import CONFIG_DIR, build, load
from examples.toy_chatter.outputs import SUMMARIES, TABLES, ParticipationSummary
from gasp_sim.api import Period, RunRecorder


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def record(tmp_path: Path, config: Path = CONFIG_DIR / "default.yaml") -> Path:
    loaded = load(config)
    model = build(loaded)
    with RunRecorder(
        tmp_path,
        simulation=model.simulation,
        loaded=loaded,
        tables=TABLES,
        summaries=SUMMARIES,
        run_id="toy",
    ) as recorder:
        model.run_days(loaded.config.days)
    return recorder.path


def test_tables_match_the_model(tmp_path: Path) -> None:
    loaded = load(CONFIG_DIR / "default.yaml")
    reference = build(loaded)
    reference.run_days(5)
    path = record(tmp_path)

    consultations = rows(path / "tables" / "consultations.csv")
    assert [
        (int(row["tick"]), int(row["agent"]), float(row["probability"]), row["spoke"] == "true")
        for row in consultations
    ] == [(d.tick, d.agent, d.probability, d.spoke) for d in reference.decisions]
    messages = rows(path / "tables" / "messages.csv")
    assert [(int(row["tick"]), int(row["sender"])) for row in messages] == [
        (entry.tick, entry.item.sender) for entry in reference.channel.visible
    ]
    assert list(consultations[0]) == [
        "run_id",
        "tick",
        "day",
        "minutes",
        "agent",
        "probability",
        "spoke",
    ]
    assert (consultations[0]["run_id"], consultations[0]["minutes"]) == ("toy", "0")


def test_summaries_match_the_model(tmp_path: Path) -> None:
    path = record(tmp_path)
    assert rows(path / "summary" / "run.csv") == [
        {"run_id": "toy", "consultations": "400", "messages": "272", "mean_participation": "0.68"}
    ]
    windows = rows(path / "summary" / "windows.csv")
    assert [
        (row["window"], row["start_day"], row["consultations"], row["messages"]) for row in windows
    ] == [
        ("0", "0", "80", "54"),
        ("1", "1", "80", "55"),
        ("2", "2", "80", "49"),
        ("3", "3", "80", "56"),
        ("4", "4", "80", "58"),
    ]
    assert [row["mean_participation"] for row in windows] == [
        "0.675",
        "0.6875",
        "0.6125",
        "0.7",
        "0.725",
    ]


def test_summary_level(tmp_path: Path) -> None:
    config = tmp_path / "toy.yaml"
    config.write_text(
        textwrap.dedent(
            """
            seed: 42
            days: 5
            recording: {level: summary, window_hours: 4}
            """
        ),
        encoding="utf-8",
    )
    path = record(tmp_path / "out", config)
    assert not (path / "tables").exists()
    assert len(rows(path / "summary" / "windows.csv")) == 10
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["summaries"]["windows"]["rows"] == 10


def test_participation_of_an_empty_period_is_empty() -> None:
    assert next(iter(ParticipationSummary().rows(Period(0, 0, 96)))).mean_participation is None


def test_run_script_records_on_request(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--output", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    (path,) = tmp_path.iterdir()
    assert path.name.endswith("-seed42")
    assert "  results: " in output
    assert path.name in output
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
