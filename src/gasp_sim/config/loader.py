"""Loading of YAML configuration files, with readable errors (ADR-0014).

Loading a file goes through these stages; every problem found is reported at once, with
its location in the file and the rule it breaks:

1. **Reading the YAML**, strictly: a setting written twice is an error (YAML libraries
   usually keep the last value silently), setting names must be text, and dates are kept
   as text.
2. **Plugins**: the modules or files listed under ``plugins:`` are loaded into a copy of
   the registry, so that their components can be selected.
3. **Preset**: if the file names a ``preset:``, the values of the file are merged over
   those of the preset (:func:`merge`).
4. **Validation** against the schema bound to the registry: unknown settings, missing
   settings, wrong types and values out of bounds; no silent conversion.
5. **Durations** in hours are checked against the time grid: a duration that must be a
   whole number of ticks is an error otherwise; any other duration is rounded to the
   nearest tick, with a warning.

The result is a :class:`LoadedConfig`: the validated, frozen configuration with every
default filled in (:meth:`LoadedConfig.resolved`), the registry used, and the warnings.
"""

from __future__ import annotations

import difflib
import math
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import ErrorDetails

from gasp_sim.config.base import RESERVED_COMPONENT_KEY, ConfigSection, DurationCheck
from gasp_sim.config.schema import (
    BoundSchema,
    RunSettings,
    SlotBinding,
    TimeSettings,
    bind_schema,
)
from gasp_sim.core.clock import TimeGrid
from gasp_sim.registry import PluginError, Registry, UnknownNameError

__all__ = [
    "ConfigError",
    "ConfigIssue",
    "LoadedConfig",
    "load_config",
    "merge",
    "parse_config",
]

type Location = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class ConfigIssue:
    """A problem found in a configuration: an error or a warning.

    Attributes
    ----------
    path : tuple[str | int, ...]
        Location of the setting, as names of settings (and positions in lists). Empty for
        a problem with the whole file.
    message : str
        What is wrong, in plain words.
    """

    path: Location
    message: str

    @property
    def location(self) -> str:
        """The path written for people, for example ``speaking_rule → feedback``."""
        return " → ".join(str(part) for part in self.path) or "(whole file)"

    def __str__(self) -> str:
        """Return ``location: message``."""
        return f"{self.location}: {self.message}"


class ConfigError(ValueError):
    """A configuration is invalid. The message lists every error, then every warning.

    Attributes
    ----------
    origin : str
        Where the configuration comes from (usually a file path).
    errors : tuple[ConfigIssue, ...]
        The errors, in the order of the file.
    warnings : tuple[ConfigIssue, ...]
        Warnings found before the errors stopped the loading.
    """

    def __init__(
        self,
        origin: str,
        errors: Sequence[ConfigIssue],
        warnings: Sequence[ConfigIssue] = (),
    ) -> None:
        self.origin = origin
        self.errors = tuple(errors)
        self.warnings = tuple(warnings)
        super().__init__(self.report())

    def report(self) -> str:
        """Return the full report, one line per problem."""
        counts = _plural(len(self.errors), "error")
        if self.warnings:
            counts += f", {_plural(len(self.warnings), 'warning')}"
        lines = [f"Invalid configuration {self.origin} ({counts}):"]
        lines += [f"  error: {issue}" for issue in self.errors]
        lines += [f"  warning: {issue}" for issue in self.warnings]
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class LoadedConfig[S: RunSettings]:
    """A validated configuration and what is needed to use it.

    Attributes
    ----------
    config : S
        The validated configuration, frozen, with every default filled in.
    registry : Registry
        The registry used for validation, including the plugins of the file. Build the
        components of the configuration with it (:meth:`Registry.create`).
    schema : BoundSchema[S]
        The schema bound to that registry.
    warnings : tuple[ConfigIssue, ...]
        Warnings (for example rounded durations), to show to the user.
    origin : str
        Where the configuration comes from.
    """

    config: S
    registry: Registry
    schema: BoundSchema[S]
    warnings: tuple[ConfigIssue, ...]
    origin: str

    def resolved(self) -> dict[str, Any]:
        """Return every setting, defaults included, as plain data.

        This is the complete record of the configuration of a run: loading it again gives
        the same configuration.
        """
        data = self.config.model_dump(mode="json")
        for path in self.schema.slots:
            parent = data
            for name in path[:-1]:
                parent = parent[name]
            selection = parent[path[-1]]
            # Write the component name first, as people write it.
            parent[path[-1]] = {
                RESERVED_COMPONENT_KEY: selection.pop(RESERVED_COMPONENT_KEY),
                **selection,
            }
        return data

    def to_yaml(self) -> str:
        """Return :meth:`resolved` as YAML text."""
        header = "# Resolved configuration: every setting, including defaults.\n"
        return header + yaml.safe_dump(
            self.resolved(), sort_keys=False, allow_unicode=True, default_flow_style=False
        )


