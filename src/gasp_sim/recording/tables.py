"""Declarations of output tables and the CSV format of their values (ADR-0015).

A model describes what happens during a run with **observations**: frozen dataclasses that
it publishes on the notification bus (for example "an agent consulted the channel"). Each
observation has a ``tick`` field, and every other field carries a description, and
optionally a unit, in its metadata::

    @dataclass(frozen=True, slots=True)
    class ConsultationObserved:
        tick: int
        agent: int = field(metadata={"description": "Agent number, from 0."})

The model itself does not know about recording: the declarations of this module, written
outside the model, turn observation types into tables (:class:`ObservationTable`) and
attach aggregators to summary tables (:class:`SummaryTable`).

Columns may hold whole numbers, decimal numbers, booleans and text, each possibly empty
(``X | None``). Values are written in CSV without loss: decimal numbers with the shortest
text that gives back exactly the same value, booleans as ``true`` and ``false``, empty
values as empty fields.
"""

from __future__ import annotations

import dataclasses
import math
import re
import types
import typing
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Union, runtime_checkable

__all__ = [
    "Aggregator",
    "Column",
    "ObservationTable",
    "Period",
    "SummaryTable",
    "format_value",
]

_NAME = re.compile(r"[a-z][a-z0-9_]*")
_METADATA_KEYS = frozenset({"description", "unit"})
_TYPES: Mapping[type, str] = {bool: "boolean", int: "integer", float: "number", str: "text"}

type ColumnType = Literal["boolean", "integer", "number", "text"]


@dataclass(frozen=True, slots=True)
class Column:
    """A column of an output table.

    Attributes
    ----------
    name : str
        Column name, as written in the CSV header.
    type : str
        ``"integer"``, ``"number"``, ``"boolean"`` or ``"text"``.
    description : str
        What the column holds, for the manifest (the definition of the measure).
    unit : str or None
        Unit of the values, if any.
    optional : bool
        Whether the column may be empty.
    """

    name: str
    type: ColumnType
    description: str
    unit: str | None = None
    optional: bool = False

    def describe(self) -> dict[str, Any]:
        """Return the description of the column written in the manifest."""
        return {
            "name": self.name,
            "type": self.type,
            "unit": self.unit,
            "optional": self.optional,
            "description": self.description,
        }

    def check(self, value: object, table: str) -> None:
        """Raise if ``value`` cannot be written in this column."""
        if value is None:
            if not self.optional:
                raise ValueError(f"{table}.{self.name}: empty value in a required column.")
            return
        if not _ACCEPTS[self.type](value):
            raise TypeError(
                f"{table}.{self.name}: expected {self.type}, got {type(value).__qualname__} "
                f"({value!r})."
            )
        if self.type == "number" and not math.isfinite(value):  # type: ignore[arg-type]
            raise ValueError(f"{table}.{self.name}: {value!r} is not a finite number.")
        if self.type == "text" and ("\r" in value or "\x00" in value):  # type: ignore[operator]
            # Not read back the same way by every CSV reader (or Python version).
            raise ValueError(
                f"{table}.{self.name}: text may not contain carriage returns or NUL characters."
            )


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# Booleans are never accepted as numbers. Subclasses of float (such as NumPy's float64)
# are accepted as numbers; NumPy integers and booleans are not Python ints and bools, and
# must be converted by the model.
_ACCEPTS: Mapping[str, Callable[[object], bool]] = {
    "boolean": lambda value: isinstance(value, bool),
    "integer": _is_integer,
    "number": lambda value: isinstance(value, float) or _is_integer(value),
    "text": lambda value: isinstance(value, str),
}


def format_value(value: object) -> str:
    """Return the CSV text of a value (empty for ``None``).

    Examples
    --------
    >>> [format_value(v) for v in (True, 3, 0.1 + 0.2, "a", None)]
    ['true', '3', '0.30000000000000004', 'a', '']
    """
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        return repr(float(value))
    if isinstance(value, int):
        return str(int(value))
    return str(value)


@dataclass(frozen=True, slots=True)
class Period:
    """A time window, or the whole run, at the end of which summaries produce rows.

    Attributes
    ----------
    index : int
        Number of the window, from 0 (always 0 for the whole run).
    start_tick : int
        First tick of the period.
    end_tick : int
        Tick after the last tick of the period.
    complete : bool
        False for a last window cut short by the end of the run.
    """

    index: int
    start_tick: int
    end_tick: int
    complete: bool = True


@runtime_checkable
class Aggregator(Protocol):
    """Computes summary rows from observations, during the run (ADR-0015).

    An aggregator receives every observation of the recorded tables, in the order in which
    they are published, and, at the end of each period (a time window, or the whole run,
    depending on its table), returns the rows of that period. It resets its own state
    between periods.
    """

    def observe(self, observation: object) -> None:
        """Take one observation into account."""

    def rows(self, period: Period) -> Iterable[object]:
        """Return the rows of the period that has just ended."""


