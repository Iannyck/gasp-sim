"""Tests of the registry of extension points, components and presets (ADR-0014)."""

import sys
import textwrap
from collections.abc import Iterator
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pytest
from pydantic import Field

import gasp_sim.registry as registry_module
from gasp_sim.api import (
    Component,
    ComponentParameters,
    ExtensionPoint,
    PluginError,
    PluginRecord,
    Preset,
    RegistrationError,
    Registry,
    UnknownNameError,
)

# --------------------------------------------------------------------------- fixtures


@runtime_checkable
class Greeter(Protocol):
    def greet(self) -> str: ...


class HelloParameters(ComponentParameters):
    """Say hello.

    More details on a second line.
    """

    name: str = "world"


class Hello:
    def __init__(self, parameters: HelloParameters) -> None:
        self.name = parameters.name

    def greet(self) -> str:
        return f"hello {self.name}"


class Mute:
    """Does not implement Greeter."""

    def __init__(self, parameters: HelloParameters) -> None: ...


GREETER: ExtensionPoint[Greeter] = ExtensionPoint("greeter", Greeter, summary="Greets.")
HELLO = Component("hello", HelloParameters, Hello)


def make_registry() -> Registry:
    registry = Registry()
    registry.add_extension_point(GREETER)
    registry.register(GREETER, HELLO)
    return registry


class Selected(HelloParameters):
    """Stands for the value of a slot of a validated configuration."""

    type: str = "hello"


@pytest.fixture
def plugin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A directory on sys.path for plugin modules written by the tests."""
    monkeypatch.syspath_prepend(str(tmp_path))
    before = set(sys.modules)
    yield tmp_path
    for name in set(sys.modules) - before:
        del sys.modules[name]


def write_plugin(directory: Path, name: str, body: str) -> Path:
    path = directory / f"{name}.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


PLUGIN = """
    from pydantic import Field
    from gasp_sim.api import Component, ComponentParameters, Preset


    class LoudParameters(ComponentParameters):
        '''Shout.'''

        volume: int = Field(default=3, ge=1)


    class Loud:
        def __init__(self, parameters: LoudParameters) -> None:
            self.volume = parameters.volume

        def greet(self) -> str:
            return "HELLO" + "!" * self.volume


    def register(registry):
        greeter = registry.extension_point("greeter")
        registry.register(greeter, Component("loud", LoudParameters, Loud))
        registry.add_preset(Preset("shouting", {"greeter": {"type": "loud"}}))
