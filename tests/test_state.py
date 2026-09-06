# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import (
    BranchId,
    CognitionState,
    Entity,
    EntityId,
    EntityScope,
    ExecutionState,
    LogicalTime,
    ProjectionPosition,
    Relation,
    RelationId,
    RelationParticipant,
    ResourceKey,
    SimulationState,
    StateVariableKey,
    TransitionId,
    TransitionRef,
    WorldScope,
    WorldState,
)
from grass.core._structured_data import StructuredValue


def test_empty_simulation_state_has_branch_origin_position_and_empty_boundaries() -> None:
    state = SimulationState.empty(BranchId("branch"))

    assert state.position == ProjectionPosition(BranchId("branch"))
    assert state.position.last_transition_ref is None
    assert state.position.last_sequence == 0
    assert state.position.logical_time is None
    assert state.world == WorldState()
    assert state.execution == ExecutionState()
    assert state.cognition == CognitionState()


def test_entity_and_world_state_recursively_copy_and_freeze_values() -> None:
    nested_values: list[StructuredValue] = [1, 2]
    source: dict[str, StructuredValue] = {"nested": {"values": nested_values}}
    entity = Entity(
        EntityId("entity"),
        "Person",
        source,
    )
    entities = {entity.entity_id: entity}
    variable_values: list[StructuredValue] = ["one"]
    variable_source: dict[str, StructuredValue] = {"current": variable_values}
    variable_key = StateVariableKey(EntityScope(entity.entity_id), "condition")
    world = WorldState(
        entities=entities,
        state_variables={variable_key: variable_source},
    )

    nested_values.append(3)
    entities.clear()
    variable_values.append("two")

    nested = entity.properties["nested"]
    assert isinstance(nested, Mapping)
    assert nested["values"] == (1, 2)
    assert world.entities == {entity.entity_id: entity}
    assert world.state_variables[variable_key] == {"current": ("one",)}
    with pytest.raises(TypeError):
        cast(dict[EntityId, Entity], world.entities)[EntityId("other")] = entity
    with pytest.raises(TypeError):
        cast(dict[str, object], entity.properties)["new"] = True
    with pytest.raises(FrozenInstanceError):
        entity.active = False  # type: ignore[misc]


def test_world_state_accepts_inactive_references_and_negative_resources() -> None:
    entity = Entity(EntityId("entity"), "Artifact", {}, active=False)
    participant = RelationParticipant("subject", entity.entity_id)
    relation = Relation(
        RelationId("relation"),
        "AssociatedWith",
        frozenset({participant}),
        {},
    )
    resource_key = ResourceKey(entity.entity_id, "balance")
    variable_key = StateVariableKey(EntityScope(entity.entity_id), "condition")

    world = WorldState(
        entities={entity.entity_id: entity},
        relations={relation.relation_id: relation},
        resources={resource_key: -2.5},
        state_variables={variable_key: None},
    )

    assert world.resources[resource_key] == -2.5
    assert world.state_variables[variable_key] is None


def test_scope_and_key_identity_are_structural() -> None:
    entity_id = EntityId("entity")

    assert WorldScope() == WorldScope()
    assert EntityScope(entity_id) == EntityScope(EntityId("entity"))
    assert StateVariableKey(WorldScope(), "weather") != StateVariableKey(
        EntityScope(entity_id), "weather"
    )


def test_projection_position_rejects_partial_or_cross_branch_positions() -> None:
    branch = BranchId("branch")
    transition_ref = TransitionRef(branch, TransitionId("transition"))

    with pytest.raises(ValueError, match="sequence zero and no time"):
        ProjectionPosition(branch, logical_time=LogicalTime(1))
    with pytest.raises(ValueError, match="must be complete"):
        ProjectionPosition(branch, transition_ref, last_sequence=1)
    with pytest.raises(ValueError, match="branches must match"):
        ProjectionPosition(
            branch,
            TransitionRef(BranchId("other"), TransitionId("transition")),
            last_sequence=1,
            logical_time=LogicalTime(1),
        )
    with pytest.raises(TypeError, match="last_sequence must be an integer"):
        ProjectionPosition(
            branch,
            transition_ref,
            last_sequence=cast(int, True),
            logical_time=LogicalTime(1),
        )


def test_world_state_rejects_dangling_structural_references() -> None:
    missing = EntityId("missing")
    participant = RelationParticipant("subject", missing)

    with pytest.raises(ValueError, match="participants must reference existing"):
        WorldState(
            relations={
                RelationId("relation"): Relation(
                    RelationId("relation"),
                    "AssociatedWith",
                    frozenset({participant}),
                    {},
                )
            }
        )
    with pytest.raises(ValueError, match="Resources must reference existing"):
        WorldState(resources={ResourceKey(missing, "balance"): 1})
    with pytest.raises(ValueError, match="Entity-scoped values"):
        WorldState(state_variables={StateVariableKey(EntityScope(missing), "condition"): True})
