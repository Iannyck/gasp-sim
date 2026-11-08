# ADR-0012: Simulation loop, phases, step context and deferred logs

- **Status:** Accepted
- **Date:** 2026-11-08
- **Related:** ADR-0003 and ADR-0007 (time model, phase order, synchronous perception),
  ADR-0011 (event queue and bus); ODD §3; dev-conventions §9

## Context

With random streams, the clock (ADR-0010) and the event queue and bus (ADR-0011) in
place, the engine needs a loop that executes ticks in the order of ODD §3, gives phases
what they need, and guarantees synchronous perception: agents consulting at the same tick
do not see each other's messages of that tick (ADR-0007).

## Decision

1. **Events reach phases through the step context.** At the start of a tick, the engine
   releases every event scheduled for it, in queue order, and exposes them in the context.
   Each phase takes the events it handles (`events_of_type`, exact type). The order of the
   phases, chosen by the model, therefore decides when each event is acted upon.
2. **The start of a working day is announced first.** At the first tick of each working
   day, the engine publishes a `DayStarted` notification on the bus *before* releasing the
   events of that tick, so that work rhythms can still schedule a consultation for it.
3. **Deferred publication is provided by the engine.** A `DeferredLog` is an append-only
   log: entries appended during tick `t` are *staged* and become *visible* from `t + 1`.
   It exposes the visible entries (and time windows of them, `visible_since`) and the
   entries staged during the current tick. The simulation opens every registered log at the
   start of a tick and commits it at the end. Appending outside a tick is an error.
4. **Phases receive a narrow context.** A `StepContext` gives the tick, day, position in
   the day, day-start flag, time grid, random streams and released events, and three
   actions: schedule a future event (absolute or relative), cancel a scheduled event,
   publish a notification. It does not give access to the simulation. The model's state
   lives in the model's own objects. A context is closed at the end of its step.
5. **Every tick runs every phase; any error stops the simulation for good.** A
   `StepCompleted` notification is published after the logs are committed. If anything
   fails during a step (a phase, a handler), the error propagates and the simulation is
   marked as failed; further steps raise `SimulationFailedError`.

Order of a step: open logs → `DayStarted` (first tick of a day) → release events → run
phases → commit logs → close context → `StepCompleted` → advance the clock.

A phase is any object with a `name` and a `run(context)` method (`typing.Protocol`,
ADR-0008); `FunctionPhase` wraps a plain function. Phase names and log names must be
unique. The first public API (`gasp_sim.api`) exports the engine's building blocks; only
names exported there are covered by semantic versioning.

The deferred logs live in a module not listed in the original directory tree
(`gasp_sim/core/deferred.py`); it belongs to the engine core and follows the same rules.

## Alternatives considered

- **Engine-dispatched event handlers before the phases:** a consultation would be handled
  before the work phase of the same tick, contrary to the decided order (ADR-0007).
- **Day start as an ordinary scheduled event:** it would have to be scheduled in advance
  and could not let handlers schedule events for the same tick.
- **Deferred visibility left to each model:** easy to get wrong, and needed by any model
  with messages.
- **Giving phases the simulation object:** a phase could advance the clock or run steps,
  which would break the loop's guarantees.
- **Skipping phases on ticks without events:** the work phase must advance tasks at every
  tick; the gain would be negligible.
- **Continuing after a failed step:** results would be drawn from an inconsistent state.

## Consequences

- Synchronous perception is guaranteed by construction for anything written through a
  `DeferredLog`; end-of-tick processes (climate update) read the staged entries.
- The recorder and the real-time display can subscribe to `StepCompleted`.
- Engine tests cover the order of a step, day starts, synchronous perception, failures,
  closed contexts and determinism; property-based tests check day boundaries, arrival of
  scheduled events and deferred visibility.
- The next step (a toy model) will check that this interface is enough to write a model
  before the GASP model depends on it.
