"""Registry of extension points, components and presets (ADR-0014).

An **extension point** is a replaceable part of a model, described by a
:class:`typing.Protocol` (for example the rule that gives the probability of speaking). A
**component** is one implementation of an extension point, chosen by its name in a
configuration file, with its own validated parameters. A **preset** is a named set of
configuration values.

A registry is filled from three sources, always explicitly:

1. **built-in** components, registered by the code of the model;
2. **installed plugins**, discovered through Python *entry points*
   (:meth:`Registry.load_entry_points`);
3. **local plugins**, listed under ``plugins:`` in a configuration file, for quick
   experiments without packaging (:meth:`Registry.load_plugin`).

A plugin is a module with a function ``register(registry)`` that adds its extension
points, components and presets. Registering a name twice is an error, whatever the
sources: a plugin can never silently replace a component.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from gasp_sim.config.base import RESERVED_COMPONENT_KEY, ComponentParameters

__all__ = [
    "Component",
    "ExtensionPoint",
    "PluginError",
    "Preset",
    "RegistrationError",
    "Registry",
    "RegistryError",
    "UnknownNameError",
]

_NAME = re.compile(r"[a-z][a-z0-9_]*")

#: Source recorded for components registered directly by code.
BUILT_IN = "built-in"


class RegistryError(Exception):
    """Base class of the errors raised by the registry."""


class RegistrationError(RegistryError):
    """An extension point, a component or a preset cannot be registered."""


class UnknownNameError(RegistryError, LookupError):
    """No extension point, component or preset has the requested name."""


class PluginError(RegistryError):
    """A plugin cannot be loaded."""


def _check_name(kind: str, name: object) -> None:
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError(
            f"{kind} name must be lowercase letters, digits and underscores, starting with a "
            f"letter; got {name!r}."
        )


@dataclass(frozen=True, slots=True)
class ExtensionPoint[P]:
    """A replaceable part of a model.

    Parameters
    ----------
    name : str
        Name used in configuration files (for example ``"speaking_rule"``).
    protocol : type
        Interface that every component must satisfy: a :class:`typing.Protocol` decorated
        with :func:`typing.runtime_checkable`, declaring methods only.
    summary : str, optional
        One-line description, shown to users.

    Notes
    -----
    Declare the type of the components when creating an extension point, so that
    :meth:`Registry.create` returns that type::

        SPEAKING_RULE: ExtensionPoint[SpeakingRule] = ExtensionPoint(
            "speaking_rule", SpeakingRule
        )

    The protocol check of Python only verifies that the methods exist, not their
    signatures; static type checking does the rest.
    """

    name: str
    protocol: type
    summary: str = ""

    def __post_init__(self) -> None:
        """Validate the name and the protocol."""
        _check_name("Extension point", self.name)
        # typing.is_protocol() only exists from Python 3.13; these attributes are set by
        # typing.Protocol and @runtime_checkable on every supported version.
        if not (
            getattr(self.protocol, "_is_protocol", False)
            and getattr(self.protocol, "_is_runtime_protocol", False)
        ):
            raise TypeError(
                f"The protocol of extension point {self.name!r} must be a typing.Protocol "
                "decorated with @runtime_checkable."
            )
        try:
            issubclass(object, self.protocol)
        except TypeError as error:
            raise TypeError(
                f"The protocol of extension point {self.name!r} must declare methods only "
                f"({error})."
            ) from None


@dataclass(frozen=True, slots=True)
class Component[T: ComponentParameters]:
    """One implementation of an extension point.

    Parameters
    ----------
    name : str
        Name used in configuration files (``type: <name>``).
    parameters : type[ComponentParameters]
        Validated parameters of the component. Its docstring describes the component to
        users.
    factory : Callable[[T], object]
        Builds the component from its validated parameters. When it is a class, the
        registry checks at registration that it satisfies the protocol of the extension
        point; otherwise the check happens when the component is created.
    summary : str, optional
        One-line description, shown to users. Defaults to the first line of the docstring
        of ``parameters``.
    """

    name: str
    parameters: type[T]
    factory: Callable[[T], object]
    summary: str = ""

    def __post_init__(self) -> None:
        """Validate the name and the parameters."""
        _check_name("Component", self.name)
        if not (
            isinstance(self.parameters, type) and issubclass(self.parameters, ComponentParameters)
        ):
            raise TypeError(
                f"The parameters of component {self.name!r} must be a subclass of "
                "ComponentParameters."
            )
        if RESERVED_COMPONENT_KEY in self.parameters.model_fields:
            raise TypeError(
                f"Component {self.name!r} cannot have a parameter named "
                f"{RESERVED_COMPONENT_KEY!r}: it is reserved to select the component."
            )
        if not callable(self.factory):
            raise TypeError(f"The factory of component {self.name!r} must be callable.")
        if not self.summary:
            first_line = (self.parameters.__doc__ or "").strip().partition("\n")[0]
            object.__setattr__(self, "summary", first_line)


@dataclass(frozen=True, slots=True)
class Preset:
    """A named set of configuration values.

    A configuration file selects a preset with ``preset: <name>``; the values of the file
    are then merged over those of the preset (see :func:`gasp_sim.config.loader.merge`).

    Parameters
    ----------
    name : str
        Name used in configuration files.
    values : Mapping[str, object]
        Configuration values, as they would be written in a file. They are validated with
        the rest of the configuration when a file uses the preset.
    summary : str, optional
        One-line description, shown to users.
    """

    name: str
    values: Mapping[str, object]
    summary: str = ""

    def __post_init__(self) -> None:
        """Validate the name and the values."""
        _check_name("Preset", self.name)
        if not isinstance(self.values, Mapping):
            raise TypeError(f"The values of preset {self.name!r} must be a mapping.")
        if "preset" in self.values or "plugins" in self.values:
            raise ValueError(f"Preset {self.name!r} cannot set 'preset' or 'plugins'.")


@dataclass(slots=True)
class _Entries:
    """Mutable content of a registry; copied as a whole to make plugin loading atomic."""

    points: dict[str, ExtensionPoint[Any]] = field(default_factory=dict)
    point_sources: dict[str, str] = field(default_factory=dict)
    components: dict[str, dict[str, tuple[Component[Any], str]]] = field(default_factory=dict)
    presets: dict[str, tuple[Preset, str]] = field(default_factory=dict)
    plugins: list[str] = field(default_factory=list)

    def copy(self) -> _Entries:
        return _Entries(
            points=dict(self.points),
            point_sources=dict(self.point_sources),
            components={name: dict(items) for name, items in self.components.items()},
            presets=dict(self.presets),
            plugins=list(self.plugins),
        )


class Registry:
    """Extension points, their components, and presets, each with its source.

    A registry is an ordinary object, not a global: each model builds its own (for example
    with a function ``default_registry()``), and loading the plugins of a configuration
    file works on a copy (:meth:`copy`).

    Examples
    --------
    >>> from typing import Protocol, runtime_checkable
    >>> @runtime_checkable
    ... class Greeter(Protocol):
    ...     def greet(self) -> str: ...
    >>> class HelloParameters(ComponentParameters):
    ...     '''Say hello.'''
    >>> class Hello:
    ...     def __init__(self, parameters: HelloParameters) -> None: ...
    ...     def greet(self) -> str:
    ...         return "hello"
    >>> GREETER: ExtensionPoint[Greeter] = ExtensionPoint("greeter", Greeter)
    >>> registry = Registry()
    >>> registry.add_extension_point(GREETER)
    >>> registry.register(GREETER, Component("hello", HelloParameters, Hello))
    >>> registry.component_names(GREETER)
    ('hello',)
    """

    def __init__(self) -> None:
        self._entries = _Entries()

    # ----------------------------------------------------------------- registration

    def add_extension_point(self, point: ExtensionPoint[Any], *, source: str = BUILT_IN) -> None:
        """Declare an extension point.

        Raises
        ------
        RegistrationError
            If an extension point with the same name is already declared.
        """
        if not isinstance(point, ExtensionPoint):
            raise TypeError(f"Expected an ExtensionPoint, got {point!r}.")
        if point.name in self._entries.points:
            raise RegistrationError(
                f"Extension point {point.name!r} is already declared "
                f"({self._entries.point_sources[point.name]}); cannot declare it again "
                f"({source})."
            )
        self._entries.points[point.name] = point
        self._entries.point_sources[point.name] = source
        self._entries.components[point.name] = {}

    def register(
        self, point: ExtensionPoint[Any], component: Component[Any], *, source: str = BUILT_IN
    ) -> None:
        """Register a component of an extension point.

        Raises
        ------
        UnknownNameError
            If the extension point has not been declared in this registry.
        RegistrationError
            If the extension point already has a component with this name, or if the
            factory is a class that does not satisfy the protocol of the extension point.
        """
        if not isinstance(component, Component):
            raise TypeError(f"Expected a Component, got {component!r}.")
        components = self._components_of(point)
        if component.name in components:
            _, previous = components[component.name]
            raise RegistrationError(
                f"{point.name} {component.name!r} is already registered ({previous}); "
                f"cannot register it again ({source})."
            )
        factory = component.factory
        if isinstance(factory, type) and not issubclass(factory, point.protocol):
            raise RegistrationError(
                f"{point.name} {component.name!r} ({source}): {factory.__qualname__} does not "
                f"implement {point.protocol.__qualname__}."
            )
        components[component.name] = (component, source)

    def add_preset(self, preset: Preset, *, source: str = BUILT_IN) -> None:
        """Register a preset.

        Raises
        ------
        RegistrationError
            If a preset with the same name is already registered.
        """
        if not isinstance(preset, Preset):
            raise TypeError(f"Expected a Preset, got {preset!r}.")
        if preset.name in self._entries.presets:
            _, previous = self._entries.presets[preset.name]
            raise RegistrationError(
                f"Preset {preset.name!r} is already registered ({previous}); cannot "
                f"register it again ({source})."
            )
        self._entries.presets[preset.name] = (preset, source)

    # ----------------------------------------------------------------- queries

    @property
    def extension_points(self) -> tuple[ExtensionPoint[Any], ...]:
        """Declared extension points, by name."""
        return tuple(self._entries.points[name] for name in sorted(self._entries.points))

    def extension_point(self, name: str) -> ExtensionPoint[Any]:
        """Return the extension point called ``name``."""
        try:
            return self._entries.points[name]
        except KeyError:
            raise UnknownNameError(
                f"Unknown extension point {name!r}; declared: {_names(self._entries.points)}."
            ) from None

    def component_names(self, point: ExtensionPoint[Any]) -> tuple[str, ...]:
        """Names of the components of ``point``, sorted."""
        return tuple(sorted(self._components_of(point)))

    def component(self, point: ExtensionPoint[Any], name: str) -> Component[Any]:
        """Return the component of ``point`` called ``name``.

        Raises
        ------
        UnknownNameError
            If there is no such component; the message lists the available ones.
        """
        components = self._components_of(point)
        try:
            return components[name][0]
        except KeyError:
            raise UnknownNameError(
                f"Unknown {point.name} {name!r}; available: {_names(components)}."
            ) from None

    def component_source(self, point: ExtensionPoint[Any], name: str) -> str:
        """Return where the component of ``point`` called ``name`` comes from."""
        self.component(point, name)
        return self._components_of(point)[name][1]

    @property
    def presets(self) -> tuple[Preset, ...]:
        """Registered presets, by name."""
        return tuple(self._entries.presets[name][0] for name in sorted(self._entries.presets))

    def preset(self, name: str) -> Preset:
        """Return the preset called ``name``.

        Raises
        ------
        UnknownNameError
            If there is no such preset; the message lists the available ones.
        """
        try:
            return self._entries.presets[name][0]
        except KeyError:
            raise UnknownNameError(
                f"Unknown preset {name!r}; available: {_names(self._entries.presets)}."
            ) from None

    @property
    def plugins(self) -> tuple[str, ...]:
        """Plugins loaded into this registry, in loading order (recorded in the manifest)."""
        return tuple(self._entries.plugins)

    # ----------------------------------------------------------------- creation

    def create[P](self, point: ExtensionPoint[P], selection: ComponentParameters) -> P:
        """Build the component selected in a validated configuration.

        Parameters
        ----------
        point : ExtensionPoint[P]
            Extension point of the component.
        selection : ComponentParameters
            Value of a component slot of a validated configuration: the parameters of the
            selected component, which also carry its name (``selection.type``).

        Returns
        -------
        P
            The component.

        Raises
        ------
        TypeError
            If ``selection`` does not come from a validated configuration, or if the
            factory returns an object that does not satisfy the protocol.
        """
        name = getattr(selection, RESERVED_COMPONENT_KEY, None)
        if not isinstance(name, str):
            raise TypeError(
                f"Expected the value of a {point.name} slot of a validated configuration, "
                f"got {selection!r}."
            )
        component = self.component(point, name)
        if not isinstance(selection, component.parameters):
            raise TypeError(
                f"The parameters of {point.name} {name!r} must be "
                f"{component.parameters.__qualname__}, got {type(selection).__qualname__}."
            )
        instance = component.factory(selection)
        if not isinstance(instance, point.protocol):
            raise TypeError(
                f"{point.name} {name!r}: the factory returned {type(instance).__qualname__}, "
                f"which does not implement {point.protocol.__qualname__}."
            )
        return cast("P", instance)

    # ----------------------------------------------------------------- plugins

    def copy(self) -> Registry:
        """Return an independent copy (the registered objects themselves are shared)."""
        duplicate = Registry()
        duplicate._entries = self._entries.copy()
        return duplicate

    def load_plugin(self, reference: str, *, base_dir: Path | None = None) -> None:
        """Load a local plugin and let it register its extensions.

        Parameters
        ----------
        reference : str
            Either an importable module name (``my_project.rules``) or the path of a Python
            file ending in ``.py``, relative to ``base_dir``.
        base_dir : Path, optional
            Directory of relative file paths (usually that of the configuration file);
            defaults to the current directory.

        Raises
        ------
        PluginError
            If the plugin cannot be imported, has no ``register`` function, or its
            ``register`` function fails. The registry is then left unchanged.
        """
        if not isinstance(reference, str) or not reference.strip():
            raise PluginError(f"A plugin reference must be a non-empty text, got {reference!r}.")
        source = f"plugin {reference!r}"
        if reference.endswith(".py"):
            module = _import_file(Path(base_dir or Path.cwd()) / reference, reference)
        else:
            try:
                module = importlib.import_module(reference)
            except Exception as error:
                raise PluginError(
                    f"Cannot import plugin module {reference!r}: {type(error).__name__}: {error}"
                ) from error
        register = getattr(module, "register", None)
        if not callable(register):
            raise PluginError(f"Plugin {reference!r} has no function register(registry) to call.")
        self._run_register(register, source=source, record=reference)

    def load_entry_points(self, group: str) -> None:
        """Load every installed plugin advertised in the entry-point group ``group``.

        Each entry point must refer to a function ``register(registry)``. Entry points are
        loaded in order of name, so that the result does not depend on installation order.

        Raises
        ------
        PluginError
            If an entry point cannot be loaded or its function fails. Plugins loaded before
            it are kept.
        """
        for point in sorted(entry_points(group=group), key=lambda item: item.name):
            self._load_entry_point(point)

    def _load_entry_point(self, point: EntryPoint) -> None:
        source = f"entry point {point.name!r} ({point.value})"
        try:
            register = point.load()
        except Exception as error:
            raise PluginError(f"Cannot load {source}: {type(error).__name__}: {error}") from error
        if not callable(register):
            raise PluginError(f"{source} does not refer to a function register(registry).")
        self._run_register(register, source=source, record=f"{point.name}={point.value}")

    def _run_register(self, register: Callable[..., object], *, source: str, record: str) -> None:
        """Call a plugin's ``register`` on a copy, and keep the result only if it succeeds."""
        trial = _SourcedRegistry(self.copy(), source)
        try:
            register(trial)
        except Exception as error:
            raise PluginError(
                f"{source[0].upper()}{source[1:]} failed to register its extensions: "
                f"{type(error).__name__}: {error}"
            ) from error
        self._entries = trial.registry._entries
        self._entries.plugins.append(record)

    def _components_of(self, point: ExtensionPoint[Any]) -> dict[str, tuple[Component[Any], str]]:
        declared = self._entries.points.get(point.name)
        if declared is None:
            raise UnknownNameError(
                f"Extension point {point.name!r} is not declared in this registry; "
                f"declared: {_names(self._entries.points)}."
            )
        if declared is not point:
            raise RegistrationError(
                f"Another extension point named {point.name!r} is declared in this registry."
            )
        return self._entries.components[point.name]


