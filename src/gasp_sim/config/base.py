"""Base classes and field types for configuration schemas (ADR-0014).

Every part of a configuration is a *section*: a pydantic model that is

- **strict**: no silent conversion (the text ``"0.5"`` is not a number, ``yes`` is not a
  number of agents); a whole number is accepted where a decimal number is expected;
- **closed**: an unknown setting is an error, so that a typo cannot leave a parameter at
  its default value without anyone noticing;
- **frozen**: a validated configuration cannot be modified;
- **finite**: infinite and not-a-number values are refused.

Durations are written in hours (dev-conventions §9.6). They are marked with
:data:`Hours` (rounded to the nearest tick, with a warning) or :data:`ExactHours` (must be
a whole number of ticks, as rhythm periods must, ADR-0007); the configuration loader checks
them against the time grid of the run.

This module does not import any other part of gasp-sim, so that the registry
(:mod:`gasp_sim.registry`) can depend on it without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RESERVED_COMPONENT_KEY",
    "ComponentParameters",
    "ConfigSection",
    "DurationCheck",
    "ExactHours",
    "Hours",
]

#: Key that selects a component in a configuration file (``type: feedback``). Component
#: parameters cannot use this name.
RESERVED_COMPONENT_KEY = "type"


class ConfigSection(BaseModel):
    """Base class of every configuration section: strict, closed, frozen and finite.

    Sequences must be declared as tuples (``tuple[str, ...]``): the configuration loader
    reads YAML lists as tuples, and a frozen configuration has no mutable lists.

    Examples
    --------
    >>> class Team(ConfigSection):
    ...     n_agents: int = 5
    >>> Team.model_validate({"n_agents": 4}).n_agents
    4
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        validate_default=False,
    )


class ComponentParameters(ConfigSection):
    """Base class of the parameters of a component (an implementation of an extension point).

    Subclass it to declare the parameters of a component, with their defaults, bounds and
    descriptions; the docstring of the subclass describes the component to users. The key
    ``type`` is reserved: in a configuration file it selects the component.

    Examples
    --------
    >>> from pydantic import Field
    >>> class ConstantRuleParameters(ComponentParameters):
    ...     '''Speak with the same probability at every consultation.'''
    ...
    ...     probability: float = Field(default=0.3, ge=0, le=1)
    >>> ConstantRuleParameters().probability
    0.3
    """


@dataclass(frozen=True, slots=True)
class DurationCheck:
    """Marks a field as a duration in hours, to be checked against the time grid.

    Parameters
    ----------
    exact : bool
        If true, the duration must be a whole number of ticks (an error otherwise). If false,
        it is rounded to the nearest tick and the loader reports a warning.
    """

    exact: bool


#: Duration in hours, non-negative and finite. When it is not a whole number of ticks, it
#: is rounded to the nearest tick (halves up) and the loader reports a warning (ADR-0010).
Hours = Annotated[float, Field(ge=0), DurationCheck(exact=False)]

#: Duration in hours that must be a whole number of ticks (for example a rhythm period,
#: ADR-0007); any other value is an error.
ExactHours = Annotated[float, Field(ge=0), DurationCheck(exact=True)]
