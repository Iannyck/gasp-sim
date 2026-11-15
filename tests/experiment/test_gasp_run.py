"""Tests of GASP runs: build, tables, summaries, determinism (step 6.1)."""

import csv
import json
import statistics
from pathlib import Path

import pytest

from gasp_sim.api import GASP, Period, run_single
from gasp_sim.experiment.gasp import (
    AgentRunRow,
    AgentRunSummary,
    ParticipationRow,
    ParticipationSummary,
    build_model,
)
from gasp_sim.model.observations import AgentDescribed, ClimateUpdated, Consulted, MessagePosted


def write(tmp_path: Path, text: str, name: str = "run.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_build_model_uses_every_setting(tmp_path: Path) -> None:
    text = (
        "seed: 5\ndays: 1\nteam_size: 5\nperception: {type: shared}\n"
        "participation_window_hours: 1\ntime: {tick_minutes: 10}\nstream_mode: single\n"
    )
    model = build_model(GASP.load(write(tmp_path, text)))
    assert model.team_size == 5
    assert model.window == 6
    assert model.grid.tick_minutes == 10
    assert model.streams.mode.value == "single"


def test_article_run_is_recorded(tmp_path: Path) -> None:
    loaded = GASP.load(write(tmp_path, "preset: article\nseed: 42\n"))
    result = run_single(GASP, loaded, tmp_path / "out", run_id="article")
    path = result.path
    assert sorted(p.name for p in (path / "tables").iterdir()) == [
        "agents.csv",
        "climate.csv",
        "consultations.csv",
        "messages.csv",
    ]
    assert sorted(p.name for p in (path / "summary").iterdir()) == [
        "agent_run.csv",
        "run.csv",
        "windows.csv",
    ]
    consultations = rows(path / "tables" / "consultations.csv")
    climate = rows(path / "tables" / "climate.csv")
    messages = rows(path / "tables" / "messages.csv")
    assert len(consultations) == 800
    assert len(climate) == 100
    [run] = rows(path / "summary" / "run.csv")
    assert int(run["consultations"]) == 800
    assert int(run["messages"]) == len(messages)
    mean = statistics.fmean(float(row["participation"]) for row in climate)
    assert float(run["mean_participation"]) == pytest.approx(mean)
    assert float(run["climate_at_end"]) == float(climate[-1]["climate"])
    assert dict(result.headline) == {
        "consultations": 800,
        "messages": len(messages),
        "mean_participation": pytest.approx(mean),
    }
    windows = rows(path / "summary" / "windows.csv")
    assert [row["complete"] for row in windows] == ["true"] * 6 + ["false"]
    assert sum(int(row["messages"]) for row in windows) == len(messages)
    agent_run = rows(path / "summary" / "agent_run.csv")
    assert [row["agent"] for row in agent_run] == [str(agent) for agent in range(8)]
    assert sum(int(row["messages"]) for row in agent_run) == len(messages)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["configuration"]["preset"] == "article"
    assert manifest["time"]["hours"] == 50


def test_same_configuration_seed_and_identifier_give_identical_files(tmp_path: Path) -> None:
    path = write(tmp_path, "seed: 7\ndays: 2\n")
    first = run_single(GASP, GASP.load(path), tmp_path / "a", run_id="same")
    second = run_single(GASP, GASP.load(path), tmp_path / "b", run_id="same")
    names = sorted(
        str(item.relative_to(first.path))
        for item in first.path.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    )
    assert len(names) == 8
    for name in names:
        assert (first.path / name).read_bytes() == (second.path / name).read_bytes(), name


def test_participation_summary() -> None:
    summary = ParticipationSummary()
    for agent in range(4):
        summary.observe(AgentDescribed(0, agent, 0.5, None))
    empty = next(iter(summary.rows(Period(0, 0, 6))))
    assert empty == ParticipationRow(0, 0, 0.0, None, None, None, None)
    summary.observe(Consulted(6, 0, 0, 0, None, 0.4, 0.5, True))
    summary.observe(Consulted(6, 1, 0, 0, None, 0.6, 0.5, False))
    summary.observe(MessagePosted(6, 0, 0, "generic"))
    summary.observe(ClimateUpdated(6, 0.25, 0.45))
    summary.observe(ClimateUpdated(12, 0.75, 0.55))
    summary.observe("ignored")
    row = next(iter(summary.rows(Period(1, 6, 18))))
    assert row == ParticipationRow(
        consultations=2,
        messages=1,
        messages_per_agent=0.25,
        mean_participation=0.5,
        speech_per_consultation=0.5,
        mean_perceived_climate=0.5,
        climate_at_end=0.55,
    )
    # The climate at the end of a period without update is the last one seen.
    assert next(iter(summary.rows(Period(2, 18, 24)))).climate_at_end == 0.55


def test_participation_summary_without_members() -> None:
    assert next(iter(ParticipationSummary().rows(Period(0, 0, 1)))).messages_per_agent == 0.0


def test_agent_run_summary() -> None:
    summary = AgentRunSummary()
    for agent in range(3):
        summary.observe(AgentDescribed(0, agent, 0.5, None))
    summary.observe(Consulted(0, 0, 0, 0, None, 0.5, 0.5, True))
    summary.observe(Consulted(6, 0, 0, 0, None, 0.5, 0.5, False))
    summary.observe(Consulted(0, 1, 0, 0, None, 0.5, 0.5, False))
    summary.observe(MessagePosted(0, 0, 0, "generic"))
    summary.observe(ClimateUpdated(0, 0.3, 0.4))
    assert list(summary.rows(Period(0, 0, 12))) == [
        AgentRunRow(0, 2, 1, 0.5),
        AgentRunRow(1, 1, 0, 0.0),
        AgentRunRow(2, 0, 0, None),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "psychological_safety: {type: beta, mean: 0.6, sd: 0.1}\n"
        "climate_rule: {type: threshold}\n"
        "expression: {type: linear, intercept: 0.1, safety_weight: 0.3, climate_weight: 0.4}\n"
        "reading: {type: last_messages, messages: 5, max_hours: 1}\n",
        "psychological_safety: {type: constant, value: 0.7}\n"
        "reading: {type: unread, max_hours: 2}\n"
        "perception: {type: individual_memory, initial_sd: 0, inertia_hours: 4}\n",
    ],
)
def test_every_built_in_component_can_be_run(tmp_path: Path, text: str) -> None:
    loaded = GASP.load(write(tmp_path, "seed: 3\ndays: 1\n" + text))
    result = run_single(GASP, loaded, tmp_path, run_id="components")
    assert dict(result.headline)["consultations"] == 128
