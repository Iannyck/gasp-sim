# gasp-sim

[![CI](https://github.com/Iannyck/gasp-sim/actions/workflows/ci.yml/badge.svg)](https://github.com/Iannyck/gasp-sim/actions/workflows/ci.yml)

Python agent-based simulator testing whether a gamified affective social proxy (GASP, a
virtual pet) can break the spiral of silence in remote Agile teams. Configurable without
coding, extensible by developers.

> **Status: pre-alpha.** The repository currently contains the project skeleton only. The
> simulation engine and the GASP model are being written; nothing can be simulated yet.

## Background

The simulator extends the Monte Carlo model of *Mitigating the Spiral of Silence in Remote
Agile Teams through Gamified Affective Social Proxies* (Vy, Imbeau & Bouchard, IEEE GEM
2026, accepted). It adds agents with different personalities, typed messages, simulated
tasks and per-agent work rhythms. The model is described with the ODD protocol, and every
structural decision is recorded as an Architecture Decision Record in [`docs/adr/`](docs/adr/).

## Installation

Not yet published. To work on the code, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start (no coding required)

To be written once the simulator can run. Researchers will be able to configure and run
experiments from readable configuration files and a user interface.

## Citation

See [CITATION.cff](CITATION.cff).

## License

[MIT](LICENSE)
