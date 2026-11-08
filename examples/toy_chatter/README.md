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
- **A small feedback loop**: the probability of speaking rises with the share of agents who
  spoke during the last hour.

## Run it

From the root of the repository:

```bash
uv run python -m examples.toy_chatter.run
```

## Files

- `model.py` — the model (`ToyChatter`, `ToyParameters`).
- `run.py` — runs five working days and prints a summary.

Tests: `tests/examples/test_toy_chatter.py`.
