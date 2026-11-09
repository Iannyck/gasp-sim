"""Toy chatter: a minimal model written with the gasp-sim engine.

.. warning::
   This is an **example** for developers. It is not the GASP model, it is not calibrated,
   and its results have **no scientific value**. Its probabilities and feedback rule are
   invented to exercise the engine.

A few agents consult a shared channel on a regular rhythm (every 30 minutes by default,
each with a personal offset, restarting every morning). At each consultation an agent
speaks with a probability given by a replaceable *speaking rule* (:class:`SpeakingRule`):
by default it rises with the recent activity of the channel (a small feedback loop).
Messages written during a tick become visible from the next tick (synchronous perception,
ADR-0007).

This module contains only the model; :mod:`examples.toy_chatter.config` makes it
configurable from a YAML file.

The model uses only the public API (:mod:`gasp_sim.api`), as a third-party extension
would. Every part of the engine is exercised: named random streams, the time grid and
duration conversion, the event queue, the notification bus, a deferred log, phases and
the step context.

Examples
--------
>>> model = ToyChatter(ToyParameters(n_agents=3), seed=7)
>>> model.run_days(1)
>>> summary = model.summary()
>>> summary.consultations
48
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from gasp_sim.api import (
    DeferredLog,
    FunctionPhase,
    RandomStreams,
    Simulation,
    StepContext,
    StreamMode,
    StreamScope,
    StreamSpec,
    TimeGrid,
)

__all__ = [
    "STREAMS",
    "ConstantRule",
    "Consultation",
    "Decision",
    "FeedbackRule",
    "Message",
    "MessageSent",
    "SpeakingRule",
    "ToyChatter",
    "ToyParameters",
    "ToySummary",
]

#: Random streams declared by the model (ADR-0010). Identifiers are permanent.
STREAMS = (
    StreamSpec("rhythm", 0, StreamScope.AGENT),
    StreamSpec("speech", 1, StreamScope.AGENT),
)


@runtime_checkable
class SpeakingRule(Protocol):
    """Gives the probability that a consulting agent speaks (extension point)."""

    def probability_for(self, recent_share: float) -> float:
        """Return the probability of speaking.

        Parameters
        ----------
        recent_share : float
            Share of the agents who spoke during the recent window, in [0, 1], as
            perceived at the start of the tick.
        """


@dataclass(frozen=True, slots=True)
class ConstantRule:
    """Speak with the same probability at every consultation, whatever the channel.

    Parameters
    ----------
    probability : float, optional
        Probability of speaking, in [0, 1] (default 0.3).
    """

    probability: float = 0.3

    def __post_init__(self) -> None:
        """Validate the probability."""
        _check_probability("probability", self.probability)

    def probability_for(self, recent_share: float) -> float:
        """Return the constant probability."""
        return self.probability


@dataclass(frozen=True, slots=True)
class FeedbackRule:
    """Speak more when others spoke recently: ``min(1, base + feedback * recent_share)``.

    Parameters
    ----------
    base_probability : float, optional
        Probability of speaking when the channel has been silent (default 0.3).
    feedback : float, optional
        Added to the probability, multiplied by the share of agents who spoke during the
        recent window (default 0.4).
    """

    base_probability: float = 0.3
    feedback: float = 0.4

    def __post_init__(self) -> None:
        """Validate the parameters."""
        _check_probability("base_probability", self.base_probability)
        if not math.isfinite(self.feedback) or self.feedback < 0:
            raise ValueError(f"feedback must be non-negative, got {self.feedback}.")

    def probability_for(self, recent_share: float) -> float:
        """Return the probability for the given recent activity."""
        return min(1.0, self.base_probability + self.feedback * recent_share)


def _check_probability(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1], got {value}.")


@dataclass(frozen=True, slots=True)
class ToyParameters:
    """Parameters of the toy model.

    Parameters
    ----------
    n_agents : int, optional
        Number of agents (default 5).
    consultation_period_hours : float, optional
        Time between two consultations of an agent, in hours (default 0.5). Must be a
        whole number of ticks.
    window_hours : float, optional
        Length of the recent window perceived by agents, in hours (default 1.0).

    Raises
    ------
    ValueError
        If a parameter is out of range.
    """

    n_agents: int = 5
    consultation_period_hours: float = 0.5
    window_hours: float = 1.0

    def __post_init__(self) -> None:
        """Validate the parameters."""
        if self.n_agents < 1:
            raise ValueError(f"n_agents must be at least 1, got {self.n_agents}.")
        for name in ("consultation_period_hours", "window_hours"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive number of hours, got {value}.")


@dataclass(frozen=True, slots=True)
class Consultation:
    """Scheduled event: ``agent`` consults the channel."""

    agent: int


@dataclass(frozen=True, slots=True)
class Message:
    """Entry of the channel: ``sender`` spoke."""

    sender: int


@dataclass(frozen=True, slots=True)
class Decision:
    """Record of one consultation; also published on the bus as an observation."""

    tick: int
    agent: int = field(metadata={"description": "Agent who consulted the channel, from 0."})
    probability: float = field(
        metadata={"description": "Probability of speaking at this consultation.", "unit": "1"}
    )
    spoke: bool = field(metadata={"description": "Whether the agent spoke."})


@dataclass(frozen=True, slots=True)
class MessageSent:
    """Observation published on the bus: ``sender`` wrote a message in the channel."""

    tick: int
    sender: int = field(metadata={"description": "Agent who wrote the message, from 0."})


@dataclass(frozen=True, slots=True)
class ToySummary:
    """Summary of a run."""

    ticks: int
    consultations: int
    messages: int
    mean_participation: float


@dataclass(slots=True)
class _Records:
    decisions: list[Decision] = field(default_factory=list)
    participation: list[tuple[int, float]] = field(default_factory=list)


class ToyChatter:
    """The toy model: its state, its phases and the simulation that runs them.

    Parameters
    ----------
    parameters : ToyParameters
        Model parameters.
    seed : int
        Run seed.
    rule : SpeakingRule, optional
        Speaking rule (default: :class:`FeedbackRule` with its default parameters).
    mode : StreamMode, optional
        Random-stream mode (default named); ``StreamMode.SINGLE`` is for verification only.
    grid : TimeGrid, optional
        Tick and working-day lengths (default: 5-minute ticks, 8-hour days).
    """

    def __init__(
        self,
        parameters: ToyParameters,
        seed: int,
        *,
        rule: SpeakingRule | None = None,
        mode: StreamMode = StreamMode.NAMED,
        grid: TimeGrid | None = None,
    ) -> None:
        self.parameters = parameters
        self.rule: SpeakingRule = rule if rule is not None else FeedbackRule()
        self.grid = grid if grid is not None else TimeGrid()
        self.streams = RandomStreams(seed=seed, specs=STREAMS, mode=mode)
        self.channel = DeferredLog[Message]("channel")
        self.period = self.grid.hours_to_ticks_exact(
            parameters.consultation_period_hours, name="consultation_period_hours"
        )
        self.window = self.grid.hours_to_ticks(parameters.window_hours, name="window_hours")
        # Personal offset within the period, drawn once from each agent's rhythm stream.
        self.offsets = tuple(
            int(self.streams.agent("rhythm", agent).integers(0, self.period))
            for agent in range(parameters.n_agents)
        )
        self._records = _Records()
        self.simulation = Simulation(
            phases=[
                FunctionPhase("consultations", self._consult),
                FunctionPhase("participation", self._measure_participation),
            ],
            day_start_phases=[FunctionPhase("start_day", self._start_day)],
            streams=self.streams,
            grid=self.grid,
            logs=[self.channel],
        )

    @property
    def decisions(self) -> list[Decision]:
        """Every consultation so far, in order."""
        return self._records.decisions

    @property
    def participation(self) -> list[tuple[int, float]]:
        """For each tick with consultations: share of consulting agents who spoke."""
        return self._records.participation

    def run_days(self, days: int) -> None:
        """Run ``days`` working days."""
        self.simulation.run_days(days)

    def summary(self) -> ToySummary:
        """Summarise the run so far."""
        shares = [share for _, share in self._records.participation]
        return ToySummary(
            ticks=self.simulation.next_tick,
            consultations=len(self._records.decisions),
            messages=len(self.channel.visible),
            mean_participation=sum(shares) / len(shares) if shares else 0.0,
        )

    def speaking_probability(self, recent_speakers: int) -> float:
        """Probability of speaking given the number of recent distinct speakers."""
        return self.rule.probability_for(recent_speakers / self.parameters.n_agents)

    # ----------------------------------------------------------------- engine hooks

    def _start_day(self, context: StepContext) -> None:
        """Day-start phase: restart every agent's rhythm (ADR-0013)."""
        for agent, offset in enumerate(self.offsets):
            context.schedule(Consultation(agent), at=context.tick + offset)

    def _consult(self, context: StepContext) -> None:
        """Phase: each consulting agent decides whether to speak."""
        consultations = context.events_of_type(Consultation)
        if not consultations:
            return
        # Perception: only what was visible before this tick, in the recent window.
        recent = self.channel.visible_since(max(0, context.tick - self.window))
        probability = self.speaking_probability(len({entry.item.sender for entry in recent}))
        for event in consultations:
            # Exactly one draw per consultation (fixed number of draws, ADR-0002).
            spoke = bool(context.streams.agent("speech", event.agent).random() < probability)
            decision = Decision(context.tick, event.agent, probability, spoke)
            self._records.decisions.append(decision)
            # Observations for whoever listens (for example a run recorder, ADR-0015).
            context.publish(decision)
            if spoke:
                self.channel.append(Message(event.agent))
                context.publish(MessageSent(context.tick, event.agent))
            next_tick = context.tick + self.period
            if context.grid.day_of(next_tick) == context.day:
                context.schedule(Consultation(event.agent), at=next_tick)
            # Otherwise the agent waits for the next morning (rhythm reset, ADR-0007).

    def _measure_participation(self, context: StepContext) -> None:
        """Phase: share of consulting agents who spoke during this tick."""
        consulted = len(context.events_of_type(Consultation))
        if consulted:
            speakers = {entry.item.sender for entry in self.channel.staged}
            self._records.participation.append((context.tick, len(speakers) / consulted))
