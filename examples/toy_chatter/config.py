"""Configuration of the toy chatter model: schema, components, presets (example only).

This module shows how a model becomes configurable from a YAML file with the public API:

- an **extension point**, :data:`SPEAKING_RULE`, for the replaceable speaking rule;
- two **components** of that extension point, ``constant`` and ``feedback``, each with its
  own validated parameters;
- a **preset**, ``no_feedback``;
- the **configuration schema**, :class:`ToyConfig`;
- :func:`default_registry`, :func:`load` and :func:`build`, from a file to a model ready to
  run.

The model itself (:mod:`examples.toy_chatter.model`) does not know about configuration
files.

Examples
--------
>>> loaded = load("examples/toy_chatter/configs/default.yaml")
>>> model = build(loaded)
>>> model.run_days(loaded.config.days)
>>> model.summary().consultations
400
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Annotated

from pydantic import Field

from examples.toy_chatter.model import (
    ConstantRule,
    FeedbackRule,
    SpeakingRule,
    ToyChatter,
    ToyParameters,
)
from gasp_sim.api import (
    Component,
    ComponentParameters,
    DurationRoundingWarning,
    ExactHours,
    ExtensionPoint,
    Hours,
    LoadedConfig,
    Preset,
    Registry,
    RunSettings,
    Slot,
    load_config,
)

__all__ = [
    "CONFIG_DIR",
    "SPEAKING_RULE",
    "ConstantRuleParameters",
    "FeedbackRuleParameters",
    "ToyConfig",
    "build",
    "default_registry",
    "load",
]

#: Directory of the example configuration files.
CONFIG_DIR = Path(__file__).parent / "configs"

#: Extension point of the rule that gives the probability of speaking.
SPEAKING_RULE: ExtensionPoint[SpeakingRule] = ExtensionPoint(
    "speaking_rule",
    SpeakingRule,
    summary="Rule that gives the probability that a consulting agent speaks.",
)

Probability = Annotated[float, Field(ge=0, le=1)]


class ConstantRuleParameters(ComponentParameters):
    """Speak with the same probability at every consultation, whatever the channel."""

    probability: Probability = Field(default=0.3, description="Probability of speaking.")


class FeedbackRuleParameters(ComponentParameters):
    """Speak more when others spoke recently: min(1, base + feedback * recent share)."""

    base_probability: Probability = Field(
        default=0.3, description="Probability of speaking when the channel has been silent."
    )
    feedback: float = Field(
        default=0.4,
        ge=0,
        description="Added to the probability, times the share of agents who spoke recently.",
    )


def _constant(parameters: ConstantRuleParameters) -> ConstantRule:
    return ConstantRule(probability=parameters.probability)


def _feedback(parameters: FeedbackRuleParameters) -> FeedbackRule:
    return FeedbackRule(base_probability=parameters.base_probability, feedback=parameters.feedback)


class ToyConfig(RunSettings):
    """Configuration of the toy chatter model (example only, no scientific value)."""

    n_agents: int = Field(default=5, ge=1, description="Number of agents.")
    consultation_period_hours: Annotated[ExactHours, Field(gt=0)] = Field(
        default=0.5,
        description="Time between two consultations of an agent, in hours.",
    )
    window_hours: Annotated[Hours, Field(gt=0)] = Field(
        default=1.0, description="Length of the recent window perceived by agents, in hours."
    )
    speaking_rule: Annotated[ComponentParameters, Slot(SPEAKING_RULE, default="feedback")]


def default_registry() -> Registry:
    """Return a registry with the built-in components and presets of the toy model."""
    registry = Registry()
    registry.add_extension_point(SPEAKING_RULE)
    registry.register(SPEAKING_RULE, Component("constant", ConstantRuleParameters, _constant))
    registry.register(SPEAKING_RULE, Component("feedback", FeedbackRuleParameters, _feedback))
    registry.add_preset(
        Preset(
            "no_feedback",
            {"speaking_rule": {"type": "constant", "probability": 0.3}},
            summary="Agents ignore the channel: constant probability of speaking.",
        )
    )
    return registry


def load(path: str | Path, registry: Registry | None = None) -> LoadedConfig[ToyConfig]:
    """Load and validate a configuration file of the toy model.

    Raises
    ------
    gasp_sim.api.ConfigError
        If the configuration is invalid; the message lists every problem.
    """
    return load_config(path, ToyConfig, registry if registry is not None else default_registry())


def build(loaded: LoadedConfig[ToyConfig]) -> ToyChatter:
    """Build the model described by a loaded configuration.

    Rounded durations are not warned about again: the loader already reported them in
    ``loaded.warnings``.
    """
    config = loaded.config
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DurationRoundingWarning)
        return ToyChatter(
            ToyParameters(
                n_agents=config.n_agents,
                consultation_period_hours=config.consultation_period_hours,
                window_hours=config.window_hours,
            ),
            seed=config.seed,
            rule=loaded.registry.create(SPEAKING_RULE, config.speaking_rule),
            mode=config.random_stream_mode(),
            grid=config.time.grid(),
        )
