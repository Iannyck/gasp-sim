"""Entry point of the ``gasp-sim`` command-line interface.

Commands to run simulations and batches (``validate``, ``run``, ``sweep``, ``plot``,
``ui``) will be added in later steps. For now the interface only reports its version.
"""

from typing import Annotated

import typer

from gasp_sim import __version__

app = typer.Typer(
    name="gasp-sim",
    help="Agent-based simulator of the spiral of silence and affective social proxies.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the version and exit when ``--version`` is given."""
    if value:
        typer.echo(f"gasp-sim {__version__}")
        raise typer.Exit()


@app.callback()
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
