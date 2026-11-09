"""Tests of the run recorder (ADR-0015)."""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import gasp_sim.recording.recorder as recorder_module
from gasp_sim.api import (
    FunctionPhase,
    LoadedConfig,
    ObservationTable,
    Period,
    RandomStreams,
    Registry,
    RunRecorder,
    RunSettings,
    Simulation,
    StepContext,
    SummaryTable,
    parse_config,
)
from gasp_sim.recording.recorder import MANIFEST_VERSION, default_run_id

# --------------------------------------------------------------------------- a tiny model


@dataclass(frozen=True, slots=True)
class Ping:
    """Published at every tick by the tiny model."""

    tick: int
    value: float = field(metadata={"description": "Tick divided by 4.", "unit": "1"})
    even: bool = field(metadata={"description": "Whether the tick is even."})


@dataclass(frozen=True, slots=True)
class Pong:
    """Published at every tenth tick."""

    tick: int
    note: str | None = field(metadata={"description": "A note, or nothing."})


@dataclass(frozen=True, slots=True)
class Count:
    pings: int = field(metadata={"description": "Pings in the period."})
    first_tick: int | None = field(metadata={"description": "First tick seen."})


class Counter:
    def __init__(self) -> None:
        self.pings: list[int] = []
        self.periods: list[Period] = []

    def observe(self, observation: object) -> None:
        if isinstance(observation, Ping):
            self.pings.append(observation.tick)

    def rows(self, period: Period) -> Iterator[Count]:
        self.periods.append(period)
        yield Count(len(self.pings), self.pings[0] if self.pings else None)
        self.pings = []


TABLES = (
    ObservationTable("pings", Ping, "One row per tick."),
    ObservationTable("pongs", Pong, "One row every ten ticks."),
)
SUMMARIES = (
    SummaryTable("windows", Count, Counter, per="window", description="Pings per window."),
    SummaryTable("run", Count, Counter, per="run", description="Pings per run."),
)


class Settings(RunSettings):
    """Configuration of the tiny model."""


def load(text: str = "") -> LoadedConfig[Settings]:
    return parse_config(
        "seed: 7\ndays: 1\n" + text, Settings, Registry(), origin="folder/tiny.yaml"
    )


def make_simulation(loaded: LoadedConfig[Settings], fail_at: int | None = None) -> Simulation:
    def run(context: StepContext) -> None:
        if context.tick == fail_at:
            raise ValueError("boom")
        context.publish(Ping(context.tick, context.tick / 4, context.tick % 2 == 0))
        if context.tick % 10 == 0:
            context.publish(Pong(context.tick, None if context.tick % 20 else "twenty"))

    config = loaded.config
    return Simulation(
        phases=[FunctionPhase("ping", run)],
        streams=RandomStreams(seed=config.seed, specs=()),
        grid=config.time.grid(),
    )


def fixed_clock(
    start: datetime = datetime(2026, 11, 8, 14, 32, 5, tzinfo=UTC),
) -> Callable[[], datetime]:
    moments = iter(start + timedelta(seconds=index) for index in range(100))
    return lambda: next(moments)


def record(
    tmp_path: Path,
    text: str = "",
    *,
    days: int = 1,
    run_id: str | None = "run-1",
    fail_at: int | None = None,
    **kwargs: Any,
) -> RunRecorder:
    loaded = load(text)
    simulation = make_simulation(loaded, fail_at)
    with RunRecorder(
        tmp_path,
        simulation=simulation,
        loaded=loaded,
        tables=kwargs.pop("tables", TABLES),
        summaries=kwargs.pop("summaries", SUMMARIES),
        run_id=run_id,
        clock=fixed_clock(),
        **kwargs,
    ) as recorder:
        simulation.run_days(days)
    return recorder


def read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def manifest(recorder: RunRecorder) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((recorder.path / "manifest.json").read_text("utf-8"))
    return result


