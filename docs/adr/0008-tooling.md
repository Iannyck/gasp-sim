# ADR-0008: Tooling (package name, licence, configuration, extensions, CLI, documentation, outputs)

- **Status:** Accepted
- **Date:** 2026-11-04
- **Related:** dev-conventions §2, §5, §7, §9; ADR-0001

## Context

The repository skeleton (`pyproject.toml`, continuous integration, documentation build) needs a set of tooling decisions. Most are low-stakes and reversible; the documentation tool and the output formats have longer-term consequences.

## Decision

1. **Package name:** `gasp_sim` (distribution name `gasp-sim`).
2. **Licence:** MIT.
3. **Configuration validation:** pydantic. Its exported JSON Schema is used to generate the user-interface forms, including for extension components.
4. **Extension mechanism:** interfaces defined as `typing.Protocol`, checked at registration; discovery through *entry points* (`importlib.metadata`) plus local loading for quick experiments; only `api.py` is covered by semantic versioning.
5. **Command line:** Typer.
6. **Documentation:** Sphinx, with MyST (pages written in Markdown, so the ODD and ADRs can be used as they are) and numpydoc (NumPy-style docstrings, with docstring checks that can run in continuous integration, to be confirmed at setup). MyST requires Sphinx below version 10; the dependency bounds must respect this.
7. **Outputs:** CSV and JSON only. Two recording levels:
   - `full`: all tables;
   - `summary`: aggregates per run and per time window.
   Default: `full` for a single run, `summary` for large batches; configurable per experiment.

## Facts checked (2026-11-04)

- MkDocs 1.x is unmaintained (no release for about 18 months; repository closed to outside contributions on 2026-10-02). MkDocs 2.0 is a pre-release rewrite with no plugin system (mkdocstrings would no longer work), not compatible with Material for MkDocs nor with existing configurations. Material for MkDocs is in maintenance mode, with critical fixes until 2027-05-05. Its authors present Zensical as the successor, not yet complete for popular plugins. Source: https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0
- Sphinx 9.1.0 packaged in March 2026 (Arch Linux; PyPI not checked directly). Source: https://www.archlinux.org/packages/python-sphinx
- MyST-Parser 5.1.0 (May 2026) requires Python ≥ 3.11 and Sphinx ≥ 8, < 10. Source: https://simple-repository.app.cern.ch/project/myst-parser
- numpydoc 1.11.0 (September 2026), with regular releases since 2023. Source: https://www.piwheels.org/project/numpydoc/

## Alternatives considered

- **MkDocs with mkdocstrings** (initial proposal): rejected; the ecosystem is in transition and its future plugin support is uncertain.
- **Zensical:** promising but young; can be re-evaluated later.
- **Sphinx with napoleon** (built-in) instead of numpydoc: no extra dependency, but no docstring validation.
- **argparse or Click** instead of Typer: fewer or similar dependencies, more verbose code. The CLI is a thin layer, easy to replace.
- **Parquet** for large batches: smaller and faster files, but unreadable without programming and a heavy dependency (pyarrow). Not used for now.
- **Single recording level (`full` only):** consistent with "record everything", but article-mode batches would produce several hundred megabytes of CSV per condition (rough estimate, not measured).

## Consequences

- In `summary` mode, an indicator not planned in advance cannot be computed after the fact.
- Documentation is written in Markdown and built with Sphinx; Sphinx configuration is less pleasant than MkDocs', a known trade-off.
- The package name becomes hard to change once published on PyPI.

## Revisit when

- Output volumes become a real problem with CSV (reconsider Parquet as an optional extra).
- Zensical matures and the team prefers it.
