"""The GASP model as run by the experiment layer: build, checks, tables, summaries (ADR-0017).

The model (:mod:`gasp_sim.model`) publishes observations and does not depend on the
recording layer (ADR-0015); this module declares how a GASP run is built from a loaded
configuration and what is recorded:

- observation tables (level ``full``): ``agents``, ``consultations``, ``messages``,
  ``climate``;
- summaries (both levels): ``windows`` (one row per time window), ``run`` (one row per
  run) and ``agent_run`` (one row per member and run).

The *mean participation* of a period is the mean, over the updates of the climate of the
team during the period, of the participation used for the update (members who wrote during
the participation window, divided by the size of the team). With synchronous rhythms, a
participation window equal to the consultation period and 50 working hours, it is the
measure of the article: the mean over 100 cycles of the participating agents divided by
the agents (formula 2).
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from gasp_sim.config.loader import ConfigIssue, LoadedConfig
from gasp_sim.core.clock import DurationRoundingWarning
from gasp_sim.core.simulation import Simulation
from gasp_sim.experiment.definition import ModelDefinition
from gasp_sim.model.climate import CLIMATE_RULE
from gasp_sim.model.config import PLUGIN_GROUP, GaspConfig, default_registry
from gasp_sim.model.distributions import DISTRIBUTION
from gasp_sim.model.expression import EXPRESSION_PROBABILITY
from gasp_sim.model.model import GaspModel
from gasp_sim.model.observations import AgentDescribed, ClimateUpdated, Consulted, MessagePosted
from gasp_sim.model.perception import CLIMATE_PERCEPTION
from gasp_sim.model.reading import READING_HABIT
from gasp_sim.model.rhythms import WORK_RHYTHM
from gasp_sim.recording.tables import ObservationTable, Period, SummaryTable

__all__ = [
    "GASP",
    "SUMMARIES",
    "TABLES",
    "AgentRunRow",
    "AgentRunSummary",
    "ParticipationRow",
    "ParticipationSummary",
    "build_model",
    "check_windows",
]


def build_model(loaded: LoadedConfig[GaspConfig]) -> GaspModel:
    """Build the GASP model described by a loaded configuration.

    Rounded durations are not warned about again: the loader already reported them.
    """
    config = loaded.config
    registry = loaded.registry
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DurationRoundingWarning)
        return GaspModel(
            team_size=config.team_size,
            seed=config.seed,
            safety=registry.create(DISTRIBUTION, config.psychological_safety),
            rhythm=registry.create(WORK_RHYTHM, config.rhythm),
            reading=registry.create(READING_HABIT, config.reading),
            perception=registry.create(CLIMATE_PERCEPTION, config.perception),
            climate_rule=registry.create(CLIMATE_RULE, config.climate_rule),
            expression=registry.create(EXPRESSION_PROBABILITY, config.expression),
            initial_climate=config.initial_climate,
            participation_window_hours=config.participation_window_hours,
            grid=config.time.grid(),
            mode=config.random_stream_mode(),
        )


def check_windows(loaded: LoadedConfig[GaspConfig]) -> list[ConfigIssue]:
    """Warn when a time window is shorter than the time between two consultations.

    Members would then often see an empty window, that is a participation of 0 (ODD
    appendix A, pitfall 9).
    """
    config = loaded.config
    grid = config.time.grid()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DurationRoundingWarning)
        period = loaded.registry.create(WORK_RHYTHM, config.rhythm).period_ticks(grid)
        windows = [
            (
                ("participation_window_hours",),
                "the participation window",
                grid.hours_to_ticks(config.participation_window_hours),
            ),
            (
                ("reading",),
                "the reading window",
                loaded.registry.create(READING_HABIT, config.reading).window_ticks(grid),
            ),
        ]
    issues = []
    for location, what, ticks in windows:
        if ticks is not None and ticks < period:
            issues.append(
                ConfigIssue(
                    location,
                    f"{what} ({grid.ticks_to_hours(ticks):g} h) is shorter than the time "
                    f"between two consultations ({grid.ticks_to_hours(period):g} h): it will "
                    "often be empty, that is a participation of 0",
                )
            )
    return issues


# --------------------------------------------------------------------------- summaries


@dataclass(frozen=True, slots=True)
class ParticipationRow:
    """Participation and climate over a period (a time window or the whole run)."""

    consultations: int = field(
        metadata={"description": "Consultations during the period.", "unit": "consultation"}
    )
    messages: int = field(
        metadata={"description": "Messages written during the period.", "unit": "message"}
    )
    messages_per_agent: float = field(
        metadata={"description": "Messages divided by the size of the team.", "unit": "message"}
    )
    mean_participation: float | None = field(
        metadata={
            "description": (
                "Mean, over the updates of the climate during the period, of the members who "
                "wrote during the participation window divided by the size of the team; "
                "empty without update. With synchronous rhythms and a window equal to the "
                "consultation period, the measure of the article (formula 2)."
            ),
            "unit": "1",
        }
    )
    speech_per_consultation: float | None = field(
        metadata={
            "description": (
                "Share of the consultations at which the member spoke (speech per "
                "opportunity); empty without consultation."
            ),
            "unit": "1",
        }
    )
    mean_perceived_climate: float | None = field(
        metadata={
            "description": "Mean of the climate perceived at the consultations of the period.",
            "unit": "1",
        }
    )
    climate_at_end: float | None = field(
        metadata={
            "description": (
                "Climate of the team at the end of the period; empty before its first update."
            ),
            "unit": "1",
        }
    )


class ParticipationSummary:
    """Aggregator of :class:`ParticipationRow`; counts are reset at the end of every period."""

    def __init__(self) -> None:
        self._team_size = 0
        self._climate: float | None = None
        self._reset()

    def _reset(self) -> None:
        self._consultations = 0
        self._spoke = 0
        self._messages = 0
        self._participations: list[float] = []
        self._perceived: list[float] = []

    def observe(self, observation: object) -> None:
        """Take one observation into account."""
        if isinstance(observation, AgentDescribed):
            self._team_size += 1
        elif isinstance(observation, Consulted):
            self._consultations += 1
            self._spoke += observation.spoke
            self._perceived.append(observation.perceived_climate)
        elif isinstance(observation, MessagePosted):
            self._messages += 1
        elif isinstance(observation, ClimateUpdated):
            self._participations.append(observation.participation)
            self._climate = observation.climate

    def rows(self, period: Period) -> Iterator[ParticipationRow]:
        """Return the row of the period that has just ended, and start a new period."""
        yield ParticipationRow(
            consultations=self._consultations,
            messages=self._messages,
            messages_per_agent=self._messages / self._team_size if self._team_size else 0.0,
            mean_participation=_mean(self._participations),
            speech_per_consultation=(
                self._spoke / self._consultations if self._consultations else None
            ),
            mean_perceived_climate=_mean(self._perceived),
            climate_at_end=self._climate,
        )
        self._reset()


@dataclass(frozen=True, slots=True)
class AgentRunRow:
    """Speech of one member over the whole run."""

    agent: int = field(metadata={"description": "Member of the team, from 0."})
    consultations: int = field(
        metadata={"description": "Consultations of the member.", "unit": "consultation"}
    )
    messages: int = field(
        metadata={"description": "Messages written by the member.", "unit": "message"}
    )
    speech_per_consultation: float | None = field(
        metadata={
            "description": (
                "Share of the member's consultations at which they spoke; empty without "
                "consultation."
            ),
            "unit": "1",
        }
    )


class AgentRunSummary:
    """Aggregator of :class:`AgentRunRow`: one row per member, in order of members."""

    def __init__(self) -> None:
        self._agents: list[int] = []
        self._consultations: dict[int, int] = {}
        self._messages: dict[int, int] = {}

    def observe(self, observation: object) -> None:
        """Take one observation into account."""
        if isinstance(observation, AgentDescribed):
            self._agents.append(observation.agent)
        elif isinstance(observation, Consulted):
            agent = observation.agent
            self._consultations[agent] = self._consultations.get(agent, 0) + 1
        elif isinstance(observation, MessagePosted):
            sender = observation.sender
            self._messages[sender] = self._messages.get(sender, 0) + 1

    def rows(self, period: Period) -> Iterator[AgentRunRow]:
        """Return one row per member."""
        for agent in self._agents:
            consultations = self._consultations.get(agent, 0)
            messages = self._messages.get(agent, 0)
            yield AgentRunRow(
                agent=agent,
                consultations=consultations,
                messages=messages,
                speech_per_consultation=messages / consultations if consultations else None,
            )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


#: Observation tables of the GASP model.
TABLES = (
    ObservationTable("agents", AgentDescribed, "One row per member of the team."),
    ObservationTable("consultations", Consulted, "One row per consultation of the channel."),
    ObservationTable("messages", MessagePosted, "One row per message of the team channel."),
    ObservationTable("climate", ClimateUpdated, "One row per update of the climate."),
)

#: Summary tables of the GASP model.
SUMMARIES = (
    SummaryTable(
        "windows",
        ParticipationRow,
        ParticipationSummary,
        per="window",
        description="Participation and climate in each time window.",
    ),
    SummaryTable(
        "run",
        ParticipationRow,
        ParticipationSummary,
        per="run",
        description="Participation and climate over the whole run.",
    ),
    SummaryTable(
        "agent_run",
        AgentRunRow,
        AgentRunSummary,
        per="run",
        description="Speech of each member over the whole run.",
    ),
)


def _build(loaded: LoadedConfig[Any]) -> Simulation:
    return build_model(loaded).simulation


#: The GASP model, as run by ``gasp-sim run``.
GASP: ModelDefinition[GaspConfig] = ModelDefinition(
    name="GASP",
    schema=GaspConfig,
    registry=default_registry,
    build=_build,
    plugin_group=PLUGIN_GROUP,
    tables=TABLES,
    summaries=SUMMARIES,
    headline=(
        ("run", "consultations"),
        ("run", "messages"),
        ("run", "mean_participation"),
    ),
    checks=check_windows,
)
