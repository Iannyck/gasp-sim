"""Property-based tests of the named random streams (ADR-0002).

The key guarantee: the draws of a stream depend only on the run seed, the stream's
identifier and the agent index. They do not depend on which other streams are declared,
on how many agents exist, or on the order in which streams are requested.
"""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from gasp_sim.core.rng import RandomStreams, StreamMode, StreamScope, StreamSpec

seeds = st.integers(min_value=0, max_value=2**64 - 1)

# A table of streams: unique identifiers, each with a scope (True = per agent).
stream_tables = st.lists(
    st.tuples(st.integers(min_value=0, max_value=10**6), st.booleans()),
    min_size=1,
    max_size=8,
    unique_by=lambda entry: entry[0],
)


def build_specs(table: list[tuple[int, bool]]) -> list[StreamSpec]:
    return [
        StreamSpec(f"s{stream_id}", stream_id, StreamScope.AGENT if per_agent else StreamScope.TEAM)
        for stream_id, per_agent in table
    ]


def request(streams: RandomStreams, spec: StreamSpec, agent_index: int) -> np.random.Generator:
    if spec.scope is StreamScope.AGENT:
        return streams.agent(spec.name, agent_index)
    return streams.team(spec.name)


def raw(generator: np.random.Generator, n: int = 4) -> list[int]:
    return [int(x) for x in generator.bit_generator.random_raw(n)]


@given(
    seed=seeds,
    table=stream_tables,
    target_position=st.integers(min_value=0, max_value=7),
    agent_index=st.integers(min_value=0, max_value=11),
    team_size=st.integers(min_value=1, max_value=12),
)
def test_draws_do_not_depend_on_other_streams_or_request_order(
    seed: int,
    table: list[tuple[int, bool]],
    target_position: int,
    agent_index: int,
    team_size: int,
) -> None:
    specs = build_specs(table)
    target = specs[target_position % len(specs)]

    # Reference: the target stream declared alone, requested first.
    alone = RandomStreams(seed=seed, specs=[target])
    expected = raw(request(alone, target, agent_index))

    # Same stream among others, after every other stream (and every other agent's
    # substream) has drawn.
    crowded = RandomStreams(seed=seed, specs=list(reversed(specs)))
    for spec in specs:
        if spec.scope is StreamScope.TEAM:
            if spec != target:
                raw(crowded.team(spec.name), 2)
            continue
        for other_agent in range(team_size):
            if spec == target and other_agent == agent_index:
                continue
            raw(crowded.agent(spec.name, other_agent), 2)
    assert raw(request(crowded, target, agent_index)) == expected


@given(seed=seeds, table=stream_tables, agent_index=st.integers(min_value=0, max_value=11))
def test_same_seed_gives_same_draws(
    seed: int, table: list[tuple[int, bool]], agent_index: int
) -> None:
    specs = build_specs(table)
    first = RandomStreams(seed=seed, specs=specs)
    second = RandomStreams(seed=seed, specs=specs)
    for spec in specs:
        assert raw(request(first, spec, agent_index)) == raw(request(second, spec, agent_index))


@given(
    seed=seeds,
    first_id=st.integers(min_value=0, max_value=10**6),
    second_id=st.integers(min_value=0, max_value=10**6),
)
def test_distinct_identifiers_give_distinct_draws(seed: int, first_id: int, second_id: int) -> None:
    if first_id == second_id:
        second_id += 1
    streams = RandomStreams(
        seed=seed,
        specs=[
            StreamSpec("a", first_id, StreamScope.TEAM),
            StreamSpec("b", second_id, StreamScope.TEAM),
        ],
    )
    assert raw(streams.team("a")) != raw(streams.team("b"))


@given(seed=seeds, table=stream_tables, agent_index=st.integers(min_value=0, max_value=11))
def test_single_mode_shares_one_generator(
    seed: int, table: list[tuple[int, bool]], agent_index: int
) -> None:
    specs = build_specs(table)
    streams = RandomStreams(seed=seed, specs=specs, mode=StreamMode.SINGLE)
    generators = {id(request(streams, spec, agent_index)) for spec in specs}
    assert len(generators) == 1
