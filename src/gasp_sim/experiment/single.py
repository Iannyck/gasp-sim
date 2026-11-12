"""One run of a model, recorded in its own directory (ADR-0016).

:func:`run_single` builds the simulation described by a loaded configuration, runs it for
the length given in the configuration (``days`` or ``hours``) and records it with a
:class:`~gasp_sim.recording.recorder.RunRecorder`. The command line (``gasp-sim run``)
uses it; batches of runs (step 7) and the user interface will use it too.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gasp_sim.config.loader import LoadedConfig
from gasp_sim.experiment.definition import ModelDefinition
from gasp_sim.recording.recorder import RunRecorder

__all__ = ["RunFailedError", "RunResult", "run_single"]


@dataclass(frozen=True, slots=True)
class RunResult:
    """Outcome of a completed run.

    Attributes
    ----------
    run_id : str
        Identifier of the run.
    path : Path
        Directory of the run.
    headline : tuple of (str, object)
        Values chosen by the model definition, as pairs (column, value); ``None`` when the
        run summary has no row.
    """

    run_id: str
    path: Path
    headline: tuple[tuple[str, object], ...]


class RunFailedError(Exception):
    """A run stopped with an error; its directory holds what was recorded until then.

    The original error is the ``__cause__`` of this one.

    Attributes
    ----------
    path : Path
        Directory of the failed run (its manifest has the status ``failed``).
    """

    def __init__(self, path: Path, error: BaseException) -> None:
        super().__init__(f"The run failed: {type(error).__name__}: {error}")
        self.path = path


def run_single(
    definition: ModelDefinition[Any],
    loaded: LoadedConfig[Any],
    output: str | Path,
    *,
    run_id: str | None = None,
) -> RunResult:
    """Build, run and record one run of a model.

    Parameters
    ----------
    definition : ModelDefinition
        The model.
    loaded : LoadedConfig
        Its configuration, loaded with :meth:`ModelDefinition.load`.
    output : str or Path
        Directory in which the directory of the run is created.
    run_id : str, optional
        Name of the directory of the run; by default the local date and time and the seed.

    Returns
    -------
    RunResult
        The run identifier, its directory and the headline values.

    Raises
    ------
    RunFailedError
        If the simulation raised an error while running; the run is recorded as
        ``failed``.
    ValueError
        If the run identifier is not a valid directory name.
    FileExistsError
        If the directory of the run already exists.
    """
    simulation = definition.build(loaded)
    recorder = RunRecorder(
        output,
        simulation=simulation,
        loaded=loaded,
        tables=definition.tables,
        summaries=definition.summaries,
        run_id=run_id,
    )
    try:
        with recorder:
            simulation.run(loaded.config.run_ticks())
    except Exception as error:
        if recorder.status != "failed":
            raise
        raise RunFailedError(recorder.path, error) from error
    rows = recorder.run_rows
    headline = tuple(
        (column, getattr(rows[table][0], column) if rows[table] else None)
        for table, column in definition.headline
    )
    return RunResult(recorder.run_id, recorder.path, headline)
