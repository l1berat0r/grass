# SPDX-License-Identifier: GPL-3.0-only

"""Closed transient candidate-effect contracts for deterministic resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import ClassVar, TypeAlias

from grass.core._structured_data import (
    StructuredValue,
    freeze_structured_mapping,
    freeze_structured_value,
)
from grass.core.execution import BinaryProgress, JobProgress, JobStatus, LinearProgress
from grass.core.identifiers import EntityId, JobId, RelationId
from grass.core.state import (
    EntityScope,
    RelationParticipant,
    ResourceQuantity,
    StateVariableScope,
    WorldScope,
)


def _token(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


def _properties(value: object, field_name: str) -> Mapping[str, StructuredValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return freeze_structured_mapping(value, description=field_name)


def _participants(value: object, field_name: str) -> frozenset[RelationParticipant]:
    if type(value) is not frozenset:
        raise TypeError(f"{field_name} must be a frozenset")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if not all(type(item) is RelationParticipant for item in value):
        raise TypeError(f"{field_name} must contain RelationParticipant values")
    return value


@dataclass(frozen=True, slots=True)
class CreateEntityEffect:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entity_id: EntityId
    entity_type: str
    properties: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _token(self.entity_type, "entity_type")
        object.__setattr__(self, "properties", _properties(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class UpdateEntityEffect:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entity_id: EntityId
    properties_after: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        object.__setattr__(
            self,
            "properties_after",
            _properties(self.properties_after, "properties_after"),
        )


@dataclass(frozen=True, slots=True)
class DeactivateEntityEffect:
    entity_id: EntityId

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")


@dataclass(frozen=True, slots=True)
class CreateRelationEffect:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    relation_id: RelationId
    relation_type: str
    participants: frozenset[RelationParticipant]
    properties: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")
        _token(self.relation_type, "relation_type")
        object.__setattr__(self, "participants", _participants(self.participants, "participants"))
        object.__setattr__(self, "properties", _properties(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class UpdateRelationEffect:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    relation_id: RelationId
    participants_after: frozenset[RelationParticipant]
    properties_after: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")
        object.__setattr__(
            self,
            "participants_after",
            _participants(self.participants_after, "participants_after"),
        )
        object.__setattr__(
            self,
            "properties_after",
            _properties(self.properties_after, "properties_after"),
        )


@dataclass(frozen=True, slots=True)
class DeactivateRelationEffect:
    relation_id: RelationId

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")


@dataclass(frozen=True, slots=True)
class ChangeResourceEffect:
    entity_id: EntityId
    resource_type: str
    quantity_after: ResourceQuantity

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _token(self.resource_type, "resource_type")
        if type(self.quantity_after) not in (int, float) or (
            type(self.quantity_after) is float and not isfinite(self.quantity_after)
        ):
            raise TypeError("quantity_after must be an integer or finite float")


@dataclass(frozen=True, slots=True)
class SetStateVariableEffect:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    scope: StateVariableScope
    state_variable_type: str
    value_after: StructuredValue

    def __post_init__(self) -> None:
        if type(self.scope) not in (WorldScope, EntityScope):
            raise TypeError("scope must be a WorldScope or EntityScope")
        _token(self.state_variable_type, "state_variable_type")
        object.__setattr__(
            self,
            "value_after",
            freeze_structured_value(self.value_after, description="value_after"),
        )


@dataclass(frozen=True, slots=True)
class UpdateJobEffect:
    job_id: JobId
    status_after: JobStatus | None = None
    progress_after: JobProgress | None = None

    def __post_init__(self) -> None:
        if type(self.job_id) is not JobId:
            raise TypeError("job_id must be a JobId")
        if self.status_after is not None and type(self.status_after) is not JobStatus:
            raise TypeError("status_after must be a JobStatus or None")
        if self.progress_after is not None and type(self.progress_after) not in (
            LinearProgress,
            BinaryProgress,
        ):
            raise TypeError("progress_after must be LinearProgress, BinaryProgress, or None")
        if self.status_after is None and self.progress_after is None:
            raise ValueError("UpdateJobEffect requires status_after or progress_after")
        if self.status_after is JobStatus.PENDING:
            raise ValueError("PENDING is not a valid status_after target")


WorldEffect: TypeAlias = (
    CreateEntityEffect
    | UpdateEntityEffect
    | DeactivateEntityEffect
    | CreateRelationEffect
    | UpdateRelationEffect
    | DeactivateRelationEffect
    | ChangeResourceEffect
    | SetStateVariableEffect
    | UpdateJobEffect
)

WORLD_EFFECT_TYPES = (
    CreateEntityEffect,
    UpdateEntityEffect,
    DeactivateEntityEffect,
    CreateRelationEffect,
    UpdateRelationEffect,
    DeactivateRelationEffect,
    ChangeResourceEffect,
    SetStateVariableEffect,
    UpdateJobEffect,
)
