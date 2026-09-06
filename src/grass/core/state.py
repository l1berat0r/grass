# SPDX-License-Identifier: GPL-3.0-only

"""Immutable authoritative simulation-state projection contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import ClassVar, Literal, TypeAlias

from grass.core._structured_data import (
    StructuredValue,
    freeze_structured_mapping,
    freeze_structured_value,
)
from grass.core.identifiers import BranchId, EntityId, RelationId
from grass.core.logical_time import LogicalTime
from grass.core.references import TransitionRef


def _require_non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class RelationParticipant:
    """One role binding in an unordered Relation participant set."""

    role: str
    entity_id: EntityId

    def __post_init__(self) -> None:
        _require_non_empty_string(self.role, "role")
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")


@dataclass(frozen=True, slots=True)
class WorldScope:
    """The single world-wide StateVariable scope."""

    kind: Literal["WORLD"] = field(default="WORLD", init=False)


@dataclass(frozen=True, slots=True)
class EntityScope:
    """A StateVariable scope associated with one Entity."""

    entity_id: EntityId
    kind: Literal["ENTITY"] = field(default="ENTITY", init=False)

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")


StateVariableScope: TypeAlias = WorldScope | EntityScope


@dataclass(frozen=True, slots=True)
class ResourceKey:
    entity_id: EntityId
    resource_type: str

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _require_non_empty_string(self.resource_type, "resource_type")


@dataclass(frozen=True, slots=True)
class StateVariableKey:
    scope: StateVariableScope
    state_variable_type: str

    def __post_init__(self) -> None:
        if type(self.scope) not in (WorldScope, EntityScope):
            raise TypeError("scope must be a WorldScope or EntityScope")
        _require_non_empty_string(self.state_variable_type, "state_variable_type")


@dataclass(frozen=True, slots=True)
class Entity:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entity_id: EntityId
    entity_type: str
    properties: Mapping[str, StructuredValue]
    active: bool = True

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _require_non_empty_string(self.entity_type, "entity_type")
        if not isinstance(self.properties, Mapping):
            raise TypeError("properties must be a mapping")
        if type(self.active) is not bool:
            raise TypeError("active must be a boolean")
        object.__setattr__(
            self,
            "properties",
            freeze_structured_mapping(self.properties, description="Entity properties"),
        )


@dataclass(frozen=True, slots=True)
class Relation:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    relation_id: RelationId
    relation_type: str
    participants: frozenset[RelationParticipant]
    properties: Mapping[str, StructuredValue]
    active: bool = True

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")
        _require_non_empty_string(self.relation_type, "relation_type")
        if type(self.participants) is not frozenset:
            raise TypeError("participants must be a frozenset")
        if not self.participants:
            raise ValueError("participants must not be empty")
        if not all(type(item) is RelationParticipant for item in self.participants):
            raise TypeError("participants must contain RelationParticipant values")
        if not isinstance(self.properties, Mapping):
            raise TypeError("properties must be a mapping")
        if type(self.active) is not bool:
            raise TypeError("active must be a boolean")
        object.__setattr__(
            self,
            "properties",
            freeze_structured_mapping(self.properties, description="Relation properties"),
        )


ResourceQuantity: TypeAlias = int | float


@dataclass(frozen=True, slots=True)
class WorldState:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entities: Mapping[EntityId, Entity] = field(default_factory=dict)
    relations: Mapping[RelationId, Relation] = field(default_factory=dict)
    resources: Mapping[ResourceKey, ResourceQuantity] = field(default_factory=dict)
    state_variables: Mapping[StateVariableKey, StructuredValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        entities = dict(self.entities)
        relations = dict(self.relations)
        resources = dict(self.resources)
        state_variables = dict(self.state_variables)

        for entity_id, entity in entities.items():
            if type(entity_id) is not EntityId or type(entity) is not Entity:
                raise TypeError("entities must map EntityId to Entity")
            if entity_id != entity.entity_id:
                raise ValueError("Entity key must match entity_id")
        for relation_id, relation in relations.items():
            if type(relation_id) is not RelationId or type(relation) is not Relation:
                raise TypeError("relations must map RelationId to Relation")
            if relation_id != relation.relation_id:
                raise ValueError("Relation key must match relation_id")
            if any(item.entity_id not in entities for item in relation.participants):
                raise ValueError("Relation participants must reference existing Entities")
        for resource_key, quantity in resources.items():
            if type(resource_key) is not ResourceKey:
                raise TypeError("resource keys must be ResourceKey values")
            if resource_key.entity_id not in entities:
                raise ValueError("Resources must reference existing Entities")
            if type(quantity) not in (int, float) or (
                type(quantity) is float and not isfinite(quantity)
            ):
                raise TypeError("Resource quantity must be an integer or finite float")
        frozen_state_variables: dict[StateVariableKey, StructuredValue] = {}
        for variable_key, value in state_variables.items():
            if type(variable_key) is not StateVariableKey:
                raise TypeError("state variable keys must be StateVariableKey values")
            if (
                type(variable_key.scope) is EntityScope
                and variable_key.scope.entity_id not in entities
            ):
                raise ValueError("Entity-scoped values must reference existing Entities")
            frozen_state_variables[variable_key] = freeze_structured_value(
                value, description="StateVariable value"
            )

        object.__setattr__(self, "entities", MappingProxyType(entities))
        object.__setattr__(self, "relations", MappingProxyType(relations))
        object.__setattr__(self, "resources", MappingProxyType(resources))
        object.__setattr__(self, "state_variables", MappingProxyType(frozen_state_variables))


@dataclass(frozen=True, slots=True)
class ExecutionState:
    """Projection boundary reserved for Plan and Job state."""


@dataclass(frozen=True, slots=True)
class CognitionState:
    """Projection boundary reserved for material actor cognition state."""


@dataclass(frozen=True, slots=True)
class ProjectionPosition:
    branch_id: BranchId
    last_transition_ref: TransitionRef | None = None
    last_sequence: int = 0
    logical_time: LogicalTime | None = None

    def __post_init__(self) -> None:
        if type(self.branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        if type(self.last_sequence) is not int:
            raise TypeError("last_sequence must be an integer")
        if self.last_transition_ref is None:
            if self.last_sequence != 0 or self.logical_time is not None:
                raise ValueError("empty projection position must use sequence zero and no time")
            return
        if type(self.last_transition_ref) is not TransitionRef:
            raise TypeError("last_transition_ref must be a TransitionRef or None")
        if self.last_transition_ref.branch_id != self.branch_id:
            raise ValueError("projection and transition branches must match")
        if self.last_sequence < 1 or type(self.logical_time) is not LogicalTime:
            raise ValueError("non-empty projection position must be complete")


@dataclass(frozen=True, slots=True)
class SimulationState:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position: ProjectionPosition
    world: WorldState = field(default_factory=WorldState)
    execution: ExecutionState = field(default_factory=ExecutionState)
    cognition: CognitionState = field(default_factory=CognitionState)

    def __post_init__(self) -> None:
        if type(self.position) is not ProjectionPosition:
            raise TypeError("position must be a ProjectionPosition")
        if type(self.world) is not WorldState:
            raise TypeError("world must be a WorldState")
        if type(self.execution) is not ExecutionState:
            raise TypeError("execution must be an ExecutionState")
        if type(self.cognition) is not CognitionState:
            raise TypeError("cognition must be a CognitionState")

    @classmethod
    def empty(cls, branch_id: BranchId) -> SimulationState:
        return cls(position=ProjectionPosition(branch_id=branch_id))
