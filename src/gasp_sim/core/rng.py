"""Named random streams derived from a single run seed.

Every source of randomness in a run draws from a *named stream*. All streams are derived
from one run seed, so a run is reproducible from that seed. Each stream is keyed by an
explicit integer identifier, so adding a stream or an agent never changes the draws of
the existing streams (ADR-0002, ADR-0010).

The engine does not know which streams exist: the model declares them as a table of
:class:`StreamSpec` and passes it to :class:`RandomStreams`.

Examples
--------
>>> specs = [
...     StreamSpec("init", 0, StreamScope.TEAM),
...     StreamSpec("speech", 2, StreamScope.AGENT),
... ]
>>> streams = RandomStreams(seed=42, specs=specs)
>>> rng = streams.agent("speech", 3)
>>> 0.0 <= float(rng.random()) < 1.0
True
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

__all__ = ["BIT_GENERATOR", "RandomStreams", "StreamMode", "StreamScope", "StreamSpec"]

#: Name of the bit generator used by every stream. It is pinned explicitly, rather than
#: relying on the default of ``numpy.random.default_rng``, so that published results do
#: not change if NumPy changes its default (ADR-0010).
BIT_GENERATOR = "PCG64DXSM"


class StreamScope(enum.Enum):
    """Whether a stream is shared by the team or split into one substream per agent."""

    TEAM = "team"
    AGENT = "agent"


class StreamMode(enum.Enum):
    """How stream names map to generators.

    ``NAMED`` (the default) gives each stream, and each agent substream, its own
    generator. ``SINGLE`` maps every name to one shared generator; it exists only to
    verify that results do not depend on how draws are spread among streams (ADR-0002).
    """

    NAMED = "named"
    SINGLE = "single"


@dataclass(frozen=True, slots=True)
class StreamSpec:
    """Declaration of one named random stream.

    Parameters
    ----------
    name : str
        Name used to request the stream, for example ``"speech"``.
    stream_id : int
        Permanent, non-negative identifier from which the stream's seed is derived. It
        must never change once results have been published, otherwise their draws change.
    scope : StreamScope
        ``StreamScope.TEAM`` for one stream shared by the team, ``StreamScope.AGENT`` for
        one substream per agent.

    Raises
    ------
    ValueError
        If the name is empty or the identifier is not a non-negative integer.
    TypeError
        If ``scope`` is not a :class:`StreamScope`.
    """

    name: str
    stream_id: int
    scope: StreamScope

    def __post_init__(self) -> None:
        """Validate the declaration."""
        name: object = self.name
        if not isinstance(name, str) or not name:
            raise ValueError(f"Stream name must be a non-empty string, got {name!r}.")
        if not _is_non_negative_int(self.stream_id):
            raise ValueError(
                f"Stream {name!r}: stream_id must be a non-negative integer, "
                f"got {self.stream_id!r}."
            )
        scope: object = self.scope
        if not isinstance(scope, StreamScope):
            raise TypeError(f"Stream {name!r}: scope must be a StreamScope, got {scope!r}.")


class RandomStreams:
    """Provider of the named random streams of one run.

    Parameters
    ----------
    seed : int
        Non-negative run seed from which every stream is derived.
    specs : iterable of StreamSpec
        Streams that may be requested. Names and identifiers must be unique.
    mode : StreamMode, optional
        ``StreamMode.NAMED`` (default) or ``StreamMode.SINGLE``.

    Raises
    ------
    ValueError
        If the seed is not a non-negative integer, or if two specs share a name or an
        identifier.
    TypeError
        If ``mode`` is not a :class:`StreamMode`.

    Notes
    -----
    In ``NAMED`` mode, the team stream with identifier ``i`` is seeded with
    ``SeedSequence(seed, spawn_key=(i,))`` and the substream of agent ``a`` with
    ``SeedSequence(seed, spawn_key=(i, a))``. In ``SINGLE`` mode, every request returns
    one generator seeded with ``SeedSequence(seed)``.

    Every generator uses the :data:`BIT_GENERATOR` bit generator. It is created on first
    request and then reused, so successive requests continue the same sequence of draws.
    """

    def __init__(
        self,
        seed: int,
        specs: Iterable[StreamSpec],
        mode: StreamMode = StreamMode.NAMED,
    ) -> None:
        if not _is_non_negative_int(seed):
            raise ValueError(f"Seed must be a non-negative integer, got {seed!r}.")
        mode_value: object = mode
        if not isinstance(mode_value, StreamMode):
            raise TypeError(f"mode must be a StreamMode, got {mode_value!r}.")

        self._seed = int(seed)
        self._mode = mode
        self._specs: dict[str, StreamSpec] = {}
        names_by_id: dict[int, str] = {}
        for spec in specs:
            if spec.name in self._specs:
                raise ValueError(f"Duplicate stream name {spec.name!r}.")
            if spec.stream_id in names_by_id:
                raise ValueError(
                    f"Streams {names_by_id[spec.stream_id]!r} and {spec.name!r} "
                    f"share stream_id {spec.stream_id}."
                )
            self._specs[spec.name] = spec
            names_by_id[spec.stream_id] = spec.name

        self._generators: dict[tuple[int, ...], np.random.Generator] = {}
        self._single: np.random.Generator | None = None

    @property
    def seed(self) -> int:
        """Run seed from which every stream is derived."""
        return self._seed

    @property
    def mode(self) -> StreamMode:
        """Mapping of names to generators (named or single)."""
        return self._mode

    @property
    def bit_generator(self) -> str:
        """Name of the bit generator used by every stream."""
        return BIT_GENERATOR

    @property
    def specs(self) -> tuple[StreamSpec, ...]:
        """Declared streams, ordered by identifier."""
        return tuple(sorted(self._specs.values(), key=lambda spec: spec.stream_id))

    def team(self, name: str) -> np.random.Generator:
        """Return the generator of a team-level stream.

        Parameters
        ----------
        name : str
            Name of a stream declared with ``StreamScope.TEAM``.

        Returns
        -------
        numpy.random.Generator
            The same generator on every call for this name.

        Raises
        ------
        ValueError
            If the stream is not declared, or is declared per agent.
        """
        spec = self._spec(name, StreamScope.TEAM)
        return self._generator((spec.stream_id,))

    def agent(self, name: str, agent_index: int) -> np.random.Generator:
        """Return the generator of one agent's substream.

        Parameters
        ----------
        name : str
            Name of a stream declared with ``StreamScope.AGENT``.
        agent_index : int
            Non-negative index of the agent in the team.

        Returns
        -------
        numpy.random.Generator
            The same generator on every call for this name and agent.

        Raises
        ------
        ValueError
            If the stream is not declared, is declared for the team, or if the agent
            index is not a non-negative integer.
        """
        spec = self._spec(name, StreamScope.AGENT)
        if not _is_non_negative_int(agent_index):
            raise ValueError(f"agent_index must be a non-negative integer, got {agent_index!r}.")
        return self._generator((spec.stream_id, int(agent_index)))

    def _spec(self, name: str, scope: StreamScope) -> StreamSpec:
        """Return the declaration of ``name`` and check that it has the expected scope."""
        try:
            spec = self._specs[name]
        except KeyError:
            declared = ", ".join(sorted(self._specs)) or "none"
            raise ValueError(f"Unknown stream {name!r}. Declared streams: {declared}.") from None
        if spec.scope is not scope:
            method = "agent()" if spec.scope is StreamScope.AGENT else "team()"
            raise ValueError(
                f"Stream {name!r} is declared with scope {spec.scope.value!r}; "
                f"request it with {method}."
            )
        return spec

    def _generator(self, key: tuple[int, ...]) -> np.random.Generator:
        """Return the cached generator for ``key``, creating it on first use."""
        if self._mode is StreamMode.SINGLE:
            if self._single is None:
                self._single = _make_generator(np.random.SeedSequence(self._seed))
            return self._single
        generator = self._generators.get(key)
        if generator is None:
            generator = _make_generator(np.random.SeedSequence(self._seed, spawn_key=key))
            self._generators[key] = generator
        return generator


def _make_generator(seed_sequence: np.random.SeedSequence) -> np.random.Generator:
    """Create a generator using the pinned bit generator."""
    return np.random.Generator(np.random.PCG64DXSM(seed_sequence))


def _is_non_negative_int(value: object) -> bool:
    """Return whether ``value`` is a non-negative integer (booleans excluded)."""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        return False
    return int(value) >= 0