# --------------------------------------------------------------------------- full level


def test_full_run_writes_every_table(tmp_path: Path) -> None:
    recorder = record(tmp_path)
    assert recorder.path == tmp_path / "run-1"
    assert recorder.status == "completed"
    pings = read(recorder.path / "tables" / "pings.csv")
    assert pings[0] == "run_id,tick,day,minutes,value,even"
    assert pings[1:4] == ["run-1,0,0,0,0.0,true", "run-1,1,0,5,0.25,false", "run-1,2,0,10,0.5,true"]
    assert len(pings) == 1 + 96
    assert read(recorder.path / "tables" / "pongs.csv")[:4] == [
        "run_id,tick,day,minutes,note",
        "run-1,0,0,0,twenty",
        "run-1,10,0,50,",
        "run-1,20,0,100,twenty",
    ]
    assert read(recorder.path / "summary" / "windows.csv") == [
        "run_id,window,start_tick,end_tick,start_day,complete,pings,first_tick",
        "run-1,0,0,96,0,true,96,0",
    ]
    assert read(recorder.path / "summary" / "run.csv") == ["run_id,pings,first_tick", "run-1,96,0"]


def test_manifest_of_a_completed_run(tmp_path: Path) -> None:
    content = manifest(record(tmp_path, "time: {tick_minutes: 10}\n"))
    assert content["manifest_version"] == MANIFEST_VERSION
    assert content["run_id"] == "run-1"
    assert content["status"] == "completed"
    assert content["started_at"] == "2026-11-08T14:32:05Z"
    assert content["finished_at"] == "2026-11-08T14:32:06Z"
    assert content["duration_seconds"] >= 0
    assert content["ticks_completed"] == 48
    assert content["error"] is None
    assert set(content["software"]) == {
        "gasp_sim",
        "python",
        "numpy",
        "pydantic",
        "pyyaml",
        "platform",
        "implementation",
    }
    assert content["random"] == {"seed": 7, "stream_mode": "named", "bit_generator": "PCG64DXSM"}
    assert content["time"] == {"tick_minutes": 10, "day_minutes": 480, "days": 1}
    assert content["configuration"] == {
        "file": "config.yaml",
        "source": "tiny.yaml",
        "preset": None,
        "plugins": [],
        "warnings": [],
    }
    assert content["recording"]["level"] == "full"
    assert content["recording"]["window_ticks"] == 48
    pings = content["tables"]["pings"]
    assert pings["file"] == "tables/pings.csv"
    assert pings["observation"].endswith("test_recorder.Ping")
    assert pings["rows"] == 48
    assert [column["name"] for column in pings["columns"]] == [
        "run_id",
        "tick",
        "day",
        "minutes",
        "value",
        "even",
    ]
    assert pings["columns"][4] == {
        "name": "value",
        "type": "number",
        "unit": "1",
        "optional": False,
        "description": "Tick divided by 4.",
    }
    windows = content["summaries"]["windows"]
    assert (windows["file"], windows["per"], windows["rows"]) == (
        "summary/windows.csv",
        "window",
        1,
    )
    assert content["summaries"]["run"]["rows"] == 1


def test_saved_configuration_loads_back(tmp_path: Path) -> None:
    loaded = load("recording: {window_hours: 2}\n")
    recorder = record(tmp_path, "recording: {window_hours: 2}\n")
    text = (recorder.path / "config.yaml").read_text(encoding="utf-8")
    assert parse_config(text, Settings, Registry()).config == loaded.config


def test_configuration_warnings_are_in_the_manifest(tmp_path: Path) -> None:
    recorder = record(tmp_path, "recording: {window_hours: 1.03}\n")
    assert manifest(recorder)["configuration"]["warnings"] == [
        "recording → window_hours: 1.03 h is not a whole number of 5-minute ticks; rounded "
        "to 12 ticks (1 h)"
    ]


# --------------------------------------------------------------------------- summary level


