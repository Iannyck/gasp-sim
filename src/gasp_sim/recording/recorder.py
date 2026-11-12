"""Recording of a run: observation tables, summaries and manifest (ADR-0015).

A :class:`RunRecorder` subscribes to the notification bus of a simulation before it runs.
It turns every published observation into a row (level ``full``), feeds the aggregators of
the summary tables (both levels), and writes everything into one directory per run::

    <output>/<run-id>/
        manifest.json     # what ran, how, and what each column means
        config.yaml       # the resolved configuration, loadable as it is
        tables/<name>.csv     # one row per observation (level "full" only)
        summary/<name>.csv    # rows of the aggregators, per window or per run

Rows are written at the end of every simulated working day. The manifest is written at
the start with the status ``running``, and completed at the end with ``completed`` or,
if the run raised an error, ``failed``; the error itself is never swallowed.

Example
-------
::

    with RunRecorder(output, simulation=model.simulation, loaded=loaded,
                     tables=TABLES, summaries=SUMMARIES) as recorder:
        model.simulation.run(loaded.config.run_ticks())
    print(recorder.path)
"""

from __future__ import annotations

import platform
import re
import sys
import time
import warnings
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

import gasp_sim
from gasp_sim.config.loader import LoadedConfig
from gasp_sim.config.schema import RunSettings
from gasp_sim.core.clock import DurationRoundingWarning
from gasp_sim.core.events import Subscription
from gasp_sim.core.rng import BIT_GENERATOR
from gasp_sim.core.simulation import Simulation, StepCompleted
from gasp_sim.recording.files import CsvFile, write_json
from gasp_sim.recording.tables import (
    Aggregator,
    Column,
    ObservationTable,
    Period,
    SummaryTable,
)

__all__ = ["MANIFEST_VERSION", "RunRecorder", "default_run_id"]

#: Version of the layout of ``manifest.json``; increased when it changes.
MANIFEST_VERSION = 2

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

_OBSERVATION_PREFIX = (
    Column("run_id", "text", "Identifier of the run."),
    Column("tick", "integer", "Tick of the observation, from 0.", unit="tick"),
    Column("day", "integer", "Working day of the observation, from 0.", unit="day"),
    Column(
        "minutes",
        "integer",
        "Working minutes since the start of the day of the observation.",
        unit="minute",
    ),
)
_WINDOW_PREFIX = (
    Column("run_id", "text", "Identifier of the run."),
    Column("window", "integer", "Number of the time window, from 0."),
    Column("start_tick", "integer", "First tick of the window.", unit="tick"),
    Column("end_tick", "integer", "Tick after the last tick of the window.", unit="tick"),
    Column("start_day", "integer", "Working day of the first tick, from 0.", unit="day"),
    Column(
        "complete",
        "boolean",
        "False for a last window cut short by the end of the run.",
    ),
)
_RUN_PREFIX = (Column("run_id", "text", "Identifier of the run."),)


def default_run_id(seed: int, moment: datetime) -> str:
    """Return a readable run identifier: local date and time, then the seed.

    Examples
    --------
    >>> default_run_id(42, datetime(2026, 11, 8, 14, 32, 5))
    '20261108-143205-seed42'
    """
    return f"{moment:%Y%m%d-%H%M%S}-seed{seed}"


