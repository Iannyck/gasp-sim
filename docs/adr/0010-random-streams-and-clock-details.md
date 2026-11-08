# ADR-0010: Implementation details of random streams and the clock

- **Status:** Accepted
- **Date:** 2026-11-08
- **Related:** ADR-0002 (random streams), ADR-0003 and ADR-0007 (time model); dev-conventions §4, §5

## Context

ADR-0002 decided one seed per run, derived into named streams with per-agent substreams by
explicit keys. ADR-0003 and ADR-0007 decided a 5-minute global tick, 8-hour working days,
durations expressed in hours, rounding with a warning for durations and refusal for rhythm
periods. Writing the engine modules `gasp_sim.core.rng` and `gasp_sim.core.clock` required
five further choices.

## Decision

1. **Stream names and identifiers are declared by the model, not by the engine.** The
   engine receives a table of `StreamSpec(name, stream_id, scope)`, where `scope` is
   `TEAM` or `AGENT`, and rejects duplicate names or identifiers. Identifiers are
   permanent: changing one changes the draws of published results.
2. **The bit generator is pinned to PCG64DXSM**, instead of relying on the default of
   `numpy.random.default_rng`. Derivation: `SeedSequence(seed, spawn_key=(stream_id,))`
   for a team stream, `SeedSequence(seed, spawn_key=(stream_id, agent_index))` for an
   agent substream, `SeedSequence(seed)` for the single-stream verification mode. A
   regression test pins the first raw outputs of reference streams.
3. **Tick length and working-day length are parameters** (`TimeGrid`, 5 minutes and
   480 minutes by default), validated so that a working day is a whole number of ticks.
4. **Durations are rounded to the nearest tick, halves up**, with a relative tolerance of
   1e-9 so that floating-point noise (0.1 h is not exactly representable) is not reported
   as rounding.
5. **Rounding is reported with Python's `warnings` mechanism**, using a dedicated
   category (`DurationRoundingWarning`). Pytest is configured to turn any unexpected
   warning into a test failure; expected warnings are asserted with `pytest.warns`.

## Facts checked (2026-11-08)

- NumPy documents a statistical weakness of PCG64 when very many parallel streams are
  created by `SeedSequence` spawning: negligible with thousands of streams, "non-negligible,
  if still small" with millions. It recommends PCG64DXSM as "a good, safe upgrade" with the
  same performance and features, and states that PCG64DXSM will eventually become the
  default bit generator of `default_rng`. Source:
  https://numpy.org/devdocs/reference/random/upgrading-pcg64.html
- A run creates about 2 + 3 × 12 = 38 streams; with 10,000 replications, several
  conditions and parameter sweeps, the total exceeds a million streams.

## Alternatives considered

- **Stream names hard-coded in the engine:** simpler, but the engine would no longer be
  generic, and adding a per-agent process would require changing the core.
- **PCG64** (NumPy's current default): adequate for thousands of streams, weaker at the
  scale of our batches.
- **Relying on `default_rng`:** results would change silently if NumPy changes its
  default.
- **Tick and day as constants:** simpler, but prevents the sensitivity analysis on tick
  length planned in the ODD.
- **Python's `round` (round half to even):** 2.5 ticks would become 2, which is surprising.
  **Always rounding down or up:** systematically shortens or lengthens every duration.
- **`logging` for rounding messages:** hard to collect for configuration validation and
  hard to test. **Raising an error:** too strict for durations (ADR-0007 asks for a
  warning); errors are kept for rhythm periods and offsets.

## Consequences

- Draws depend only on the run seed, the stream identifier and the agent index; property
  tests check that they do not depend on other declared streams, team size or request
  order.
- The stream table of the GASP model becomes part of the reproducibility contract and
  needs its own test pinning the identifiers.
- Unexpected warnings from third-party libraries also fail the tests; they must be
  addressed or explicitly filtered in `pyproject.toml`.