def test_summary_level_writes_only_the_summaries(tmp_path: Path) -> None:
    recorder = record(tmp_path, "recording: {level: summary}\n")
    assert not (recorder.path / "tables").exists()
    assert read(recorder.path / "summary" / "run.csv")[1] == "run-1,96,0"
    content = manifest(recorder)
    assert content["tables"]["pings"]["file"] is None
    assert content["tables"]["pings"]["rows"] is None
    assert content["recording"]["level"] == "summary"


# --------------------------------------------------------------------------- windows


def test_windows_continue_across_days_and_the_last_one_may_be_partial(tmp_path: Path) -> None:
    # 5-hour windows (60 ticks) over two 8-hour days (192 ticks).
    recorder = record(tmp_path, "recording: {window_hours: 5}\n", days=2)
    assert read(recorder.path / "summary" / "windows.csv")[1:] == [
        "run-1,0,0,60,0,true,60,0",
        "run-1,1,60,120,0,true,60,60",
        "run-1,2,120,180,1,true,60,120",
        "run-1,3,180,192,1,false,12,180",
    ]
    assert read(recorder.path / "summary" / "run.csv")[1] == "run-1,192,0"


def test_window_longer_than_the_run(tmp_path: Path) -> None:
    recorder = record(tmp_path, "recording: {window_hours: 16}\n")
    assert read(recorder.path / "summary" / "windows.csv")[1:] == ["run-1,0,0,96,0,false,96,0"]


def test_run_without_ticks(tmp_path: Path) -> None:
    recorder = record(tmp_path, days=0)
    assert read(recorder.path / "summary" / "windows.csv") == [
        "run_id,window,start_tick,end_tick,start_day,complete,pings,first_tick"
    ]
    assert read(recorder.path / "summary" / "run.csv")[1] == "run-1,0,"
    assert manifest(recorder)["ticks_completed"] == 0


# --------------------------------------------------------------------------- writing


def test_rows_are_written_at_the_end_of_every_day(tmp_path: Path) -> None:
    loaded = load()
    simulation = make_simulation(loaded)
    recorder = RunRecorder(
        tmp_path, simulation=simulation, loaded=loaded, tables=TABLES, run_id="r"
    )
    recorder.start()
    pings = recorder.path / "tables" / "pings.csv"
    simulation.run(95)
    assert len(read(pings)) == 1  # header only: the day is not over
    assert manifest(recorder)["status"] == "running"
    simulation.run(1)
    assert len(read(pings)) == 97
    simulation.run(10)
    recorder.finish()
    assert len(read(pings)) == 107
    assert manifest(recorder)["status"] == "completed"


def test_failed_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="boom"):
        record(tmp_path, "recording: {window_hours: 1}\n", days=2, fail_at=130)
    path = tmp_path / "run-1"
    content = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert content["status"] == "failed"
    assert content["error"] == {"type": "ValueError", "message": "boom", "tick": 130}
    assert content["ticks_completed"] == 130
    assert content["tables"]["pings"]["rows"] == 130
    assert len(read(path / "tables" / "pings.csv")) == 1 + 130
    # Ten complete one-hour windows (120 ticks); no row for the window in progress.
    assert len(read(path / "summary" / "windows.csv")) == 1 + 10
    assert read(path / "summary" / "run.csv") == ["run_id,pings,first_tick"]
    assert content["summaries"]["run"]["rows"] == 0


def test_interruption_is_recorded_as_a_failure(tmp_path: Path) -> None:
    loaded = load()
    simulation = make_simulation(loaded)
    with (
        pytest.raises(KeyboardInterrupt),
        RunRecorder(tmp_path, simulation=simulation, loaded=loaded, run_id="r"),
    ):
        simulation.run(3)
        raise KeyboardInterrupt
    content = json.loads((tmp_path / "r" / "manifest.json").read_text(encoding="utf-8"))
    assert content["status"] == "failed"
    assert content["error"]["type"] == "KeyboardInterrupt"


