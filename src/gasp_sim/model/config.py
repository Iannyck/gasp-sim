"""Configuration of the GASP model: schema, built-in components and presets.

Every modelling assumption is a replaceable component, chosen by name in a configuration
file with its own parameters (dev-conventions §9.1). A setting appears only once it has an
effect in the model: the proxy, personality and types of messages come in later steps.

The defaults are those of the model of this project; the ``article`` preset reconstructs
the setting of the simulation of the article (independent re-implementation from its
published description). The tables, summaries and construction of a run from a loaded
file live in :mod:`gasp_sim.experiment.gasp`, since the model does not depend on the
recording layer.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from gasp_sim.config.base import ComponentParameters, Hours
from gasp_sim.config.schema import RunSettings, Slot
from gasp_sim.model.climate import CLIMATE_RULE, register_climate_rules
from gasp_sim.model.distributions import DISTRIBUTION, register_distributions
from gasp_sim.model.expression import EXPRESSION_PROBABILITY, register_expression_probabilities
from gasp_sim.model.perception import CLIMATE_PERCEPTION, register_perceptions
from gasp_sim.model.reading import READING_HABIT, register_reading_habits
from gasp_sim.model.rhythms import WORK_RHYTHM, register_rhythms
from gasp_sim.registry import Preset, Registry

__all__ = ["ARTICLE", "PLUGIN_GROUP", "GaspConfig", "default_registry"]

#: Entry-point group in which installed packages advertise GASP plugins (ADR-0016).
PLUGIN_GROUP = "gasp_sim.plugins"


class GaspConfig(RunSettings):
    """Configuration of the GASP model."""

    team_size: int = Field(default=8, ge=3, le=12, description="Number of team members.")
    psychological_safety: Annotated[ComponentParameters, Slot(DISTRIBUTION, default="uniform")] = (
        Field(description="Distribution of the psychological safety of the members.")
    )
    rhythm: Annotated[ComponentParameters, Slot(WORK_RHYTHM, default="synchronous")] = Field(
        description="When the members consult the team channel."
    )
    reading: Annotated[ComponentParameters, Slot(READING_HABIT, default="recent")] = Field(
        description="Which messages a member reads at a consultation."
    )
    perception: Annotated[
        ComponentParameters, Slot(CLIMATE_PERCEPTION, default="individual_memory")
    ] = Field(description="What climate each member perceives when deciding to speak.")
    initial_climate: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Climate of the team before the first update (0.5: neutral).",
    )
    participation_window_hours: Annotated[Hours, Field(gt=0)] = Field(
        default=0.5,
        description=(
            "Window over which the participation of the team is measured, in working hours."
        ),
    )
    climate_rule: Annotated[ComponentParameters, Slot(CLIMATE_RULE, default="ema")] = Field(
        description="How the climate follows the participation."
    )
    expression: Annotated[ComponentParameters, Slot(EXPRESSION_PROBABILITY, default="logistic")] = (
        Field(description="Probability that a member speaks at a consultation.")
    )


_ARTICLE_VALUES: dict[str, Any] = {
    "team_size": 8,
    "hours": 50,
    "psychological_safety": {"type": "uniform", "low": 0.0, "high": 1.0},
    "rhythm": {"type": "synchronous", "period_hours": 0.5},
    "reading": {"type": "recent", "hours": 0.5},
    "perception": {"type": "shared"},
    "initial_climate": 0.5,
    "participation_window_hours": 0.5,
    "climate_rule": {"type": "ema", "inertia_hours": 0.5},
    "expression": {
        "type": "logistic",
        "intercept": -0.5,
        "safety_weight": 2.0,
        "climate_weight": 2.0,
    },
}

#: Reconstruction of the setting of the article's simulation: 8 members, 100 consultation
#: cycles of 30 minutes (50 working hours), safety drawn uniformly in [0, 1], a neutral
#: initial climate perceived by everyone.
ARTICLE = Preset(
    "article",
    _ARTICLE_VALUES,
    summary=(
        "Setting of the simulation of the article (independent re-implementation): 8 members, "
        "50 working hours, consultations every 30 minutes, climate shared by everyone."
    ),
)

#: The ``article`` preset with the literal reading of the article's climate rule.
ARTICLE_THRESHOLD = Preset(
    "article_threshold",
    {
        **_ARTICLE_VALUES,
        "climate_rule": {"type": "threshold", "threshold": 0.5, "rate_per_hour": 0.1},
    },
    summary=(
        "The 'article' preset with a threshold climate rule, the literal reading of the "
        "article; the level reached then depends mostly on the threshold."
    ),
)


def default_registry() -> Registry:
    """Return a registry with the built-in components and presets of the GASP model."""
    registry = Registry()
    register_distributions(registry)
    register_rhythms(registry)
    register_reading_habits(registry)
    register_perceptions(registry)
    register_climate_rules(registry)
    register_expression_probabilities(registry)
    registry.add_preset(ARTICLE)
    registry.add_preset(ARTICLE_THRESHOLD)
    return registry
