r"""Writing of CSV tables and of the JSON manifest (ADR-0015).

CSV files: comma separator, decimal point, UTF-8 without byte-order mark, ``\n`` line
endings on every system, fields quoted only when needed (RFC 4180). Rows are kept in
memory and appended to the file when :meth:`CsvFile.flush` is called.

The manifest is replaced atomically: it is written to a temporary file in the same
directory, then renamed, so that it is never left half-written.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from gasp_sim.recording.tables import format_value

__all__ = ["CsvFile", "write_json"]


class CsvFile:
    """A CSV file written by batches.

    Parameters
    ----------
    path : Path
        File to create; it must not exist yet.
    header : sequence of str
        Column names, written immediately.
    """

    def __init__(self, path: Path, header: Sequence[str]) -> None:
        self.path = path
        self.rows = 0
        self._pending: list[list[str]] = []
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerow(header)

    def add(self, values: Sequence[object]) -> None:
        """Keep one row, to be written at the next flush."""
        self._pending.append([format_value(value) for value in values])
        self.rows += 1

    def flush(self) -> None:
        """Append the pending rows to the file."""
        if not self._pending:
            return
        with self.path.open("a", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(self._pending)
        self._pending.clear()


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Write ``data`` as indented JSON, replacing ``path`` atomically."""
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
