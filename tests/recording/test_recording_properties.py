"""Property-based tests of the CSV values (ADR-0015)."""

import csv
import io

from hypothesis import given
from hypothesis import strategies as st

from gasp_sim.recording.tables import format_value


@given(value=st.floats(allow_nan=False, allow_infinity=False))
def test_numbers_are_written_without_loss(value: float) -> None:
    assert float(format_value(value)) == value


@given(value=st.integers(min_value=-(2**70), max_value=2**70))
def test_whole_numbers_are_written_exactly(value: int) -> None:
    assert int(format_value(value)) == value


@given(values=st.lists(st.text(st.characters(exclude_characters="\r\x00")), min_size=1, max_size=5))
def test_any_text_reads_back_from_the_csv(values: list[str]) -> None:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerow([format_value(value) for value in values])
    stream.seek(0)
    assert next(csv.reader(stream)) == values
