# Toy chatter — example model

> **Example only.** This is not the GASP model, it is not calibrated, and its results have
> **no scientific value**.

*Toy chatter* is a *toy model* (a deliberately simplified model) in which a few agents
"chatter" at random in a shared channel. It is the smallest complete model written with the
gasp-sim engine, and it uses only the public API (`gasp_sim.api`), as a third-party extension
would.

## What it shows

- **Random streams** declared by the model (`STREAMS`), one substream per agent.
- **Work rhythms**: each agent consults the channel every 30 minutes with a personal offset;
  rhythms restart every morning, in a *day-start phase*.
- **Scheduled events**: each consultation schedules the next one, within the working day.
- **Synchronous perception**: messages go to a `DeferredLog`; what is written during a tick
  becomes visible from the next tick, so agents consulting at the same tick never see each
  other's messages of that tick.
- **Phases**: `start_day` (at the first tick of each day), then, at every tick,
  `consultations` (agents decide whether to speak) and `participation` (share of consulting
  agents who spoke, read from the entries staged during the tick).
- **A replaceable speaking rule** (an *extension point*): `feedback` (the default, the
  probability of speaking rises with the share of agents who spoke during the last hour)
  or `constant`.
- **Configuration files** (ADR-0014): the model is configured from a YAML file, validated
  strictly, with presets and plugins.

## Run it

From the root of the repository:

```bash
uv run python -m examples.toy_chatter.run                                   # configs/default.yaml
uv run python -m examples.toy_chatter.run examples/toy_chatter/configs/no_feedback.yaml
uv run python -m examples.toy_chatter.run examples/toy_chatter/configs/with_plugin.yaml
uv run python -m examples.toy_chatter.run examples/toy_chatter/configs/default.yaml --resolved
uv run python -m examples.toy_chatter.run --output results                  # record the run
```

`--resolved` prints every setting, defaults included, instead of running the model. An
invalid file prints every problem found, for example:

```text
Invalid configuration bad.yaml (3 errors):
  error: speaking_rule → base_probability: must be at most 1 (got 1.5)
  error: n_agnets: unknown setting; did you mean 'n_agents'?
  error: consultation_period_hours: must be a whole number of 5-minute ticks (got 0.1)
```

## Recorded outputs

With `--output results`, the run is recorded in a new directory inside `results/`
(ADR-0015):

```text
results/20261108-143205-seed42/
  manifest.json            # status, versions, seed, settings, meaning of every column
  config.yaml              # the resolved configuration, loadable as it is
  tables/consultations.csv # one row per consultation (level "full" only)
  tables/messages.csv      # one row per message (level "full" only)
  summary/windows.csv      # participation in each time window
  summary/run.csv          # participation over the whole run
```

For example, the first rows of `tables/consultations.csv`:

```csv
run_id,tick,day,minutes,agent,probability,spoke
20261108-143205-seed42,0,0,0,3,0.3,false
20261108-143205-seed42,2,0,10,1,0.3,false
```

The level (`full` or `summary`) and the length of the time windows are set in the
configuration file:

```yaml
recording:
  level: summary       # only the summaries
  window_hours: 4
```

The model only publishes observations (`Decision`, `MessageSent`); `outputs.py` declares
the tables and the aggregator of the summaries, outside the model.

## Configuration files

```yaml
seed: 42
days: 5
n_agents: 5
consultation_period_hours: 0.5   # must be a whole number of 5-minute ticks
window_hours: 1.0                # rounded to the nearest tick, with a warning
speaking_rule:
  type: feedback                 # the component, then its parameters
  base_probability: 0.3
  feedback: 0.4
```

Settings left out keep their default value. Advanced settings common to every model:
`stream_mode` (`named` or `single`), `time` (`tick_minutes`, `day_hours`), `recording`
(`level`, `window_hours`), `preset` and `plugins`.

## Adding a component (developers)

`extra_rules.py` is a complete plugin: a class implementing `SpeakingRule`, a
`ComponentParameters` model for its parameters, and a function `register(registry)`. List
the module (or a Python file, relative to the configuration file) under `plugins:`, as in
`configs/with_plugin.yaml`. A plugin may also be published in a package and advertised as an
entry point.

## Files

- `model.py` — the model (`ToyChatter`, `ToyParameters`, the speaking rules); it knows
  nothing about configuration files.
- `config.py` — the extension point, the components, the preset, the schema (`ToyConfig`),
  `default_registry()`, `load()` and `build()`.
- `outputs.py` — the recorded tables and the summaries (`ParticipationSummary`).
- `extra_rules.py` — an example plugin adding the `threshold` speaking rule.
- `configs/` — example configuration files.
- `run.py` — runs a configuration file, prints a summary and, on request, records the run.

Tests: `tests/examples/test_toy_chatter.py`, `test_toy_config.py`,
`test_toy_config_properties.py`, `test_toy_outputs.py`.