class RunRecorder:
    """Record one run of a simulation.

    Parameters
    ----------
    output : str or Path
        Directory in which the directory of the run is created.
    simulation : Simulation
        The simulation to record; it must not have run yet.
    loaded : LoadedConfig
        The configuration of the run (its resolved form is saved, and its ``recording``
        settings choose the level and the windows).
    tables : sequence of ObservationTable
        Observation types to record; their aggregators receive them in both levels.
    summaries : sequence of SummaryTable
        Summary tables, written in both levels.
    run_id : str, optional
        Name of the directory of the run; by default the local date and time and the
        seed (:func:`default_run_id`). The directory must not exist.
    clock : callable, optional
        Returns the current time (timezone-aware); for tests.

    Raises
    ------
    ValueError
        If two tables share a name or an observation type, if the run identifier is not a
        valid directory name, or if the simulation has already run.
    """

    def __init__(
        self,
        output: str | Path,
        *,
        simulation: Simulation,
        loaded: LoadedConfig[Any],
        tables: Sequence[ObservationTable] = (),
        summaries: Sequence[SummaryTable] = (),
        run_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock if clock is not None else _utc_now
        config: RunSettings = loaded.config
        self._simulation = simulation
        self._loaded = loaded
        self._tables = tuple(tables)
        self._summaries = tuple(summaries)
        _check_declarations(self._tables, self._summaries)
        self._run_id = (
            run_id
            if run_id is not None
            else default_run_id(config.seed, self._clock().astimezone())
        )
        if _RUN_ID.fullmatch(self._run_id) is None:
            raise ValueError(
                f"Invalid run identifier {self._run_id!r}: use letters, digits, '.', '_' and "
                "'-', starting with a letter or a digit."
            )
        if simulation.next_tick != 0:
            raise ValueError("A run must be recorded from its first tick.")
        self._path = Path(output) / self._run_id
        self._level: Literal["full", "summary"] = config.recording.level
        grid = simulation.grid
        with warnings.catch_warnings():
            # Already reported by the configuration loader.
            warnings.simplefilter("ignore", DurationRoundingWarning)
            self._window_ticks = grid.hours_to_ticks(
                config.recording.window_hours, name="recording.window_hours"
            )
        self._status: Literal["new", "running", "completed", "failed"] = "new"
        self._subscriptions: list[Subscription] = []
        self._observation_files: dict[type, tuple[ObservationTable, CsvFile | None]] = {}
        self._summary_files: list[tuple[SummaryTable, CsvFile, Aggregator]] = []
        self._manifest: dict[str, Any] = {}
        self._run_rows: dict[str, tuple[object, ...]] = {}
        self._started = 0.0

    # ----------------------------------------------------------------- properties

    @property
    def run_id(self) -> str:
        """Identifier of the run, also the name of its directory."""
        return self._run_id

    @property
    def path(self) -> Path:
        """Directory of the run."""
        return self._path

    @property
    def status(self) -> str:
        """``"new"``, ``"running"``, ``"completed"`` or ``"failed"``."""
        return self._status

    @property
    def run_rows(self) -> dict[str, tuple[object, ...]]:
        """Rows of the summaries of the whole run, by table name, once the run is completed.

        Empty before :meth:`finish`, and after a failed run (no run summary is written).
        """
        return dict(self._run_rows)

    # ----------------------------------------------------------------- life cycle

    def __enter__(self) -> Self:
        """Start recording."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Finish the record: ``completed`` without error, ``failed`` otherwise."""
        if exc is None:
            self.finish()
            return
        try:
            self.fail(exc)
        except Exception as error:
            exc.add_note(f"The run record could not be completed: {error!r}")

    def start(self) -> None:
        """Create the directory, write the configuration and the manifest, subscribe.

        Raises
        ------
        FileExistsError
            If the directory of the run already exists (results are never overwritten).
        """
        self._require("new")
        aggregators = [summary.aggregator() for summary in self._summaries]
        for summary, aggregator in zip(self._summaries, aggregators, strict=True):
            if not isinstance(aggregator, Aggregator):
                raise TypeError(
                    f"Summary table {summary.name!r}: the aggregator must have the methods "
                    "observe(observation) and rows(period)."
                )
        self._path.mkdir(parents=True, exist_ok=False)
        (self._path / "config.yaml").write_text(self._loaded.to_yaml(), encoding="utf-8")
        bus = self._simulation.bus
        for table in self._tables:
            observation_file = None
            if self._level == "full":
                header = [column.name for column in (*_OBSERVATION_PREFIX, *table.columns)]
                observation_file = CsvFile(self._path / "tables" / f"{table.name}.csv", header)
            self._observation_files[table.observation] = (table, observation_file)
            self._subscriptions.append(bus.subscribe(table.observation, self._observe))
        for summary, aggregator in zip(self._summaries, aggregators, strict=True):
            prefix = _WINDOW_PREFIX if summary.per == "window" else _RUN_PREFIX
            header = [column.name for column in (*prefix, *summary.columns)]
            summary_file = CsvFile(self._path / "summary" / f"{summary.name}.csv", header)
            self._summary_files.append((summary, summary_file, aggregator))
        self._subscriptions.append(bus.subscribe(StepCompleted, self._step_completed))
        self._status = "running"
        self._started = time.perf_counter()
        self._manifest = self._initial_manifest()
        self._write_manifest()

    def finish(self) -> None:
        """Write the last summaries and every pending row; mark the run ``completed``."""
        self._require("running")
        ticks = self._simulation.next_tick
        last_window = ticks // self._window_ticks
        if ticks % self._window_ticks:
            self._close_period(
                "window",
                Period(last_window, last_window * self._window_ticks, ticks, complete=False),
            )
        self._close_period("run", Period(0, 0, ticks))
        self._end("completed", error=None)

    def fail(self, error: BaseException) -> None:
        """Write the pending rows and mark the run ``failed`` with ``error``.

        Summaries of the window in progress and of the whole run are not written: they
        would describe an incomplete period.
        """
        self._require("running")
        self._end(
            "failed",
            error={
                "type": type(error).__name__,
                "message": str(error),
                "tick": self._simulation.next_tick,
            },
        )

    # ----------------------------------------------------------------- bus handlers

    def _observe(self, observation: object) -> None:
        table, file = self._observation_files[type(observation)]
        tick = getattr(observation, "tick")  # noqa: B009 - checked by ObservationTable
        current = self._simulation.next_tick
        if tick != current:
            raise ValueError(
                f"{table.name}: observation of tick {tick!r} published during tick {current}."
            )
        values = [getattr(observation, column.name) for column in table.columns]
        for column, value in zip(table.columns, values, strict=True):
            column.check(value, table.name)
        if file is not None:
            grid = self._simulation.grid
            minutes = grid.tick_of_day(tick) * grid.tick_minutes
            file.add([self._run_id, tick, grid.day_of(tick), minutes, *values])
        for _, _, aggregator in self._summary_files:
            aggregator.observe(observation)

    def _step_completed(self, notification: StepCompleted) -> None:
        tick = notification.tick
        if (tick + 1) % self._window_ticks == 0:
            index = tick // self._window_ticks
            self._close_period("window", Period(index, index * self._window_ticks, tick + 1))
        if (tick + 1) % self._simulation.grid.ticks_per_day == 0:
            self._flush()

    # ----------------------------------------------------------------- internals

    def _close_period(self, per: str, period: Period) -> None:
        grid = self._simulation.grid
        for summary, file, aggregator in self._summary_files:
            if summary.per != per:
                continue
            rows = tuple(aggregator.rows(period))
            if per == "run":
                self._run_rows[summary.name] = rows
            for row in rows:
                if type(row) is not summary.row:
                    raise TypeError(
                        f"Summary table {summary.name!r}: expected rows of type "
                        f"{summary.row.__qualname__}, got {type(row).__qualname__}."
                    )
                values = [getattr(row, column.name) for column in summary.columns]
                for column, value in zip(summary.columns, values, strict=True):
                    column.check(value, summary.name)
                if per == "window":
                    prefix: list[object] = [
                        self._run_id,
                        period.index,
                        period.start_tick,
                        period.end_tick,
                        grid.day_of(period.start_tick),
                        period.complete,
                    ]
                else:
                    prefix = [self._run_id]
                file.add([*prefix, *values])

    def _flush(self) -> None:
        for _, file in self._observation_files.values():
            if file is not None:
                file.flush()
        for _, file, _ in self._summary_files:
            file.flush()

    def _end(self, status: Literal["completed", "failed"], error: dict[str, Any] | None) -> None:
        for subscription in self._subscriptions:
            self._simulation.bus.unsubscribe(subscription)
        self._subscriptions.clear()
        self._status = status
        try:
            self._flush()
        finally:
            self._manifest.update(
                status=status,
                finished_at=_timestamp(self._clock()),
                duration_seconds=round(time.perf_counter() - self._started, 3),
                ticks_completed=self._simulation.next_tick,
                error=error,
            )
            for table, observation_file in self._observation_files.values():
                if observation_file is not None:
                    self._manifest["tables"][table.name]["rows"] = observation_file.rows
            for summary, file, _ in self._summary_files:
                self._manifest["summaries"][summary.name]["rows"] = file.rows
            self._write_manifest()

    def _initial_manifest(self) -> dict[str, Any]:
        config: RunSettings = self._loaded.config
        grid = self._simulation.grid
        return {
            "manifest_version": MANIFEST_VERSION,
            "run_id": self._run_id,
            "status": "running",
            "started_at": _timestamp(self._clock()),
            "finished_at": None,
            "duration_seconds": None,
            "ticks_completed": None,
            "error": None,
            "software": _software(),
            "random": {
                "seed": config.seed,
                "stream_mode": config.stream_mode,
                "bit_generator": BIT_GENERATOR,
            },
            "time": {
                "tick_minutes": grid.tick_minutes,
                "day_minutes": grid.day_minutes,
                "days": config.days,
                "hours": config.hours,
                "ticks": config.run_ticks(),
            },
            "configuration": {
                "file": "config.yaml",
                "source": Path(self._loaded.origin).name,
                "preset": config.preset,
                "plugins": [plugin.describe() for plugin in self._loaded.registry.plugins],
                "warnings": [str(issue) for issue in self._loaded.warnings],
            },
            "recording": {
                "level": self._level,
                "window_hours": config.recording.window_hours,
                "window_ticks": self._window_ticks,
                "csv": {
                    "separator": ",",
                    "decimal": ".",
                    "booleans": ["true", "false"],
                    "empty": "",
                    "encoding": "utf-8",
                },
            },
            "tables": {
                table.name: {
                    "file": f"tables/{table.name}.csv" if self._level == "full" else None,
                    "observation": _qualified_name(table.observation),
                    "description": table.description,
                    "rows": None,
                    "columns": [
                        column.describe() for column in (*_OBSERVATION_PREFIX, *table.columns)
                    ],
                }
                for table in self._tables
            },
            "summaries": {
                summary.name: {
                    "file": f"summary/{summary.name}.csv",
                    "per": summary.per,
                    "description": summary.description,
                    "rows": None,
                    "columns": [
                        column.describe()
                        for column in (
                            *(_WINDOW_PREFIX if summary.per == "window" else _RUN_PREFIX),
                            *summary.columns,
                        )
                    ],
                }
                for summary in self._summaries
            },
        }

    def _write_manifest(self) -> None:
        write_json(self._path / "manifest.json", self._manifest)

    def _require(self, status: str) -> None:
        if self._status != status:
            raise RuntimeError(f"The recorder is {self._status}; expected {status}.")


def _check_declarations(
    tables: tuple[ObservationTable, ...], summaries: tuple[SummaryTable, ...]
) -> None:
    for table in tables:
        if not isinstance(table, ObservationTable):
            raise TypeError(f"Expected an ObservationTable, got {table!r}.")
    for summary in summaries:
        if not isinstance(summary, SummaryTable):
            raise TypeError(f"Expected a SummaryTable, got {summary!r}.")
    for kind, names in (
        ("table", [table.name for table in tables]),
        ("summary table", [summary.name for summary in summaries]),
        ("observation type", [_qualified_name(table.observation) for table in tables]),
    ):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Each {kind} can be recorded once; repeated: {duplicates}.")


def _software() -> dict[str, Any]:
    def installed(distribution: str) -> str | None:
        try:
            return version(distribution)
        except PackageNotFoundError:
            return None

    return {
        "gasp_sim": gasp_sim.__version__,
        "python": platform.python_version(),
        "numpy": installed("numpy"),
        "pydantic": installed("pydantic"),
        "pyyaml": installed("pyyaml"),
        "platform": platform.platform(),
        "implementation": sys.implementation.name,
    }


def _qualified_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
