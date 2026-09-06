# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError

import pytest

from grass.core import (
    Branch,
    BranchId,
    CommittedTransition,
    HistoryPosition,
    InMemoryEventStore,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
)
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def commit_facts(
    store: InMemoryEventStore,
    branch: str,
    transition: str,
    logical_time: int,
    *event_labels: str,
) -> CommittedTransition:
    return store.commit_transition(
        transition_to_commit(
            branch,
            transition,
            logical_time,
            [event_to_commit(label) for label in event_labels],
        )
    )


def test_history_position_and_branch_are_immutable_syntactic_values() -> None:
    parent_id = BranchId("parent")
    child_id = BranchId("child")
    inherited_ref = TransitionRef(BranchId("ancestor"), TransitionId("transition"))
    position = HistoryPosition(parent_id, inherited_ref)
    root = Branch(parent_id)
    child = Branch(child_id, position)

    assert root.parent_branch_id is None
    assert child.parent_branch_id == parent_id
    assert child.fork_position == position
    assert position.transition_ref == inherited_ref
    with pytest.raises(FrozenInstanceError):
        position.branch_id = child_id  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        child.fork_position = None  # type: ignore[misc]
    with pytest.raises(ValueError, match="committed-transition fork"):
        Branch(child_id, HistoryPosition(parent_id))
    with pytest.raises(ValueError, match="own parent"):
        Branch(parent_id, position)


def test_root_registration_is_explicit_and_unknown_commit_consumes_nothing() -> None:
    store = InMemoryEventStore()
    branch_id = stable_id(BranchId, "root")
    candidate = transition_to_commit("root", "first", 1, [event_to_commit("root:first")])

    with pytest.raises(ValueError, match="has not been registered"):
        store.commit_transition(candidate)

    root = store.create_root_branch(branch_id)
    committed = store.commit_transition(candidate)

    assert root == Branch(branch_id)
    assert store.read_branch(branch_id) == root
    assert committed.events[0].sequence == 1
    assert store.head_position(branch_id) == HistoryPosition(branch_id, committed.transition_ref)
    with pytest.raises(ValueError, match="already been registered"):
        store.create_root_branch(branch_id)


def test_empty_root_position_is_valid_but_empty_child_fork_is_rejected() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")

    assert store.head_position(root_id) == HistoryPosition(root_id)
    assert store.read_visible_transitions(HistoryPosition(root_id)) == ()
    with pytest.raises(ValueError, match="committed-transition fork"):
        store.fork_branch(stable_id(BranchId, "child"), HistoryPosition(root_id))


def test_fork_captures_complete_immutable_prefix_and_local_continuation() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    first = commit_facts(store, "root", "first", 10, "first:a", "first:b")
    second = commit_facts(store, "root", "second", 11, "second")
    fork_position = HistoryPosition(root_id, first.transition_ref)

    child = store.fork_branch(child_id, fork_position)
    parent_snapshot = store.read_visible_transitions(
        HistoryPosition(root_id, second.transition_ref)
    )
    later_parent = commit_facts(store, "root", "later", 12, "later")
    child_local = commit_facts(store, "child", "local", 10, "child:local")

    visible = store.read_visible_transitions(store.head_position(child_id))
    assert child == Branch(child_id, fork_position)
    assert store.read_transitions(child_id) == (child_local,)
    assert visible == (first, child_local)
    assert visible[0] is first
    assert len(visible[0].events) == 2
    assert child_local.events[0].sequence == 1
    assert parent_snapshot == (first, second)
    assert later_parent not in visible


def test_first_child_commit_cannot_precede_fork_and_rejection_consumes_nothing() -> None:
    store = rooted_store("root")
    root = commit_facts(store, "root", "fork", 20, "root:event")
    child_id = stable_id(BranchId, "child")
    store.fork_branch(
        child_id,
        HistoryPosition(stable_id(BranchId, "root"), root.transition_ref),
    )
    candidate = transition_to_commit("child", "first", 19, [event_to_commit("child:event")])

    with pytest.raises(ValueError, match="must not precede the fork"):
        store.commit_transition(candidate)

    accepted = store.commit_transition(
        TransitionToCommit(
            candidate.transition_ref,
            root.logical_time,
            candidate.events,
        )
    )
    assert accepted.events[0].sequence == 1


