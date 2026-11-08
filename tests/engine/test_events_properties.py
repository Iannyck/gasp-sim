"""Property-based tests of the event queue and the notification bus (ADR-0011).

Guarantees checked on arbitrary schedules:

- events are released in total order: tick, then priority, then order of scheduling;
- every pending event is released exactly once, at its own tick, never earlier;
- cancelled events are never released, and cancelling does not change the order of the
  others;
- the bus calls matching handlers in order of subscription.
"""

from hypothesis import given
from hypothesis import strategies as st

from gasp_sim.core.events import EventBus, EventQueue

MAX_TICK = 40

# (tick, priority, cancel?) for each scheduled event.
schedules = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=MAX_TICK),
        st.integers(min_value=-3, max_value=3),
        st.booleans(),
    ),
    max_size=60,
)


def drain(queue: EventQueue[int], last_tick: int) -> list[tuple[int, int, int]]:
    """Release ticks 0..last_tick and return (tick, priority, event) in release order."""
    released = []
    for tick in range(last_tick + 1):
        for scheduled in queue.pop_due(tick):
            assert scheduled.tick == tick
            released.append((scheduled.tick, scheduled.priority, scheduled.event))
    return released


@given(entries=schedules)
def test_active_events_are_released_once_in_total_order(
    entries: list[tuple[int, int, bool]],
) -> None:
    queue = EventQueue[int]()
    handles = [queue.schedule(i, tick, priority=prio) for i, (tick, prio, _) in enumerate(entries)]
    for handle, (_, _, cancel) in zip(handles, entries, strict=True):
        if cancel:
            assert queue.cancel(handle) is True

    expected = sorted(
        (tick, prio, i) for i, (tick, prio, cancel) in enumerate(entries) if not cancel
    )
    assert len(queue) == len(expected)
    assert drain(queue, MAX_TICK) == expected
    assert len(queue) == 0
    assert queue.peek_tick() is None


@given(
    initial=schedules,
    follow_ups=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=10),  # delay after the releasing tick
            st.integers(min_value=-3, max_value=3),
        ),
        max_size=40,
    ),
)
def test_events_scheduled_while_draining_are_released_in_order(
    initial: list[tuple[int, int, bool]],
    follow_ups: list[tuple[int, int]],
) -> None:
    """Events scheduled from inside a tick (always for a later tick) keep the total order."""
    queue = EventQueue[int]()
    expected: list[tuple[int, int, int]] = []
    next_id = 0
    for tick, prio, _ in initial:
        queue.schedule(next_id, tick, priority=prio)
        expected.append((tick, prio, next_id))
        next_id += 1

    released: list[tuple[int, int, int]] = []
    plan = list(follow_ups)
    last_tick = MAX_TICK + 10
    for tick in range(last_tick + 1):
        for scheduled in queue.pop_due(tick):
            released.append((scheduled.tick, scheduled.priority, scheduled.event))
            if plan:
                delay, prio = plan.pop(0)
                target = tick + delay
                if target <= last_tick:
                    queue.schedule(next_id, target, priority=prio)
                    expected.append((target, prio, next_id))
                    next_id += 1

    assert released == sorted(expected)


@given(entries=schedules, cancel_after=st.integers(min_value=0, max_value=MAX_TICK))
def test_cancelling_reports_whether_the_event_was_still_pending(
    entries: list[tuple[int, int, bool]], cancel_after: int
) -> None:
    queue = EventQueue[int]()
    handles = [queue.schedule(i, tick, priority=prio) for i, (tick, prio, _) in enumerate(entries)]
    for tick in range(cancel_after + 1):
        queue.pop_due(tick)
    for handle in handles:
        assert queue.cancel(handle) is (handle.tick > cancel_after)
    assert len(queue) == 0


@given(
    subscriptions=st.lists(st.sampled_from(["A", "B", "all"]), max_size=12),
    publications=st.lists(st.sampled_from(["A", "B"]), max_size=12),
)
def test_bus_calls_matching_handlers_in_subscription_order(
    subscriptions: list[str], publications: list[str]
) -> None:
    class A:
        pass

    class B:
        pass

    types = {"A": A, "B": B}
    bus = EventBus()
    calls: list[tuple[int, str]] = []
    for index, kind in enumerate(subscriptions):

        def handler(event: object, index: int = index) -> None:
            calls.append((index, type(event).__name__))

        if kind == "all":
            bus.subscribe_all(handler)
        else:
            bus.subscribe(types[kind], handler)

    for name in publications:
        bus.publish(types[name]())

    expected = [
        (index, name)
        for name in publications
        for index, kind in enumerate(subscriptions)
        if kind in ("all", name)
    ]
    assert calls == expected
