# ADR-0009: Dependency management, quality tooling and delivery workflow

- **Status:** Accepted
- **Date:** 2026-11-04
- **Related:** dev-conventions §2–§4, §6, §9; ADR-0008

## Context

Before writing the repository skeleton, the remaining development conventions had to be settled: Python version, dependency management, build backend, quality and test tooling, Git workflow, continuous integration, and how code produced by Claude reaches the repository.

The repository is public (https://github.com/Iannyck/gasp-sim). The maintainer manages commits with GitHub Desktop and prefers to push changes personally.

## Decision

1. **Python ≥ 3.12**, continuous integration on 3.12 to 3.15, development on **3.14** (pinned in `.python-version`). The minimum follows NumPy, the only scientific dependency, which requires Python ≥ 3.12 since version 2.5. Python 3.14 is used for development because 3.15 was released only in October 2026 and not every development tool may support it yet; it remains tested in continuous integration.
2. **uv** for dependency and environment management, with `uv.lock` committed. Users can still install the package with `pip`; the lockfile serves development, continuous integration and the reproduction of published experiments.
3. **hatchling** as build backend; `src/` layout; PEP 621 metadata in `pyproject.toml`.
4. **Quality:** ruff (format and lint, line length 100), mypy in strict mode (at least on `core` and `model`), NumPy-style docstrings, pre-commit.
5. **Tests:** pytest with pytest-cov, coverage ≥ 80 % on `core`. **Hypothesis** for property-based tests, limited to the engine (event queue, random streams, clock, rhythms), with a deterministic profile in continuous integration and an exploratory profile locally.
6. **Git:** one branch per feature, merged by pull request; Conventional Commits; SemVer and `CHANGELOG.md`; GitHub Actions for lint, typing, layer rules, tests and documentation build.
7. **Architecture:** the principles, layers and directory tree of dev-conventions §9 are accepted.
8. **Delivery workflow:** Claude has **read-only** access to the repository. Each step is delivered as an archive of files, with a ready-to-copy commit message, the list of added, modified and deleted files, and review notes. The maintainer commits with GitHub Desktop and pushes. Each step is pushed before the next one starts, because Claude always builds on the public state of the repository. Switching later to Git patches (`git format-patch` / `git am`) remains possible.

## Facts checked (2026-11-04)

- OpenAI announced the acquisition of Astral (maker of uv and ruff) on 2026-03-19, subject to regulatory approval; both companies committed to keeping uv and ruff open source (MIT licence). Source: https://dev.to/max_quimby/openai-just-acquired-astral-what-it-means-for-uv-ruff-and-every-python-developer-41ah
- uv can export its lockfile to the standard `pylock.toml` format (PEP 751) and to `requirements.txt`. Source: https://docs.astral.sh/uv/concepts/projects/export/
- pip has an experimental `pip lock` command (since 25.1) whose output is only guaranteed for the current Python version and platform, whereas `uv.lock` is universal. Source: https://pydevtools.com/blog/did-pip-26-close-the-gap-with-uv/
- hatchling 1.33.0 was released on 2026-10-28 (requires Python ≥ 3.10). Source: https://simple-repository.app.cern.ch/project/hatchling
- Hypothesis 6.168.2 was released on 2026-09-27, with newer releases available (requires Python ≥ 3.10). Source: https://pypi.org/project/hypothesis/6.168.2/
- Python release status (2026-11-06): 3.15 released on 2026-10-09 (support until 2031-10); 3.14 in bugfix mode (until 2030-10); 3.12 and 3.13 in security mode (until 2028-10 and 2029-10); 3.11 in security mode until 2027-10. Sources: https://www.python.org/downloads/, https://peps.python.org/pep-0790/
- NumPy 2.5.4 (2026-10-10) requires Python ≥ 3.12 and supports 3.12 to 3.15. Source: https://simple-repository.app.cern.ch/project/numpy

## Alternatives considered

- **pip alone:** no universal lockfile, slower; acceptable for users, weaker for reproducing experiments.
- **Python ≥ 3.11** (initial proposal): tests under 3.11 would have run with an older NumPy than on the other versions, and 3.11 support ends in October 2027.
- **Python ≥ 3.14**: fewer versions to test and longer support, and uv installs Python without administrator rights; but environments with an imposed, older Python (lab servers, computing clusters) would be excluded, and no 3.13 or 3.14 feature is essential to the code.
- **setuptools** as build backend: the classic choice, more configuration for the same result.
- **Example-based tests only:** misses subtle ordering or seeding bugs that would silently bias results.
- **Write access for Claude (branches and pull requests):** smoother, but the maintainer prefers to keep every push in their own hands.
- **Patches or Git bundles for delivery:** preserve fine-grained history, but require the command line, while the maintainer works in GitHub Desktop.

## Consequences

- One commit per step in the history, rather than one commit per logical change.
- Dependency on tools from Astral (uv, ruff), whose ownership changed in 2026. Mitigation: both rely on Python standards (`pyproject.toml`), and the lockfile can be exported to `pylock.toml`; switching tools would be cheap.
- Hypothesis must be configured to stay deterministic in continuous integration.

## Revisit when

- The maintainer wants finer-grained history (switch to patches) or grants write access.
- uv or ruff change licence or direction.
