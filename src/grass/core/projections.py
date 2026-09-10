# SPDX-License-Identifier: GPL-3.0-only

"""Pure deterministic reconstruction of authoritative SimulationState."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from grass.core.events import CommittedTransition
from grass.core.execution_events import (
    EXECUTION_EVENT_TYPES,
    ExecutionEventPayload,
    ExecutionEventPayloadError,
    decode_execution_event,
    is_execution_event_payload,
)
from grass.core.execution_projection import ExecutionProjectionError, project_execution_state
from grass.core.identifiers import BranchId, EntityId, JobId, RelationId
from grass.core.initialization_events import (
    SIMULATION_INITIALIZED,
    InitializationEventPayloadError,
    SimulationInitializedPayload,
    decode_initialization_event,
)
from grass.core.resolution_events import (
    RESOLUTION_EVENT_TYPES,
    ResolutionEventPayloadError,
    ResolutionOutcomeRecordedPayload,
    decode_resolution_event,
)
from grass.core.state import (
    Entity,
    ProjectionPosition,
    Relation,
    ResourceKey,
    SimulationState,
    StateVariableKey,
    WorldState,
)
from grass.core.world_events import (
    WORLD_EVENT_TYPES,
    EntityCreatedPayload,
    EntityDeactivatedPayload,
    EntityUpdatedPayload,
    RelationCreatedPayload,
    RelationDeactivatedPayload,
    RelationUpdatedPayload,
    ResourceChangedPayload,
    StateVariableChangedPayload,
    WorldEventPayload,
    WorldEventPayloadError,
    decode_world_event,
)

Identity = TypeVar("Identity")
ProjectionEventPayload = (
    WorldEventPayload
    | SimulationInitializedPayload
    | ExecutionEventPayload
    | ResolutionOutcomeRecordedPayload
)


class ProjectionError(ValueError):
    """Committed history cannot be projected under the supported contracts."""


def _validate_position(state: SimulationState, transition: CommittedTransition) -> None:
    if transition.branch_id != state.position.branch_id:
        raise ProjectionError("transition branch does not match projection branch")
    expected_sequence = state.position.last_sequence + 1
    if transition.events[0].sequence != expected_sequence:
        raise ProjectionError(
            f"expected Event sequence {expected_sequence}, got {transition.events[0].sequence}"
        )
    if (
        state.position.logical_time is not None
        and transition.logical_time < state.position.logical_time
    ):
        raise ProjectionError("transition logical time must be nondecreasing")


def _decode_transition(
    transition: CommittedTransition,
) -> tuple[ProjectionEventPayload, ...]:
    decoded: list[ProjectionEventPayload] = []
    for event in transition.events:
        # Routing is owned here so future execution/cognition Events can be added
        # without weakening strict unknown-Event handling.
        try:
            if event.event_type in WORLD_EVENT_TYPES:
                decoded.append(decode_world_event(event))
            elif event.event_type in EXECUTION_EVENT_TYPES:
                decoded.append(decode_execution_event(event))
            elif event.event_type == SIMULATION_INITIALIZED:
                decoded.append(decode_initialization_event(event))
            elif event.event_type in RESOLUTION_EVENT_TYPES:
                decoded.append(decode_resolution_event(event))
            else:
                raise ProjectionError(f"unknown Event type: {event.event_type}")
        except (
            ExecutionEventPayloadError,
            InitializationEventPayloadError,
            ResolutionEventPayloadError,
            WorldEventPayloadError,
        ) as error:
            raise ProjectionError(str(error)) from error
    return tuple(decoded)


def _record_write(seen: set[Identity], identity: Identity, description: str) -> None:
    if identity in seen:
        raise ProjectionError(f"duplicate {description} write in one transition")
    seen.add(identity)


def _validate_unique_writes(payloads: tuple[ProjectionEventPayload, ...]) -> None:
    entity_writes: set[EntityId] = set()
    relation_writes: set[RelationId] = set()
    resource_writes: set[ResourceKey] = set()
    state_variable_writes: set[StateVariableKey] = set()
    resolution_outcomes: set[JobId] = set()
    initialization_count = 0

    for index, payload in enumerate(payloads):
        if type(payload) is SimulationInitializedPayload:
            initialization_count += 1
            if initialization_count > 1:
                raise ProjectionError("duplicate SimulationInitialized Event in one transition")
            if index != 0:
                raise ProjectionError("SimulationInitialized must be the first Event")
        elif is_execution_event_payload(payload):
            continue
        elif type(payload) is ResolutionOutcomeRecordedPayload:
            _record_write(resolution_outcomes, payload.job_id, "Resolution outcome")
        elif isinstance(
            payload,
            (
                EntityCreatedPayload,
                EntityUpdatedPayload,
                EntityDeactivatedPayload,
            ),
        ):
            _record_write(entity_writes, payload.entity_id, "Entity")
        elif isinstance(
            payload,
            (
                RelationCreatedPayload,
                RelationUpdatedPayload,
                RelationDeactivatedPayload,
            ),
        ):
            _record_write(relation_writes, payload.relation_id, "Relation")
        elif type(payload) is ResourceChangedPayload:
            resource_key = ResourceKey(payload.entity_id, payload.resource_type)
            _record_write(resource_writes, resource_key, "Resource")
        else:
            if type(payload) is not StateVariableChangedPayload:
                raise AssertionError("unhandled world Event payload")
            variable_key = StateVariableKey(payload.scope, payload.state_variable_type)
            _record_write(state_variable_writes, variable_key, "StateVariable")


def _active_entity(entities: dict[EntityId, Entity], entity_id: EntityId) -> Entity:
    entity = entities.get(entity_id)
    if entity is None:
        raise ProjectionError("Entity does not exist")
    if not entity.active:
        raise ProjectionError("Entity is inactive")
    return entity


def _active_relation(relations: dict[RelationId, Relation], relation_id: RelationId) -> Relation:
    relation = relations.get(relation_id)
    if relation is None:
        raise ProjectionError("Relation does not exist")
    if not relation.active:
        raise ProjectionError("Relation is inactive")
    return relation


def project_transition(state: SimulationState, transition: CommittedTransition) -> SimulationState:
    """Apply one complete transition atomically to an immutable state."""

    if type(state) is not SimulationState:
        raise TypeError("state must be a SimulationState")
    if type(transition) is not CommittedTransition:
        raise TypeError("transition must be a CommittedTransition")

    _validate_position(state, transition)
    payloads = _decode_transition(transition)
    _validate_unique_writes(payloads)

    entities = dict(state.world.entities)
    relations = dict(state.world.relations)
    resources = dict(state.world.resources)
    state_variables = dict(state.world.state_variables)

    for payload in payloads:
        if type(payload) in (
            SimulationInitializedPayload,
            ResolutionOutcomeRecordedPayload,
        ) or is_execution_event_payload(payload):
            continue
        if type(payload) is EntityCreatedPayload:
            if payload.entity_id in entities:
                raise ProjectionError("Entity already exists")
            entities[payload.entity_id] = Entity(
                entity_id=payload.entity_id,
                entity_type=payload.entity_type,
                properties=payload.properties,
            )
        elif type(payload) is EntityUpdatedPayload:
            entity = _active_entity(entities, payload.entity_id)
            entities[payload.entity_id] = Entity(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                properties=payload.properties_after,
            )
        elif type(payload) is EntityDeactivatedPayload:
            entity = _active_entity(entities, payload.entity_id)
            entities[payload.entity_id] = Entity(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                properties=entity.properties,
                active=False,
            )
        elif type(payload) is RelationCreatedPayload:
            if payload.relation_id in relations:
                raise ProjectionError("Relation already exists")
            relations[payload.relation_id] = Relation(
                relation_id=payload.relation_id,
                relation_type=payload.relation_type,
                participants=payload.participants,
                properties=payload.properties,
            )
        elif type(payload) is RelationUpdatedPayload:
            relation = _active_relation(relations, payload.relation_id)
            relations[payload.relation_id] = Relation(
                relation_id=relation.relation_id,
                relation_type=relation.relation_type,
                participants=payload.participants_after,
                properties=payload.properties_after,
            )
        elif type(payload) is RelationDeactivatedPayload:
            relation = _active_relation(relations, payload.relation_id)
            relations[payload.relation_id] = Relation(
                relation_id=relation.relation_id,
                relation_type=relation.relation_type,
                participants=relation.participants,
                properties=relation.properties,
                active=False,
            )
        elif type(payload) is ResourceChangedPayload:
            resources[ResourceKey(payload.entity_id, payload.resource_type)] = (
                payload.quantity_after
            )
        else:
            if type(payload) is not StateVariableChangedPayload:
                raise AssertionError("unhandled world Event payload")
            state_variables[StateVariableKey(payload.scope, payload.state_variable_type)] = (
                payload.value_after
            )

    try:
        world = WorldState(
            entities=entities,
            relations=relations,
            resources=resources,
            state_variables=state_variables,
        )
    except (TypeError, ValueError) as error:
        raise ProjectionError(str(error)) from error

    execution_payloads = tuple(
        payload for payload in payloads if is_execution_event_payload(payload)
    )
    try:
        execution = project_execution_state(
            state.execution,
            execution_payloads,
            frozenset(world.entities),
        )
    except ExecutionProjectionError as error:
        raise ProjectionError(str(error)) from error

    for payload in payloads:
        if (
            type(payload) is ResolutionOutcomeRecordedPayload
            and payload.job_id not in execution.jobs
        ):
            raise ProjectionError("Resolution outcome must reference an existing Job")

    final_event = transition.events[-1]
    return SimulationState(
        position=ProjectionPosition(
            branch_id=transition.branch_id,
            last_transition_ref=transition.transition_ref,
            last_sequence=final_event.sequence,
            logical_time=transition.logical_time,
        ),
        world=world,
        execution=execution,
        cognition=state.cognition,
    )


def replay_transitions(
    branch_id: BranchId, transitions: Iterable[CommittedTransition]
) -> SimulationState:
    """Reconstruct branch-origin state from complete committed transitions."""

    if type(branch_id) is not BranchId:
        raise TypeError("branch_id must be a BranchId")
    state = SimulationState.empty(branch_id)
    for transition in transitions:
        state = project_transition(state, transition)
    return state
