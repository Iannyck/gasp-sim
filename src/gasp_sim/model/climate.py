"""Update rules of the communication climate (extension point ``climate_rule``, ODD 7.8).

The climate is updated from the participation in the team channel [article]. The exact
rule is not published; two components are offered [modelling assumption]:

- ``ema`` (default): exponential moving average of the participation, set by its
  **inertia** (see below).
- ``threshold``: the reading of the article's wording "participation gradually decreases
  when communication activity falls below a predefined threshold": the climate falls by
  ``rate * dt`` when ``p`` is below the threshold and rises by as much otherwise, within
  [0, 1]. With this rule the climate never settles, except at the bounds or around the
  level where participation equals the threshold, which therefore largely sets the level
  reached.

The same rule updates the climate of the team and, by default, the impressions of the
members (``individual_memory`` perception).

Inertia of the climate
----------------------
The climate is a slow collective state: it should not swing from one consultation to the
next (ODD 7.8). The **inertia** ``h``, in working hours, says how slowly it follows the
participation. At every update, rule ``ema`` replaces a share ``alpha`` of the climate by
the participation ``p`` just observed::

    alpha = 1 - 2 ** (-dt / h)
    c <- c + alpha * (p - c)

where ``dt`` is the number of working hours since the previous update. The weight of the
past therefore fades progressively instead of being dropped at once: after ``h`` hours,
half of the former climate has been replaced by what was observed; after ``2 h``, three
quarters; after ``3 h``, seven eighths. In other words, ``h`` is the *half-life* of an
exponential moving average, the name used in data analysis.

Examples with updates every 30 minutes (``dt = 0.5``):

- ``h = 0.5``: each update replaces half of the climate, which closely follows the last
  cycles (``article`` preset: closest to "the participation rate was used to update the
  climate for the subsequent cycle");
- ``h = 16`` (default, two working days): each update replaces about 2 % of the climate;
  half of it has been renewed after 16 working hours.

Because the inertia is expressed in time rather than as a share per update, the climate
has the same inertia whatever the rhythm of the updates (every 30 minutes or every hour),
and the impressions of members who consult at different moments forget at the same pace.
The inertia is a speed of forgetting, not a moment on the time grid: it is never rounded
to ticks. Updates themselves only happen at ticks with consultations, so an inertia much
shorter than the time between updates simply replaces almost all of the climate each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import Field

from gasp_sim.config.base import ComponentParameters
from gasp_sim.registry import Component, ExtensionPoint, Registry

__all__ = [
    "CLIMATE_RULE",
    "ClimateRule",
    "EmaParameters",
    "EmaRule",
    "ThresholdParameters",
    "ThresholdRule",
    "register_climate_rules",
]


@runtime_checkable
class ClimateRule(Protocol):
    """Updates a climate value from an observed participation (``climate_rule``)."""

    def update(self, value: float, participation: float, elapsed_hours: float) -> float:
        """Return the new value.

        Parameters
        ----------
        value : float
            Current value, in [0, 1].
        participation : float
            Participation observed, in [0, 1].
        elapsed_hours : float
            Working hours since the previous update (positive).

        Returns
        -------
        float
            New value, in [0, 1].
        """


#: Extension point of the climate update rules.
CLIMATE_RULE: ExtensionPoint[ClimateRule] = ExtensionPoint(
    "climate_rule",
    ClimateRule,
    summary="How a climate value follows the participation observed.",
)


class EmaParameters(ComponentParameters):
    """Exponential moving average of the participation, with an inertia in hours."""

    inertia_hours: float = Field(
        default=16.0,
        gt=0,
        description=(
            "Inertia of the climate, in working hours: the time after which half of the "
            "former value has been replaced by what was observed (half-life of an "
            "exponential moving average)."
        ),
    )


class ThresholdParameters(ComponentParameters):
    """Falls below a participation threshold and rises above it, at a constant rate."""

    threshold: float = Field(
        default=0.5, ge=0, le=1, description="Participation below which the value falls."
    )
    rate_per_hour: float = Field(
        default=0.1, ge=0, description="Change of the value per working hour."
    )


@dataclass(frozen=True, slots=True)
class EmaRule:
    """Exponential moving average with an inertia (half-life) of ``inertia_hours``."""

    inertia_hours: float

    def update(self, value: float, participation: float, elapsed_hours: float) -> float:
        """Move ``value`` towards ``participation``."""
        weight = 1 - 2 ** (-elapsed_hours / self.inertia_hours)
        return value + weight * (participation - value)


@dataclass(frozen=True, slots=True)
class ThresholdRule:
    """Fall below ``threshold``, rise otherwise, by ``rate_per_hour`` per working hour."""

    threshold: float
    rate_per_hour: float

    def update(self, value: float, participation: float, elapsed_hours: float) -> float:
        """Move ``value`` down or up, within [0, 1]."""
        step = self.rate_per_hour * elapsed_hours
        moved = value - step if participation < self.threshold else value + step
        return min(1.0, max(0.0, moved))


def _ema(parameters: EmaParameters) -> EmaRule:
    return EmaRule(parameters.inertia_hours)


def _threshold(parameters: ThresholdParameters) -> ThresholdRule:
    return ThresholdRule(parameters.threshold, parameters.rate_per_hour)


def register_climate_rules(registry: Registry) -> None:
    """Add the extension point and its built-in components to ``registry``."""
    registry.add_extension_point(CLIMATE_RULE)
    registry.register(CLIMATE_RULE, Component("ema", EmaParameters, _ema))
    registry.register(CLIMATE_RULE, Component("threshold", ThresholdParameters, _threshold))
