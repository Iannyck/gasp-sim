# gasp-sim

[![CI](https://github.com/Iannyck/gasp-sim/actions/workflows/ci.yml/badge.svg)](https://github.com/Iannyck/gasp-sim/actions/workflows/ci.yml)

Python agent-based simulator testing whether a gamified affective social proxy (GASP, a
virtual pet) can break the spiral of silence in remote Agile teams. Configurable without
coding, extensible by developers.

> **Status: pre-alpha.** The GASP model runs in its control condition (team, climate and
> decisions to speak, without the affective proxy yet), from a configuration file and the
> `gasp-sim` command. The proxy, personalities, typed messages and tasks are being written;
> no comparison between conditions can be run yet.

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
uv run gasp-sim run examples/configs/article.yaml
```

To work on the code, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start (no coding required)

A run is described by a configuration file (YAML). Two commented examples are in
[`examples/configs`](examples/configs/):

- `article.yaml`: the setting of the article's simulation (independent re-implementation:
  8 members, 50 working hours, consultations every 30 minutes);
- `default.yaml`: every setting of the model with its default value and what it means.

```bash
uv run gasp-sim validate examples/configs/default.yaml             # check a file
uv run gasp-sim validate examples/configs/default.yaml --resolved  # every setting
uv run gasp-sim run examples/configs/article.yaml                  # run and record
```

`gasp-sim run` creates a new directory in `results/` with the resolved configuration, a
manifest describing the run and every column, the tables (one row per consultation,
message and update of the climate) and the summaries (per working day, per run and per
member), in CSV. The modelling assumptions are described in
[`docs/adr/0017-gasp-model-control-condition.md`](docs/adr/0017-gasp-model-control-condition.md).

An example model for developers, with no scientific value, shows the engine on its own:
see [`examples/toy_chatter`](examples/toy_chatter/README.md).

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