"""Tests of configuration schemas and of the YAML loader (ADR-0014)."""

import textwrap
from pathlib import Path
from typing import Annotated, Any, Protocol, runtime_checkable

import pytest
from pydantic import Field, ValidationError

from gasp_sim.api import (
    Component,
    ComponentParameters,
    ConfigError,
    ConfigIssue,
    ConfigSection,
    ExactHours,
    ExtensionPoint,
    Hours,
    Preset,
    Registry,
    RunSettings,
    Slot,
    StreamMode,
    TimeGrid,
    TimeSettings,
    UnknownNameError,
    bind_schema,
    config_json_schema,
    load_config,
    merge,
    parse_config,
)

# --------------------------------------------------------------------------- test model


@runtime_checkable
class Greeter(Protocol):
    def greet(self) -> str: ...


class HelloParameters(ComponentParameters):
    """Say hello to someone."""

    name: str = "world"


class LoudParameters(ComponentParameters):
    """Shout, then pause."""

    volume: int = Field(default=3, ge=1, le=10)
    pause_hours: Hours = 0.25
    loud: bool = True


class Greeting:
    def __init__(self, text: str) -> None:
        self.text = text

    def greet(self) -> str:
        return self.text


GREETER: ExtensionPoint[Greeter] = ExtensionPoint("greeter", Greeter, summary="Who greets.")


def make_registry() -> Registry:
    registry = Registry()
    registry.add_extension_point(GREETER)
    registry.register(
        GREETER, Component("hello", HelloParameters, lambda p: Greeting(f"hello {p.name}"))
    )
    registry.register(
        GREETER, Component("loud", LoudParameters, lambda p: Greeting("HELLO" + "!" * p.volume))
    )
    registry.add_preset(Preset("shouting", {"greeter": {"type": "loud", "volume": 5}}))
    registry.add_preset(Preset("crowd", {"n_agents": 20, "tags": ["a", "b"]}))
    return registry


class Team(ConfigSection):
    """A nested section with its own slot and duration."""

    leader: Annotated[ComponentParameters, Slot(GREETER, default="hello")]
    meeting_hours: Hours = 1.0


class Settings(RunSettings):
    """Configuration of the test model."""

    n_agents: int = Field(default=5, ge=1)
    period_hours: Annotated[ExactHours, Field(gt=0)] = 0.5
    window_hours: Annotated[Hours, Field(gt=0)] = 1.0
    tags: tuple[str, ...] = ()
    greeter: Annotated[ComponentParameters, Slot(GREETER, default="hello")]
    team: Team = Field(default_factory=lambda: None)  # replaced when the schema is bound


MINIMAL = "seed: 1\ndays: 2\n"


def parse(text: str, registry: Registry | None = None) -> Any:
    return parse_config(
        textwrap.dedent(text), Settings, registry if registry is not None else make_registry()
    )


def errors_of(text: str, registry: Registry | None = None) -> list[str]:
    with pytest.raises(ConfigError) as caught:
        parse(text, registry)
    return [str(issue) for issue in caught.value.errors]


# --------------------------------------------------------------------------- valid files


def test_minimal_file_gets_every_default() -> None:
    loaded = parse(MINIMAL)
    config = loaded.config
    assert isinstance(config, Settings)
    assert (config.seed, config.days, config.n_agents) == (1, 2, 5)
    assert config.stream_mode == "named"
    assert config.random_stream_mode() is StreamMode.NAMED
    assert config.time.grid() == TimeGrid()
    assert config.greeter.model_dump() == {"name": "world", "type": "hello"}
    assert config.team.leader.model_dump() == {"name": "world", "type": "hello"}
    assert loaded.warnings == ()
    assert loaded.origin == "<text>"


