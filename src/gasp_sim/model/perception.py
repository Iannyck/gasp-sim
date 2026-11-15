"""How each member perceives the climate (extension point ``climate_perception``).

In the spiral of silence, people fall silent according to the climate *as they perceive
it*. The climate of the team is always computed and recorded; the perception decides what
each member uses when deciding to speak (step 6 decision D1):

- ``shared``: every member perceives the climate of the team, as in the article;
- ``individual_memory`` (default): each member starts from an impression of their own,
  drawn from a beta distribution, and updates it at every consultation with the
  participation they observe in the messages they read (others only, never themselves).
  The update uses the climate rule of the team, or an exponential moving average with an
  inertia of its own if ``inertia_hours`` is set. There is no update at a member's
  first consultation (no history yet).

The state of each member (their impression) is kept by the model and passed to the
component, which holds no state of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Self, runtime_checkable

import numpy as np
from pydantic import Field, model_validator

from gasp_sim.config.base import ComponentParameters
from gasp_sim.model.climate import ClimateRule, EmaRule
from gasp_sim.model.distributions import BetaDistribution, beta_sd_limit
from gasp_sim.registry import Component, ExtensionPoint, Registry

__all__ = [
    "CLIMATE_PERCEPTION",
    "ClimatePerception",
    "IndividualMemoryParameters",
    "IndividualMemoryPerception",
    "Perceived",
    "SharedParameters",
    "SharedPerception",
    "register_perceptions",
]


@dataclass(frozen=True, slots=True)
class Perceived:
    """Result of a perception.

    Attributes
    ----------
    climate : float
        Climate perceived, used to decide whether to speak.
    impression : float or None
        New impression of the member, kept until their next consultation (``None`` for
        perceptions without memory).
    """

    climate: float
    impression: float | None


@runtime_checkable
class ClimatePerception(Protocol):
    """Gives the climate perceived by a member at a consultation (``climate_perception``)."""

    def initial_impression(self, rng: np.random.Generator) -> float | None:
        """Return the impression of a member before their first consultation, if any.

        ``rng`` is the ``perception`` stream of the member.
        """

    def perceive(
        self,
        impression: float | None,
        *,
        team_climate: float,
        observed: float | None,
        elapsed_hours: float | None,
        rule: ClimateRule,
    ) -> Perceived:
        """Return what a member perceives at a consultation.

        Parameters
        ----------
        impression : float or None
            The member's impression after their previous consultation (or initial).
        team_climate : float
            Climate of the team at the start of the tick.
        observed : float or None
            Participation the member observed in the messages read: other senders divided
            by the number of other members; ``None`` if nothing could be read.
        elapsed_hours : float or None
            Working hours since the member's previous consultation; ``None`` at their
            first consultation.
        rule : ClimateRule
            Climate rule of the team.
        """


#: Extension point of the perceptions of the climate.
CLIMATE_PERCEPTION: ExtensionPoint[ClimatePerception] = ExtensionPoint(
    "climate_perception",
    ClimatePerception,
    summary="What climate each member perceives when deciding to speak.",
)


class SharedParameters(ComponentParameters):
    """Every member perceives the climate of the team (as in the article)."""


class IndividualMemoryParameters(ComponentParameters):
    """Each member keeps an impression of their own, updated with what they read."""

    initial_mean: float = Field(
        default=0.5, gt=0, lt=1, description="Mean of the initial impressions."
    )
    initial_sd: float = Field(
        default=0.1,
        ge=0,
        description=(
            "Standard deviation of the initial impressions (beta distribution); 0 gives "
            "everyone the mean."
        ),
    )
    inertia_hours: float | None = Field(
        default=None,
        gt=0,
        description=(
            "If set, impressions follow an exponential moving average with this inertia, in "
            "working hours (time after which half of the former impression has been "
            "replaced); otherwise they follow the climate rule of the team."
        ),
    )

    @model_validator(mode="after")
    def _check_spread(self) -> Self:
        limit = beta_sd_limit(self.initial_mean)
        if self.initial_sd >= limit:
            raise ValueError(
                f"initial_sd must be smaller than {limit:.4g} for an initial_mean of "
                f"{self.initial_mean:g} (got {self.initial_sd:g})"
            )
        return self


@dataclass(frozen=True, slots=True)
class SharedPerception:
    """Perceive the climate of the team; no impression, no draw."""

    def initial_impression(self, rng: np.random.Generator) -> float | None:
        """Return ``None``."""
        return None

    def perceive(
        self,
        impression: float | None,
        *,
        team_climate: float,
        observed: float | None,
        elapsed_hours: float | None,
        rule: ClimateRule,
    ) -> Perceived:
        """Return the climate of the team."""
        return Perceived(team_climate, None)


@dataclass(frozen=True, slots=True)
class IndividualMemoryPerception:
    """Keep an impression, drawn at the start, updated with the participation observed."""

    initial_mean: float
    initial_sd: float
    inertia_hours: float | None

    def initial_impression(self, rng: np.random.Generator) -> float | None:
        """Draw the initial impression (beta distribution)."""
        return BetaDistribution(self.initial_mean, self.initial_sd).draw(rng)

    def perceive(
        self,
        impression: float | None,
        *,
        team_climate: float,
        observed: float | None,
        elapsed_hours: float | None,
        rule: ClimateRule,
    ) -> Perceived:
        """Update the impression with the participation observed, then perceive it."""
        if impression is None:
            raise ValueError("individual_memory needs the initial impression of the member.")
        if observed is not None and elapsed_hours is not None:
            own = rule if self.inertia_hours is None else EmaRule(self.inertia_hours)
            impression = own.update(impression, observed, elapsed_hours)
        return Perceived(impression, impression)


def _shared(parameters: SharedParameters) -> SharedPerception:
    return SharedPerception()


def _individual_memory(parameters: IndividualMemoryParameters) -> IndividualMemoryPerception:
    return IndividualMemoryPerception(
        parameters.initial_mean, parameters.initial_sd, parameters.inertia_hours
    )


def register_perceptions(registry: Registry) -> None:
    """Add the extension point and its built-in components to ``registry``."""
    registry.add_extension_point(CLIMATE_PERCEPTION)
    registry.register(CLIMATE_PERCEPTION, Component("shared", SharedParameters, _shared))
    registry.register(
        CLIMATE_PERCEPTION,
        Component("individual_memory", IndividualMemoryParameters, _individual_memory),
    )
