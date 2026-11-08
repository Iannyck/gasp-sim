# Contributing to gasp-sim

Thank you for your interest in gasp-sim. This guide explains how to set up a development
environment and the conventions the project follows. A guide to writing extensions
(new behaviours, personalities, proxies or measures) will be added once the extension
interfaces exist.

## Language

All code, comments, docstrings, documentation, commit messages and issues are in English.

## Development setup

The project uses [uv](https://docs.astral.sh/uv/) to manage dependencies; the lockfile
`uv.lock` is committed so that everyone works with the same versions. The development
Python version (3.14) is pinned in `.python-version`; uv installs it automatically if it
is missing.

```bash
git clone https://github.com/Iannyck/gasp-sim.git
cd gasp-sim
uv sync --extra dev --extra docs   # create .venv with all development dependencies
uv run pre-commit install          # run ruff and mypy before each commit
```

## Running the checks

These are the same checks as in continuous integration:

```bash
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # static typing (strict)
uv run lint-imports          # layer rules between subpackages
uv run pytest --cov          # tests with coverage
uv run sphinx-build -W -b html docs docs/_build/html   # documentation
```

Property-based tests use Hypothesis. Locally they explore new examples on each run; in
continuous integration they are deterministic (`HYPOTHESIS_PROFILE=ci`).

## Conventions

- **Python ≥ 3.12** (development on 3.14), type annotations everywhere, NumPy-style
  docstrings for every public function and class, no `print` in library code (use
  `logging`).
- **Randomness:** never use the global `random` module or `np.random.seed`. Ask the stream
  provider for a named stream (see ADR-0002).
- **Layers:** the engine core (`gasp_sim.core`) depends only on NumPy; the model never
  imports the user-facing layers. These rules are checked by import-linter.
- **Model documentation:** every formula or modelling assumption in the code refers to the
  matching section of the ODD model specification. A changed assumption is written in the
  specification first, then implemented.

## Git workflow

- `main` always works. Work on a branch per feature and open a pull request.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`…).
- Versions follow [Semantic Versioning](https://semver.org/); notable changes go in
  `CHANGELOG.md`.

## Architecture decisions

Structural decisions are recorded as Architecture Decision Records in `docs/adr/`. An
accepted record is not rewritten: a decision that changes gets a new record that
supersedes the old one.