def test_fork_rejects_unknown_and_non_visible_transition_references() -> None:
    store = rooted_store("a", "b")
    a_id = stable_id(BranchId, "a")
    b_transition = commit_facts(store, "b", "only-b", 1, "b:event")

    with pytest.raises(ValueError, match="has not been registered"):
        store.fork_branch(
            stable_id(BranchId, "child-unknown"),
            HistoryPosition(stable_id(BranchId, "unknown"), b_transition.transition_ref),
        )
    with pytest.raises(ValueError, match="not visible"):
        store.fork_branch(
            stable_id(BranchId, "child-sibling"),
            HistoryPosition(a_id, b_transition.transition_ref),
        )
    with pytest.raises(ValueError, match="not visible"):
        store.fork_branch(
            stable_id(BranchId, "child-missing"),
            HistoryPosition(
                a_id,
                TransitionRef(a_id, stable_id(TransitionId, "missing")),
            ),
        )


def test_nested_branches_can_fork_at_local_or_inherited_visible_transitions() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    parent_id = stable_id(BranchId, "parent")
    grandchild_id = stable_id(BranchId, "grandchild")
    rewound_id = stable_id(BranchId, "rewound")
    first = commit_facts(store, "root", "first", 1, "root:first")
    second = commit_facts(store, "root", "second", 2, "root:second")
    store.fork_branch(parent_id, HistoryPosition(root_id, second.transition_ref))
    parent_local = commit_facts(store, "parent", "local", 3, "parent:local")

    store.fork_branch(grandchild_id, HistoryPosition(parent_id, parent_local.transition_ref))
    store.fork_branch(rewound_id, HistoryPosition(parent_id, first.transition_ref))

    assert store.read_visible_transitions(store.head_position(grandchild_id)) == (
        first,
        second,
        parent_local,
    )
    assert store.read_visible_transitions(store.head_position(rewound_id)) == (first,)


def test_nested_child_time_floor_uses_inherited_fork_transition() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    parent_id = stable_id(BranchId, "parent")
    child_id = stable_id(BranchId, "child")
    inherited = commit_facts(store, "root", "inherited", 10, "root:inherited")
    later = commit_facts(store, "root", "later", 20, "root:later")
    store.fork_branch(parent_id, HistoryPosition(root_id, later.transition_ref))
    store.fork_branch(child_id, HistoryPosition(parent_id, inherited.transition_ref))

    with pytest.raises(ValueError, match="must not precede the fork"):
        commit_facts(store, "child", "too-early", 9, "child:too-early")

    accepted = commit_facts(store, "child", "accepted", 10, "child:accepted")
    assert accepted.events[0].sequence == 1


def test_parent_child_and_sibling_continuations_are_isolated() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    sibling_id = stable_id(BranchId, "sibling")
    shared = commit_facts(store, "root", "shared", 1, "root:shared")
    fork = HistoryPosition(root_id, shared.transition_ref)
    store.fork_branch(child_id, fork)
    store.fork_branch(sibling_id, fork)

    parent_local = commit_facts(store, "root", "parent", 2, "root:parent")
    child_local = commit_facts(store, "child", "child", 2, "child:event")
    sibling_local = commit_facts(store, "sibling", "sibling", 2, "sibling:event")

    assert store.read_visible_transitions(store.head_position(root_id)) == (
        shared,
        parent_local,
    )
    assert store.read_visible_transitions(store.head_position(child_id)) == (
        shared,
        child_local,
    )
    assert store.read_visible_transitions(store.head_position(sibling_id)) == (
        shared,
        sibling_local,
    )
