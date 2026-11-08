# ADR-0011: Event queue for future events and synchronous notification bus

- **Status:** Accepted
- **Date:** 2026-11-08
- **Related:** ADR-0001 (in-house engine), ADR-0003 and ADR-0007 (time model and phase
  order); ODD §3

## Context

The engine must release events at known future ticks (an agent's next consultation, the
proxy's next evaluation, the end of a task) in a deterministic order, as required by the
ODD (§3) and ADR-0003. Some components also need to learn immediately about something that
has just happened, without it having a date: the output recorder must note each published
message, for instance.

## Decision

1. **Two distinct mechanisms.** An `EventQueue` holds events scheduled for future ticks;
   an `EventBus` delivers notifications immediately to subscribers.
2. **Queue order: tick, then priority (lower values first), then order of scheduling.**
   Priorities are plain integers; their meaning (for example, proxy evaluation before
   consultations) is defined by the model, not by the engine.
3. **Only future events.** An event can be scheduled only for a tick strictly after the
   last released tick: never in the past, and never for the tick being processed.
   Releasing a tick that would skip a pending event is an error. What must happen within
   the same tick goes through the phase order (ADR-0007) or the bus.
4. **Lazy cancellation by handle.** Scheduling returns an immutable `EventHandle`. The queue
   keeps the set of pending sequence numbers; cancelling removes the number from that set,
   and cancelled entries are skipped when their tick is released. Cancelling twice, or
   cancelling an event already released, has no effect and returns `False`. A handle from
   another queue is rejected. `len()` counts only pending events.
5. **Synchronous bus.** Handlers are called immediately, in order of subscription. A
   handler subscribes to one exact type (subclasses are not delivered) or to every
   notification. Errors raised by a handler propagate to the publisher and stop delivery.
   Subscriptions made or cancelled during a delivery take effect from the next
   publication.

## Alternatives considered

- **A single mechanism** (notifications routed through the queue): notifications have no
  future date; giving them one would complicate the order within a tick.
- **Unspecified order for simultaneous events:** not reproducible.
- **Accepting events for the tick being processed** and releasing them in the same tick:
  more flexible, but the position of an event added during processing would need its own
  rule. The strict rule fixes the order of a tick before it starts. It can be relaxed later
  if the model needs it; the reverse would be harder.
- **No cancellation** (each component checks whether an event is still valid): error-prone.
  **Eager removal from the heap:** slower and more complex, for no benefit here.
- **Delivery by `isinstance`** (subclasses included): less predictable as event classes
  multiply.
- **Asynchronous or parallel handlers:** order no longer guaranteed. **Logging handler
  errors and continuing:** a run could end "normally" with wrong or incomplete outputs.

## Consequences

- A chain of scheduled events takes at least one tick (5 minutes) per link.
- Property-based tests check total order, that every pending event is released exactly
  once at its own tick, that cancelled events are never released, and the delivery order
  of the bus.
- A failing output handler stops the run instead of silently corrupting results.
