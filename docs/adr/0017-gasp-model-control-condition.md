# ADR-0017: GASP model, control condition (team, climate, decisions to speak)

- **Status:** Accepted
- **Date:** 2026-11-14
- **Amends:** ADR-0014 (presets and run length), ADR-0016 (model checks)
- **Related:** ADR-0002 and ADR-0010 (random streams), ADR-0003 and ADR-0007 (time and
  rhythms), ADR-0004 (intentions), ADR-0014 (components and presets), ADR-0015 (outputs),
  ADR-0016 (running a model), ODD sections 2 to 9, dev-conventions §9

## Context

Step 6 writes the GASP model sub-model by sub-model (6.1 control condition, 6.2 proxy,
6.3 personality, 6.4 messages and intentions, 6.5 tasks, 6.6 other reactions). This record
covers step 6.1: the team, the team channel, the communication climate and the decision
to speak, without the affective proxy.

The article (Vy, Imbeau & Bouchard, IEEE GEM 2026) states that at every cycle each agent
computes a probability of speaking `P_speak`, draws `r ~ U(0, 1)` and speaks if `r ≤ P_speak`
(equation 1); that the probability decreases with perceived social isolation and increases
with psychological safety; that safety is drawn in [0, 1]; that the climate starts neutral
and is updated from the participation rate (formula 2: participating agents divided by
agents). It does not publish the formula of the probability, the update rule of the
climate, nor their parameters. Its code is not used in this project.

Labels used below: **[article]** taken from the article; **[assumption]** modelling
assumption of this project, to be tested in sensitivity analyses.

## Decision

### Model

1. **Decision rule** [article]: one uniform draw per member and consultation, from the
   member's `speech` stream; the member speaks if `r ≤ P`.
2. **Probability of speaking** (extension point `expression_probability`) [assumption]:
   - `logistic` (default):
     `logit P = intercept + safety_weight (safety − 0.5) + climate_weight (climate − 0.5)`.
     Centring on 0.5 makes each weight readable (below). Later terms (propensity, fear of
     isolation × social risk, courage) will be added on the same scale.
   - `linear`, clipped to [0, 1], for sensitivity analyses; its parameters have no default.
   - The climate used is the one **perceived by the member**.
   - A component that returns a value outside [0, 1], or not a finite number, stops the run
     with an error naming the member.
3. **Perception of the climate** (extension point `climate_perception`): the climate of the
   team is always computed and recorded; the perception decides what each member uses.
   - `shared`: everyone perceives the climate of the team, as in the article.
   - `individual_memory` (default of the project) [assumption]: each member starts from an
     impression drawn from a beta distribution (mean and standard deviation), and updates
     it at each consultation with the participation they observe, using the climate rule of
     the team or an inertia of their own. No update at the first consultation (no history).
   - Added noise and an influence of one's own behaviour on one's perception are left for
     later, as sensitivity components, when they can be justified.
4. **Reading habits** (extension point `reading_habit`): a member sees only the messages
   of the team channel and their senders, never silent consultations. The habit decides
   which messages are read: `recent` (the last `hours`, default 0.5), `unread` (since the
   previous consultation, optionally capped), `last_messages` (a number of messages, with a
   **required** age limit: without it a channel silent for days would look as lively as its
   last messages). Version 1 gives the same habit to the whole team; mixed habits come with
   heterogeneous rhythms, independently of personality. The same habit will decide what a
   member perceives of help requests (step 6.5).
5. **Participation** [article formula 2, generalised]: what is visible counts, that is who
   wrote.
   - Observed by a member: other members among the senders of the messages read, divided
     by the number of other members. Oneself is excluded.
   - Of the team: members who wrote during the participation window (0.5 h by default)
     ending with the current tick, divided by the size of the team. With synchronous
     rhythms and a window equal to the consultation period, it is exactly formula 2.
   - Speech per opportunity (spoke at a consultation) is recorded as well, for analyses
     (ODD appendix A, pitfall 1), but does not feed the climate.
6. **Climate rule** (extension point `climate_rule`) [assumption]:
   - `ema` (default, also for the `article` preset): exponential moving average set by its
     **inertia** (see the next section).
   - `threshold`: the literal reading of the article's wording ("participation gradually
     decreases when communication activity falls below a predefined threshold"): the
     climate falls by `rate_per_hour × Δt` below the threshold and rises by as much
     otherwise. With it, the climate never settles except at the bounds or around the level
     where participation equals the threshold, which then largely sets the level reached.
     It is offered through the `article_threshold` preset. Choosing `ema` for `article` is a
     deliberate departure from the literal wording, so that the level of the control
     condition emerges from the decisions of the members instead of being set by a
     threshold chosen by hand (step 6 decision T6).
   - The climate of the team is updated after the consultations of every tick that has
     some. The first update covers the participation window; later ones, the time since
     the previous update.
