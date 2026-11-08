# ADR-0001: In-house simulation engine instead of Mesa

- **Status:** Accepted. Open point on the paper's simulator closed on 2026-11-04 (the old code is not used in this project).
- **Date:** 2026-11-03
- **Related:** ODD §3; ADR-0002, ADR-0003

## Context

The simulator needs:

- no spatial dimension; teams of 3 to 12 agents;
- a hybrid time model (regular ticks plus an event queue) with a deterministic, documented processing order;
- strict control of randomness (see ADR-0002);
- long-term reproducibility of published results;
- behaviours selected and parameterised from configuration, so that researchers can change them without coding, and extensions written without touching the core.

Mesa is the reference agent-based modelling framework in Python and was the main alternative.

## Facts checked (2026-11-03)

- Latest stable release on PyPI: Mesa 3.5.2 (October 2026). Mesa 4 is in active development, with pre-releases published. Sources: https://pypi.org/project/Mesa, https://github.com/mesa/mesa
- Since Mesa 3.5, the `Simulator`, `ABMSimulator` and `DEVSimulator` classes are deprecated and will be removed in Mesa 4.0; they are replaced by `Model.run_for()`, `run_until()`, `schedule_event()` and `schedule_recurring()`. Source: https://mesa.readthedocs.io/stable/apis/experimental.html
- Mesa's `EventList` is a heap ordered by time, priority and a unique id, which gives a total ordering. Source: https://mesa.readthedocs.io/stable/apis/time.html
- Mesa models and agents expose both a standard-library `random` generator and a NumPy `rng` generator.
- `batch_run` assumes the model has a `datacollector` attribute; its `iterations` argument is deprecated in favour of `rng`. Source: https://mesa.readthedocs.io/stable/apis/batchrunner.html
- mesa-frames (vectorised Mesa) targets models with very many agents and is not a good fit for strict per-agent sequencing. Source: https://github.com/mesa/mesa-frames

## Decision

Write a small simulation engine for the project, with no dependency on an agent-based modelling framework.

The GASP domain depends only on the engine's public API (phases, events, `step()`), never on its internals, so that a Mesa adapter remains possible later.

## Alternatives considered

**Mesa as the core.** Arguments for:
- event scheduling with total ordering is now part of Mesa's core;
- a seeded NumPy generator is built in;
- visibility and legitimacy in the agent-based modelling community; citable (ter Hoeven et al., 2025, *Journal of Open Source Software*);
- browser-based visualisation (SolaraViz);
- a large community that has already exercised the code;
- an ecosystem that includes Mesa-LLM, a possible future direction (agents producing message content), although its API is still unstable and LLM outputs conflict with strict reproducibility;
- Apache 2.0 licence, compatible with an MIT-licensed project.

Arguments against:
- the API is in transition (deprecations in 3.5, removals planned in 4.0, release date of 4.0 unknown);
- two random generators coexist (standard library and NumPy), which conflicts with the project's randomness rules and is a known source of silent reproducibility bugs;
- the most expensive parts of this project (configuration-driven component selection, extension registry, generated forms, event logs, manifest) are not provided by Mesa; its main strength, space, is not needed;
- coupling the domain model to the framework would expose the model and third-party extensions to every major Mesa migration;
- results could change between Mesa versions without any change to our code (risk, not observed);
- developers used to Mesa expect to subclass `Agent` and override `step()`, which conflicts with the composition-based design chosen here.

**Domain independent of Mesa, with an optional Mesa adapter.** Kept as a future option rather than built now.

**Performance** was considered neutral: the bottleneck is the number of runs, not the number of agents per run, and parallel runs work the same way with or without Mesa.

## Consequences

- The engine must be tested by the project itself: total ordering of events, events scheduled for future ticks, determinism for a given seed.
- Scheduling semantics must be written down in the ODD (§3), since no known framework documents them for us.
- The choice must be justified briefly in the documentation and in publications (non-spatial model, small teams, randomness control, long-term stability).

## Open points

- Unknown whether the simulator used for the IEEE GEM 2026 paper was built with Mesa. If it was, continuity would ease the planned validation comparison. *Closed on 2026-11-04: the old code is not used in this project; validation is against published results only.*

## Revisit when

- Mesa 4 is released as stable and its API has settled; or
- integration with the Mesa ecosystem (e.g. Mesa-LLM, the examples library) becomes a research need; or
- reviewers or the community ask for it. The expected response is an adapter module, not a rewrite.
