# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Sequence
from dataclasses import FrozenInstanceError

import pytest

from grass.core import (
    BranchId,
    CommittedTransition,
    EntityId,
    EventPayload,
    HistoryPosition,
    InMemoryEventStore,
    ProjectionPosition,
    ResourceKey,
    SimulationState,
    StateCheckpoint,
    replay_branch,
)
from grass.core.world_events import ENTITY_CREATED, ENTITY_UPDATED, RESOURCE_CHANGED
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def commit_world_transition(
    store: InMemoryEventStore,
    branch: str,
    transition: str,
    logical_time: int,
    events: Sequence[tuple[str, EventPayload]],
) -> CommittedTransition:
    return store.commit_transition(
        transition_to_commit(
            branch,
            transition,
            logical_time,
            [
                event_to_commit(
                    f"{branch}:{transition}:{index}",
                    event_type=event_type,
                    payload=payload,
                )
                for index, (event_type, payload) in enumerate(events)
            ],
        )
    )


def create_entity(entity_id: str, value: str) -> tuple[str, EventPayload]:
    return (
        ENTITY_CREATED,
        {
            "entity_id": entity_id,
            "entity_type": "Person",
            "properties": {"value": value},
        },
    )


def update_entity(entity_id: str, value: str) -> tuple[str, EventPayload]:
    return (
        ENTITY_UPDATED,
        {"entity_id": entity_id, "properties_after": {"value": value}},
    )


class StaticCheckpointLoader:
    def __init__(self, checkpoint: StateCheckpoint | None) -> None:
        self.checkpoint = checkpoint
        self.targets: list[HistoryPosition] = []

    def load_checkpoint(self, target: HistoryPosition, /) -> StateCheckpoint | None:
        self.targets.append(target)
        return self.checkpoint


def test_replay_reconstructs_root_and_exact_historical_position() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    created = commit_world_transition(
        store, "root", "create", 1, [create_entity("entity", "created")]
    )
    updated = commit_world_transition(
        store, "root", "update", 2, [update_entity("entity", "updated")]
    )

    earlier = replay_branch(store, HistoryPosition(root_id, created.transition_ref))
    head = replay_branch(store, HistoryPosition(root_id, updated.transition_ref))

    assert earlier.world.entities[EntityId("entity")].properties == {"value": "created"}
    assert earlier.position.last_transition_ref == created.transition_ref
    assert head.world.entities[EntityId("entity")].properties == {"value": "updated"}
    assert head.position.last_transition_ref == updated.transition_ref


def test_replay_child_without_local_events_carries_prefix_and_resets_local_position() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    created = commit_world_transition(
        store, "root", "create", 5, [create_entity("entity", "shared")]
    )
    store.fork_branch(child_id, HistoryPosition(root_id, created.transition_ref))

    state = replay_branch(store, store.head_position(child_id))

    assert state.world.entities[EntityId("entity")].properties == {"value": "shared"}
    assert state.position == ProjectionPosition(child_id)


def test_parent_and_child_replay_diverge_without_mutating_shared_prefix() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    shared = commit_world_transition(
        store, "root", "shared", 1, [create_entity("entity", "shared")]
    )
    store.fork_branch(child_id, HistoryPosition(root_id, shared.transition_ref))
    commit_world_transition(store, "root", "parent-update", 2, [update_entity("entity", "parent")])
    child_local = commit_world_transition(
        store, "child", "child-update", 2, [update_entity("entity", "child")]
    )

    parent_state = replay_branch(store, store.head_position(root_id))
    child_state = replay_branch(store, store.head_position(child_id))
    inherited_state = replay_branch(store, HistoryPosition(child_id, shared.transition_ref))

    assert parent_state.world.entities[EntityId("entity")].properties == {"value": "parent"}
    assert child_state.world.entities[EntityId("entity")].properties == {"value": "child"}
    assert inherited_state.world.entities[EntityId("entity")].properties == {"value": "shared"}
    assert child_state.position.last_transition_ref == child_local.transition_ref
    assert inherited_state.position == ProjectionPosition(child_id)


def test_nested_branch_replay_applies_each_origin_segment_once() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    parent_id = stable_id(BranchId, "parent")
    grandchild_id = stable_id(BranchId, "grandchild")
    root = commit_world_transition(store, "root", "create", 1, [create_entity("entity", "root")])
    store.fork_branch(parent_id, HistoryPosition(root_id, root.transition_ref))
    parent = commit_world_transition(
        store, "parent", "update", 2, [update_entity("entity", "parent")]
    )
    store.fork_branch(grandchild_id, HistoryPosition(parent_id, parent.transition_ref))
    grandchild = commit_world_transition(
        store,
        "grandchild",
        "resource",
        3,
        [
            (
                RESOURCE_CHANGED,
                {
                    "entity_id": "entity",
                    "resource_type": "balance",
                    "quantity_after": 7,
                },
            )
        ],
    )

    state = replay_branch(store, store.head_position(grandchild_id))

    assert state.world.entities[EntityId("entity")].properties == {"value": "parent"}
    assert state.world.resources[ResourceKey(EntityId("entity"), "balance")] == 7
    assert state.position.last_transition_ref == grandchild.transition_ref
    assert state.position.last_sequence == 1


