"""Public API of gasp-sim for model and extension developers.

Only the names exported here are covered by semantic versioning (dev-conventions §9.5,
ADR-0008). Everything else, including the modules of :mod:`gasp_sim.core`, may change
without notice between minor versions.
"""

from gasp_sim.core.clock import Clock, DurationRoundingWarning, TimeGrid
from gasp_sim.core.context import StepContext
from gasp_sim.core.deferred import DeferredLog, LogEntry
from gasp_sim.core.events import EventBus, EventHandle, EventQueue, ScheduledEvent, Subscription
from gasp_sim.core.phases import FunctionPhase, Phase
from gasp_sim.core.rng import BIT_GENERATOR, RandomStreams, StreamMode, StreamScope, StreamSpec
from gasp_sim.core.simulation import DayStarted, Simulation, SimulationFailedError, StepCompleted

__all__ = [
    "BIT_GENERATOR",
    "Clock",
    "DayStarted",
    "DeferredLog",
    "DurationRoundingWarning",
    "EventBus",
    "EventHandle",
    "EventQueue",
    "FunctionPhase",
    "LogEntry",
    "Phase",
    "RandomStreams",
    "ScheduledEvent",
    "Simulation",
    "SimulationFailedError",
    "StepCompleted",
    "StepContext",
    "StreamMode",
    "StreamScope",
    "StreamSpec",
    "Subscription",
    "TimeGrid",
]
