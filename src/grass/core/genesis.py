# SPDX-License-Identifier: GPL-3.0-only

"""Pure materialization of initial conditions into one genesis transition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from grass.core._structured_data import StructuredValue
from grass.core.events import EventToCommit, TransitionToCommit
from grass.core.identifiers import EventId
from grass.core.initialization_events import SIMULATION_INITIALIZED
from grass.core.provenance import Provenance, ProvenanceSourceRef
from grass.core.references import TransitionRef
from grass.core.state import (
    Entity,
    EntityScope,
    Relation,
    ResourceKey,
    StateVariableKey,
    WorldScope,
    WorldState,
)
from grass.core.world_definitions import SimulationRunConfig, WorldDefinition
from grass.core.world_events import (
    ENTITY_CREATED,
    RELATION_CREATED,
    RESOURCE_CHANGED,
    STATE_VARIABLE_CHANGED,
)


class GenesisError(ValueError):
    """Initial conditions cannot be materialized as a valid genesis transition."""


def _validate_candidate_world(world_definition: WorldDefinition) -> None:
    initial = world_definition.initial_conditions
    try:
        WorldState(
            entities={
                item.entity_id: Entity(item.entity_id, item.entity_type, item.properties)
                for item in initial.entities
            },
            relations={
                item.relation_id: Relation(
                    item.relation_id,
                    item.relation_type,
                    item.participants,
                    item.properties,
                )
                for item in initial.relations
            },
            resources={
                ResourceKey(item.entity_id, item.resource_type): item.quantity
                for item in initial.resources
            },
            state_variables={
                StateVariableKey(item.scope, item.state_variable_type): item.value
                for item in initial.state_variables
            },
        )
    except (TypeError, ValueError) as error:
        raise GenesisError(str(error)) from error


def _scope_payload(scope: WorldScope | EntityScope) -> Mapping[str, StructuredValue]:
    if type(scope) is WorldScope:
        return {"kind": "WORLD"}
    if type(scope) is EntityScope:
        return {"kind": "ENTITY", "entity_id": scope.entity_id.value}
    raise AssertionError("unsupported StateVariable scope")


def _genesis_records(
    world_definition: WorldDefinition,
) -> tuple[tuple[str, Mapping[str, StructuredValue]], ...]:
    initial = world_definition.initial_conditions
    records: list[tuple[str, Mapping[str, StructuredValue]]] = [
        (
            SIMULATION_INITIALIZED,
            {
                "world_definition_ref": {
                    "world_definition_id": world_definition.world_definition_id.value,
                    "version": world_definition.version,
                },
                "world_definition_schema_version": world_definition.schema_version,
            },
        )
    ]
    records.extend(
        (
            ENTITY_CREATED,
            {
                "entity_id": item.entity_id.value,
                "entity_type": item.entity_type,
                "properties": item.properties,
            },
        )
        for item in initial.entities
    )
    records.extend(
        (
            RELATION_CREATED,
            {
                "relation_id": item.relation_id.value,
                "relation_type": item.relation_type,
                "participants": [
                    {"role": participant.role, "entity_id": participant.entity_id.value}
                    for participant in sorted(
                        item.participants,
                        key=lambda participant: (
                            participant.role,
                            participant.entity_id.value,
                        ),
                    )
                ],
                "properties": item.properties,
            },
        )
        for item in initial.relations
    )
    records.extend(
        (
            RESOURCE_CHANGED,
            {
                "entity_id": item.entity_id.value,
                "resource_type": item.resource_type,
                "quantity_after": item.quantity,
            },
        )
        for item in initial.resources
    )
    records.extend(
        (
            STATE_VARIABLE_CHANGED,
            {
                "scope": _scope_payload(item.scope),
                "state_variable_type": item.state_variable_type,
                "value_after": item.value,
            },
        )
        for item in initial.state_variables
    )
    return tuple(records)


def build_genesis_transition(
    world_definition: WorldDefinition,
    run_config: SimulationRunConfig,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
) -> TransitionToCommit:
    """Validate and materialize one complete genesis transition without committing it."""

    if type(world_definition) is not WorldDefinition:
        raise TypeError("world_definition must be a WorldDefinition")
    if type(run_config) is not SimulationRunConfig:
        raise TypeError("run_config must be a SimulationRunConfig")
    if type(transition_ref) is not TransitionRef:
        raise TypeError("transition_ref must be a TransitionRef")
    if run_config.world_definition_ref != world_definition.ref:
        raise GenesisError("SimulationRunConfig does not reference this WorldDefinition")

    ids = tuple(event_ids)
    if not all(type(event_id) is EventId for event_id in ids):
        raise TypeError("event_ids must contain only EventId values")
    if len(set(ids)) != len(ids):
        raise GenesisError("event_ids must be unique")

    _validate_candidate_world(world_definition)
    records = _genesis_records(world_definition)
    if len(ids) != len(records):
        raise GenesisError(
            f"genesis requires exactly {len(records)} EventId values, got {len(ids)}"
        )

    provenance = Provenance(
        source_kind="ENGINE",
        source_ref=ProvenanceSourceRef(
            kind="WORLD_DEFINITION",
            value=world_definition.world_definition_id.value,
        ),
        metadata={
            "world_definition_version": world_definition.version,
            "world_definition_schema_version": world_definition.schema_version,
        },
    )
    events = tuple(
        EventToCommit(
            event_id=event_id,
            event_type=event_type,
            event_version=1,
            payload=payload,
            provenance=provenance,
        )
        for event_id, (event_type, payload) in zip(ids, records, strict=True)
    )
    return TransitionToCommit(
        transition_ref=transition_ref,
        logical_time=world_definition.initial_conditions.logical_time,
        events=events,
    )