def load_config[S: RunSettings](
    path: str | Path, schema: type[S], registry: Registry
) -> LoadedConfig[S]:
    """Load and validate a YAML configuration file.

    Parameters
    ----------
    path : str or Path
        The configuration file. Local plugins are looked for relative to its directory.
    schema : type[S]
        The configuration schema of the model.
    registry : Registry
        Components and presets available; it is not modified (plugins are loaded into a
        copy, available as :attr:`LoadedConfig.registry`).

    Returns
    -------
    LoadedConfig[S]
        The validated configuration.

    Raises
    ------
    ConfigError
        If the file cannot be read or the configuration is invalid; the message lists
        every problem.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(
            str(file), [ConfigIssue((), f"cannot read the file ({error.strerror})")]
        ) from None
    return parse_config(text, schema, registry, origin=str(file), base_dir=file.parent)


def parse_config[S: RunSettings](
    text: str,
    schema: type[S],
    registry: Registry,
    *,
    origin: str = "<text>",
    base_dir: Path | None = None,
) -> LoadedConfig[S]:
    """Validate a configuration given as YAML text.

    Parameters are those of :func:`load_config`; ``origin`` names the text in messages and
    ``base_dir`` is the directory of local plugin files.
    """
    raw = _read_yaml(text, origin)
    registry, raw = _apply_plugins_and_preset(raw, registry, origin, base_dir)
    bound = bind_schema(schema, registry)
    try:
        config = bound.model.model_validate(raw)
    except ValidationError as error:
        # Durations are still checked, as far as the invalid configuration allows, so that
        # every problem is reported at once.
        errors, rounding = _check_durations(_raw_durations(bound, raw), _raw_grid(raw))
        raise ConfigError(origin, [*_validation_issues(error, bound), *errors], rounding) from None
    errors, rounding = _check_durations(_durations(config, ()), config.time.grid())
    if errors:
        raise ConfigError(origin, errors, rounding)
    return LoadedConfig(
        config=config,
        registry=registry,
        schema=bound,
        warnings=tuple(rounding),
        origin=origin,
    )


def merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge configuration values: those of ``override`` win.

    Groups of settings are merged setting by setting. A component block whose ``type``
    differs from the one in ``base`` replaces it entirely, since the parameters of one
    component mean nothing to another. Lists and single values are replaced.

    Examples
    --------
    >>> merge({"rule": {"type": "a", "x": 1, "y": 2}}, {"rule": {"y": 3}})
    {'rule': {'type': 'a', 'x': 1, 'y': 3}}
    >>> merge({"rule": {"type": "a", "x": 1}}, {"rule": {"type": "b"}})
    {'rule': {'type': 'b'}}
    """
    result = dict(base)
    for key, value in override.items():
        previous = result.get(key)
        if (
            isinstance(previous, Mapping)
            and isinstance(value, Mapping)
            and value.get(RESERVED_COMPONENT_KEY, previous.get(RESERVED_COMPONENT_KEY))
            == previous.get(RESERVED_COMPONENT_KEY)
        ):
            result[key] = merge(previous, value)
        else:
            result[key] = value
    return result


