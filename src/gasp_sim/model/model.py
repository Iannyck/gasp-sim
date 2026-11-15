"""The GASP model: team, team channel, climate and decisions to speak (ODD sections 2 to 7).

Version of step 6.1: the control condition (no proxy). At each consultation a member reads
messages of the team channel (reading habit), perceives a climate (climate perception),
and speaks with a probability that depends on their psychological safety and on that
climate (expression probability). After the consultations of a tick, the climate of the
team is updated from the participation in the channel (climate rule).

Order within a tick (ODD section 3): at the first tick of a day, the consultations of the
day are scheduled; then the members who consult decide, all from what was visible before
the tick (synchronous perception); their messages become visible from the next tick;
finally the climate of the team is updated.

The model is built from components; :mod:`gasp_sim.model.config` builds it from a
configuration file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from gasp_sim.core.clock import TimeGrid
from gasp_sim.core.context import StepContext
from gasp_sim.core.deferred import DeferredLog
from gasp_sim.core.phases import FunctionPhase
from gasp_sim.core.rng import RandomStreams, StreamMode, StreamScope, StreamSpec
from gasp_sim.core.simulation import Simulation
from gasp_sim.model._time import ticks_of
from gasp_sim.model.climate import ClimateRule
from gasp_sim.model.distributions import Distribution
from gasp_sim.model.expression import ExpressionProbability, SpeakerView
from gasp_sim.model.observations import AgentDescribed, ClimateUpdated, Consulted, MessagePosted
from gasp_sim.model.perception import ClimatePerception
from gasp_sim.model.reading import ReadingHabit
from gasp_sim.model.rhythms import WorkRhythm

__all__ = ["GENERIC", "STREAMS", "Consultation", "GaspModel", "Message"]

#: Random streams of the model (ADR-0002, ADR-0010). Identifiers are permanent: never
#: change or reuse one. Reserved for later steps: 0 ``init`` (team), 1 ``proxy`` (team),
#: 4 ``tasks`` (per agent), 7 ``personality`` (per agent).
STREAMS = (
    StreamSpec("rhythm", 2, StreamScope.AGENT),
    StreamSpec("speech", 3, StreamScope.AGENT),
    StreamSpec("traits", 5, StreamScope.AGENT),
    StreamSpec("perception", 6, StreamScope.AGENT),
)

#: Type of the single message type of step 6.1 (and of the ``article`` preset).
GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class Consultation:
    """Scheduled event: ``agent`` consults the team channel."""

    agent: int


@dataclass(frozen=True, slots=True)
class Message:
    """A message of the team channel; it has no text, its type stands for its content."""

    number: int
    sender: int
    message_type: str


@dataclass(slots=True)
class _Member:
    """State of a member during a run."""

    safety: float
    impression: float | None
    previous: int | None = None


class GaspModel:
    """The GASP model: its state, its phases and the simulation that runs them.

    Parameters
    ----------
    team_size : int
        Number of members.
    seed : int
        Seed of the run.
    safety : Distribution
        Distribution of psychological safety.
    rhythm : WorkRhythm
        Consultation rhythm of the members.
    reading : ReadingHabit
        Reading habit of the members.
    perception : ClimatePerception
        Perception of the climate.
    climate_rule : ClimateRule
        Update rule of the climate of the team (and, by default, of impressions).
    expression : ExpressionProbability
        Probability of speaking.
    initial_climate : float, optional
        Climate of the team before the first update (default 0.5, neutral).
    participation_window_hours : float, optional
        Window over which the participation of the team is measured (default 0.5).
    grid : TimeGrid, optional
        Time grid (default: 5-minute ticks, 8-hour days).
    mode : StreamMode, optional
        Random-stream mode (default named; single is for verification only).

    Raises
    ------
    ValueError
        If the team has fewer than two members or a value is out of range.
    """

    def __init__(
        self,
        *,
        team_size: int,
        seed: int,
        safety: Distribution,
        rhythm: WorkRhythm,
        reading: ReadingHabit,
        perception: ClimatePerception,
        climate_rule: ClimateRule,
        expression: ExpressionProbability,
        initial_climate: float = 0.5,
        participation_window_hours: float = 0.5,
        grid: TimeGrid | None = None,
        mode: StreamMode = StreamMode.NAMED,
    ) -> None:
        if team_size < 2:
            raise ValueError(f"team_size must be at least 2, got {team_size}.")
        _check_unit("initial_climate", initial_climate)
        self.team_size = team_size
        self.grid = grid if grid is not None else TimeGrid()
        self.rhythm = rhythm
        self.reading = reading
        self.perception = perception
        self.climate_rule = climate_rule
        self.expression = expression
        self.streams = RandomStreams(seed=seed, specs=STREAMS, mode=mode)
        self.window = ticks_of(participation_window_hours, self.grid)
        if self.window < 1:
            raise ValueError("participation_window_hours must be at least one tick.")
        self.climate = initial_climate
        self.channel = DeferredLog[Message]("team_channel")
        self._messages = 0
        self._last_update: int | None = None
        self._members = [
            _Member(
                safety=_check_unit(
                    "psychological safety", safety.draw(self.streams.agent("traits", agent))
                ),
                impression=perception.initial_impression(self.streams.agent("perception", agent)),
            )
            for agent in range(team_size)
        ]
        self.simulation = Simulation(
            phases=[
                FunctionPhase("consultations", self._consult),
                FunctionPhase("climate", self._update_climate),
            ],
            day_start_phases=[FunctionPhase("start_day", self._start_day)],
            streams=self.streams,
            grid=self.grid,
            logs=[self.channel],
        )

    # ----------------------------------------------------------------- phases

    def _start_day(self, context: StepContext) -> None:
        """Describe the members (first tick only) and schedule the day's consultations."""
        if context.tick == 0:
            for agent, member in enumerate(self._members):
                context.publish(AgentDescribed(0, agent, member.safety, member.impression))
        for agent in range(self.team_size):
            ticks = self.rhythm.consultations_of_day(
                agent, self.grid, self.streams.agent("rhythm", agent)
            )
            for tick_of_day in ticks:
                if not 0 <= tick_of_day < self.grid.ticks_per_day:
                    raise ValueError(
                        f"The work rhythm gave tick {tick_of_day!r} for member {agent}; "
                        f"expected a tick of the day in [0, {self.grid.ticks_per_day})."
                    )
                context.schedule(Consultation(agent), at=context.tick + tick_of_day)

    def _consult(self, context: StepContext) -> None:
        """Each consulting member reads, perceives and decides whether to speak."""
        tick = context.tick
        visible = self.channel.visible
        for event in context.events_of_type(Consultation):
            agent = event.agent
            member = self._members[agent]
            reading = self.reading.read(
                visible, tick=tick, previous=member.previous, grid=self.grid
            )
            others = {entry.item.sender for entry in reading.entries} - {agent}
            observed = len(others) / (self.team_size - 1) if reading.start_tick < tick else None
            elapsed = (
                self.grid.ticks_to_hours(tick - member.previous)
                if member.previous is not None
                else None
            )
            perceived = self.perception.perceive(
                member.impression,
                team_climate=self.climate,
                observed=observed,
                elapsed_hours=elapsed,
                rule=self.climate_rule,
            )
            perceived_climate = _check_unit("perceived climate", perceived.climate)
            probability = _check_unit(
                f"probability of speaking of member {agent}",
                self.expression.probability(SpeakerView(member.safety, perceived_climate)),
            )
            # One draw per consultation; the member speaks if r ≤ P (equation 1 of the
            # article).
            spoke = bool(context.streams.agent("speech", agent).random() <= probability)
            context.publish(
                Consulted(
                    tick,
                    agent,
                    messages_read=len(reading.entries),
                    read_minutes=(tick - reading.start_tick) * self.grid.tick_minutes,
                    observed_participation=observed,
                    perceived_climate=perceived_climate,
                    probability=probability,
                    spoke=spoke,
                )
            )
            if spoke:
                message = Message(self._messages, agent, GENERIC)
                self._messages += 1
                self.channel.append(message)
                context.publish(MessagePosted(tick, message.number, agent, GENERIC))
            member.impression = perceived.impression
            member.previous = tick

    def _update_climate(self, context: StepContext) -> None:
        """After consultations, update the climate of the team from its participation."""
        if not context.events_of_type(Consultation):
            return
        tick = context.tick
        recent = self.channel.visible_since(tick - self.window + 1)
        writers = {entry.item.sender for entry in (*recent, *self.channel.staged)}
        participation = len(writers) / self.team_size
        # The first update covers the participation window; later ones, the time since
        # the previous update.
        elapsed = self.window if self._last_update is None else tick - self._last_update
        climate = self.climate_rule.update(
            self.climate, participation, self.grid.ticks_to_hours(elapsed)
        )
        self.climate = _check_unit("climate", climate)
        self._last_update = tick
        context.publish(ClimateUpdated(tick, participation, self.climate))


def _check_unit(name: str, value: float) -> float:
    """Return ``value`` if it is a finite number in [0, 1]; raise otherwise."""
    if not (isinstance(value, int | float) and math.isfinite(value) and 0 <= value <= 1):
        raise ValueError(f"The {name} must be a number in [0, 1], got {value!r}.")
    return float(value)