def test_components_are_selected_by_type_with_their_parameters_alongside() -> None:
    loaded = parse(
        """
        seed: 1
        days: 2
        greeter:
          type: loud
          volume: 4
        """
    )
    greeter = loaded.registry.create(GREETER, loaded.config.greeter)
    assert greeter.greet() == "HELLO!!!!"
    assert isinstance(loaded.config.greeter, LoudParameters)


def test_whole_numbers_are_accepted_for_decimal_numbers() -> None:
    assert parse(MINIMAL + "period_hours: 1\n").config.period_hours == 1.0


def test_lists_are_read_as_tuples_and_the_configuration_is_frozen() -> None:
    config = parse(MINIMAL + "tags: [a, b]\n").config
    assert config.tags == ("a", "b")
    with pytest.raises(ValidationError, match="frozen"):
        config.n_agents = 3


def test_empty_text_is_an_empty_configuration() -> None:
    assert errors_of("") == [
        "seed: required setting is missing",
        "days: required setting is missing",
    ]


def test_dates_stay_text() -> None:
    assert parse(MINIMAL + "tags: [2026-11-08]\n").config.tags == ("2026-11-08",)


def test_resolved_configuration_loads_back_identically() -> None:
    loaded = parse(MINIMAL + "preset: shouting\ngreeter: {pause_hours: 0.5}\n")
    resolved = loaded.resolved()
    assert list(resolved["greeter"]) == ["type", "volume", "pause_hours", "loud"]
    assert resolved["greeter"] == {"type": "loud", "volume": 5, "pause_hours": 0.5, "loud": True}
    assert list(resolved)[:6] == ["preset", "plugins", "seed", "days", "stream_mode", "time"]
    again = parse(loaded.to_yaml())
    assert again.config == loaded.config
    assert loaded.to_yaml().startswith("# Resolved configuration")


def test_load_config_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "run.yaml"
    path.write_text(MINIMAL, encoding="utf-8")
    loaded = load_config(path, Settings, make_registry())
    assert loaded.origin == str(path)
    assert loaded.config.days == 2


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\(whole file\): cannot read the file"):
        load_config(tmp_path / "missing.yaml", Settings, make_registry())


# --------------------------------------------------------------------------- strict validation


def test_every_error_is_reported_at_once_with_its_location() -> None:
    errors = errors_of(
        """
        seed: "42"
        days: yes
        n_agnets: 4
        period_hours: 0.1
        greeter:
          type: loud
          volume: 11
          volum: 2
        team:
          meeting_hours: 1.03
        """
    )
    assert errors == [
        "seed: must be a whole number; write numbers without quotes (got '42')",
        "days: must be a whole number (got true)",
        "greeter → volume: must be at most 10 (got 11)",
        "greeter → volum: unknown setting; did you mean 'volume'?",
        "n_agnets: unknown setting; did you mean 'n_agents'?",
        "period_hours: must be a whole number of 5-minute ticks (got 0.1)",
    ]


