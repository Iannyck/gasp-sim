"""Smoke tests: the package installs, imports and exposes its command-line interface."""

import importlib
from importlib.metadata import version

import pytest
from typer.testing import CliRunner

import gasp_sim
from gasp_sim.cli.main import app

SUBPACKAGES = [
    "core",
    "model",
    "config",
    "recording",
    "experiment",
    "analysis",
    "viz",
    "ui",
    "cli",
]


def test_version_matches_package_metadata() -> None:
    assert gasp_sim.__version__ == version("gasp-sim")


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_is_importable(name: str) -> None:
    module = importlib.import_module(f"gasp_sim.{name}")
    assert module.__doc__, f"gasp_sim.{name} should describe its role in a docstring"


def test_cli_reports_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"gasp-sim {gasp_sim.__version__}"


def test_cli_without_arguments_shows_help() -> None:
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output