class _SourcedRegistry(Registry):
    """View of a registry given to a plugin: every registration records the plugin."""

    def __init__(self, registry: Registry, source: str) -> None:
        super().__init__()
        self.registry = registry
        self._entries = registry._entries
        self._source = source

    def add_extension_point(self, point: ExtensionPoint[Any], *, source: str = "") -> None:
        """Declare an extension point on behalf of the plugin."""
        super().add_extension_point(point, source=source or self._source)

    def register(
        self, point: ExtensionPoint[Any], component: Component[Any], *, source: str = ""
    ) -> None:
        """Register a component on behalf of the plugin."""
        super().register(point, component, source=source or self._source)

    def add_preset(self, preset: Preset, *, source: str = "") -> None:
        """Register a preset on behalf of the plugin."""
        super().add_preset(preset, source=source or self._source)


def _import_file(path: Path, reference: str) -> ModuleType:
    """Import a plugin from a Python file, under a private module name."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise PluginError(f"Plugin file {reference!r} not found (looked for {resolved}).")
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:16]
    module_name = f"_gasp_sim_plugin_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    # Never None for an existing file ending in ".py".
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        del sys.modules[module_name]
        raise PluginError(
            f"Cannot import plugin file {reference!r}: {type(error).__name__}: {error}"
        ) from error
    return module


def _names(mapping: Mapping[str, object]) -> str:
    return ", ".join(sorted(mapping)) or "none"