def test_error_report_lists_errors_then_warnings() -> None:
    with pytest.raises(ConfigError) as caught:
        parse(MINIMAL + "period_hours: 0.1\nwindow_hours: 1.03\n")
    error = caught.value
    assert error.origin == "<text>"
    assert [str(issue) for issue in error.warnings] == [
        "window_hours: 1.03 h is not a whole number of 5-minute ticks; rounded to 12 ticks (1 h)"
    ]
    assert str(error) == "\n".join(
        [
            "Invalid configuration <text> (1 error, 1 warning):",
            "  error: period_hours: must be a whole number of 5-minute ticks (got 0.1)",
            "  warning: window_hours: 1.03 h is not a whole number of 5-minute ticks; "
            "rounded to 12 ticks (1 h)",
        ]
    )


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("n_agents: 0", "n_agents: must be at least 1 (got 0)"),
        ("n_agents: 2.0", "n_agents: must be a whole number (got 2.0)"),
        ("window_hours: 0", "window_hours: must be greater than 0 (got 0)"),
        ("window_hours: '1e-3'", "with a decimal point and no quotes, as in 1.0e-3 (got '1e-3')"),
        ("window_hours: abc", "window_hours: must be a number (got 'abc')"),
        ("window_hours: .inf", "window_hours: must be a finite number (got inf)"),
        ("tags: a", "tags: must be a list (got 'a')"),
        ("tags: [1]", "tags → 0: must be text (got 1)"),
        ("tags: [no]", "YAML reads yes/no/on/off as true/false: put the text in quotes"),
        ("stream_mode: shared", "stream_mode: must be one of: 'named' or 'single' (got 'shared')"),
        ("time: 5", "time: must be a group of settings (name: value) (got 5)"),
        ("time: {day_hours: 7.99}", "time → day_hours: must be a whole number of minutes"),
        ("time: {tick_minutes: 7}", "time: the working day (480 min) must be a whole number"),
        ("preset: 3", "preset: must be text (got 3)"),
        ("team: {meeting: 1}", "team → meeting: unknown setting; did you mean 'meeting_hours'?"),
        ("team: {zzz: 1}", "team → zzz: unknown setting"),
        ("greeter: {type: hello, name: [a]}", "greeter → name: must be text (got a list)"),
        ("greeter: {type: hello, name: {a: 1}}", "must be text (got a group of settings)"),
        ("greeter: {type: hello, name: null}", "greeter → name: must be text (got null)"),
    ],
)
def test_readable_messages(line: str, message: str) -> None:
    errors = errors_of(MINIMAL + line + "\n")
    assert any(message in error for error in errors), errors


def test_other_rules_use_the_message_of_pydantic() -> None:
    class Labelled(RunSettings):
        label: str = Field(default="xy", min_length=2)

    with pytest.raises(ConfigError) as caught:
        parse_config(MINIMAL + "label: a\n", Labelled, make_registry())
    assert [str(issue) for issue in caught.value.errors] == [
        "label: string should have at least 2 characters (got 'a')"
    ]


def test_negative_seed_and_no_days() -> None:
    assert errors_of("seed: -1\ndays: 0\n") == [
        "seed: must be at least 0 (got -1)",
        "days: must be at least 1 (got 0)",
    ]


def test_unknown_setting_without_close_match_inside_a_list() -> None:
    class Listed(RunSettings):
        sections: tuple[Team, ...] = ()

    with pytest.raises(ConfigError) as caught:
        parse_config(MINIMAL + "sections: [{zzz: 1}]\n", Listed, make_registry())
    assert "sections → 0 → zzz: unknown setting" in str(caught.value)


def test_component_errors() -> None:
    assert errors_of(MINIMAL + "greeter: {type: shy}\n") == [
        "greeter: unknown greeter 'shy'; available: hello, loud"
    ]
    assert errors_of(MINIMAL + "greeter: {volume: 2}\n") == [
        "greeter: missing 'type': choose a greeter among: hello, loud"
    ]
    assert errors_of(MINIMAL + "greeter: loud\n") == [
        "greeter: must be a group of settings (got 'loud'); to choose this component, write "
        "'type: loud' on the next line, indented"
    ]
    assert errors_of(MINIMAL + "greeter: 3\n") == [
        "greeter: must be a group of settings (name: value) (got 3)"
    ]


def test_parameter_named_like_its_component_keeps_its_location() -> None:
    registry = make_registry()

    class EchoParameters(ComponentParameters):
        echo: int = 1

    registry.register(GREETER, Component("echo", EchoParameters, lambda p: Greeting("echo")))
    assert errors_of(MINIMAL + "greeter: {type: echo, echo: x}\n", registry) == [
        "greeter → echo: must be a whole number (got 'x')"
    ]


