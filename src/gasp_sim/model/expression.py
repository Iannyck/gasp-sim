"""Probability of expressing an intention (extension point ``expression_probability``).

According to the article, the probability of speaking decreases with perceived isolation
and increases with psychological safety; its formula is not published [article]. A member
speaks if a uniform draw ``r`` satisfies ``r ≤ P`` (equation 1 of the article).

Two components [modelling assumptions]:

- ``logistic`` (default):
  ``logit P = intercept + safety_weight (safety - 0.5) + climate_weight (climate - 0.5)``.
  Centring on 0.5 makes the weights readable: with ``intercept`` 0, a member of average
  safety in a neutral climate speaks one time in two; ``exp(safety_weight)`` is the odds
  ratio between the safest member and the least safe one. Further terms (propensity,
  fear of isolation * social risk, courage) will be added on the same scale.
- ``linear``: ``P = intercept + safety_weight * safety + climate_weight * climate``, clipped
  to [0, 1]; easier to read, but flat beyond the bounds. For sensitivity analyses.

The climate is the one perceived by the member (see :mod:`gasp_sim.model.perception`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import Field

from gasp_sim.config.base import ComponentParameters
from gasp_sim.registry import Component, ExtensionPoint, Registry

__all__ = [
    "EXPRESSION_PROBABILITY",
    "ExpressionProbability",
    "LinearParameters",
    "LinearProbability",
    "LogisticParameters",
    "LogisticProbability",
    "SpeakerView",
    "register_expression_probabilities",
]


@dataclass(frozen=True, slots=True)
class SpeakerView:
    """What the probability of expressing an intention may depend on.

    New attributes will be added as the model grows (propensity, fear of isolation, social
    risk of the message, signal of the proxy); components only read those they use.

    Attributes
    ----------
    psychological_safety : float
        Psychological safety of the member, in [0, 1].
    perceived_climate : float
        Climate perceived by the member at this consultation, in [0, 1].
    """

    psychological_safety: float
    perceived_climate: float


@runtime_checkable
class ExpressionProbability(Protocol):
    """Gives the probability that a member expresses an intention (``expression_probability``)."""

    def probability(self, speaker: SpeakerView) -> float:
        """Return a probability in [0, 1]."""


#: Extension point of the probability of expressing an intention.
EXPRESSION_PROBABILITY: ExtensionPoint[ExpressionProbability] = ExtensionPoint(
    "expression_probability",
    ExpressionProbability,
    summary="Probability that a member expresses an intention at a consultation.",
)


class LogisticParameters(ComponentParameters):
    """Logistic: weights on the log-odds, centred on safety 0.5 and climate 0.5."""

    intercept: float = Field(
        default=-0.5,
        description=(
            "Log-odds of speaking for average safety in a neutral climate (0: one time in "
            "two; -0.5: about 38 %, speaking in public has a cost)."
        ),
    )
    safety_weight: float = Field(
        default=2.0,
        ge=0,
        description="Increase of the log-odds from the least safe to the safest member.",
    )
    climate_weight: float = Field(
        default=2.0,
        ge=0,
        description="Increase of the log-odds from a silent to a fully active climate.",
    )


class LinearParameters(ComponentParameters):
    """Linear, clipped to [0, 1]: intercept + weights * safety and climate.

    For sensitivity analyses; its parameters have no default and must be given.
    """

    intercept: float = Field(description="Probability for safety 0 and climate 0.")
    safety_weight: float = Field(ge=0, description="Added per unit of safety.")
    climate_weight: float = Field(ge=0, description="Added per unit of climate.")


@dataclass(frozen=True, slots=True)
class LogisticProbability:
    """Logistic probability, centred on safety 0.5 and climate 0.5."""

    intercept: float
    safety_weight: float
    climate_weight: float

    def probability(self, speaker: SpeakerView) -> float:
        """Return the probability."""
        log_odds = (
            self.intercept
            + self.safety_weight * (speaker.psychological_safety - 0.5)
            + self.climate_weight * (speaker.perceived_climate - 0.5)
        )
        return 1 / (1 + math.exp(-log_odds))


@dataclass(frozen=True, slots=True)
class LinearProbability:
    """Linear probability, clipped to [0, 1]."""

    intercept: float
    safety_weight: float
    climate_weight: float

    def probability(self, speaker: SpeakerView) -> float:
        """Return the probability."""
        value = (
            self.intercept
            + self.safety_weight * speaker.psychological_safety
            + self.climate_weight * speaker.perceived_climate
        )
        return min(1.0, max(0.0, value))


def _logistic(parameters: LogisticParameters) -> LogisticProbability:
    return LogisticProbability(
        parameters.intercept, parameters.safety_weight, parameters.climate_weight
    )


def _linear(parameters: LinearParameters) -> LinearProbability:
    return LinearProbability(
        parameters.intercept, parameters.safety_weight, parameters.climate_weight
    )


def register_expression_probabilities(registry: Registry) -> None:
    """Add the extension point and its built-in components to ``registry``."""
    registry.add_extension_point(EXPRESSION_PROBABILITY)
    registry.register(EXPRESSION_PROBABILITY, Component("logistic", LogisticParameters, _logistic))
    registry.register(EXPRESSION_PROBABILITY, Component("linear", LinearParameters, _linear))
