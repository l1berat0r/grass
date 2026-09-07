# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Sequence
from typing import cast

import pytest

from grass.core import (
    BranchId,
    EntityId,
    EntityScope,
    EventId,
    GenesisError,
    HistoryPosition,
    ResourceKey,
    SimulationRunConfig,
    SimulationState,
    StateVariableKey,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    WorldDefinition,
    WorldDefinitionId,
    WorldDefinitionRef,
    WorldScope,
    build_genesis_transition,
    load_world_definition,
    project_transition,
    replay_branch,
)
from grass.core.initialization_events import SIMULATION_INITIALIZED
from grass.core.world_events import (
    ENTITY_CREATED,
    RELATION_CREATED,
    RESOURCE_CHANGED,
    STATE_VARIABLE_CHANGED,
)
from tests.support import rooted_store, stable_id


def world_document(*, empty: bool = False) -> dict[str, object]:
    vocabulary = {
        "entity_types": [] if empty else ["Person"],
        "relation_types": [] if empty else ["Knows"],
        "resource_types": [] if empty else ["balance"],
        "state_variable_types": [] if empty else ["weather", "condition"],
    }
    initial_conditions = {
        "logical_time": 7,
        "entities": []
        if empty
        else [
            {"entity_id": "second", "entity_type": "Person", "properties": {"order": 2}},
            {"entity_id": "first", "entity_type": "Person", "properties": {"order": 1}},
        ],
        "relations": []
        if empty
        else [
            {
                "relation_id": "knows",
                "relation_type": "Knows",
                "participants": [
                    {"role": "subject", "entity_id": "second"},
                    {"role": "object", "entity_id": "first"},
                ],
                "properties": {},
            }
        ],
        "resources": []
        if empty
        else [
            {"entity_id": "second", "resource_type": "balance", "quantity": -3},
        ],
        "state_variables": []
        if empty
        else [
            {
                "scope": {"kind": "WORLD"},
                "state_variable_type": "weather",
                "value": "clear",
            },
            {
                "scope": {"kind": "ENTITY", "entity_id": "first"},
                "state_variable_type": "condition",
                "value": {"ready": True},
            },
        ],
    }
    return {
        "world_definition_id": "world",
        "version": "v1",
        "schema_version": 1,
        "vocabulary": vocabulary,
        "initial_conditions": initial_conditions,
        "metadata": {},
    }


def definition(*, empty: bool = False) -> WorldDefinition:
    return load_world_definition(world_document(empty=empty))


def genesis_ids(count: int) -> tuple[EventId, ...]:
    return tuple(stable_id(EventId, f"genesis:{index}") for index in range(count))


def build(
    world_definition: WorldDefinition,
    event_ids: Sequence[EventId],
    *,
    branch: str = "root",
) -> TransitionToCommit:
    return build_genesis_transition(
        world_definition,
        SimulationRunConfig(world_definition.ref),
        TransitionRef(stable_id(BranchId, branch), stable_id(TransitionId, "genesis")),
        event_ids,
    )


def test_materializes_existing_events_in_deterministic_category_order() -> None:
    transition = build(definition(), genesis_ids(7))

    assert [event.event_type for event in transition.events] == [
        SIMULATION_INITIALIZED,
        ENTITY_CREATED,
        ENTITY_CREATED,
        RELATION_CREATED,
        RESOURCE_CHANGED,
        STATE_VARIABLE_CHANGED,
        STATE_VARIABLE_CHANGED,
    ]
    assert [event.payload.get("entity_id") for event in transition.events[1:3]] == [
        "second",
        "first",
    ]
    assert transition.events[4].payload["quantity_after"] == -3
    assert "quantity" not in transition.events[4].payload
    assert transition.events[5].payload["value_after"] == "clear"
    assert "value" not in transition.events[5].payload


def test_initialization_payload_separates_definition_and_schema_identity() -> None:
    transition = build(definition(), genesis_ids(7))

    assert transition.events[0].payload == {
        "world_definition_ref": {"world_definition_id": "world", "version": "v1"},
        "world_definition_schema_version": 1,
    }


