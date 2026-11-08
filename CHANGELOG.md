# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
