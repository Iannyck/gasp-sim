"""Observations published by the GASP model on the notification bus (ADR-0015).

Each observation is a frozen dataclass with a ``tick`` field; every other field carries a
description, and a unit when it has one. The model does not know how they are recorded:
the tables and summaries are declared in :mod:`gasp_sim.experiment.gasp`.

Agents, messages and windows are numbered from 0, as everywhere in the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["AgentDescribed", "ClimateUpdated", "Consulted", "MessagePosted"]


@dataclass(frozen=True, slots=True)
class AgentDescribed:
    """A member of the team, described at the first tick of the run."""

    tick: int
    agent: int = field(metadata={"description": "Member of the team, from 0."})
    psychological_safety: float = field(
        metadata={"description": "Psychological safety of the member.", "unit": "1"}
    )
    initial_impression: float | None = field(
        metadata={
            "description": (
                "Impression of the climate before the first consultation (perception "
                "'individual_memory'); empty when members perceive the climate of the team."
            ),
            "unit": "1",
        }
    )


@dataclass(frozen=True, slots=True)
class Consulted:
    """A member consulted the team channel and decided whether to speak."""

    tick: int
    agent: int = field(metadata={"description": "Member who consulted the channel, from 0."})
    messages_read: int = field(
        metadata={"description": "Messages read at this consultation.", "unit": "message"}
    )
    read_minutes: int = field(
        metadata={
            "description": "Working minutes covered by the messages read, up to this tick.",
            "unit": "minute",
        }
    )
    observed_participation: float | None = field(
        metadata={
            "description": (
                "Other members who wrote among the messages read, divided by the number of "
                "other members; empty if nothing could be read (start of the run)."
            ),
            "unit": "1",
        }
    )
    perceived_climate: float = field(
        metadata={"description": "Climate perceived and used to decide.", "unit": "1"}
    )
    probability: float = field(
        metadata={"description": "Probability of speaking at this consultation.", "unit": "1"}
    )
    spoke: bool = field(metadata={"description": "Whether the member spoke."})


@dataclass(frozen=True, slots=True)
class MessagePosted:
    """A message was written in the team channel; visible to others from the next tick."""

    tick: int
    message: int = field(metadata={"description": "Number of the message, from 0."})
    sender: int = field(metadata={"description": "Member who wrote it, from 0."})
    message_type: str = field(
        metadata={"description": "Type of message; 'generic' while there is a single type."}
    )


@dataclass(frozen=True, slots=True)
class ClimateUpdated:
    """The climate of the team was updated (at every tick with consultations)."""

    tick: int
    participation: float = field(
        metadata={
            "description": (
                "Members who wrote during the participation window ending with this tick, "
                "divided by the size of the team."
            ),
            "unit": "1",
        }
    )
    climate: float = field(
        metadata={"description": "Climate of the team after the update.", "unit": "1"}
    )
