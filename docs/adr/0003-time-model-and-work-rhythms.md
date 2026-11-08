# ADR-0003: Global fine-grained clock with per-agent work rhythms

- **Status:** Accepted. Open points on the global tick, rhythms across days, synchronous perception and phase order resolved by ADR-0007.
- **Date:** 2026-11-03 (clock and per-agent rhythms); 2026-11-04 (30-minute default period, working time only)
- **Related:** ODD §2.7, §3, §7.2, Annex A; ADR-0002

## Context

The paper uses N = 100 communication cycles without saying what a cycle represents in real time. The simulator needs a time scale that makes task durations, help-request delays and the proxy's silence threshold meaningful.

Options discussed: a one-hour step, a half-day step, a 15-minute step, and a 30-minute step (interpretable as a cycle of 25 minutes of focused work and 5 minutes of break, in the manner of the Pomodoro technique). A single global step implies that every team member takes breaks at the same time, which is unrealistic.

## Decision

1. **A global clock with a fine tick** (5 minutes proposed, still open), common to all entities, plus an event queue ordered by (tick, priority, sequence number).
2. **Each agent has a work rhythm** (replaceable `WorkRhythm` component: period, offset, optional variability). Agents perceive and communicate only at their **consultations**; in between, they work.
3. **Default rhythm: synchronous**, every agent every 30 minutes at the same tick (period configurable). This reproduces the paper's schema exactly. Heterogeneous rhythms come later, after the base model is validated against the paper. A sensitivity analysis compares 30 minutes and 1 hour. Chosen over 1 hour because responses can arrive within 30 minutes, which is plausible for team messaging; the cost is smaller per-consultation probabilities, harder to calibrate.
4. **The proxy has its own evaluation period** (the real artefact synchronises periodically).
5. **Durations are expressed in hours** in configuration and converted to ticks by the simulator.
6. **Working time only:** only worked hours exist (8-hour day); nights and weekends are skipped. A day index is kept so that daily events (e.g. a morning stand-up) can be added later. All delays are therefore measured in **working hours**.
7. **Event-driven activation:** ticks without consultations cost almost nothing.

## Alternatives considered

- **A single global step (1 hour, 30 minutes):** simpler, but synchronised breaks and a response delay fixed by the step.
- **One clock per agent:** rejected; the climate, the proxy and the records need a common time.
- **Pure continuous-time discrete-event simulation:** unnecessary for the questions at hand.
- **Calendar time with working hours** (agents unavailable outside their schedule; the proxy ignores those periods): more realistic delays ("answered the next day") and required for time zones, which are common in remote teams; more complex to specify. Not chosen for version 1. Adopting it later would touch the engine's core.
- **No days at all** (continuous working time, as in the paper): simplest, but loses any daily structure (morning stand-up, rhythms restarting each day).

## Consequences

- Response delays emerge from colleagues' rhythms; help-request measures become more informative.
- Participation must be defined over **time windows** (and per tick only in synchronous mode); the climate and the proxy also work on windows.
- Consultations must be recorded so that speaking can be measured per opportunity.
- A list of interpretation and implementation pitfalls, with countermeasures, is kept in ODD Annex A (e.g. silence caused by rhythm mistaken for silence caused by fear; hidden synchronisation; rhythm drift; warm-up).
- Delays measured in working hours hide overnight waiting: a request made at the end of a day and read the next morning appears to have waited a single consultation. Interpretations of delays must say so.
- Calibration becomes harder: probabilities per opportunity are smaller, and converting them between tick durations requires an assumption about how speaking is distributed in time.
- A sensitivity analysis on tick and rhythm durations is planned, to check that conclusions do not depend on them.

## Open points

- Global tick (5 minutes proposed; all rhythm periods must be multiples of it). *Resolved by ADR-0007.*
- Whether rhythms restart every morning or continue across days; how windows behave across day boundaries. *Resolved by ADR-0007.*
- Length of the warm-up period.
- What the "article" mode preserves: 100 consultations (50 working hours at 30 minutes) or a duration.
- Synchronous perception within a tick (proposed default: agents consulting at the same tick do not see each other's messages from that tick). *Resolved by ADR-0007.*
- The Pomodoro interpretation is a modelling assumption; a verified reference is needed before citing it.
