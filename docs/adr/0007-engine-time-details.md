# ADR-0007: Engine time details (tick, days, synchronous perception, phase order)

- **Status:** Accepted
- **Date:** 2026-11-04
- **Related:** ADR-0003 (resolves its open points on these topics); ODD §2.7, §3, Annex A

## Context

ADR-0003 set up a global fine-grained clock with per-agent work rhythms, working time only and a 30-minute synchronous default rhythm. It left open the points that the engine core needs before it can be written: the size of the global tick, how rhythms behave from one day to the next, what agents consulting at the same tick can see, and the order of phases within a tick.

## Decision

1. **Global tick: 5 minutes** (96 ticks per 8-hour working day). Every rhythm period and offset must be a multiple of it. A duration given in hours that does not fall on a multiple of the tick is rounded **with a warning**, never silently.
2. **Days.** The engine emits a **day-start event** at the first tick of each working day, before any other event of that tick. Rhythm components can listen to it.
   - Default rhythm behaviour: **reset every morning** (first consultation at the start of the day, plus the agent's personal offset).
   - Continuous rhythms (carrying on from one day to the next) remain available as an option of the rhythm component.
   - With the default 30-minute synchronous rhythm, both behaviours give identical results; the choice only matters for heterogeneous rhythms.
3. **Observation windows** (proxy silence, participation, climate) are **continuous across days**, in working time.
4. **Synchronous perception within a tick.** Agents consulting at the same tick decide from the state frozen at the previous tick and do not see each other's messages from that tick; messages become visible at the next tick. Agent processing order therefore has no influence on outcomes.
5. **Phase order within a tick** (ODD §3), with two explicit choices:
   - the **proxy is evaluated before consultations**, so agents at tick t see a signal reflecting activity up to t − 1;
   - **work is processed before consultations**, so an agent that becomes blocked at tick t can ask for help at a consultation in the same tick.

## Alternatives considered

- **Tick of 1 minute:** finer than the model's assumptions justify. **Tick of 15 minutes:** forbids 25- or 45-minute periods and fine offsets between agents.
- **Rhythms always continuous across days:** with periods that do not divide the working day (e.g. 45 minutes), consultations would drift every morning, which is unrealistic (people check messages on arrival).
- **Sequential perception** (agents processed one after another in a random order, each seeing the messages of those before): closer to a live conversation, but outcomes depend on processing order and an extra random stream would be needed to draw it.
- **Proxy evaluated after consultations:** the proxy would react to messages not yet written from the agents' point of view.
- **Consultations before work:** adds an artificial one-consultation delay between becoming blocked and being able to ask for help.

## Consequences

- Computational cost of the fine tick stays negligible thanks to event-driven activation; task progress is the only per-tick update (about 4,800 updates per run in the article mode).
- In synchronous mode, a reply to a help request arrives at the earliest at the next consultation (30 minutes later), consistent with the "read messages at the break" interpretation.
- Engine tests must cover the day-start event (emitted first, once per working day).
- Configuration validation warns on rounded durations and rejects rhythm periods or offsets that are not multiples of the tick.

## Open points (not blocking the engine)

- Proxy evaluation period (model stage).
- Length of the warm-up period (model stage).
- What the "article" mode preserves: 100 consultations or a duration (model stage).
