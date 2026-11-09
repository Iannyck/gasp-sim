"""Public API of gasp-sim for model and extension developers.

Only the names exported here are covered by semantic versioning (dev-conventions §9.5,
ADR-0008). Everything else, including the modules of :mod:`gasp_sim.core`, may change
without notice between minor versions.
"""

from gasp_sim.config.base import ComponentParameters, ConfigSection, ExactHours, Hours
from gasp_sim.config.loader import (
    ConfigError,
    ConfigIssue,
    LoadedConfig,
    load_config,
    merge,
    parse_config,
)
from gasp_sim.config.schema import (
    RecordingSettings,
    RunSettings,
    Slot,
    TimeSettings,
    bind_schema,
    config_json_schema,
)
from gasp_sim.core.clock import Clock, DurationRoundingWarning, TimeGrid
from gasp_sim.core.context import StepContext
from gasp_sim.core.deferred import DeferredLog, LogEntry
from gasp_sim.core.events import EventBus, EventHandle, EventQueue, ScheduledEvent, Subscription
from gasp_sim.core.phases import FunctionPhase, Phase
from gasp_sim.core.rng import BIT_GENERATOR, RandomStreams, StreamMode, StreamScope, StreamSpec
from gasp_sim.core.simulation import DayStarted, Simulation, SimulationFailedError, StepCompleted
from gasp_sim.recording.recorder import RunRecorder
from gasp_sim.recording.tables import Aggregator, ObservationTable, Period, SummaryTable
from gasp_sim.registry import (
    Component,
    ExtensionPoint,
    PluginError,
    Preset,
    RegistrationError,
    Registry,
    RegistryError,
    UnknownNameError,
)

__all__ = [
    "BIT_GENERATOR",
    "Aggregator",
    "Clock",
    "Component",
    "ComponentParameters",
    "ConfigError",
    "ConfigIssue",
    "ConfigSection",
    "DayStarted",
    "DeferredLog",
    "DurationRoundingWarning",
    "EventBus",
    "EventHandle",
    "EventQueue",
    "ExactHours",
    "ExtensionPoint",
    "FunctionPhase",
    "Hours",
    "LoadedConfig",
    "LogEntry",
    "ObservationTable",
    "Period",
    "Phase",
    "PluginError",
    "Preset",
    "RandomStreams",
    "RecordingSettings",
    "RegistrationError",
    "Registry",
    "RegistryError",
    "RunRecorder",
    "RunSettings",
    "ScheduledEvent",
    "Simulation",
    "SimulationFailedError",
    "Slot",
    "StepCompleted",
    "StepContext",
    "StreamMode",
    "StreamScope",
    "StreamSpec",
    "Subscription",
    "SummaryTable",
    "TimeGrid",
    "TimeSettings",
    "UnknownNameError",
    "bind_schema",
    "config_json_schema",
    "load_config",
    "merge",
    "parse_config",
]