7. **Initial values**: climate of the team 0.5 [article: "neutral"; value an assumption];
   with the centred logistic, a neutral climate pushes neither way.
8. **Team**: 3 to 12 members, 8 by default [article: K = 8]; psychological safety drawn
   from a distribution (extension point `distribution`: `uniform`, default U[0, 1] as in
   the article; `beta` set by mean and standard deviation; `constant`).
9. **Rhythm**: extension point `work_rhythm`, component `synchronous` (every 30 minutes by
   default, everyone together, restarting every morning). Heterogeneous rhythms come later.
10. **A setting appears only once it has an effect.** Personality, the proxy, types of
    messages and tasks are not in the configuration yet. The single type of message is
    `generic`.

### Inertia of the climate

The climate is a slow collective state that should not swing from one consultation to the
next (ODD 7.8). Its **inertia** `h`, in working hours (`inertia_hours`), says how slowly it
follows the participation. At every update, rule `ema` replaces a share `α` of the climate
by the participation `p` just observed:

```
α = 1 − 2^(−Δt / h)
c ← c + α (p − c)
```

where `Δt` is the number of working hours since the previous update. The weight of the
past fades progressively: after `h` hours, half of the former climate has been replaced by
what was observed; after `2h`, three quarters; after `3h`, seven eighths. In data
analysis, `h` is called the *half-life* of an exponential moving average; the name
*inertia* comes from the ODD and is meant for researchers.

| Inertia | Share replaced at each 30-minute update | Meaning |
|---|---|---|
| 0.5 h (`article`) | 50 % | the climate closely follows the last cycles |
| 16 h (default) | about 2 % | half of the climate is renewed after two working days |

Because it is a duration rather than a share per update, the inertia gives the same
behaviour whatever the rhythm of updates (every 30 minutes or every hour), and members who
consult at different moments forget at the same pace. It is a speed of forgetting, not a
moment on the time grid: it is **not rounded to ticks**. Updates only happen at ticks with
consultations, so an inertia much shorter than the time between updates simply replaces
almost all of the climate each time. Individual impressions use the same notion
(`individual_memory`, optional `inertia_hours`).

### Values [assumption, validated on 2026-11-14]

Each value is set from a stated reference point, not by matching the results of the
article (decision T6):

| Setting | Value | Reference point |
|---|---|---|
| `safety_weight` | 2 | odds ratio ≈ 7.4 between the least and the safest member; in a neutral climate, P from 0.27 to 0.73 (intercept 0) |
| `climate_weight` | 2 | the climate weighs as much as safety: the two factors named by the article, with equal weight |
| `intercept` | −0.5 | speaking in public has a cost: an average member in a neutral climate speaks at about 38 % of consultations |
| inertia, `article` | 0.5 h | half of the climate renewed at each cycle, the closest to "the participation rate was used to update the communication climate for the subsequent cycle" |
| inertia, default | 16 h | two working days ("several days", ODD 7.8) |
| `initial_sd` of impressions | 0.1 | initial impressions mostly within ±0.2 of neutral |
| `article_threshold` | threshold 0.5, 0.1 per hour | half of the team writes; the climate can go from neutral to 0 in 5 hours |

**The intercept is the key assumption of the control condition.** Without a cost of
speaking (intercept 0), the model is symmetric around the neutral climate and nothing
pushes participation down rather than up. In step 6.1 the intercept stands for the term
"fear of isolation × social risk" that will make this asymmetry explicit in step 6.4.

### Exploration (before choosing the values)

Control condition, `article` setting with shared perception; 200 runs per combination of
intercept, climate weight and inertia, and 500 runs for the curves; seeds 0 to 499; named
streams. These are results of this model under its assumptions, not empirical findings.

- With intercept 0, the mean participation stays at 0.49–0.50 from the first to the last
  cycle. With a strong feedback (climate weight ≥ 6), teams split: about half end below
  0.2 and half above 0.8.
- A decline appears as soon as speaking has a cost (intercept < 0) and the climate feeds
  back (climate weight > 0). Without feedback, participation stays flat (0.38 with
  intercept −0.5).
- The strength of the feedback sets the regime: with climate weight 2, participation falls
  from 0.37 at the first cycle to about 0.31 and settles; with 4, 74 % of teams end below
  0.2.
- The inertia sets the speed of the decline, not its level: about ten cycles with 0.5 h,
  the whole run with 8 h, to about 0.31 in both cases.
- With the chosen values, the mean over 1 000 runs (seeds 0 to 999) of the mean
  participation of a run is 0.312, with a standard deviation of 0.077 between runs.
- The article reports a control condition that declines and converges towards about 50 %.
  This reconstruction declines and settles at about 31 %. Following decision T6, nothing
  was adjusted to come closer; only the direction and order of magnitude of the
  difference between conditions will be compared, once the proxy exists (step 6.2).

### Configuration and running

