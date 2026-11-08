"""Run the toy chatter model from a configuration file (example only, no scientific value).

Run from the root of the repository::

    uv run python -m examples.toy_chatter.run                       # configs/default.yaml
    uv run python -m examples.toy_chatter.run path/to/config.yaml
    uv run python -m examples.toy_chatter.run path/to/config.yaml --resolved

``--resolved`` prints every setting, defaults included, instead of running the model.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from examples.toy_chatter.config import CONFIG_DIR, build, load
from gasp_sim.api import ConfigError

DEFAULT_CONFIG = CONFIG_DIR / "default.yaml"


def main(argv: Sequence[str] | None = None) -> int:
    """Load a configuration, run the model and print a summary; return the exit status."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    resolved = "--resolved" in arguments
    paths = [argument for argument in arguments if argument != "--resolved"]
    if len(paths) > 1 or any(path.startswith("-") for path in paths):
        print("usage: python -m examples.toy_chatter.run [CONFIG] [--resolved]", file=sys.stderr)
        return 2
    path = Path(paths[0]) if paths else DEFAULT_CONFIG
    try:
        loaded = load(path)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    for warning in loaded.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if resolved:
        print(loaded.to_yaml(), end="")
        return 0
    config = loaded.config
    rule = loaded.resolved()["speaking_rule"]
    rule_name = rule.pop("type")
    rule_parameters = ", ".join(f"{name}={value}" for name, value in rule.items())
    model = build(loaded)
    model.run_days(config.days)
    summary = model.summary()
    print("Toy chatter (example model, no scientific value)")
    print(f"  configuration: {os.path.relpath(path)}")
    print(f"  speaking rule: {rule_name} ({rule_parameters})")
    print(f"  seed: {config.seed}, agents: {config.n_agents}, working days: {config.days}")
    print(f"  ticks: {summary.ticks}, consultations: {summary.consultations}")
    print(f"  messages: {summary.messages}")
    print(f"  mean participation per consultation round: {summary.mean_participation:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
