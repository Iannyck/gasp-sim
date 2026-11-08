"""Example plugin: adds a ``threshold`` speaking rule to the toy chatter model.

A plugin is a module with a function ``register(registry)``. List it under ``plugins:`` in
a configuration file (see ``configs/with_plugin.yaml``), or publish it in a package under
an entry point.

Toy example only: the rule has no scientific basis.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from examples.toy_chatter.config import SPEAKING_RULE
from gasp_sim.api import Component, ComponentParameters, Registry

__all__ = ["ThresholdRule", "ThresholdRuleParameters", "register"]


@dataclass(frozen=True, slots=True)
class ThresholdRule:
    """Speak with one probability in a quiet channel, another in a lively one."""

    threshold: float
    quiet_probability: float
    lively_probability: float

    def probability_for(self, recent_share: float) -> float:
        """Return the probability for the given recent activity."""
        if recent_share >= self.threshold:
            return self.lively_probability
        return self.quiet_probability


class ThresholdRuleParameters(ComponentParameters):
    """Speak with one probability in a quiet channel and another in a lively one."""

    threshold: float = Field(
        default=0.5, ge=0, le=1, description="Share of recent speakers that makes it lively."
    )
    quiet_probability: float = Field(default=0.2, ge=0, le=1)
    lively_probability: float = Field(default=0.6, ge=0, le=1)


def _build(parameters: ThresholdRuleParameters) -> ThresholdRule:
    return ThresholdRule(
        threshold=parameters.threshold,
        quiet_probability=parameters.quiet_probability,
        lively_probability=parameters.lively_probability,
    )


def register(registry: Registry) -> None:
    """Register the ``threshold`` speaking rule."""
    registry.register(SPEAKING_RULE, Component("threshold", ThresholdRuleParameters, _build))
