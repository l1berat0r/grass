# SPDX-License-Identifier: GPL-3.0-only

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import (
    BranchId,
    CauseRef,
    CorrelationId,
    EventId,
    LogicalTime,
    Provenance,
    ProvenanceSourceRef,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
)
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def test_store_assigns_contiguous_branch_local_sequences_in_submitted_order() -> None:
    store = rooted_store("branch")

    first = store.commit_transition(
        transition_to_commit(
            "branch",
            "first",
            10,
            [event_to_commit("one"), event_to_commit("two")],
        )
    )
    second = store.commit_transition(
        transition_to_commit("branch", "second", 11, [event_to_commit("three")])
    )

    assert [event.event_id for event in first.events] == [
        stable_id(EventId, "one"),
        stable_id(EventId, "two"),
    ]
    assert [event.sequence for event in first.events] == [1, 2]
    assert [event.sequence for event in second.events] == [3]
    assert store.read_transitions(stable_id(BranchId, "branch")) == (first, second)


def test_branch_sequences_include_only_events_originating_on_that_branch() -> None:
    store = rooted_store("a", "b")

    branch_a = store.commit_transition(
        transition_to_commit("a", "shared-value", 10, [event_to_commit("a-event")])
    )
    branch_b = store.commit_transition(
        transition_to_commit("b", "shared-value", 20, [event_to_commit("b-event")])
    )

    assert branch_a.events[0].sequence == 1
    assert branch_b.events[0].sequence == 1
    assert branch_a.transition_id == branch_b.transition_id
    assert branch_a.transition_ref != branch_b.transition_ref


def test_reusing_committed_transition_ref_fails_without_consuming_sequence() -> None:
    store = rooted_store("branch")
    committed = transition_to_commit("branch", "transition", 10, [event_to_commit("one")])
    store.commit_transition(committed)

    with pytest.raises(ValueError, match="already been committed"):
        store.commit_transition(
            transition_to_commit("branch", "transition", 10, [event_to_commit("two")])
        )

    next_transition = store.commit_transition(
        transition_to_commit("branch", "next", 10, [event_to_commit("three")])
    )
    assert next_transition.events[0].sequence == 2


def test_empty_transition_rejection_consumes_nothing() -> None:
    store = rooted_store("branch")
    transition_ref = TransitionRef(
        stable_id(BranchId, "branch"), stable_id(TransitionId, "transition")
    )

    with pytest.raises(ValueError, match="at least one Event"):
        TransitionToCommit(transition_ref, LogicalTime(0), [])

    committed = store.commit_transition(
        TransitionToCommit(
            transition_ref,
            LogicalTime(0),
            [event_to_commit("event")],
        )
    )
    assert committed.events[0].sequence == 1


def test_duplicate_event_ids_within_transition_are_rejected_atomically() -> None:
    store = rooted_store("branch")
    duplicate = event_to_commit("duplicate")
    rejected = transition_to_commit("branch", "rejected", 10, [duplicate, duplicate])

    with pytest.raises(ValueError, match="unique within a transition"):
        store.commit_transition(rejected)

    committed = store.commit_transition(
        transition_to_commit("branch", "rejected", 10, [event_to_commit("accepted")])
    )
    assert committed.events[0].sequence == 1


def test_event_id_is_unique_across_branches() -> None:
    store = rooted_store("a", "b")
    store.commit_transition(transition_to_commit("a", "first", 10, [event_to_commit("same-event")]))

    with pytest.raises(ValueError, match="event_id has already been committed"):
        store.commit_transition(
            transition_to_commit("b", "second", 10, [event_to_commit("same-event")])
        )

    assert store.read_transitions(stable_id(BranchId, "b")) == ()


def test_logical_time_is_shared_equal_and_nondecreasing() -> None:
    store = rooted_store("branch")
    first = store.commit_transition(
        transition_to_commit("branch", "first", 10, [event_to_commit("one")])
    )
    equal = store.commit_transition(
        transition_to_commit("branch", "equal", 10, [event_to_commit("two")])
    )

    assert first.events[0].logical_time == equal.events[0].logical_time
    assert all(event.logical_time == equal.logical_time for event in equal.events)

    with pytest.raises(ValueError, match="must not decrease"):
        store.commit_transition(
            transition_to_commit("branch", "earlier", 9, [event_to_commit("three")])
        )

    accepted = store.commit_transition(
        transition_to_commit("branch", "earlier", 11, [event_to_commit("three")])
    )
    assert accepted.events[0].sequence == 3


