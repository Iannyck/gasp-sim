"""Example-based tests of the event queue and the notification bus (gasp_sim.core.events)."""

from dataclasses import dataclass

import pytest

from gasp_sim.core.events import EventBus, EventQueue, ScheduledEvent

# --------------------------------------------------------------------------- queue


def events_of(released: list[ScheduledEvent[str]]) -> list[str]:
    return [scheduled.event for scheduled in released]


def test_events_are_released_by_tick_then_priority_then_scheduling_order() -> None:
    queue = EventQueue[str]()
    queue.schedule("b-late", 3, priority=1)
    queue.schedule("a", 2, priority=5)
    queue.schedule("b-first", 3, priority=0)
    queue.schedule("b-tie-1", 3, priority=1)
    queue.schedule("b-tie-2", 3, priority=1)

    assert events_of(queue.pop_due(0)) == []
    assert events_of(queue.pop_due(2)) == ["a"]
    assert events_of(queue.pop_due(3)) == ["b-first", "b-late", "b-tie-1", "b-tie-2"]
    assert len(queue) == 0


def test_released_events_carry_their_scheduling_information() -> None:
    queue = EventQueue[str]()
    handle = queue.schedule("x", 4, priority=-2)
    (released,) = queue.pop_due(4)
    assert released.handle == handle
    assert (released.tick, released.priority, released.event) == (4, -2, "x")


def test_tick_zero_can_be_scheduled_before_the_first_release() -> None:
    queue = EventQueue[str]()
    assert queue.current_tick is None
    queue.schedule("start", 0)
    assert events_of(queue.pop_due(0)) == ["start"]
    assert queue.current_tick == 0


def test_only_future_ticks_can_be_scheduled() -> None:
    queue = EventQueue[str]()
    queue.pop_due(5)
    with pytest.raises(ValueError, match="only later ticks"):
        queue.schedule("now", 5)
    with pytest.raises(ValueError, match="only later ticks"):
        queue.schedule("past", 3)
    queue.schedule("next", 6)
    assert events_of(queue.pop_due(6)) == ["next"]


def test_a_released_tick_cannot_be_released_again() -> None:
    queue = EventQueue[str]()
    queue.pop_due(1)
    with pytest.raises(ValueError, match="already been released"):
        queue.pop_due(1)
    with pytest.raises(ValueError, match="already been released"):
        queue.pop_due(0)


def test_releasing_a_tick_cannot_skip_pending_events() -> None:
    queue = EventQueue[str]()
    queue.schedule("pending", 2)
    with pytest.raises(ValueError, match="would be skipped"):
        queue.pop_due(3)
    assert queue.current_tick is None
    assert events_of(queue.pop_due(2)) == ["pending"]


def test_cancelled_events_are_never_released_and_not_counted() -> None:
    queue = EventQueue[str]()
    keep = queue.schedule("keep", 1)
    drop = queue.schedule("drop", 1)
    assert len(queue) == 2
    assert queue.cancel(drop) is True
    assert len(queue) == 1
    assert events_of(queue.pop_due(1)) == ["keep"]
    assert queue.cancel(keep) is False  # already released


def test_cancelling_twice_has_no_effect() -> None:
    queue = EventQueue[str]()
    handle = queue.schedule("x", 1)
    assert queue.cancel(handle) is True
    assert queue.cancel(handle) is False
    assert len(queue) == 0


def test_cancelled_events_do_not_block_later_ticks() -> None:
    queue = EventQueue[str]()
    queue.cancel(queue.schedule("cancelled", 2))
    queue.schedule("later", 5)
    assert queue.peek_tick() == 5
    assert events_of(queue.pop_due(5)) == ["later"]


def test_peek_tick() -> None:
    queue = EventQueue[str]()
    assert queue.peek_tick() is None
    queue.schedule("x", 7)
    queue.schedule("y", 3)
    assert queue.peek_tick() == 3


def test_handle_from_another_queue_is_rejected() -> None:
    first, second = EventQueue[str](), EventQueue[str]()
    handle = first.schedule("x", 1)
    with pytest.raises(ValueError, match="another event queue"):
        second.cancel(handle)


@pytest.mark.parametrize("tick", [-1, 1.0, True, "1"])
def test_invalid_tick_is_rejected(tick: object) -> None:
    queue = EventQueue[str]()
    with pytest.raises(ValueError, match="tick"):
        queue.schedule("x", tick)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tick"):
        queue.pop_due(tick)  # type: ignore[arg-type]


