"""Run the toy chatter model from a configuration file (example only, no scientific value).

Run from the root of the repository::

    uv run python -m examples.toy_chatter.run                       # configs/default.yaml
    uv run python -m examples.toy_chatter.run path/to/config.yaml
    uv run python -m examples.toy_chatter.run path/to/config.yaml --resolved
    uv run python -m examples.toy_chatter.run path/to/config.yaml --output results

``--resolved`` prints every setting, defaults included, instead of running the model.
``--output DIR`` records the run (tables, summaries, manifest) in a new directory inside
``DIR`` (ADR-0015).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from examples.toy_chatter.config import CONFIG_DIR, build, load
from examples.toy_chatter.outputs import SUMMARIES, TABLES
from gasp_sim.api import ConfigError, RunRecorder

DEFAULT_CONFIG = CONFIG_DIR / "default.yaml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examples.toy_chatter.run",
        description="Run the toy chatter model (example only, no scientific value).",
    )
    parser.add_argument("config", nargs="?", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--resolved", action="store_true", help="print every setting instead of running"
    )
    parser.add_argument(
        "--output", type=Path, metavar="DIR", help="record the run in a new directory in DIR"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Load a configuration, run the model and print a summary; return the exit status."""
    try:
        arguments = _parser().parse_args(argv)
    except SystemExit as exit_request:
        return int(exit_request.code or 0)
    path: Path = arguments.config
    try:
        loaded = load(path)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    for warning in loaded.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if arguments.resolved:
        print(loaded.to_yaml(), end="")
        return 0
    config = loaded.config
    rule = loaded.resolved()["speaking_rule"]
    rule_name = rule.pop("type")
    rule_parameters = ", ".join(f"{name}={value}" for name, value in rule.items())
    model = build(loaded)
    if arguments.output is None:
        model.simulation.run(config.run_ticks())
        record = None
    else:
        with RunRecorder(
            arguments.output,
            simulation=model.simulation,
            loaded=loaded,
            tables=TABLES,
            summaries=SUMMARIES,
        ) as recorder:
            model.simulation.run(config.run_ticks())
        record = recorder.path
    summary = model.summary()
    print("Toy chatter (example model, no scientific value)")
    print(f"  configuration: {os.path.relpath(path)}")
    print(f"  speaking rule: {rule_name} ({rule_parameters})")
    length = f"{config.days} working days" if config.days else f"{config.hours:g} working hours"
    print(f"  seed: {config.seed}, agents: {config.n_agents}, length: {length}")
    print(f"  ticks: {summary.ticks}, consultations: {summary.consultations}")
    print(f"  messages: {summary.messages}")
    print(f"  mean participation per consultation round: {summary.mean_participation:.3f}")
    if record is not None:
        print(f"  results: {os.path.relpath(record)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
