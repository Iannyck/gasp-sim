"""Configuration schemas: common run settings and component slots (ADR-0014).

A model describes its configuration with a subclass of :class:`RunSettings`. A field whose
value is a component (an implementation of an extension point) is declared with a
:class:`Slot`::

    class ToyConfig(RunSettings):
        n_agents: int = Field(default=5, ge=1)
        speaking_rule: Annotated[ComponentParameters, Slot(SPEAKING_RULE, default="feedback")]

In a configuration file, a component is written as its name under ``type``, with its
parameters at the same level::

    speaking_rule:
      type: feedback
      base_probability: 0.3

The components available depend on the registry, which plugins can extend. A schema is
therefore *bound* to a registry before validation (:func:`bind_schema`): each slot becomes
a choice between the components registered for its extension point, selected by ``type``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union, cast

from pydantic import Field, create_model, field_validator, model_validator
from pydantic.fields import FieldInfo

from gasp_sim.config.base import (
    RESERVED_COMPONENT_KEY,
    ComponentParameters,
    ConfigSection,
    Hours,
)
from gasp_sim.core.clock import TimeGrid
from gasp_sim.core.rng import StreamMode
from gasp_sim.registry import ExtensionPoint, Registry

__all__ = [
    "BoundSchema",
    "RecordingSettings",
    "RunSettings",
    "Slot",
    "SlotBinding",
    "TimeSettings",
    "bind_schema",
    "config_json_schema",
]


class TimeSettings(ConfigSection):
    """Length of a tick and of a working day (ADR-0003, ADR-0007)."""

    tick_minutes: int = Field(
        default=5, ge=1, description="Length of a tick (time step), in minutes."
    )
    day_hours: float = Field(default=8.0, gt=0, description="Length of a working day, in hours.")

    @field_validator("day_hours")
    @classmethod
    def _check_whole_minutes(cls, day_hours: float) -> float:
        minutes = day_hours * 60
        if not math.isclose(minutes, round(minutes), rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"must be a whole number of minutes (got {day_hours:g})")
        return day_hours

    @model_validator(mode="after")
    def _check_grid(self) -> TimeSettings:
        self.grid()
        return self

    def grid(self) -> TimeGrid:
        """Return the time grid of the engine.

        Raises
        ------
        ValueError
            If the working day is not a whole number of ticks.
        """
        return TimeGrid(tick_minutes=self.tick_minutes, day_minutes=round(self.day_hours * 60))


class RecordingSettings(ConfigSection):
    """What is recorded during a run (ADR-0015)."""

    level: Literal["full", "summary"] = Field(
        default="full",
        description=(
            "'full' writes every observation table and the summaries; 'summary' writes the "
            "summaries only (per time window and per run). An indicator that was not "
            "planned cannot be computed afterwards from a 'summary' run."
        ),
    )
    window_hours: Annotated[Hours, Field(gt=0)] = Field(
        default=8.0,
        description="Length of the time windows of the summaries, in working hours.",
    )


class RunSettings(ConfigSection):
    """Settings common to every run, whatever the model.

    Subclass it to describe the configuration of a model.
    """

    preset: str | None = Field(
        default=None,
        description="Name of a preset whose values this file completes or overrides.",
    )
    plugins: tuple[str, ...] = Field(
        default=(),
        description=(
            "Local plugins to load before validation: module names, or paths of Python "
            "files relative to this file."
        ),
    )
    seed: int = Field(ge=0, description="Seed of the run; every random draw derives from it.")
    days: int = Field(ge=1, description="Number of working days to simulate.")
    stream_mode: Literal["named", "single"] = Field(
        default="named",
        description=(
            "Advanced. 'named' gives each process its own random stream; 'single' is only "
            "for verifying that results do not depend on it (ADR-0002)."
        ),
    )
    time: TimeSettings = Field(
        default_factory=TimeSettings, description="Length of a tick and of a working day."
    )
    recording: RecordingSettings = Field(
        default_factory=RecordingSettings, description="What is recorded during the run."
    )

    def random_stream_mode(self) -> StreamMode:
        """Return :attr:`stream_mode` as a :class:`~gasp_sim.core.rng.StreamMode`."""
        return StreamMode(self.stream_mode)


@dataclass(frozen=True, slots=True)
class Slot:
    """Marks a configuration field whose value is a component of an extension point.

    Use it in the metadata of a field typed :class:`ComponentParameters`::

        speaking_rule: Annotated[ComponentParameters, Slot(SPEAKING_RULE, default="feedback")]

    Parameters
    ----------
    point : ExtensionPoint
        Extension point whose components can fill the slot.
    default : str, optional
        Name of the component used, with its default parameters, when the configuration
        does not set the field. Without a default, the field is required.
    """

    point: ExtensionPoint[Any]
    default: str | None = None


@dataclass(frozen=True, slots=True)
class SlotBinding:
    """A slot of a bound schema: its extension point and the models of its components."""

    point: ExtensionPoint[Any]
    members: Mapping[str, type[ComponentParameters]]


@dataclass(frozen=True, slots=True)
class BoundSchema[S: ConfigSection]:
    """A configuration schema bound to the components of a registry.

    Attributes
    ----------
    model : type[S]
        Pydantic model that validates complete configurations. It is a subclass of the
        unbound schema, so a validated configuration is an instance of the schema.
    slots : Mapping[tuple[str, ...], SlotBinding]
        Component slots, by path of field names.
    """

    model: type[S]
    slots: Mapping[tuple[str, ...], SlotBinding]


def bind_schema[S: ConfigSection](schema: type[S], registry: Registry) -> BoundSchema[S]:
    """Bind ``schema`` to the components registered in ``registry``.

    Slots may be fields of the schema or of nested sections (not items of lists).

    Raises
    ------
    UnknownNameError
        If a slot refers to an extension point or a default component that is not in the
        registry.
    TypeError
        If a default component cannot be built from default parameters alone.
    """
    key = (schema, _signature(registry))
    cached = _BOUND.get(key)
    if cached is None:
        slots: dict[tuple[str, ...], SlotBinding] = {}
        model = _bind_section(schema, registry, (), slots)
        cached = _BOUND[key] = BoundSchema(model=model, slots=slots)
    return cast("BoundSchema[S]", cached)


def config_json_schema(schema: type[ConfigSection], registry: Registry) -> dict[str, Any]:
    """Return the JSON Schema of ``schema`` bound to ``registry``.

    The JSON Schema describes every setting, with its type, bounds, default and
    description, including the parameters of every registered component (extensions
    included). It is meant to generate forms in the user interface.
    """
    return bind_schema(schema, registry).model.model_json_schema()


# --------------------------------------------------------------------------- binding

# Bound schemas are cached, so that loading two files with the same components gives
# configurations of the same classes (which compare equal when their values are equal).
type _Signature = tuple[tuple[ExtensionPoint[Any], tuple[tuple[str, type], ...]], ...]
_BOUND: dict[tuple[type[ConfigSection], _Signature], BoundSchema[Any]] = {}


def _signature(registry: Registry) -> _Signature:
    """Return the components of a registry, which determine a bound schema."""
    return tuple(
        (
            point,
            tuple(
                (name, registry.component(point, name).parameters)
                for name in registry.component_names(point)
            ),
        )
        for point in registry.extension_points
    )


def _slot_of(field: FieldInfo) -> Slot | None:
    return next((item for item in field.metadata if isinstance(item, Slot)), None)


def _bind_section[S: ConfigSection](
    section: type[S],
    registry: Registry,
    path: tuple[str, ...],
    slots: dict[tuple[str, ...], SlotBinding],
) -> type[S]:
    overrides: dict[str, Any] = {}
    for name, field in section.model_fields.items():
        slot = _slot_of(field)
        if slot is not None:
            overrides[name] = _bind_slot(slot, field, registry, (*path, name), slots)
            continue
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, ConfigSection):
            bound = _bind_section(annotation, registry, (*path, name), slots)
            if bound is not annotation:
                overrides[name] = (bound, _bound_default(bound, field))
    if not overrides:
        return section
    return cast(
        "type[S]",
        create_model(
            section.__name__,
            __base__=section,
            __module__=section.__module__,
            __doc__=section.__doc__,
            **overrides,
        ),
    )


def _bind_slot(
    slot: Slot,
    field: FieldInfo,
    registry: Registry,
    path: tuple[str, ...],
    slots: dict[tuple[str, ...], SlotBinding],
) -> tuple[Any, Any]:
    """Return the annotation and the field of a bound slot."""
    point = slot.point
    members: dict[str, type[ComponentParameters]] = {}
    for component_name in registry.component_names(point):
        component = registry.component(point, component_name)
        tag = cast("Any", Literal)[component_name]
        # The field name is RESERVED_COMPONENT_KEY ("type"), written out for the type checker.
        members[component_name] = create_model(
            f"{_camel(point.name)}{_camel(component_name)}",
            __base__=component.parameters,
            __module__=component.parameters.__module__,
            __doc__=component.parameters.__doc__ or component.summary or None,
            type=(tag, Field(description=f"{point.name}: {component_name}")),
        )
    if not members:
        raise TypeError(f"Extension point {point.name!r} has no registered component.")
    slots[path] = SlotBinding(point=point, members=members)
    # Built at run time from the registered components, hence the casts.
    union = cast("Any", Union)[tuple(members.values())]
    choice = cast("Any", Annotated)[union, Field(discriminator=RESERVED_COMPONENT_KEY)]
    description = field.description or point.summary or None
    if slot.default is None:
        return choice, Field(description=description)
    registry.component(point, slot.default)  # raises UnknownNameError with the alternatives
    try:
        default = members[slot.default].model_validate({RESERVED_COMPONENT_KEY: slot.default})
    except ValueError as error:
        raise TypeError(
            f"Default {point.name} {slot.default!r} needs parameters without defaults; give "
            f"them defaults or make the slot required."
        ) from error
    return choice, Field(default=default, description=description)


def _bound_default(bound: type[ConfigSection], field: FieldInfo) -> Any:
    """Default of a nested section that contains slots: its own defaults, when complete."""
    if field.is_required():
        return Field(description=field.description)
    try:
        default = bound.model_validate({})
    except ValueError:
        return Field(description=field.description)
    return Field(default=default, description=field.description)


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))
