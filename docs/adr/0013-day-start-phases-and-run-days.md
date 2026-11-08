# ADR-0013: Day-start phases and `run_days`

- **Status:** Accepted
- **Date:** 2026-11-08
- **Related:** ADR-0007 (rhythms restart every morning), ADR-0012 (simulation loop; this
  ADR extends its step order)

## Context

Writing the toy chatter example (step 3) with the public API showed one awkward point. To
restart work rhythms every morning, the model subscribed to the `DayStarted` notification.
Bus handlers receive no step context, so the model had to keep a reference to the whole
simulation and call `simulation.schedule(...)`, which is what ADR-0012 (decision 4) meant
to avoid. GASP's work rhythms will have the same need. The example also had to write its
own helper to run whole working days.

## Decision

1. **Day-start phases.** `Simulation` accepts a second, optional sequence of phases,
   `day_start_phases`, run only at the first tick of each working day. They run after the
   `DayStarted` notification and **before** the events of that tick are released, with their
   own `StepContext`: its `events` are empty, and it may schedule events for the current
   tick, since that tick has not been released yet. The context is closed before the events
   are released. Phase names must be unique across both sequences.
2. **`Simulation.run_days(days)`** executes `days` times the number of ticks in a working day,
   counting from the next tick (in the middle of a day, `run_days(1)` ends in the middle of
   the next day).

Order of a step, replacing the one in ADR-0012: open logs → `DayStarted` notification
(first tick of a day) → day-start phases → release events → phases → commit logs → close
context → `StepCompleted` → advance the clock.

Both changes are additions to the public API; nothing existing changes.

## Alternatives considered

- **Attaching a context to the `DayStarted` notification:** shorter, but any bus subscriber
  (such as an output recorder) could then schedule events, which the bus is not meant to
  allow.
- **Keeping `simulation.schedule(...)` in handlers and documenting it:** contrary to
  ADR-0012, decision 4.
- **`run_days` running until the end of the current day:** less predictable when called in
  the middle of a day.

## Consequences

- Models restart rhythms through the same notion of phase as everything else; observers
  keep using the `DayStarted` notification.
- Scheduling for the current tick is possible only in day-start phases; ordinary phases
  keep the strict rule of ADR-0011.
- The toy chatter example uses both additions; its results are unchanged (checked on
  2,400 consultations), and its demonstration still prints 400 consultations, 272 messages
  and a mean participation of 0.680 with seed 42.
