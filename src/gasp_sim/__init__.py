"""gasp-sim: agent-based simulator of the spiral of silence in remote Agile teams.

The simulator tests whether a gamified affective social proxy (GASP, a virtual pet)
can break the spiral of silence. The model is described with the ODD protocol, and
structural decisions are recorded as Architecture Decision Records (ADRs) in the
documentation.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gasp-sim")
except PackageNotFoundError:  # pragma: no cover - only when the package is not installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
