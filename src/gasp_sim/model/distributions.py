"""Probability distributions of individual characteristics (extension point ``distribution``).

One extension point describes every distribution of the model (for example the
psychological safety of the agents), so that researchers write them all the same way::

    psychological_safety: {type: uniform, low: 0, high: 1}
    psychological_safety: {type: beta, mean: 0.6, sd: 0.15}
    psychological_safety: {type: constant, value: 0.5}

The beta distribution is set by its mean and standard deviation rather than by its usual
parameters ``a`` and ``b``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Self, runtime_checkable

import numpy as np
from pydantic import Field, model_validator

from gasp_sim.config.base import ComponentParameters
from gasp_sim.registry import Component, ExtensionPoint, Registry

__all__ = [
    "DISTRIBUTION",
    "BetaDistribution",
    "BetaParameters",
    "ConstantDistribution",
    "ConstantParameters",
    "Distribution",
    "UniformDistribution",
    "UniformParameters",
    "beta_sd_limit",
    "register_distributions",
]


@runtime_checkable
class Distribution(Protocol):
    """Draws values in [0, 1] (extension point ``distribution``)."""

    def draw(self, rng: np.random.Generator) -> float:
        """Return one value, drawn with ``rng`` (the stream of one agent)."""


#: Extension point of the distributions of individual characteristics.
DISTRIBUTION: ExtensionPoint[Distribution] = ExtensionPoint(
    "distribution",
    Distribution,
    summary="Probability distribution of a characteristic, with values in [0, 1].",
)


def beta_sd_limit(mean: float) -> float:
    """Return the largest standard deviation (excluded) of a beta distribution of ``mean``.

    Examples
    --------
    >>> beta_sd_limit(0.5)
    0.5
    """
    return math.sqrt(mean * (1 - mean))


class UniformParameters(ComponentParameters):
    """Uniform distribution between two bounds."""

    low: float = Field(default=0.0, ge=0, le=1, description="Smallest value.")
    high: float = Field(default=1.0, ge=0, le=1, description="Largest value.")

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.low > self.high:
            raise ValueError(f"low ({self.low:g}) must not exceed high ({self.high:g})")
        return self


class BetaParameters(ComponentParameters):
    """Beta distribution set by its mean and standard deviation.

    A standard deviation of 0 gives the mean to everyone. The standard deviation must be
    smaller than the square root of mean * (1 - mean).
    """

    mean: float = Field(default=0.5, gt=0, lt=1, description="Mean of the values.")
    sd: float = Field(default=0.1, ge=0, description="Standard deviation of the values.")

    @model_validator(mode="after")
    def _check_spread(self) -> Self:
        limit = beta_sd_limit(self.mean)
        if self.sd >= limit:
            raise ValueError(
                f"sd must be smaller than {limit:.4g} for a mean of {self.mean:g} (got {self.sd:g})"
            )
        return self


class ConstantParameters(ComponentParameters):
    """The same value for everyone."""

    value: float = Field(default=0.5, ge=0, le=1, description="The value.")


@dataclass(frozen=True, slots=True)
class UniformDistribution:
    """Uniform distribution between ``low`` and ``high``; one draw per value."""

    low: float
    high: float

    def draw(self, rng: np.random.Generator) -> float:
        """Return one value."""
        return float(self.low + (self.high - self.low) * rng.random())


@dataclass(frozen=True, slots=True)
class BetaDistribution:
    """Beta distribution of the given mean and standard deviation; with ``sd`` 0, the mean."""

    mean: float
    sd: float

    def draw(self, rng: np.random.Generator) -> float:
        """Return one value."""
        if self.sd == 0:
            return self.mean
        concentration = self.mean * (1 - self.mean) / self.sd**2 - 1
        return float(rng.beta(self.mean * concentration, (1 - self.mean) * concentration))


@dataclass(frozen=True, slots=True)
class ConstantDistribution:
    """The same value for everyone; no draw."""

    value: float

    def draw(self, rng: np.random.Generator) -> float:
        """Return the value."""
        return self.value


def _uniform(parameters: UniformParameters) -> UniformDistribution:
    return UniformDistribution(parameters.low, parameters.high)


def _beta(parameters: BetaParameters) -> BetaDistribution:
    return BetaDistribution(parameters.mean, parameters.sd)


def _constant(parameters: ConstantParameters) -> ConstantDistribution:
    return ConstantDistribution(parameters.value)


def register_distributions(registry: Registry) -> None:
    """Add the extension point and its built-in components to ``registry``."""
    registry.add_extension_point(DISTRIBUTION)
    registry.register(DISTRIBUTION, Component("uniform", UniformParameters, _uniform))
    registry.register(DISTRIBUTION, Component("beta", BetaParameters, _beta))
    registry.register(DISTRIBUTION, Component("constant", ConstantParameters, _constant))
