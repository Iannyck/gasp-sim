# gasp-sim

[![CI](https://github.com/Iannyck/gasp-sim/actions/workflows/ci.yml/badge.svg)](https://github.com/Iannyck/gasp-sim/actions/workflows/ci.yml)

Python agent-based simulator testing whether a gamified affective social proxy (GASP, a
virtual pet) can break the spiral of silence in remote Agile teams. Configurable without
coding, extensible by developers.

> **Status: pre-alpha.** The simulation engine and the configuration files work, and an
> example model (*toy chatter*, with no scientific value) can be run from a configuration
> file. The GASP model itself is being written: no GASP experiment can be run yet.

## Background

The simulator extends the Monte Carlo model of *Mitigating the Spiral of Silence in Remote
Agile Teams through Gamified Affective Social Proxies* (Vy, Imbeau & Bouchard, IEEE GEM
2026, accepted). It adds agents with different personalities, typed messages, simulated
tasks and per-agent work rhythms. The model is described with the ODD protocol, and every
structural decision is recorded as an Architecture Decision Record in [`docs/adr/`](docs/adr/).

## Installation

Not yet published. To try the current version, clone the repository and install
[uv](https://docs.astral.sh/uv/), then run the example model from the root of the
repository:

```bash
uv sync
uv run python -m examples.toy_chatter.run
```

To work on the code, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start (no coding required)

To be written once the GASP model can run. Researchers will configure and run experiments
from readable configuration files, and later from a user interface. The example model shows
what these files look like: see [`examples/toy_chatter`](examples/toy_chatter/README.md).

## Citation

The citation metadata is in [CITATION.cff](CITATION.cff) (on GitHub: "Cite this
repository"). In BibTeX, the software:

```bibtex
@software{gasp_sim,
  author = {{Capybaravy}},
  title  = {gasp-sim},
  year   = {2026},
  url    = {https://github.com/Iannyck/gasp-sim},
  note   = {Agent-based simulator of a gamified affective social proxy against the
            spiral of silence},
}
```

Please also state the version or commit you used. The paper the simulator extends
(accepted; pages and DOI will be added once it is published):

```bibtex
@inproceedings{vy2026mitigating,
  author    = {Vy, Thi Huyen and Imbeau, Gilles and Bouchard, Bruno},
  title     = {Mitigating the Spiral of Silence in Remote Agile Teams through Gamified
               Affective Social Proxies},
  booktitle = {IEEE GEM 2026},
  year      = {2026},
  note      = {Accepted},
}
```

## License

[MIT](LICENSE)