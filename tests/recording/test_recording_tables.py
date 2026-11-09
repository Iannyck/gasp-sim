"""Tests of table declarations, CSV values and files (ADR-0015)."""

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pytest

import gasp_sim.recording.files as files_module
from gasp_sim.api import ObservationTable, Period, SummaryTable
from gasp_sim.recording.files import CsvFile, write_json
from gasp_sim.recording.tables import Column, format_value


@dataclass(frozen=True, slots=True)
class Seen:
    tick: int
    agent: int = field(metadata={"description": "Agent.", "unit": "agent"})
    share: float = field(metadata={"description": "Share."})
    flag: bool = field(metadata={"description": "Flag."})
    label: str | None = field(metadata={"description": "Label."})
    other: Optional[int] = field(metadata={"description": "Other."})  # noqa: UP045


@dataclass(frozen=True, slots=True)
class Row:
    value: float = field(metadata={"description": "Value."})


class Counter:
    def observe(self, observation: object) -> None: ...

    def rows(self, period: Period) -> list[Row]:
        return [Row(1.0)]


# --------------------------------------------------------------------------- values


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (True, "true"),
        (False, "false"),
        (0, "0"),
        (-3, "-3"),
        (0.3, "0.3"),
        (0.1 + 0.2, "0.30000000000000004"),
        (1e-20, "1e-20"),
        (2.0, "2.0"),
        (np.float64(0.25), "0.25"),
        ("a, b", "a, b"),
        (None, ""),
    ],
)
def test_format_value(value: object, text: str) -> None:
    assert format_value(value) == text


@pytest.mark.parametrize(
    ("column_type", "value"),
    [
        ("integer", 3),
        ("number", 3),
        ("number", 0.5),
        ("number", np.float64(0.5)),
        ("boolean", True),
        ("text", "x"),
    ],
)
def test_accepted_values(column_type: Any, value: object) -> None:
    Column("c", column_type, "C.").check(value, "t")


@pytest.mark.parametrize(
    ("column_type", "value"),
    [
        ("integer", True),
        ("integer", 1.0),
        ("integer", np.int64(1)),
        ("number", False),
        ("number", "0.5"),
        ("boolean", 1),
        ("boolean", np.bool_(True)),
        ("text", 3),
    ],
)
def test_refused_types(column_type: Any, value: object) -> None:
    with pytest.raises(TypeError, match=r"t\.c: expected"):
        Column("c", column_type, "C.").check(value, "t")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_numbers_must_be_finite(value: float) -> None:
    with pytest.raises(ValueError, match="not a finite number"):
        Column("c", "number", "C.").check(value, "t")


@pytest.mark.parametrize("value", ["a\rb", "a\x00b"])
def test_text_without_carriage_returns_or_nul(value: str) -> None:
    Column("c", "text", "C.").check("line\nbreak", "t")
    with pytest.raises(ValueError, match="carriage returns or NUL"):
        Column("c", "text", "C.").check(value, "t")


def test_empty_values_only_in_optional_columns() -> None:
    Column("c", "integer", "C.", optional=True).check(None, "t")
    with pytest.raises(ValueError, match="empty value in a required column"):
        Column("c", "integer", "C.").check(None, "t")


# --------------------------------------------------------------------------- declarations


def test_observation_table_columns() -> None:
    table = ObservationTable("seen", Seen, "One row per sighting.")
    assert [column.name for column in table.columns] == [
        "agent",
        "share",
        "flag",
        "label",
        "other",
    ]
    assert table.columns[0].describe() == {
        "name": "agent",
        "type": "integer",
        "unit": "agent",
        "optional": False,
        "description": "Agent.",
    }
    assert [column.type for column in table.columns] == [
        "integer",
        "number",
        "boolean",
        "text",
        "integer",
    ]
    assert [column.optional for column in table.columns] == [False, False, False, True, True]


def test_summary_table_columns() -> None:
    table = SummaryTable("totals", Row, Counter, per="run", description="Totals.")
    assert [column.name for column in table.columns] == ["value"]


@pytest.mark.parametrize("name", ["", "Seen", "1seen", "seen-table", 3])
def test_table_names(name: Any) -> None:
    with pytest.raises(ValueError, match="lowercase"):
        ObservationTable(name, Seen, "x")
    with pytest.raises(ValueError, match="lowercase"):
        SummaryTable(name, Row, Counter, per="run", description="x")