@pytest.mark.parametrize("priority", [0.5, True, None])
def test_invalid_priority_is_rejected(priority: object) -> None:
    with pytest.raises(ValueError, match="priority"):
        EventQueue[str]().schedule("x", 1, priority=priority)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- bus


@dataclass(frozen=True)
class MessagePublished:
    sender: int


@dataclass(frozen=True)
class TaskBlocked:
    agent: int


@dataclass(frozen=True)
class UrgentMessagePublished(MessagePublished):
    pass


def test_handlers_are_called_in_subscription_order() -> None:
    bus = EventBus()
    calls: list[str] = []
    bus.subscribe(MessagePublished, lambda event: calls.append(f"first:{event.sender}"))
    bus.subscribe_all(lambda event: calls.append("all"))
    bus.subscribe(MessagePublished, lambda event: calls.append(f"second:{event.sender}"))
    bus.publish(MessagePublished(sender=3))
    assert calls == ["first:3", "all", "second:3"]


def test_handlers_receive_only_their_exact_type() -> None:
    bus = EventBus()
    messages: list[object] = []
    blocked: list[object] = []
    bus.subscribe(MessagePublished, messages.append)
    bus.subscribe(TaskBlocked, blocked.append)
    bus.publish(MessagePublished(1))
    bus.publish(TaskBlocked(2))
    bus.publish(UrgentMessagePublished(3))  # subclass: not delivered to MessagePublished
    assert messages == [MessagePublished(1)]
    assert blocked == [TaskBlocked(2)]


def test_subscribe_all_receives_everything() -> None:
    bus = EventBus()
    seen: list[object] = []
    bus.subscribe_all(seen.append)
    bus.publish(MessagePublished(1))
    bus.publish("anything")
    assert seen == [MessagePublished(1), "anything"]


def test_unsubscribe() -> None:
    bus = EventBus()
    seen: list[object] = []
    subscription = bus.subscribe(MessagePublished, seen.append)
    assert bus.unsubscribe(subscription) is True
    assert bus.unsubscribe(subscription) is False
    bus.publish(MessagePublished(1))
    assert seen == []


def test_unsubscribe_removes_only_the_given_subscription() -> None:
    bus = EventBus()
    calls: list[str] = []
    bus.subscribe_all(lambda event: calls.append("first"))
    middle = bus.subscribe_all(lambda event: calls.append("middle"))
    bus.subscribe_all(lambda event: calls.append("last"))
    assert bus.unsubscribe(middle) is True
    bus.publish("x")
    assert calls == ["first", "last"]


def test_subscription_from_another_bus_is_rejected() -> None:
    subscription = EventBus().subscribe_all(print)
    with pytest.raises(ValueError, match="another event bus"):
        EventBus().unsubscribe(subscription)


def test_handler_errors_propagate_and_stop_delivery() -> None:
    bus = EventBus()
    calls: list[str] = []

    def failing(event: object) -> None:
        raise RuntimeError("recorder failed")

    bus.subscribe_all(lambda event: calls.append("before"))
    bus.subscribe_all(failing)
    bus.subscribe_all(lambda event: calls.append("after"))
    with pytest.raises(RuntimeError, match="recorder failed"):
        bus.publish("x")
    assert calls == ["before"]


def test_subscriptions_made_during_delivery_apply_from_the_next_publication() -> None:
    bus = EventBus()
    calls: list[str] = []

    def subscribe_another(event: object) -> None:
        calls.append("first")
        bus.subscribe_all(lambda event: calls.append("late"))

    subscription = bus.subscribe_all(subscribe_another)
    bus.publish("one")
    assert calls == ["first"]
    bus.unsubscribe(subscription)
    bus.publish("two")
    assert calls == ["first", "late"]


def test_nested_publication_is_delivered_immediately() -> None:
    bus = EventBus()
    calls: list[str] = []

    def on_message(event: MessagePublished) -> None:
        calls.append("message")
        bus.publish(TaskBlocked(event.sender))

    bus.subscribe(MessagePublished, on_message)
    bus.subscribe(TaskBlocked, lambda event: calls.append("blocked"))
    bus.subscribe(MessagePublished, lambda event: calls.append("message-2"))
    bus.publish(MessagePublished(1))
    assert calls == ["message", "blocked", "message-2"]


def test_invalid_subscriptions_are_rejected() -> None:
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type"):
        bus.subscribe("MessagePublished", print)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="handler"):
        bus.subscribe_all("not callable")  # type: ignore[arg-type]