# --------------------------------------------------------------------------- YAML


class _StrictLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses repeated settings and keeps dates as text."""


_TIMESTAMP = "tag:yaml.org,2002:timestamp"
_MERGE = "tag:yaml.org,2002:merge"
_StrictLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != _TIMESTAMP]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[str, Any]:
    written = sum(1 for key_node, _ in node.value if key_node.tag != _MERGE)
    # Settings brought by YAML merge keys (<<) come first; those written in the group may
    # override them, but not each other.
    loader.flatten_mapping(node)
    merged = len(node.value) - written
    mapping: dict[str, Any] = {}
    explicit: set[str] = set()
    for index, (key_node, value_node) in enumerate(node.value):
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(
                None, None, f"setting names must be text, got {key!r}", key_node.start_mark
            )
        if index >= merged:
            if key in explicit:
                raise yaml.constructor.ConstructorError(
                    None, None, f"'{key}' is set twice in the same group", key_node.start_mark
                )
            explicit.add(key)
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


def _construct_sequence(loader: _StrictLoader, node: yaml.SequenceNode) -> tuple[Any, ...]:
    return tuple(loader.construct_object(child, deep=True) for child in node.value)


_StrictLoader.add_constructor("tag:yaml.org,2002:map", _construct_mapping)
_StrictLoader.add_constructor("tag:yaml.org,2002:seq", _construct_sequence)


def _read_yaml(text: str, origin: str) -> dict[str, Any]:
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # a SafeLoader subclass
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
        problem = error.problem or error.context or "invalid YAML"
        raise ConfigError(origin, [ConfigIssue((), f"{where}{problem}")]) from None
    except yaml.YAMLError as error:
        raise ConfigError(origin, [ConfigIssue((), f"invalid YAML: {error}")]) from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            origin,
            [ConfigIssue((), f"must be a group of settings (name: value), got {_show(data)}")],
        )
    return data


def _normalise(value: Any) -> Any:
    """Give values written in Python (presets) the shapes produced by the YAML loader."""
    if isinstance(value, Mapping):
        return {key: _normalise(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return tuple(_normalise(item) for item in value)
    return value


# --------------------------------------------------------------------------- plugins, preset


def _apply_plugins_and_preset(
    raw: dict[str, Any], registry: Registry, origin: str, base_dir: Path | None
) -> tuple[Registry, dict[str, Any]]:
    errors: list[ConfigIssue] = []
    registry = registry.copy()
    plugins = raw.get("plugins", ())
    if not isinstance(plugins, tuple) or not all(isinstance(item, str) for item in plugins):
        errors.append(
            ConfigIssue(("plugins",), "must be a list of module names or Python file paths")
        )
    else:
        for index, reference in enumerate(plugins):
            try:
                registry.load_plugin(reference, base_dir=base_dir)
            except PluginError as error:
                errors.append(ConfigIssue(("plugins", index), _lower_first(str(error))))
    preset_name = raw.get("preset")
    if isinstance(preset_name, str) and not errors:
        try:
            preset = registry.preset(preset_name)
        except UnknownNameError as error:
            errors.append(ConfigIssue(("preset",), _lower_first(str(error))))
        else:
            raw = merge(_normalise(preset.values), raw)
    if errors:
        raise ConfigError(origin, errors)
    return registry, raw


# --------------------------------------------------------------------------- validation errors


def _validation_issues(error: ValidationError, bound: BoundSchema[Any]) -> list[ConfigIssue]:
    issues = []
    for detail in error.errors(include_url=False):
        path, section = _resolve(detail["loc"], bound)
        issues.append(ConfigIssue(path, _message(detail, path, section, bound)))
    return issues


def _resolve(
    loc: tuple[str | int, ...], bound: BoundSchema[Any]
) -> tuple[Location, type[ConfigSection] | None]:
    """Clean a pydantic location and find the section holding its last setting.

    Pydantic inserts the name of the selected component right after the location of a
    component slot; it is removed. The section is used to suggest names of settings.
    """
    path: list[str | int] = []
    section: type[ConfigSection] | None = bound.model
    parent: type[ConfigSection] | None = bound.model
    expected_tag: SlotBinding | None = None
    for item in loc:
        if expected_tag is not None and isinstance(item, str) and item in expected_tag.members:
            section = expected_tag.members[item]
            expected_tag = None
            continue
        path.append(item)
        expected_tag = bound.slots.get(tuple(str(part) for part in path))
        field = section.model_fields.get(str(item)) if section is not None else None
        annotation = field.annotation if field is not None else None
        parent = section
        if isinstance(annotation, type) and issubclass(annotation, ConfigSection):
            section = annotation
        else:
            section = None
    return tuple(path), parent


_BOUNDS = {
    "greater_than": "must be greater than {gt}",
    "greater_than_equal": "must be at least {ge}",
    "less_than": "must be less than {lt}",
    "less_than_equal": "must be at most {le}",
    "literal_error": "must be one of: {expected}",
}

_TYPES = {
    "int_type": "must be a whole number",
    "float_type": "must be a number",
    "finite_number": "must be a finite number",
    "bool_type": "must be true or false",
    "string_type": "must be text",
    "tuple_type": "must be a list",
    "model_type": "must be a group of settings (name: value)",
    "model_attributes_type": "must be a group of settings (name: value)",
    "dict_type": "must be a group of settings (name: value)",
    "none_required": "must be empty (null)",
}


def _message(
    detail: ErrorDetails,
    path: Location,
    section: type[ConfigSection] | None,
    bound: BoundSchema[Any],
) -> str:
    kind = detail["type"]
    context = detail.get("ctx", {})
    value = detail["input"]
    if kind == "missing":
        return "required setting is missing"
    if kind == "extra_forbidden":
        return "unknown setting" + _suggestion(path[-1], section)
    slot = bound.slots.get(tuple(str(part) for part in path))
    if kind in ("union_tag_invalid", "union_tag_not_found"):
        assert slot is not None  # pydantic reports these errors at a slot
        available = ", ".join(sorted(slot.members))
        if kind == "union_tag_not_found":
            return f"missing 'type': choose a {slot.point.name} among: {available}"
        return f"unknown {slot.point.name} {_show(context['tag'])}; available: {available}"
    if slot is not None and kind in _TYPES and isinstance(value, str) and value in slot.members:
        return (
            f"must be a group of settings (got {_show(value)}); to choose this component, "
            f"write 'type: {value}' on the next line, indented"
        )
    if kind in _BOUNDS:
        text = _BOUNDS[kind].format(**{k: _show_bound(v) for k, v in context.items()})
    elif kind in _TYPES:
        text = _TYPES[kind] + _hint(kind, value)
    elif kind == "value_error":
        return _lower_first(str(context.get("error", detail["msg"])))
    else:
        text = detail["msg"][:1].lower() + detail["msg"][1:]
    return f"{text} (got {_show(value)})"


def _suggestion(name: str | int, section: type[ConfigSection] | None) -> str:
    if section is None:
        return ""
    known = [key for key in section.model_fields if key != RESERVED_COMPONENT_KEY]
    close = difflib.get_close_matches(str(name), known, n=1, cutoff=0.6)
    return f"; did you mean '{close[0]}'?" if close else ""


def _hint(kind: str, value: object) -> str:
    if kind in ("int_type", "float_type") and isinstance(value, str):
        try:
            float(value)
        except ValueError:
            return ""
        if "e" in value.lower():
            return "; in YAML, write exponents with a decimal point and no quotes, as in 1.0e-3"
        return "; write numbers without quotes"
    if kind == "string_type" and isinstance(value, bool):
        return "; YAML reads yes/no/on/off as true/false: put the text in quotes"
    return ""


def _show(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, Mapping):
        return "a group of settings"
    if isinstance(value, tuple):
        return "a list"
    return repr(value)


def _show_bound(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# --------------------------------------------------------------------------- durations


type _Duration = tuple[Location, float, DurationCheck]


def _check_durations(
    durations: Iterable[_Duration], grid: TimeGrid | None
) -> tuple[list[ConfigIssue], list[ConfigIssue]]:
    """Check durations in hours against the time grid; return errors and warnings."""
    errors: list[ConfigIssue] = []
    rounded: list[ConfigIssue] = []
    if grid is None:
        return errors, rounded
    tick = f"{grid.tick_minutes}-minute tick"
    for path, hours, check in durations:
        if check.exact:
            try:
                grid.hours_to_ticks_exact(hours)
            except ValueError:
                errors.append(
                    ConfigIssue(path, f"must be a whole number of {tick}s (got {hours:g})")
                )
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ticks = grid.hours_to_ticks(hours)
        if ticks == 0 and hours > 0:
            errors.append(
                ConfigIssue(
                    path, f"is shorter than half a {tick} and would be rounded to 0 (got {hours:g})"
                )
            )
        elif caught:
            rounded.append(
                ConfigIssue(
                    path,
                    f"{hours:g} h is not a whole number of {tick}s; rounded to {ticks} ticks "
                    f"({grid.ticks_to_hours(ticks):g} h)",
                )
            )
    return errors, rounded


def _duration_check(field: FieldInfo) -> DurationCheck | None:
    return next((item for item in field.metadata if isinstance(item, DurationCheck)), None)


def _durations(section: ConfigSection, path: Location) -> Iterator[_Duration]:
    """Durations of a validated configuration, defaults included."""
    for name, field in type(section).model_fields.items():
        value = getattr(section, name)
        check = _duration_check(field)
        if check is not None:
            yield (*path, name), float(value), check
        elif isinstance(value, ConfigSection):
            yield from _durations(value, (*path, name))


def _raw_durations(bound: BoundSchema[Any], raw: Mapping[str, Any]) -> Iterator[_Duration]:
    """Durations written in an invalid configuration that are at least valid numbers."""

    def walk(
        section: type[ConfigSection], data: Mapping[str, Any], path: tuple[str, ...]
    ) -> Iterator[_Duration]:
        for name, field in section.model_fields.items():
            if name not in data:
                continue
            value, here = data[name], (*path, name)
            check = _duration_check(field)
            slot = bound.slots.get(here)
            if check is not None:
                is_number = isinstance(value, int | float) and not isinstance(value, bool)
                if is_number and math.isfinite(value) and value >= 0:
                    yield here, float(value), check
            elif isinstance(value, Mapping):
                annotation = field.annotation
                if slot is not None:
                    tag = value.get(RESERVED_COMPONENT_KEY)
                    member = slot.members.get(tag) if isinstance(tag, str) else None
                    if member is not None:
                        yield from walk(member, value, here)
                elif isinstance(annotation, type) and issubclass(annotation, ConfigSection):
                    yield from walk(annotation, value, here)

    return walk(bound.model, raw, ())


def _raw_grid(raw: Mapping[str, Any]) -> TimeGrid | None:
    """Time grid of an invalid configuration, if its own settings are valid."""
    try:
        return TimeSettings.model_validate(raw.get("time", {})).grid()
    except (ValidationError, ValueError):
        return None


# --------------------------------------------------------------------------- text


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _lower_first(text: str) -> str:
    text = text.rstrip(".")
    return text[:1].lower() + text[1:]