def test_observations_must_be_frozen_dataclasses_with_an_integer_tick() -> None:
    class Plain:
        tick: int

    @dataclass
    class Mutable:
        tick: int

    @dataclass(frozen=True)
    class NoTick:
        agent: int = field(metadata={"description": "Agent."})

    @dataclass(frozen=True)
    class OptionalTick:
        tick: int | None

    @dataclass(frozen=True)
    class TextTick:
        tick: str

    with pytest.raises(TypeError, match="must be a dataclass"):
        ObservationTable("t", Plain, "x")
    with pytest.raises(TypeError, match="must be a frozen dataclass"):
        ObservationTable("t", Mutable, "x")
    for cls in (NoTick, OptionalTick, TextTick):
        with pytest.raises(TypeError, match="needs an integer 'tick' field"):
            ObservationTable("t", cls, "x")


def test_field_declarations_are_checked() -> None:
    @dataclass(frozen=True)
    class NoDescription:
        tick: int
        agent: int

    @dataclass(frozen=True)
    class BlankDescription:
        tick: int
        agent: int = field(metadata={"description": " "})

    @dataclass(frozen=True)
    class Typo:
        tick: int
        agent: int = field(metadata={"descripton": "Agent."})

    @dataclass(frozen=True)
    class BadUnit:
        tick: int
        agent: int = field(metadata={"description": "Agent.", "unit": 3})

    @dataclass(frozen=True)
    class ListField:
        tick: int
        agents: list[int] = field(metadata={"description": "Agents."})

    @dataclass(frozen=True)
    class TwoTypes:
        tick: int
        value: int | str = field(metadata={"description": "Value."})

    @dataclass(frozen=True)
    class TwoTypesOrNone:
        tick: int
        value: int | str | None = field(metadata={"description": "Value."})

    for cls in (NoDescription, BlankDescription):
        with pytest.raises(TypeError, match="a description is required"):
            ObservationTable("t", cls, "x")
    with pytest.raises(TypeError, match=r"unknown metadata \['descripton'\]"):
        ObservationTable("t", Typo, "x")
    with pytest.raises(TypeError, match="the unit must be text"):
        ObservationTable("t", BadUnit, "x")
    for cls in (ListField, TwoTypes, TwoTypesOrNone):
        with pytest.raises(TypeError, match="cannot be written in a table"):
            ObservationTable("t", cls, "x")


def test_summary_table_parameters() -> None:
    with pytest.raises(ValueError, match="per must be 'window' or 'run'"):
        SummaryTable("t", Row, Counter, per="day", description="x")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="aggregator must be callable"):
        SummaryTable("t", Row, Counter(), per="run", description="x")  # type: ignore[arg-type]


def test_period_is_complete_by_default() -> None:
    assert Period(0, 0, 96).complete


# --------------------------------------------------------------------------- files


def test_csv_file_follows_the_format(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "t.csv"
    file = CsvFile(path, ["a", "b", "c", "d"])
    assert path.read_bytes() == b"a,b,c,d\n"
    file.flush()  # nothing pending
    file.add([1, 0.1 + 0.2, True, 'say "hi", then\nleave'])
    file.add([2, None, False, "é"])
    assert file.rows == 2
    assert path.read_bytes() == b"a,b,c,d\n"  # not written before a flush
    file.flush()
    assert path.read_bytes() == (
        b'a,b,c,d\n1,0.30000000000000004,true,"say ""hi"", then\nleave"\n2,,false,\xc3\xa9\n'
    )
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[1][3] == 'say "hi", then\nleave'


def test_csv_files_are_never_overwritten(tmp_path: Path) -> None:
    CsvFile(tmp_path / "t.csv", ["a"])
    with pytest.raises(FileExistsError):
        CsvFile(tmp_path / "t.csv", ["a"])


def test_json_is_replaced_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "manifest.json"
    write_json(path, {"status": "running", "name": "é"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "running", "name": "é"}
    assert path.read_text(encoding="utf-8").endswith("}\n")

    def fail(source: str, target: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(files_module.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        write_json(path, {"status": "completed"})
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "running"
    assert [item.name for item in tmp_path.iterdir()] == ["manifest.json"]


def test_json_refuses_non_finite_numbers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        write_json(tmp_path / "m.json", {"value": math.nan})
