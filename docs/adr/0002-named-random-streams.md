# ADR-0002: One seed per run, derived into named streams with per-agent substreams

- **Status:** Accepted (supersedes the earlier rule "a single generator per run")
- **Date:** 2026-11-03
- **Related:** ODD §4 (stochasticity), §9; ADR-0003, ADR-0004

## Context

Every run must be reproducible from its seed. Both a single random stream and several derived streams satisfy that.

The research questions, however, are comparisons between configurations: control versus GASP, with or without the task module, effects by personality profile. With a single stream shared by all modules, any module that consumes draws in one condition and not in the other shifts every later draw. Example: with the task module on, failure draws at tick 1 shift the speech draws used at tick 2, so the same speaking decision is made with different random numbers in the two conditions. Part of the measured difference is then luck rather than the mechanism under study.

With per-agent work rhythms (ADR-0003), the number of speech decisions also depends on the number of consultations, which can vary between agents.

## Decision

1. **One seed per run**, derived into named streams:
   - team-level streams: `init`, `proxy`;
   - per-agent substreams: `speech`, `tasks`, `rhythm`.
2. **Derivation by explicit keys** (integer stream id, agent index), never by order of creation, so that adding a stream or an agent does not shift existing draws. For instance with NumPy: `SeedSequence(entropy=run_seed, spawn_key=(stream_id, agent_index))`. Stream ids are integer constants in the code, never `hash()` of a string, because string hashing is randomised between Python processes.
3. **Modules never receive a generator directly**: they ask a stream provider for their stream by name.
4. **Fixed number of draws** per consultation and per module (e.g. one draw per message type for intention appearance and one for expression, whether the type is eligible or not). A generic test enforces this for every expression policy and extension component.
5. **Stream mode:** `named` by default, the only mode exposed in the user interface and examples; `single` (every name maps to the same generator) as an advanced option used only for verification. The mode is recorded in the run manifest.
6. **Common random numbers:** compared conditions share the seed of each replication.
7. Never the global `random` module nor `np.random.seed`.

## Alternatives considered

- **Single stream** (previous convention): simplest; adequate for reproducing one run; poor for comparisons (see Context); fragile regression tests, since adding one draw anywhere changes everything downstream.
- **Named streams without per-agent substreams:** misaligned as soon as the number of consultations or task events differs between agents or conditions.
- **Sequential spawning** (`spawn()` in order): rejected, because adding a stream later shifts the others.
- **Both modes as equal user-facing choices:** rejected; the mode has no theoretical meaning for researchers and would make results produced months apart non-comparable by accident.

## Consequences

- Paired comparisons with reduced variance at equal numbers of replications.
- A discipline to maintain (fixed draws), documented and tested.
- Slightly more complexity: a stream provider instead of one generator.
- Trajectories still diverge once the proxy changes behaviour; named streams guarantee the same dice, not the same history.
- A verification test: the two modes must give statistically equivalent distributions; a difference reveals code that depends on draw ordering.

## Revisit when

- A new per-agent process is added (it gets its own substream), or the stream granularity proves insufficient.
