"""Outputs of the toy chatter model: recorded tables and summaries (example only).

The model publishes two kinds of observations on the notification bus
(:class:`~examples.toy_chatter.model.Decision` at every consultation and
:class:`~examples.toy_chatter.model.MessageSent` for every message). This module, outside
the model, declares:

- the observation tables ``consultations`` and ``messages`` (level ``full``);
- the summary tables ``windows`` (one row per time window) and ``run`` (one row per run),
  computed during the run by :class:`ParticipationSummary`.

The participation of a round is the share of the agents consulting at a tick who spoke;
the mean participation is the mean over the rounds of the period, as in
:meth:`~examples.toy_chatter.model.ToyChatter.summary`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from examples.toy_chatter.model import Decision, MessageSent
from gasp_sim.api import ObservationTable, Period, SummaryTable

__all__ = ["SUMMARIES", "TABLES", "ParticipationRow", "ParticipationSummary"]


@dataclass(frozen=True, slots=True)
class ParticipationRow:
    """Participation over a period."""

    consultations: int = field(metadata={"description": "Consultations during the period."})
    messages: int = field(metadata={"description": "Messages written during the period."})
    mean_participation: float | None = field(
        metadata={
            "description": (
                "Mean, over the ticks with consultations, of the share of consulting agents "
                "who spoke; empty if there was no consultation."
            ),
            "unit": "1",
        }
    )


class ParticipationSummary:
    """Aggregator of :class:`ParticipationRow`, reset at the end of every period."""

    def __init__(self) -> None:
        self._rounds: dict[int, list[int]] = {}
        self._messages = 0

    def observe(self, observation: object) -> None:
        """Count consultations, speakers per tick, and messages."""
        if isinstance(observation, Decision):
            counts = self._rounds.setdefault(observation.tick, [0, 0])
            counts[0] += 1
            counts[1] += observation.spoke
        elif isinstance(observation, MessageSent):
            self._messages += 1

    def rows(self, period: Period) -> Iterator[ParticipationRow]:
        """Return the row of the period that has just ended, and start a new period."""
        shares = [spoke / consulted for consulted, spoke in self._rounds.values()]
        yield ParticipationRow(
            consultations=sum(consulted for consulted, _ in self._rounds.values()),
            messages=self._messages,
            mean_participation=sum(shares) / len(shares) if shares else None,
        )
        self._rounds = {}
        self._messages = 0


#: Observation tables of the toy model.
TABLES = (
    ObservationTable("consultations", Decision, "One row per consultation of the channel."),
    ObservationTable("messages", MessageSent, "One row per message written in the channel."),
)

#: Summary tables of the toy model.
SUMMARIES = (
    SummaryTable(
        "windows",
        ParticipationRow,
        ParticipationSummary,
        per="window",
        description="Participation in each time window.",
    ),
    SummaryTable(
        "run",
        ParticipationRow,
        ParticipationSummary,
        per="run",
        description="Participation over the whole run.",
    ),
)
