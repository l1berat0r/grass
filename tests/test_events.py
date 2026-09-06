# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import (
    BranchId,
    CauseRef,
    CommittedTransition,
    CorrelationId,
    Event,
    EventId,
    EventPayload,
    EventToCommit,
    LogicalTime,
    Provenance,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
)
from tests.support import event_to_commit


def committed_event(
    label: str,
    sequence: int,
    *,
    branch: str = "branch",
    transition: str = "transition",
    logical_time: int = 10,
) -> Event:
    return Event(
        event_id=EventId(label),
        branch_id=BranchId(branch),
        sequence=sequence,
        logical_time=LogicalTime(logical_time),
        transition_id=TransitionId(transition),
        event_type="TestFactRecorded",
        event_version=1,
        payload={},
        provenance=Provenance("ENGINE"),
    )


def test_cause_reference_is_opaque_immutable_and_non_empty() -> None:
    cause = CauseRef("event", "opaque:event/value")

    assert cause.kind == "event"
    assert cause.value == "opaque:event/value"
    with pytest.raises(FrozenInstanceError):
        cause.value = "other"  # type: ignore[misc]
    with pytest.raises(ValueError, match="cause kind must not be empty"):
        CauseRef("", "value")
    with pytest.raises(ValueError, match="cause value must not be empty"):
        CauseRef("kind", "")


def test_event_to_commit_freezes_payload_and_causation_refs() -> None:
    details: dict[str, EventPayload | str | list[int]] = {
        "name": "before",
        "values": [1, 2],
    }
    payload = cast(EventPayload, {"details": details})
    causes = [CauseRef("event", "one")]

    record = event_to_commit("event", payload=payload, causation_refs=causes)
    details["name"] = "after"
    cast(list[int], details["values"]).append(3)
    causes.append(CauseRef("event", "two"))

    frozen_details = record.payload["details"]
    assert isinstance(frozen_details, Mapping)
    assert frozen_details == {"name": "before", "values": (1, 2)}
    assert record.causation_refs == (CauseRef("event", "one"),)
    with pytest.raises(TypeError):
        cast(dict[str, object], record.payload)["new"] = True


@pytest.mark.parametrize("event_type", ["", cast(str, 1)])
def test_event_to_commit_rejects_invalid_event_type(event_type: str) -> None:
    error = ValueError if event_type == "" else TypeError
    with pytest.raises(error):
        event_to_commit("event", event_type=event_type)


@pytest.mark.parametrize("event_version", [0, -1])
def test_event_to_commit_requires_positive_event_version(event_version: int) -> None:
    with pytest.raises(ValueError, match="event_version must be positive"):
        event_to_commit("event", event_version=event_version)


def test_event_to_commit_rejects_boolean_event_version() -> None:
    with pytest.raises(TypeError, match="event_version must be an integer"):
        event_to_commit("event", event_version=cast(int, True))


def test_event_to_commit_requires_provenance() -> None:
    with pytest.raises(TypeError, match="provenance must be Provenance"):
        EventToCommit(
            EventId("event"),
            "TestFactRecorded",
            1,
            {},
            cast(Provenance, None),
        )


def test_transition_to_commit_is_non_empty_and_copies_records() -> None:
    transition_ref = TransitionRef(BranchId("branch"), TransitionId("transition"))
    records = [event_to_commit("event")]
    transition = TransitionToCommit(transition_ref, LogicalTime(10), records)
    records.append(event_to_commit("later"))

    assert transition.events == (event_to_commit("event"),)
    with pytest.raises(ValueError, match="at least one Event"):
        TransitionToCommit(transition_ref, LogicalTime(10), [])


def test_committed_transition_derives_identity_and_time_from_events() -> None:
    events = (committed_event("one", 3), committed_event("two", 4))
    committed = CommittedTransition(events)

    assert committed.events == events
    assert committed.branch_id == BranchId("branch")
    assert committed.transition_id == TransitionId("transition")
    assert committed.transition_ref == TransitionRef(BranchId("branch"), TransitionId("transition"))
    assert committed.logical_time == LogicalTime(10)


@pytest.mark.parametrize(
    "events, message",
    [
        ((), "at least one Event"),
        ((committed_event("one", 1), committed_event("two", 3)), "must be contiguous"),
        (
            (committed_event("one", 1), committed_event("two", 2, branch="other")),
            "share one branch_id",
        ),
        (
            (committed_event("one", 1), committed_event("two", 2, transition="other")),
            "share one transition_id",
        ),
        (
            (committed_event("one", 1), committed_event("two", 2, logical_time=11)),
            "share one logical_time",
        ),
    ],
)
def test_committed_transition_rejects_incoherent_events(
    events: tuple[Event, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        CommittedTransition(events)


def test_event_keeps_causation_and_correlation_explicit() -> None:
    cause = CauseRef("event", "cause")
    correlation_id = CorrelationId("correlation")
    event = Event(
        event_id=EventId("event"),
        branch_id=BranchId("branch"),
        sequence=1,
        logical_time=LogicalTime(10),
        transition_id=TransitionId("transition"),
        event_type="TestFactRecorded",
        event_version=1,
        payload={},
        provenance=Provenance("ENGINE"),
        causation_refs=[cause],
        correlation_id=correlation_id,
    )

    assert event.causation_refs == (cause,)
    assert event.correlation_id == correlation_id


def test_event_is_immutable_and_unhashable() -> None:
    event = committed_event("event", 1)

    with pytest.raises(FrozenInstanceError):
        event.sequence = 2  # type: ignore[misc]
    with pytest.raises(TypeError, match="unhashable type"):
        hash(event)
