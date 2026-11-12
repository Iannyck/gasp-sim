"""Entry point of the ``gasp-sim`` command-line interface (ADR-0016).

Commands:

- ``gasp-sim validate CONFIG [--resolved]`` checks a configuration file and reports every
  error and warning; ``--resolved`` prints every setting, defaults included.
- ``gasp-sim run CONFIG [--output DIR] [--run-id ID]`` runs the model and records the run
  in a new directory inside ``DIR`` (``results`` by default).

Exit status: 0 on success; 1 if the configuration is invalid or the run fails; 2 if the
command itself is mistyped. Commands for batches, figures and the user interface (``sweep``,
``plot``, ``ui``) will be added in later steps.

The commands only read their arguments and print results; the work is done by the
experiment layer (:func:`gasp_sim.experiment.single.run_single`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from gasp_sim import __version__
from gasp_sim.config.loader import ConfigError, LoadedConfig
from gasp_sim.experiment.definition import ModelDefinition
from gasp_sim.experiment.single import RunFailedError, run_single
from gasp_sim.recording.tables import format_value
from gasp_sim.registry import PluginError

__all__ = ["ModelUnavailableError", "app", "default_model", "make_app"]

#: Directory of the results when ``--output`` is not given.
DEFAULT_OUTPUT = Path("results")


class ModelUnavailableError(Exception):
    """The model to run cannot be provided."""


def default_model() -> ModelDefinition[Any]:
    """Return the definition of the GASP model.

    Raises
    ------
    ModelUnavailableError
        Until the GASP model is written (step 6.1b).
    """
    raise ModelUnavailableError("The GASP model is not available yet in this version.")


def make_app(model: Callable[[], ModelDefinition[Any]] = default_model) -> typer.Typer:
    """Create the command-line application for the model returned by ``model``.

    The model is obtained only when a command needs it, so that ``--help`` and
    ``--version`` always work.
    """
    application = typer.Typer(
        name="gasp-sim",
        help="Agent-based simulator of the spiral of silence and affective social proxies.",
        no_args_is_help=True,
        add_completion=False,
    )

    @application.callback()
    def main(
        version: Annotated[
            bool,
            typer.Option(
                "--version",
                callback=_version_callback,
                is_eager=True,
                help="Show the version and exit.",
            ),
        ] = False,
    ) -> None:
        """Run gasp-sim from the command line."""

    @application.command()
    def validate(
        config: Annotated[Path, typer.Argument(help="Configuration file (YAML).")],
        resolved: Annotated[
            bool,
            typer.Option("--resolved", help="Print every setting, defaults included."),
        ] = False,
    ) -> None:
        """Check a configuration file and report every error and warning."""
        loaded = _load(_model(model), config)
        if resolved:
            typer.echo(loaded.to_yaml(), nl=False)
        else:
            typer.echo(f"{config}: valid configuration.")

    @application.command()
    def run(
        config: Annotated[Path, typer.Argument(help="Configuration file (YAML).")],
        output: Annotated[
            Path,
            typer.Option(
                "--output",
                help="Directory in which a new directory is created for the run.",
            ),
        ] = DEFAULT_OUTPUT,
        run_id: Annotated[
            str | None,
            typer.Option(
                "--run-id",
                help="Name of the directory of the run (default: date, time and seed).",
            ),
        ] = None,
    ) -> None:
        """Run the model and record the run (tables, summaries, manifest)."""
        definition = _model(model)
        loaded = _load(definition, config)
        try:
            result = run_single(definition, loaded, output, run_id=run_id)
        except RunFailedError as error:
            _fail(f"error: {error}\npartial results: {error.path}")
        except (ValueError, FileExistsError) as error:
            _fail(f"error: {error}")
        typer.echo(f"results: {result.path}")
        for column, value in result.headline:
            typer.echo(f"  {column}: {format_value(value) if value is not None else '(none)'}")

    return application


def _version_callback(value: bool) -> None:
    """Print the version and exit when ``--version`` is given."""
    if value:
        typer.echo(f"gasp-sim {__version__}")
        raise typer.Exit()


def _model(model: Callable[[], ModelDefinition[Any]]) -> ModelDefinition[Any]:
    try:
        return model()
    except ModelUnavailableError as error:
        _fail(f"error: {error}")


def _load(definition: ModelDefinition[Any], config: Path) -> LoadedConfig[Any]:
    """Load a configuration file, print its warnings, or stop with its errors."""
    try:
        loaded = definition.load(config)
    except (ConfigError, PluginError) as error:
        _fail(str(error))
    for warning in loaded.warnings:
        typer.echo(f"warning: {warning}", err=True)
    return loaded


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


#: The ``gasp-sim`` application (entry point declared in ``pyproject.toml``).
app = make_app()