"""


# --------------------------------------------------------------------------- declarations


def test_extension_point_requires_a_runtime_checkable_protocol() -> None:
    class Plain(Protocol):
        def greet(self) -> str: ...

    with pytest.raises(TypeError, match="runtime_checkable"):
        ExtensionPoint("plain", Plain)
    with pytest.raises(TypeError, match="runtime_checkable"):
        ExtensionPoint("not_a_protocol", Hello)


def test_extension_point_protocol_must_declare_methods_only() -> None:
    @runtime_checkable
    class WithData(Protocol):
        size: int

    with pytest.raises(TypeError, match="methods only"):
        ExtensionPoint("with_data", WithData)


@pytest.mark.parametrize("name", ["", "Greeter", "1greeter", "greeter-2", "greeter name", 3])
def test_names_must_be_lowercase_identifiers(name: Any) -> None:
    with pytest.raises(ValueError, match="lowercase"):
        ExtensionPoint(name, Greeter)
    with pytest.raises(ValueError, match="lowercase"):
        Component(name, HelloParameters, Hello)
    with pytest.raises(ValueError, match="lowercase"):
        Preset(name, {})


def test_component_parameters_must_be_component_parameters() -> None:
    with pytest.raises(TypeError, match="ComponentParameters"):
        Component("hello", dict, Hello)  # type: ignore[type-var]


def test_component_cannot_have_a_parameter_named_type() -> None:
    class Typed(ComponentParameters):
        type: str = "x"

    with pytest.raises(TypeError, match="reserved"):
        Component("typed", Typed, Hello)


def test_component_factory_must_be_callable() -> None:
    with pytest.raises(TypeError, match="callable"):
        Component("hello", HelloParameters, "Hello")  # type: ignore[arg-type]


def test_component_summary_defaults_to_the_first_docstring_line() -> None:
    assert HELLO.summary == "Say hello."
    assert Component("hello", HelloParameters, Hello, summary="Hi.").summary == "Hi."


def test_preset_values_must_be_a_mapping_without_preset_or_plugins() -> None:
    with pytest.raises(TypeError, match="mapping"):
        Preset("bad", [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="preset"):
        Preset("bad", {"preset": "other"})
    with pytest.raises(ValueError, match="plugins"):
        Preset("bad", {"plugins": ["x"]})


# --------------------------------------------------------------------------- registration


def test_registration_and_queries() -> None:
    registry = make_registry()
    registry.add_preset(Preset("friendly", {"greeter": {"type": "hello"}}))
    assert registry.extension_points == (GREETER,)
    assert registry.extension_point("greeter") is GREETER
    assert registry.component_names(GREETER) == ("hello",)
    assert registry.component(GREETER, "hello") is HELLO
    assert registry.component_source(GREETER, "hello") == "built-in"
    assert [preset.name for preset in registry.presets] == ["friendly"]
    assert registry.preset("friendly").values == {"greeter": {"type": "hello"}}
    assert registry.plugins == ()


def test_wrong_kinds_of_objects_are_refused() -> None:
    registry = make_registry()
    with pytest.raises(TypeError, match="ExtensionPoint"):
        registry.add_extension_point("greeter")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Component"):
        registry.register(GREETER, "hello")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Preset"):
        registry.add_preset("friendly")  # type: ignore[arg-type]


def test_name_collisions_are_errors_naming_both_sources() -> None:
    registry = make_registry()
    with pytest.raises(RegistrationError, match=r"already declared \(built-in\).*\(mine\)"):
        registry.add_extension_point(GREETER, source="mine")
    with pytest.raises(RegistrationError, match=r"'hello' is already registered \(built-in\)"):
        registry.register(GREETER, Component("hello", HelloParameters, Hello), source="mine")
    registry.add_preset(Preset("friendly", {}))
    with pytest.raises(RegistrationError, match="Preset 'friendly' is already registered"):
        registry.add_preset(Preset("friendly", {}), source="mine")


def test_component_classes_are_checked_against_the_protocol_at_registration() -> None:
    registry = make_registry()
    with pytest.raises(RegistrationError, match="Mute does not implement Greeter"):
        registry.register(GREETER, Component("mute", HelloParameters, Mute))


def test_unknown_names_list_the_alternatives() -> None:
    registry = make_registry()
    with pytest.raises(UnknownNameError, match="Unknown greeter 'helo'; available: hello"):
        registry.component(GREETER, "helo")
    with pytest.raises(UnknownNameError, match="Unknown preset 'x'; available: none"):
        registry.preset("x")
    with pytest.raises(UnknownNameError, match="declared: greeter"):
        registry.extension_point("speaker")


def test_extension_points_must_be_declared_in_the_registry() -> None:
    registry = Registry()
    with pytest.raises(UnknownNameError, match="not declared"):
        registry.register(GREETER, HELLO)
    registry.add_extension_point(ExtensionPoint("greeter", Greeter))
    with pytest.raises(RegistrationError, match="Another extension point"):
        registry.register(GREETER, HELLO)


def test_unknown_name_error_is_a_lookup_error() -> None:
    assert issubclass(UnknownNameError, LookupError)


# --------------------------------------------------------------------------- creation


def test_create_builds_the_selected_component() -> None:
    greeter = make_registry().create(GREETER, Selected(name="you"))
    assert greeter.greet() == "hello you"


def test_create_requires_a_selection_from_a_validated_configuration() -> None:
    registry = make_registry()
    with pytest.raises(TypeError, match="validated configuration"):
        registry.create(GREETER, HelloParameters())

    class OtherSelected(ComponentParameters):
        type: str = "hello"

    with pytest.raises(TypeError, match="must be HelloParameters"):
        registry.create(GREETER, OtherSelected())


def test_create_checks_what_a_factory_function_returns() -> None:
    registry = make_registry()
    registry.register(GREETER, Component("broken", HelloParameters, lambda parameters: 42))

    class Broken(HelloParameters):
        type: str = "broken"

    with pytest.raises(TypeError, match="returned int, which does not implement Greeter"):
        registry.create(GREETER, Broken())


# --------------------------------------------------------------------------- copies, plugins


def test_copies_are_independent() -> None:
    registry = make_registry()
    duplicate = registry.copy()
    duplicate.register(GREETER, Component("other", HelloParameters, Hello))
    duplicate.add_preset(Preset("friendly", {}))
    assert registry.component_names(GREETER) == ("hello",)
    assert registry.presets == ()
    assert duplicate.component_names(GREETER) == ("hello", "other")


def test_plugin_module_registers_with_its_own_source(plugin_dir: Path) -> None:
    write_plugin(plugin_dir, "loud_plugin", PLUGIN)
    registry = make_registry()
    registry.load_plugin("loud_plugin")
    assert registry.component_names(GREETER) == ("hello", "loud")
    assert registry.component_source(GREETER, "loud") == "plugin 'loud_plugin'"
    assert registry.preset("shouting").name == "shouting"
    assert registry.plugins == (PluginRecord("loud_plugin", "module"),)


def test_plugin_file_relative_to_a_directory(plugin_dir: Path) -> None:
    subdirectory = plugin_dir / "config"
    subdirectory.mkdir()
    write_plugin(plugin_dir, "loud_file", PLUGIN)
    registry = make_registry()
    registry.load_plugin("../loud_file.py", base_dir=subdirectory)
    assert "loud" in registry.component_names(GREETER)
    assert registry.plugins == (PluginRecord("../loud_file.py", "file"),)


def test_plugin_file_relative_to_the_current_directory(
    plugin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_plugin(plugin_dir, "loud_here", PLUGIN)
    monkeypatch.chdir(plugin_dir)
    registry = make_registry()
    registry.load_plugin("loud_here.py")
    assert "loud" in registry.component_names(GREETER)


def test_plugin_can_declare_extension_points(plugin_dir: Path) -> None:
    write_plugin(
        plugin_dir,
        "new_point",
        """
        from typing import Protocol, runtime_checkable
        from gasp_sim.api import ExtensionPoint

        @runtime_checkable
        class Farewell(Protocol):
            def bye(self) -> str: ...

        def register(registry):
            registry.add_extension_point(ExtensionPoint("farewell", Farewell))
        """,
    )
    registry = make_registry()
    registry.load_plugin("new_point")
    assert [point.name for point in registry.extension_points] == ["farewell", "greeter"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("raise RuntimeError('boom')", "Cannot import plugin module 'bad_plugin': RuntimeError"),
        ("register = 3", "has no function register"),
        (
            "def register(registry):\n    raise ValueError('nope')",
            "Plugin 'bad_plugin' failed to register its extensions: ValueError: nope",
        ),
    ],
)
def test_broken_plugin_modules(plugin_dir: Path, body: str, message: str) -> None:
    write_plugin(plugin_dir, "bad_plugin", body)
    with pytest.raises(PluginError, match=message):
        make_registry().load_plugin("bad_plugin")


def test_broken_plugin_files(plugin_dir: Path) -> None:
    write_plugin(plugin_dir, "bad_file", "raise RuntimeError('boom')")
    with pytest.raises(
        PluginError, match=r"Cannot import plugin file 'bad_file\.py': RuntimeError"
    ):
        make_registry().load_plugin("bad_file.py", base_dir=plugin_dir)
    with pytest.raises(PluginError, match=r"Plugin file 'missing\.py' not found"):
        make_registry().load_plugin("missing.py", base_dir=plugin_dir)


@pytest.mark.parametrize("reference", ["", "   ", 3])
def test_plugin_reference_must_be_text(reference: Any) -> None:
    with pytest.raises(PluginError, match="non-empty text"):
        make_registry().load_plugin(reference)


def test_a_failing_plugin_leaves_the_registry_unchanged(plugin_dir: Path) -> None:
    write_plugin(
        plugin_dir,
        "half_plugin",
        """
        from gasp_sim.api import Preset

        def register(registry):
            registry.add_preset(Preset("half", {}))
            greeter = registry.extension_point("greeter")
            registry.register(greeter, registry.component(greeter, "hello"))  # collision
        """,
    )
    registry = make_registry()
    with pytest.raises(PluginError, match="already registered"):
        registry.load_plugin("half_plugin")
    assert registry.presets == ()
    assert registry.plugins == ()


def test_loading_the_same_plugin_twice_is_a_collision(plugin_dir: Path) -> None:
    write_plugin(plugin_dir, "loud_twice", PLUGIN)
    registry = make_registry()
    registry.load_plugin("loud_twice")
    with pytest.raises(PluginError, match=r"'loud' is already registered \(plugin 'loud_twice'\)"):
        registry.load_plugin("loud_twice")


# --------------------------------------------------------------------------- entry points


def fake_entry_points(monkeypatch: pytest.MonkeyPatch, points: list[EntryPoint]) -> None:
    def select(*, group: str) -> list[EntryPoint]:
        return [point for point in points if point.group == group]

    monkeypatch.setattr(registry_module, "entry_points", select)


def test_entry_points_are_loaded_in_order_of_name(
    plugin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_plugin(plugin_dir, "zz_loud_entry", PLUGIN)
    write_plugin(
        plugin_dir,
        "aa_order_entry",
        """
        from gasp_sim.api import Preset

        def register(registry):
            # Needs the "shouting" preset of the other plugin to have been loaded first.
            registry.preset("shouting")
            registry.add_preset(Preset("after", {}))
        """,
    )
    fake_entry_points(
        monkeypatch,
        [
            EntryPoint("b_order", "aa_order_entry:register", "gasp_sim.test"),
            EntryPoint("a_loud", "zz_loud_entry:register", "gasp_sim.test"),
            EntryPoint("ignored", "nowhere:register", "other.group"),
        ],
    )
    registry = make_registry()
    registry.load_entry_points("gasp_sim.test")
    assert registry.component_source(GREETER, "loud") == (
        "entry point 'a_loud' (zz_loud_entry:register)"
    )
    assert registry.plugins == (
        PluginRecord("a_loud=zz_loud_entry:register", "entry_point"),
        PluginRecord("b_order=aa_order_entry:register", "entry_point"),
    )


def test_broken_entry_points(plugin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_plugin(plugin_dir, "value_entry", "register = 3")
    fake_entry_points(monkeypatch, [EntryPoint("missing", "nowhere:register", "gasp_sim.test")])
    with pytest.raises(PluginError, match="Cannot load entry point 'missing'"):
        make_registry().load_entry_points("gasp_sim.test")
    fake_entry_points(monkeypatch, [EntryPoint("value", "value_entry:register", "gasp_sim.test")])
    with pytest.raises(PluginError, match="does not refer to a function"):
        make_registry().load_entry_points("gasp_sim.test")


class FakeDistribution:
    """Stands for an installed package (importlib.metadata.Distribution)."""

    name = "gasp-sim-loud"
    version = "1.2.0"


def test_entry_points_record_their_package_and_version(
    plugin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_plugin(plugin_dir, "loud_packaged", PLUGIN)
    point = EntryPoint("loud", "loud_packaged:register", "gasp_sim.test")
    vars(point).update(dist=FakeDistribution())  # as importlib.metadata does
    fake_entry_points(monkeypatch, [point])
    registry = make_registry()
    registry.load_entry_points("gasp_sim.test")
    assert registry.plugins == (
        PluginRecord("loud=loud_packaged:register", "entry_point", "gasp-sim-loud", "1.2.0"),
    )
    assert registry.plugins[0].describe() == {
        "reference": "loud=loud_packaged:register",
        "kind": "entry_point",
        "distribution": "gasp-sim-loud",
        "version": "1.2.0",
    }


@pytest.mark.parametrize(
    ("providers", "versions", "expected"),
    [
        ({"loud_pkg": ["gasp-sim-loud"]}, {"gasp-sim-loud": "2.0"}, ("gasp-sim-loud", "2.0")),
        (
            {"loud_pkg": ["gasp-sim-loud", "gasp-sim-loud"]},
            {"gasp-sim-loud": "2.0"},
            ("gasp-sim-loud", "2.0"),
        ),
        ({"loud_pkg": ["one", "two"]}, {}, (None, None)),
        ({}, {}, (None, None)),
        ({"loud_pkg": ["gone"]}, {}, ("gone", None)),
    ],
)
def test_plugin_modules_record_the_package_that_provides_them(
    plugin_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    providers: dict[str, list[str]],
    versions: dict[str, str],
    expected: tuple[str | None, str | None],
) -> None:
    package = plugin_dir / "loud_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    write_plugin(package, "rules", PLUGIN)

    def version(name: str) -> str:
        try:
            return versions[name]
        except KeyError:
            raise registry_module.PackageNotFoundError(name) from None

    monkeypatch.setattr(registry_module, "packages_distributions", lambda: providers)
    monkeypatch.setattr(registry_module, "version", version)
    registry = make_registry()
    registry.load_plugin("loud_pkg.rules")
    assert registry.plugins == (PluginRecord("loud_pkg.rules", "module", *expected),)


def test_component_parameters_validate_strictly() -> None:
    class Bounded(ComponentParameters):
        level: int = Field(default=1, ge=0)

    assert Bounded.model_validate({"level": 2}).level == 2
    with pytest.raises(ValueError, match="valid integer"):
        Bounded.model_validate({"level": "2"})