def test_recording_errors_while_failing_are_attached_to_the_run_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = load()
    simulation = make_simulation(loaded, fail_at=5)
    recorder = RunRecorder(tmp_path, simulation=simulation, loaded=loaded, run_id="r")

    def broken(path: Path, data: object) -> None:
        raise OSError("disk full")

    with pytest.raises(ValueError, match="boom") as caught, recorder:
        monkeypatch.setattr(recorder_module, "write_json", broken)
        simulation.run(10)
    assert any("disk full" in note for note in caught.value.__notes__)


# --------------------------------------------------------------------------- determinism


def test_same_configuration_and_seed_give_identical_files(tmp_path: Path) -> None:
    first = record(tmp_path / "a", "recording: {window_hours: 3}\n", days=2)
    second = record(tmp_path / "b", "recording: {window_hours: 3}\n", days=2)
    names = sorted(
        str(path.relative_to(first.path))
        for path in first.path.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    assert names == [
        "config.yaml",
        "summary/run.csv",
        "summary/windows.csv",
        "tables/pings.csv",
        "tables/pongs.csv",
    ]
    for name in names:
        assert (first.path / name).read_bytes() == (second.path / name).read_bytes()


# --------------------------------------------------------------------------- run identifiers


def test_default_run_identifier_uses_the_local_time_and_the_seed(tmp_path: Path) -> None:
    moment = datetime(2026, 11, 8, 14, 32, 5, tzinfo=UTC)
    recorder = record(tmp_path, run_id=None)
    assert recorder.run_id == default_run_id(7, moment.astimezone())
    assert recorder.run_id.endswith("-seed7")


@pytest.mark.parametrize("run_id", ["", "-run", "a/b", "run 1", "..", "é"])
def test_invalid_run_identifiers(tmp_path: Path, run_id: str) -> None:
    loaded = load()
    with pytest.raises(ValueError, match="Invalid run identifier"):
        RunRecorder(tmp_path, simulation=make_simulation(loaded), loaded=loaded, run_id=run_id)


def test_results_are_never_overwritten(tmp_path: Path) -> None:
    record(tmp_path)
    with pytest.raises(FileExistsError):
        record(tmp_path)


def test_an_existing_directory_is_never_reused(tmp_path: Path) -> None:
    (tmp_path / "run-1").mkdir()
    with pytest.raises(FileExistsError):
        record(tmp_path)
    assert list((tmp_path / "run-1").iterdir()) == []


# --------------------------------------------------------------------------- misuse


def test_a_run_is_recorded_from_its_first_tick(tmp_path: Path) -> None:
    loaded = load()
    simulation = make_simulation(loaded)
    simulation.run(1)
    with pytest.raises(ValueError, match="from its first tick"):
        RunRecorder(tmp_path, simulation=simulation, loaded=loaded)


def test_declarations_are_checked(tmp_path: Path) -> None:
    loaded = load()
    simulation = make_simulation(loaded)

    def recorder(**kwargs: Any) -> RunRecorder:
        return RunRecorder(tmp_path, simulation=simulation, loaded=loaded, **kwargs)

    with pytest.raises(TypeError, match="Expected an ObservationTable"):
        recorder(tables=[Ping])
    with pytest.raises(TypeError, match="Expected a SummaryTable"):
        recorder(summaries=[Count])
    with pytest.raises(ValueError, match=r"Each table can be recorded once; repeated: \['pings'\]"):
        recorder(tables=[TABLES[0], ObservationTable("pings", Pong, "x")])
    with pytest.raises(ValueError, match="Each observation type can be recorded once"):
        recorder(tables=[TABLES[0], ObservationTable("other", Ping, "x")])
    with pytest.raises(ValueError, match="Each summary table can be recorded once"):
        recorder(summaries=[SUMMARIES[0], SUMMARIES[0]])


def test_aggregators_are_checked_before_anything_is_written(tmp_path: Path) -> None:
    loaded = load()
    summary = SummaryTable("bad", Count, object, per="run", description="x")
    recorder = RunRecorder(
        tmp_path, simulation=make_simulation(loaded), loaded=loaded, summaries=[summary]
    )
    with pytest.raises(TypeError, match="must have the methods observe"):
        recorder.start()
    assert list(tmp_path.iterdir()) == []


def test_summary_rows_must_have_the_declared_type(tmp_path: Path) -> None:
    class Wrong(Counter):
        def rows(self, period: Period) -> Iterator[Count]:
            yield Ping(0, 0.0, True)  # type: ignore[misc]

    summary = SummaryTable("bad", Count, Wrong, per="run", description="x")
    with pytest.raises(TypeError, match="expected rows of type Count, got Ping"):
        record(tmp_path, summaries=[summary])


def test_summary_values_are_checked(tmp_path: Path) -> None:
    class Wrong(Counter):
        def rows(self, period: Period) -> Iterator[Count]:
            yield Count(1.5, None)  # type: ignore[arg-type]

    summary = SummaryTable("bad", Count, Wrong, per="window", description="x")
    with pytest.raises(TypeError, match=r"bad\.pings: expected integer"):
        record(tmp_path, summaries=[summary])


def test_observation_values_are_checked(tmp_path: Path) -> None:
    loaded = load()

    def run(context: StepContext) -> None:
        context.publish(Ping(context.tick, "x", True))  # type: ignore[arg-type]

    simulation = Simulation(
        phases=[FunctionPhase("ping", run)], streams=RandomStreams(seed=1, specs=())
    )
    with (
        pytest.raises(TypeError, match=r"pings\.value: expected number"),
        RunRecorder(tmp_path, simulation=simulation, loaded=loaded, tables=TABLES, run_id="r"),
    ):
        simulation.run(1)


def test_observations_must_be_published_during_their_tick(tmp_path: Path) -> None:
    loaded = load()

    def run(context: StepContext) -> None:
        context.publish(Ping(context.tick + 1, 0.0, True))

    simulation = Simulation(
        phases=[FunctionPhase("ping", run)], streams=RandomStreams(seed=1, specs=())
    )
    with (
        pytest.raises(ValueError, match="pings: observation of tick 1 published during tick 0"),
        RunRecorder(tmp_path, simulation=simulation, loaded=loaded, tables=TABLES, run_id="r"),
    ):
        simulation.run(1)


def test_life_cycle(tmp_path: Path) -> None:
    loaded = load()
    simulation = make_simulation(loaded)
    recorder = RunRecorder(tmp_path, simulation=simulation, loaded=loaded, run_id="r")
    assert recorder.status == "new"
    with pytest.raises(RuntimeError, match="The recorder is new; expected running"):
        recorder.finish()
    recorder.start()
    with pytest.raises(RuntimeError, match="The recorder is running; expected new"):
        recorder.start()
    recorder.finish()
    with pytest.raises(RuntimeError, match="expected running"):
        recorder.fail(ValueError("late"))


def test_nothing_is_recorded_after_the_end(tmp_path: Path) -> None:
    loaded = load()
    simulation = make_simulation(loaded)
    with RunRecorder(
        tmp_path, simulation=simulation, loaded=loaded, tables=TABLES, run_id="r"
    ) as recorder:
        simulation.run(2)
    simulation.run(2)
    assert len(read(recorder.path / "tables" / "pings.csv")) == 1 + 2


def test_missing_distributions_are_recorded_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def version(distribution: str) -> str:
        raise recorder_module.PackageNotFoundError(distribution)

    monkeypatch.setattr(recorder_module, "version", version)
    software = manifest(record(tmp_path))["software"]
    assert (software["numpy"], software["pydantic"], software["pyyaml"]) == (None, None, None)