11. **Configuration** (`GaspConfig`): `team_size`, `psychological_safety`, `rhythm`,
    `reading`, `perception`, `initial_climate`, `participation_window_hours`,
    `climate_rule`, `expression`, with the common settings (ADR-0014, ADR-0016).
    Parameters are declared with pydantic in the model (decision T1); the model never
    reads configuration files (import rule).
12. **Presets**: `article` (8 members, 50 working hours, synchronous consultations every 30
    minutes, recent reading of 30 minutes, shared perception, neutral initial climate,
    participation window of 30 minutes, `ema` with an inertia of 0.5 h, logistic with the
    values above) and `article_threshold` (the same with the `threshold` rule). The
    `article` preset is described as an *independent re-implementation* aiming at
    *relational alignment* with the article: direction and order of magnitude of the
    difference between conditions, not numerical identity or distributional equivalence.
13. **Run length and presets** (amends ADR-0014): the length of a run is one setting,
    written in days or in hours. When a file gives `days` or `hours`, it replaces the
    length of its preset in either unit.
14. **Model checks** (amends ADR-0016): `ModelDefinition.checks` adds warnings that only the
    model can produce. The GASP model warns when the participation window or the reading
    window is shorter than the time between two consultations (ODD appendix A, pitfall 9).
    They are shown by `gasp-sim validate` and `gasp-sim run` and recorded in the manifest.
15. **Outputs** (ADR-0015), declared in `gasp_sim.experiment.gasp`:
    - tables `agents` (member, safety, initial impression), `consultations` (member,
      messages read, minutes covered, observed participation, perceived climate,
      probability, spoke), `messages` (number, sender, type), `climate` (participation,
      climate);
    - summaries `windows` and `run` (consultations, messages, messages per member, mean
      participation, speech per consultation, mean perceived climate, climate at the end)
      and `agent_run` (one row per member);
    - columns needed later (message number, message type) are present from now on, so
      that the reference files of the `article` preset, frozen in step 6.2, do not change
      for a technical reason.
16. **Command line**: `gasp-sim validate` and `gasp-sim run` now run the GASP model; the
    headline values are the consultations, messages and mean participation of the run.
17. **Random streams** (identifiers permanent): `rhythm` 2, `speech` 3, `traits` 5,
    `perception` 6, all per member. Reserved: `init` 0 and `proxy` 1 (team), `tasks` 4 and
    `personality` 7 (per member). One stream per family of draws, so that adding a family
    later (for example personality) does not change the draws of the others.
18. **Public API**: the extension points and protocols of the model, `GaspConfig`, `GASP`
    and `PLUGIN_GROUP` are exported by `gasp_sim.api` for extension developers. The model
    itself imports the modules of the engine, configuration and registry directly, since
    `gasp_sim.api` also exports the experiment and recording layers.

## Alternatives considered

- **Linear probability by default**: easier to read, but flat beyond its bounds.
- **A single climate perceived identically by all**: the article's simplification; the
  theory rests on the climate *as perceived*. Kept as `shared` for the `article` preset.
- **A fixed bias of perception per member**: equivalent, on the logistic scale, to a
  different tendency to speak; it would add a parameter without adding a mechanism.
- **Perception "since my last consultation"**: members who consult rarely would see more
  senders, so their perceived climate would depend on their rhythm.
- **Reading a number of messages without an age limit**: blind to silence.
- **Participation as the share of consultations with a message**: identical with
  synchronous rhythms, but not what members can see.
- **The threshold rule for `article`**: the level of the control condition would be set
  by the threshold.
- **A share replaced per update instead of an inertia**: its effect would depend on how
  often updates happen.
- **Rounding the inertia to ticks**: it would change the rule without reason, and give 0
  for inertias shorter than half a tick.
- **Calibrating the values on the 50 % and 85 % of the article**: circular with more free
  parameters than targets (decision T6).

## Consequences

- Researchers run the control condition with `gasp-sim run examples/configs/article.yaml`
  (or `default.yaml`), and every assumption of the decision to speak is a setting.
- The decline of participation in the control condition is a consequence of two declared
  assumptions (a cost of speaking, a feedback of the perceived climate), and the region of
  parameters where it appears is to be mapped in step 7.
- `individual_memory` and `shared` give almost the same results with synchronous rhythms;
  they will differ with heterogeneous rhythms and reading habits.
- Extension developers add components to six extension points with the same interfaces as
  the built-in ones.

## Open points

- References for the comparison of models (relational alignment, replication) are cited
  once checked by the researcher.
- Mixed reading habits and heterogeneous rhythms within a team.
- Noise of perception, influence of one's own behaviour on one's perception.
- Warm-up period (step 6.6).
- Shorthand `proxy: none` and the GASP proxy (step 6.2).

## Revisit when

- the proxy (step 6.2) shows that the control condition leaves no room for an effect, or
  too much; or
- the sensitivity analyses of step 7 show that the chosen reference points sit at a
  boundary between regimes.