def test_empty_root_replay_requires_no_events() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")

    assert replay_branch(store, HistoryPosition(root_id)) == SimulationState.empty(root_id)


def test_checkpoint_assisted_replay_matches_full_reconstruction() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    first = commit_world_transition(store, "root", "create", 1, [create_entity("entity", "first")])
    second = commit_world_transition(
        store, "root", "update", 2, [update_entity("entity", "second")]
    )
    store.fork_branch(child_id, HistoryPosition(root_id, second.transition_ref))
    commit_world_transition(
        store,
        "child",
        "resource",
        3,
        [
            (
                RESOURCE_CHANGED,
                {
                    "entity_id": "entity",
                    "resource_type": "balance",
                    "quantity_after": 4,
                },
            )
        ],
    )
    checkpoint_position = HistoryPosition(root_id, first.transition_ref)
    checkpoint = StateCheckpoint(
        checkpoint_position,
        replay_branch(store, checkpoint_position),
    )
    loader = StaticCheckpointLoader(checkpoint)
    target = store.head_position(child_id)

    full = replay_branch(store, target)
    assisted = replay_branch(store, target, loader)

    assert assisted == full
    assert loader.targets == [target]


def test_checkpoint_at_inherited_child_position_can_resume_child_sequence() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    shared = commit_world_transition(
        store, "root", "create", 1, [create_entity("entity", "shared")]
    )
    store.fork_branch(child_id, HistoryPosition(root_id, shared.transition_ref))
    commit_world_transition(store, "child", "update", 2, [update_entity("entity", "child")])
    inherited_position = HistoryPosition(child_id, shared.transition_ref)
    checkpoint = StateCheckpoint(
        inherited_position,
        replay_branch(store, inherited_position),
    )
    target = store.head_position(child_id)

    assert replay_branch(store, target, StaticCheckpointLoader(checkpoint)) == replay_branch(
        store, target
    )


def test_cross_view_checkpoint_returns_canonical_target_projection_position() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    shared = commit_world_transition(
        store, "root", "create", 1, [create_entity("entity", "shared")]
    )
    root_position = HistoryPosition(root_id, shared.transition_ref)
    store.fork_branch(child_id, root_position)
    child_position = HistoryPosition(child_id, shared.transition_ref)
    checkpoint = StateCheckpoint(
        child_position,
        replay_branch(store, child_position),
    )

    assisted = replay_branch(store, root_position, StaticCheckpointLoader(checkpoint))
    full = replay_branch(store, root_position)

    assert assisted == full
    assert assisted.position.last_transition_ref == shared.transition_ref
    assert assisted.position.last_sequence == 1


def test_checkpoint_loader_may_decline_optimization() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    transition = commit_world_transition(
        store, "root", "create", 1, [create_entity("entity", "value")]
    )
    target = HistoryPosition(root_id, transition.transition_ref)

    assert replay_branch(store, target, StaticCheckpointLoader(None)) == replay_branch(
        store, target
    )


def test_replay_rejects_checkpoint_that_is_not_a_target_prefix() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    first = commit_world_transition(store, "root", "create", 1, [create_entity("entity", "first")])
    second = commit_world_transition(
        store, "root", "update", 2, [update_entity("entity", "second")]
    )
    checkpoint_position = HistoryPosition(root_id, second.transition_ref)
    checkpoint = StateCheckpoint(
        checkpoint_position,
        replay_branch(store, checkpoint_position),
    )

    with pytest.raises(ValueError, match="not a prefix"):
        replay_branch(
            store,
            HistoryPosition(root_id, first.transition_ref),
            StaticCheckpointLoader(checkpoint),
        )


def test_replay_rejects_checkpoint_with_incoherent_projection_position() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    transition = commit_world_transition(
        store, "root", "create", 1, [create_entity("entity", "value")]
    )
    target = HistoryPosition(root_id, transition.transition_ref)
    checkpoint = StateCheckpoint(target, SimulationState.empty(root_id))

    with pytest.raises(ValueError, match="does not match canonical history"):
        replay_branch(store, target, StaticCheckpointLoader(checkpoint))


def test_state_checkpoint_is_immutable() -> None:
    root_id = stable_id(BranchId, "root")
    checkpoint = StateCheckpoint(HistoryPosition(root_id), SimulationState.empty(root_id))

    with pytest.raises(FrozenInstanceError):
        checkpoint.state = SimulationState.empty(root_id)  # type: ignore[misc]