def test_causation_is_not_inferred_from_adjacency() -> None:
    store = rooted_store("branch")
    committed = store.commit_transition(
        transition_to_commit(
            "branch",
            "transition",
            10,
            [event_to_commit("one"), event_to_commit("two")],
        )
    )

    assert committed.events[0].causation_refs == ()
    assert committed.events[1].causation_refs == ()


def test_store_preserves_the_complete_event_envelope() -> None:
    store = rooted_store("branch")
    provenance = Provenance(
        "ENGINE",
        ProvenanceSourceRef("operation", "commit"),
        {"mode": "deterministic"},
    )
    cause = CauseRef("event", "cause")
    correlation_id = CorrelationId("correlation")
    record = event_to_commit(
        "event",
        event_type="TestFactRecorded",
        event_version=3,
        payload={"fact": {"value": 42}},
        provenance=provenance,
        causation_refs=[cause],
        correlation_id=correlation_id,
    )

    event = store.commit_transition(
        transition_to_commit("branch", "transition", 10, [record])
    ).events[0]

    assert event.event_id == record.event_id
    assert event.branch_id == stable_id(BranchId, "branch")
    assert event.sequence == 1
    assert event.logical_time == LogicalTime(10)
    assert event.transition_id == stable_id(TransitionId, "transition")
    assert event.event_type == "TestFactRecorded"
    assert event.event_version == 3
    assert event.payload == {"fact": {"value": 42}}
    assert event.provenance == provenance
    assert event.causation_refs == (cause,)
    assert event.correlation_id == correlation_id


def test_reader_snapshots_are_complete_immutable_and_stable() -> None:
    store = rooted_store("branch")
    first = store.commit_transition(
        transition_to_commit(
            "branch",
            "first",
            10,
            [event_to_commit("one"), event_to_commit("two")],
        )
    )
    snapshot = store.read_transitions(stable_id(BranchId, "branch"))

    store.commit_transition(
        transition_to_commit("branch", "second", 11, [event_to_commit("three")])
    )

    assert snapshot == (first,)
    assert len(snapshot[0].events) == 2
    assert len(store.read_transitions(stable_id(BranchId, "branch"))) == 2
    with pytest.raises(FrozenInstanceError):
        snapshot[0].events[0].sequence = 99  # type: ignore[misc]


def test_store_has_no_update_or_delete_operations() -> None:
    store = rooted_store()

    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")


def test_store_rejects_invalid_argument_types() -> None:
    store = rooted_store()

    with pytest.raises(TypeError, match="TransitionToCommit"):
        store.commit_transition(cast(TransitionToCommit, "transition"))
    with pytest.raises(TypeError, match="BranchId"):
        store.read_transitions(cast(BranchId, "branch"))


def test_unknown_branch_is_rejected() -> None:
    store = rooted_store()

    with pytest.raises(ValueError, match="has not been registered"):
        store.read_transitions(stable_id(BranchId, "unknown"))


def test_concurrent_commits_publish_complete_non_overlapping_sequences() -> None:
    store = rooted_store("branch")
    transition_count = 20

    def commit(index: int) -> None:
        store.commit_transition(
            transition_to_commit(
                "branch",
                f"transition-{index}",
                10,
                [
                    event_to_commit(f"event-{index}-a"),
                    event_to_commit(f"event-{index}-b"),
                ],
            )
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(commit, range(transition_count)))

    transitions = store.read_transitions(stable_id(BranchId, "branch"))
    events = tuple(event for transition in transitions for event in transition.events)

    assert len(transitions) == transition_count
    assert all(len(transition.events) == 2 for transition in transitions)
    assert [event.sequence for event in events] == list(range(1, transition_count * 2 + 1))
    assert len({event.event_id for event in events}) == transition_count * 2