def test_relation_participants_are_encoded_in_canonical_order() -> None:
    transition = build(definition(), genesis_ids(7))

    assert transition.events[3].payload["participants"] == (
        {"role": "object", "entity_id": "first"},
        {"role": "subject", "entity_id": "second"},
    )


def test_builder_uses_supplied_ids_time_transition_and_engine_provenance() -> None:
    world_definition = definition()
    ids = genesis_ids(7)
    transition = build(world_definition, ids)

    assert [event.event_id for event in transition.events] == list(ids)
    assert transition.logical_time == world_definition.initial_conditions.logical_time
    assert transition.transition_ref == TransitionRef(
        stable_id(BranchId, "root"), stable_id(TransitionId, "genesis")
    )
    assert all(event.provenance.source_kind == "ENGINE" for event in transition.events)
    assert all(
        event.provenance.source_ref is not None
        and event.provenance.source_ref.kind == "WORLD_DEFINITION"
        and event.provenance.source_ref.value == "world"
        for event in transition.events
    )
    assert transition.events[0].provenance.metadata == {
        "world_definition_version": "v1",
        "world_definition_schema_version": 1,
    }


@pytest.mark.parametrize("count", [0, 6, 8])
def test_builder_requires_exactly_sufficient_event_ids(count: int) -> None:
    with pytest.raises(GenesisError, match="exactly 7"):
        build(definition(), genesis_ids(count))


def test_builder_rejects_duplicate_and_non_event_ids() -> None:
    duplicate = stable_id(EventId, "duplicate")
    with pytest.raises(GenesisError, match="unique"):
        build(definition(), (duplicate,) * 7)

    invalid = cast(
        Sequence[EventId], [stable_id(EventId, f"id:{index}") for index in range(6)] + ["bad"]
    )
    with pytest.raises(TypeError, match="EventId"):
        build(definition(), invalid)


def test_builder_rejects_mismatched_run_config_reference() -> None:
    world_definition = definition()

    with pytest.raises(GenesisError, match="does not reference"):
        build_genesis_transition(
            world_definition,
            SimulationRunConfig(WorldDefinitionRef(WorldDefinitionId("other"), "v1")),
            TransitionRef(stable_id(BranchId, "root"), stable_id(TransitionId, "genesis")),
            genesis_ids(7),
        )


def test_empty_world_still_produces_non_empty_genesis() -> None:
    transition = build(definition(empty=True), genesis_ids(1))

    assert len(transition.events) == 1
    assert transition.events[0].event_type == SIMULATION_INITIALIZED


def test_builder_is_pure_and_committed_genesis_projects_and_replays() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    transition_to_commit = build(definition(), genesis_ids(7))

    assert store.read_transitions(root_id) == ()
    committed = store.commit_transition(transition_to_commit)
    projected = project_transition(SimulationState.empty(root_id), committed)
    replayed = replay_branch(store, store.head_position(root_id))

    assert projected == replayed
    assert projected.world.entities[EntityId("second")].properties == {"order": 2}
    assert projected.world.resources[ResourceKey(EntityId("second"), "balance")] == -3
    assert projected.world.state_variables[StateVariableKey(WorldScope(), "weather")] == "clear"
    assert projected.world.state_variables[
        StateVariableKey(EntityScope(EntityId("first")), "condition")
    ] == {"ready": True}


def test_child_inherits_original_genesis_without_copying_events() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    committed = store.commit_transition(build(definition(), genesis_ids(7)))
    store.fork_branch(child_id, HistoryPosition(root_id, committed.transition_ref))

    visible = store.read_visible_transitions(store.head_position(child_id))
    state = replay_branch(store, store.head_position(child_id))

    assert visible == (committed,)
    assert visible[0] is committed
    assert state.world.entities[EntityId("first")].properties == {"order": 1}
    assert state.position.branch_id == child_id
    assert state.position.last_transition_ref is None