def test_nested_slots_are_located() -> None:
    assert errors_of(MINIMAL + "team: {leader: {type: loud, volume: 0}}\n") == [
        "team → leader → volume: must be at least 1 (got 0)"
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("seed: 1\nseed: 2\n", "(whole file): line 2, column 1: 'seed' is set twice"),
        ("seed: 1\n3: x\n", "(whole file): line 2, column 1: setting names must be text, got 3"),
        ("seed: [1\n", "(whole file): line 2, column 1: expected ',' or ']'"),
        ("- 1\n- 2\n", "(whole file): must be a group of settings (name: value), got a list"),
        ("seed: *missing\n", "(whole file): line 1, column 7: found undefined alias"),
        (
            "seed: !!python/name:os.system\n",
            "(whole file): line 1, column 7: could not determine a constructor",
        ),
    ],
)
def test_yaml_problems(text: str, message: str) -> None:
    errors = errors_of(text)
    assert len(errors) == 1
    assert errors[0].startswith(message), errors


def test_yaml_errors_without_location(monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    def fail(*args: object, **kwargs: object) -> None:
        raise yaml.YAMLError("unreadable")

    monkeypatch.setattr(yaml, "load", fail)
    assert errors_of(MINIMAL) == ["(whole file): invalid YAML: unreadable"]

    def fail_marked(*args: object, **kwargs: object) -> None:
        raise yaml.MarkedYAMLError()

    monkeypatch.setattr(yaml, "load", fail_marked)
    assert errors_of(MINIMAL) == ["(whole file): invalid YAML"]


def test_yaml_anchors_and_merge_keys_are_supported() -> None:
    config = parse(
        """
        seed: 1
        days: 2
        greeter: &shared {type: loud, volume: 2}
        team:
          leader:
            <<: *shared
            volume: 4
        """
    ).config
    assert config.greeter.model_dump()["volume"] == 2
    assert config.team.leader.model_dump()["volume"] == 4


# --------------------------------------------------------------------------- durations


def test_rounded_durations_are_warnings() -> None:
    loaded = parse(
        MINIMAL + "window_hours: 1.03\ngreeter: {type: loud, pause_hours: 0.2}\n"
        "team: {meeting_hours: 0.51}\n"
    )
    assert [str(issue) for issue in loaded.warnings] == [
        "window_hours: 1.03 h is not a whole number of 5-minute ticks; rounded to 12 ticks (1 h)",
        "greeter → pause_hours: 0.2 h is not a whole number of 5-minute ticks; rounded to "
        "2 ticks (0.166667 h)",
        "team → meeting_hours: 0.51 h is not a whole number of 5-minute ticks; rounded to "
        "6 ticks (0.5 h)",
    ]


def test_default_durations_are_checked_against_the_configured_grid() -> None:
    errors = errors_of(MINIMAL + "time: {tick_minutes: 20}\n")
    assert errors == ["period_hours: must be a whole number of 20-minute ticks (got 0.5)"]


def test_durations_shorter_than_half_a_tick_are_errors() -> None:
    assert errors_of(MINIMAL + "window_hours: 0.01\n") == [
        "window_hours: is shorter than half a 5-minute tick and would be rounded to 0 (got 0.01)"
    ]


def test_durations_are_checked_even_when_other_settings_are_invalid() -> None:
    errors = errors_of(
        "seed: x\ndays: 1\nperiod_hours: 0.1\nwindow_hours: abc\n"
        "greeter: {type: loud, pause_hours: 0.01, volume: 0}\n"
        "team: {leader: {type: shy}, meeting_hours: 0.01}\n"
    )
    assert "period_hours: must be a whole number of 5-minute ticks (got 0.1)" in errors
    assert any(error.startswith("greeter → pause_hours: is shorter") for error in errors)
    assert any(error.startswith("team → meeting_hours: is shorter") for error in errors)


def test_durations_are_not_checked_when_the_grid_is_invalid() -> None:
    errors = errors_of(MINIMAL + "period_hours: 0.1\ntime: {tick_minutes: 0}\n")
    assert errors == ["time → tick_minutes: must be at least 1 (got 0)"]


# --------------------------------------------------------------------------- presets, plugins


def test_preset_values_are_completed_and_overridden_by_the_file() -> None:
    config = parse(MINIMAL + "preset: shouting\ngreeter: {pause_hours: 0.5}\n").config
    assert config.greeter.model_dump() == {
        "volume": 5,
        "pause_hours": 0.5,
        "loud": True,
        "type": "loud",
    }
    assert config.preset == "shouting"


def test_choosing_another_component_replaces_the_preset_block() -> None:
    config = parse(MINIMAL + "preset: shouting\ngreeter: {type: hello}\n").config
    assert config.greeter.model_dump() == {"name": "world", "type": "hello"}


def test_preset_lists_are_read_like_yaml_lists() -> None:
    assert parse(MINIMAL + "preset: crowd\n").config.tags == ("a", "b")


def test_unknown_preset() -> None:
    assert errors_of(MINIMAL + "preset: whisper\n") == [
        "preset: unknown preset 'whisper'; available: crowd, shouting"
    ]


def test_merge_rules() -> None:
    assert merge({"a": 1, "b": {"c": 2, "d": 3}}, {"b": {"d": 4}, "e": 5}) == {
        "a": 1,
        "b": {"c": 2, "d": 4},
        "e": 5,
    }
    assert merge({"r": {"type": "x", "p": 1}}, {"r": {"type": "x", "q": 2}}) == {
        "r": {"type": "x", "p": 1, "q": 2}
    }
    assert merge({"r": {"type": "x", "p": 1}}, {"r": {"type": "y"}}) == {"r": {"type": "y"}}
    assert merge({"r": {"p": 1}}, {"r": {"type": "y"}}) == {"r": {"type": "y"}}
    assert merge({"r": {"p": 1}}, {"r": 3}) == {"r": 3}


def write(path: Path, text: str) -> Path:
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


PLUGIN = """
    from gasp_sim.api import Component, ComponentParameters


    class ShyParameters(ComponentParameters):
        '''Whisper.'''


    class Shy:
        def __init__(self, parameters):
            pass

        def greet(self):
            return "hi"


    def register(registry):
        registry.register(registry.extension_point("greeter"), Component("shy", ShyParameters, Shy))
"""


def test_local_plugins_are_loaded_into_a_copy_of_the_registry(tmp_path: Path) -> None:
    write(tmp_path / "shy.py", PLUGIN)
    path = write(tmp_path / "run.yaml", MINIMAL + "plugins: [shy.py]\ngreeter: {type: shy}\n")
    registry = make_registry()
    loaded = load_config(path, Settings, registry)
    assert loaded.registry.create(GREETER, loaded.config.greeter).greet() == "hi"
    assert loaded.registry.plugins == ("shy.py",)
    assert loaded.config.plugins == ("shy.py",)
    assert "shy" not in registry.component_names(GREETER)


def test_plugin_errors_are_located(tmp_path: Path) -> None:
    path = write(tmp_path / "run.yaml", MINIMAL + "plugins: [missing.py, no_such_module_xyz]\n")
    with pytest.raises(ConfigError) as caught:
        load_config(path, Settings, make_registry())
    messages = [str(issue) for issue in caught.value.errors]
    assert messages[0].startswith("plugins → 0: plugin file 'missing.py' not found")
    assert messages[1].startswith("plugins → 1: cannot import plugin module 'no_such_module_xyz'")


@pytest.mark.parametrize("value", ["shy.py", "[1]", "{a: b}"])
def test_plugins_must_be_a_list_of_text(value: str) -> None:
    assert errors_of(MINIMAL + f"plugins: {value}\n") == [
        "plugins: must be a list of module names or Python file paths"
    ]


def test_preset_from_a_plugin_is_available(tmp_path: Path) -> None:
    write(
        tmp_path / "presets.py",
        """
        from gasp_sim.api import Preset

        def register(registry):
            registry.add_preset(Preset("large", {"n_agents": 50}))
        """,
    )
    path = write(tmp_path / "run.yaml", MINIMAL + "plugins: [presets.py]\npreset: large\n")
    assert load_config(path, Settings, make_registry()).config.n_agents == 50


# --------------------------------------------------------------------------- schema binding


def test_bound_schema_is_a_subclass_with_the_slots_listed() -> None:
    bound = bind_schema(Settings, make_registry())
    assert issubclass(bound.model, Settings)
    assert set(bound.slots) == {("greeter",), ("team", "leader")}
    assert set(bound.slots[("greeter",)].members) == {"hello", "loud"}
    assert bound.slots[("greeter",)].point is GREETER


def test_schema_without_slots_is_used_as_it_is() -> None:
    class Plain(RunSettings):
        n_agents: int = 1

    assert bind_schema(Plain, make_registry()).model is Plain


def test_required_slot() -> None:
    class Required(RunSettings):
        greeter: Annotated[ComponentParameters, Slot(GREETER)]

    with pytest.raises(ConfigError, match="greeter: required setting is missing"):
        parse_config(MINIMAL, Required, make_registry())


def test_nested_section_with_a_required_slot_is_required() -> None:
    class Inner(ConfigSection):
        greeter: Annotated[ComponentParameters, Slot(GREETER)]

    class Outer(RunSettings):
        inner: Inner
        optional: Inner = Field(default_factory=lambda: None)

    with pytest.raises(ConfigError) as caught:
        parse_config(MINIMAL, Outer, make_registry())
    assert [str(issue) for issue in caught.value.errors] == [
        "inner: required setting is missing",
        "optional: required setting is missing",
    ]


def test_slot_errors_of_the_schema_author() -> None:
    class UnknownDefault(RunSettings):
        greeter: Annotated[ComponentParameters, Slot(GREETER, default="shy")]

    with pytest.raises(UnknownNameError, match="Unknown greeter 'shy'"):
        bind_schema(UnknownDefault, make_registry())

    class NeedsName(ComponentParameters):
        name: str

    registry = Registry()
    registry.add_extension_point(GREETER)
    registry.register(GREETER, Component("named", NeedsName, lambda p: Greeting(p.name)))

    class NoDefaults(RunSettings):
        greeter: Annotated[ComponentParameters, Slot(GREETER, default="named")]

    with pytest.raises(TypeError, match="needs parameters without defaults"):
        bind_schema(NoDefaults, registry)

    empty = Registry()
    empty.add_extension_point(GREETER)
    with pytest.raises(TypeError, match="has no registered component"):
        bind_schema(NoDefaults, empty)


def test_json_schema_describes_every_component() -> None:
    schema = config_json_schema(Settings, make_registry())
    greeter = schema["properties"]["greeter"]
    assert greeter["description"] == "Who greets."
    assert greeter["discriminator"]["propertyName"] == "type"
    assert set(greeter["discriminator"]["mapping"]) == {"hello", "loud"}
    loud = schema["$defs"]["GreeterLoud"]
    assert loud["description"] == "Shout, then pause."
    assert loud["additionalProperties"] is False
    assert loud["properties"]["volume"] == {
        "default": 3,
        "maximum": 10,
        "minimum": 1,
        "title": "Volume",
        "type": "integer",
    }
    assert loud["properties"]["type"]["const"] == "loud"
    assert set(schema["required"]) == {"seed", "days"}


def test_time_settings() -> None:
    assert TimeSettings(tick_minutes=15, day_hours=7.5).grid() == TimeGrid(15, 450)
    with pytest.raises(ValidationError, match="whole number of minutes"):
        TimeSettings(day_hours=7.99)


def test_config_issue_text() -> None:
    assert str(ConfigIssue(("a", 0, "b"), "wrong")) == "a → 0 → b: wrong"
    assert ConfigIssue((), "wrong").location == "(whole file)"
