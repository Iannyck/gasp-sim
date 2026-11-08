# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Configuration files (`gasp_sim.config`, ADR-0014): YAML files validated strictly
  against a pydantic schema, with every problem listed at once with its location and the
  rule broken (unknown settings with suggestions, no silent conversion, settings written
  twice, durations that are not whole numbers of ticks); rounded durations reported as
  warnings; presets merged with the file; resolved, frozen configuration that loads back
  identically; JSON Schema export including the parameters of every component.
- Registry of extension points, components and presets (`gasp_sim.registry`, ADR-0014),
  filled by built-in code, installed plugins (entry points) and local plugins listed in a
  configuration file; registering a name twice is an error.
- Settings common to every run (`RunSettings`: seed, days, stream mode, time grid,
  preset, plugins) and duration fields `Hours` and `ExactHours`.
- New dependencies: pydantic and PyYAML.
- Toy chatter example: replaceable speaking rule (`constant`, `feedback`), configuration
  schema, preset `no_feedback`, example plugin adding a `threshold` rule, three example
  files, and `run.py` now runs a configuration file (its reference run is unchanged).
- Day-start phases (`Simulation(day_start_phases=...)`): run at the first tick of each
  working day with their own step context, before the events of that tick are released
  (ADR-0013).
- `Simulation.run_days(days)`.
- Example model `examples/toy_chatter` (toy model, no scientific value) written with the
  public API only, with tests and a first check that named and single random-stream
  modes give statistically equivalent results (ADR-0002).
- Engine simulation loop (`gasp_sim.core.simulation`): phases run in order at every
  tick, `DayStarted` published before the events of the first tick of each day,
  `StepCompleted` after each tick, failed simulations cannot be resumed.
- Step context (`gasp_sim.core.context`), phase interface (`gasp_sim.core.phases`) and
  deferred logs (`gasp_sim.core.deferred`) guaranteeing synchronous perception.
- First public API (`gasp_sim.api`) for model and extension developers.
- Engine events (`gasp_sim.core.events`): queue of future events released tick by tick
  in total order (tick, priority, order of scheduling), lazy cancellation by handle, and a
  synchronous notification bus delivering to subscribers in order of subscription.
- Engine random streams (`gasp_sim.core.rng`): named streams derived from one run seed
  by explicit keys, per-agent substreams, pinned PCG64DXSM bit generator, single-stream
  verification mode.
- Engine clock (`gasp_sim.core.clock`): 5-minute ticks and 8-hour working days by
  default, day boundaries, conversion of durations from hours to ticks with a warning on
  rounding.
- Pytest treats unexpected warnings as errors.
- Project skeleton: `src/` layout with the `gasp_sim` package and its subpackages,
  `gasp-sim --version` command, smoke tests.
- Development tooling: uv with a committed lockfile, hatchling, ruff, mypy (strict),
  pytest with coverage, Hypothesis profiles, import-linter layer rules, pre-commit hooks.
- Continuous integration on GitHub Actions (lint, types, layer rules, tests on Python
  3.12 to 3.15, documentation build).
- Sphinx documentation with MyST and numpydoc, including the Architecture Decision
  Records 0001 to 0009.
