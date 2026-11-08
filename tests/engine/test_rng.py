"""Example-based tests of the named random streams (gasp_sim.core.rng)."""

import numpy as np
import pytest

from gasp_sim.core.rng import (
    BIT_GENERATOR,
    RandomStreams,
    StreamMode,
    StreamScope,
    StreamSpec,
)

SEED = 20261108

SPECS = [
    StreamSpec("init", 0, StreamScope.TEAM),
    StreamSpec("proxy", 1, StreamScope.TEAM),
    StreamSpec("speech", 2, StreamScope.AGENT),
    StreamSpec("tasks", 3, StreamScope.AGENT),
]


def make_streams(seed: int = SEED, mode: StreamMode = StreamMode.NAMED) -> RandomStreams:
    return RandomStreams(seed=seed, specs=SPECS, mode=mode)


def raw(generator: np.random.Generator, n: int = 3) -> list[int]:
    """First raw 64-bit outputs of a generator; stable across NumPy versions."""
    return [int(x) for x in generator.bit_generator.random_raw(n)]


# --------------------------------------------------------------------------- derivation


def test_bit_generator_is_pinned() -> None:
    streams = make_streams()
    assert BIT_GENERATOR == "PCG64DXSM"
    assert streams.bit_generator == "PCG64DXSM"
    assert isinstance(streams.team("init").bit_generator, np.random.PCG64DXSM)


def test_team_stream_derivation_is_documented_one() -> None:
    expected = np.random.Generator(
        np.random.PCG64DXSM(np.random.SeedSequence(SEED, spawn_key=(1,)))
    )
    assert raw(make_streams().team("proxy")) == raw(expected)


def test_agent_stream_derivation_is_documented_one() -> None:
    expected = np.random.Generator(
        np.random.PCG64DXSM(np.random.SeedSequence(SEED, spawn_key=(2, 5)))
    )
    assert raw(make_streams().agent("speech", 5)) == raw(expected)


def test_draws_match_pinned_reference_values() -> None:
    """Guards against any change in the derivation, in SeedSequence or in PCG64DXSM.

    If this test fails, results produced with earlier versions can no longer be
    reproduced: do not update the values without recording the change in an ADR.
    """
    assert raw(make_streams().team("init")) == [
        9385014330978260317,
        11103771711000755436,
        15178288584659874911,
    ]
    assert raw(make_streams().agent("speech", 3)) == [
        13312644661060283468,
        14347537080139399415,
        2198773921418683718,
    ]
    assert raw(make_streams(mode=StreamMode.SINGLE).team("init")) == [
        18307037155449548791,
        704571796665578634,
        18002665333277717887,
    ]


# --------------------------------------------------------------------------- behaviour


def test_same_request_returns_same_generator() -> None:
    streams = make_streams()
    assert streams.team("init") is streams.team("init")
    assert streams.agent("speech", 2) is streams.agent("speech", 2)


def test_successive_requests_continue_the_sequence() -> None:
    streams = make_streams()
    first = raw(streams.team("init"), 2)
    second = raw(streams.team("init"), 2)
    assert first + second == raw(make_streams().team("init"), 4)


def test_distinct_streams_and_agents_get_distinct_draws() -> None:
    streams = make_streams()
    draws = [
        raw(streams.team("init")),
        raw(streams.team("proxy")),
        raw(streams.agent("speech", 0)),
        raw(streams.agent("speech", 1)),
        raw(streams.agent("tasks", 0)),
    ]
    assert len({tuple(d) for d in draws}) == len(draws)


def test_different_seeds_give_different_draws() -> None:
    assert raw(make_streams(seed=1).team("init")) != raw(make_streams(seed=2).team("init"))


def test_single_mode_returns_one_shared_generator() -> None:
    streams = make_streams(mode=StreamMode.SINGLE)
    shared = streams.team("init")
    assert streams.team("proxy") is shared
    assert streams.agent("speech", 0) is shared
    assert streams.agent("tasks", 7) is shared


def test_properties_describe_the_provider() -> None:
    streams = RandomStreams(seed=7, specs=list(reversed(SPECS)))
    assert streams.seed == 7
    assert streams.mode is StreamMode.NAMED
    assert [spec.stream_id for spec in streams.specs] == [0, 1, 2, 3]


def test_numpy_integer_seed_and_index_are_accepted() -> None:
    streams = RandomStreams(seed=np.int64(SEED), specs=SPECS)
    assert raw(streams.agent("speech", np.int64(3))) == raw(make_streams().agent("speech", 3))


# --------------------------------------------------------------------------- errors


@pytest.mark.parametrize("seed", [-1, 1.5, "42", True, None])
def test_invalid_seed_is_rejected(seed: object) -> None:
    with pytest.raises(ValueError, match="Seed"):
        RandomStreams(seed=seed, specs=SPECS)  # type: ignore[arg-type]


def test_invalid_mode_is_rejected() -> None:
    with pytest.raises(TypeError, match="mode"):
        RandomStreams(seed=SEED, specs=SPECS, mode="named")  # type: ignore[arg-type]


def test_duplicate_name_is_rejected() -> None:
    specs = [StreamSpec("init", 0, StreamScope.TEAM), StreamSpec("init", 1, StreamScope.TEAM)]
    with pytest.raises(ValueError, match="Duplicate stream name"):
        RandomStreams(seed=SEED, specs=specs)


def test_duplicate_identifier_is_rejected() -> None:
    specs = [StreamSpec("init", 0, StreamScope.TEAM), StreamSpec("proxy", 0, StreamScope.TEAM)]
    with pytest.raises(ValueError, match="share stream_id 0"):
        RandomStreams(seed=SEED, specs=specs)


def test_unknown_stream_is_rejected_with_the_declared_names() -> None:
    with pytest.raises(ValueError, match=r"Unknown stream 'climate'.*init, proxy"):
        make_streams().team("climate")


def test_scope_mismatch_is_rejected() -> None:
    streams = make_streams()
    with pytest.raises(ValueError, match=r"request it with agent\(\)"):
        streams.team("speech")
    with pytest.raises(ValueError, match=r"request it with team\(\)"):
        streams.agent("init", 0)


@pytest.mark.parametrize("index", [-1, 1.0, True])
def test_invalid_agent_index_is_rejected(index: object) -> None:
    with pytest.raises(ValueError, match="agent_index"):
        make_streams().agent("speech", index)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "stream_id", "scope", "error"),
    [
        ("", 0, StreamScope.TEAM, ValueError),
        ("init", -1, StreamScope.TEAM, ValueError),
        ("init", True, StreamScope.TEAM, ValueError),
        ("init", 0, "team", TypeError),
    ],
)
def test_invalid_spec_is_rejected(
    name: str, stream_id: int, scope: StreamScope, error: type[Exception]
) -> None:
    with pytest.raises(error):
        StreamSpec(name, stream_id, scope)