@dataclass(frozen=True, slots=True)
class ObservationTable:
    """A table with one row per observation of a given type.

    Parameters
    ----------
    name : str
        Table name; the file is ``tables/<name>.csv``.
    observation : type
        Frozen dataclass published by the model. It must have an integer ``tick`` field;
        every other field needs a ``description`` (and may have a ``unit``) in its
        metadata.
    description : str
        What one row represents.

    Notes
    -----
    The recorder adds the columns ``run_id``, ``tick``, ``day`` and ``minutes`` (working
    minutes since the start of the day) before the fields of the observation.
    """

    name: str
    observation: type
    description: str
    columns: tuple[Column, ...] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """Check the declaration and derive the columns."""
        _check_name(self.name)
        fields = _dataclass_columns(self.observation, f"observation {self.name!r}")
        tick = next((column for column in fields if column.name == "tick"), None)
        if tick is None or tick.type != "integer" or tick.optional:
            raise TypeError(
                f"Observation {self.observation.__qualname__} needs an integer 'tick' field."
            )
        object.__setattr__(
            self, "columns", tuple(column for column in fields if column.name != "tick")
        )


@dataclass(frozen=True, slots=True)
class SummaryTable:
    """A table of summary rows computed by an aggregator.

    Parameters
    ----------
    name : str
        Table name; the file is ``summary/<name>.csv``.
    row : type
        Frozen dataclass of the rows; every field needs a ``description`` in its metadata.
    aggregator : callable
        Called once per run, without arguments, to create the aggregator.
    per : {"window", "run"}
        Whether rows are produced at the end of every time window or once per run.
    description : str
        What one row represents.

    Notes
    -----
    The recorder adds the column ``run_id``, and for window tables the columns ``window``,
    ``start_tick``, ``end_tick``, ``start_day`` and ``complete``.
    """

    name: str
    row: type
    aggregator: Callable[[], Aggregator]
    per: Literal["window", "run"]
    description: str
    columns: tuple[Column, ...] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """Check the declaration and derive the columns."""
        _check_name(self.name)
        if self.per not in ("window", "run"):
            raise ValueError(f"Summary table {self.name!r}: per must be 'window' or 'run'.")
        if not callable(self.aggregator):
            raise TypeError(f"Summary table {self.name!r}: aggregator must be callable.")
        object.__setattr__(
            self, "columns", _dataclass_columns(self.row, f"summary table {self.name!r}")
        )


def _check_name(name: object) -> None:
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError(
            "Table names must be lowercase letters, digits and underscores, starting with a "
            f"letter; got {name!r}."
        )


def _dataclass_columns(cls: object, what: str) -> tuple[Column, ...]:
    """Derive columns from the fields of a frozen dataclass."""
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise TypeError(f"The {what} must be a dataclass, got {cls!r}.")
    if not cls.__dataclass_params__.frozen:  # type: ignore[attr-defined]
        raise TypeError(f"The {what} must be a frozen dataclass.")
    hints = typing.get_type_hints(cls)
    columns = []
    for field in dataclasses.fields(cls):
        column_type, optional = _column_type(hints[field.name], f"{what}, field {field.name!r}")
        metadata = dict(field.metadata)
        unknown = set(metadata) - _METADATA_KEYS
        if unknown:
            raise TypeError(
                f"The {what}, field {field.name!r}: unknown metadata {sorted(unknown)}; "
                f"allowed: {sorted(_METADATA_KEYS)}."
            )
        description = metadata.get("description")
        if field.name != "tick" and not (isinstance(description, str) and description.strip()):
            raise TypeError(f"The {what}, field {field.name!r}: a description is required.")
        unit = metadata.get("unit")
        if unit is not None and not isinstance(unit, str):
            raise TypeError(f"The {what}, field {field.name!r}: the unit must be text.")
        columns.append(
            Column(
                name=field.name,
                type=column_type,
                description=description or "Tick of the observation.",
                unit=unit,
                optional=optional,
            )
        )
    return tuple(columns)


def _column_type(annotation: object, where: str) -> tuple[ColumnType, bool]:
    """Return the column type of an annotation and whether it may be empty."""
    optional = False
    if typing.get_origin(annotation) in (Union, types.UnionType):
        members = [item for item in typing.get_args(annotation) if item is not type(None)]
        if len(members) == 1 and len(typing.get_args(annotation)) == 2:
            annotation, optional = members[0], True
    if isinstance(annotation, type) and annotation in _TYPES:
        return typing.cast("ColumnType", _TYPES[annotation]), optional
    raise TypeError(
        f"The {where}: type {annotation!r} cannot be written in a table; use int, float, "
        "bool or str, possibly with '| None'."
    )
