# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project skeleton: `src/` layout with the `gasp_sim` package and its subpackages,
  `gasp-sim --version` command, smoke tests.
- Development tooling: uv with a committed lockfile, hatchling, ruff, mypy (strict),
  pytest with coverage, Hypothesis profiles, import-linter layer rules, pre-commit hooks.
- Continuous integration on GitHub Actions (lint, types, layer rules, tests on Python
  3.12 to 3.15, documentation build).
- Sphinx documentation with MyST and numpydoc, including the Architecture Decision
  Records 0001 to 0009.
