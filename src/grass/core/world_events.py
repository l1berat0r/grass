# SPDX-License-Identifier: GPL-3.0-only

"""Strict versioned payload decoding for initial world Events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import ClassVar, TypeAlias, cast

from grass.core._structured_data import (
    StructuredValue,
    freeze_structured_mapping,
    freeze_structured_value,
)
from grass.core.events import Event
from grass.core.identifiers import EntityId, RelationId
from grass.core.state import (
    EntityScope,
    RelationParticipant,
    ResourceQuantity,
    StateVariableScope,
    WorldScope,
)

ENTITY_CREATED = "EntityCreated"
ENTITY_UPDATED = "EntityUpdated"
ENTITY_DEACTIVATED = "EntityDeactivated"
RELATION_CREATED = "RelationCreated"
RELATION_UPDATED = "RelationUpdated"
RELATION_DEACTIVATED = "RelationDeactivated"
RESOURCE_CHANGED = "ResourceChanged"
STATE_VARIABLE_CHANGED = "StateVariableChanged"

WORLD_EVENT_TYPES = frozenset(
    {
        ENTITY_CREATED,
        ENTITY_UPDATED,
        ENTITY_DEACTIVATED,
        RELATION_CREATED,
        RELATION_UPDATED,
        RELATION_DEACTIVATED,
        RESOURCE_CHANGED,
        STATE_VARIABLE_CHANGED,
    }
)


class WorldEventPayloadError(ValueError):
    """A known world Event has an invalid version or payload."""


@dataclass(frozen=True, slots=True)
class EntityCreatedPayload:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entity_id: EntityId
    entity_type: str
    properties: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _token(self.entity_type, "entity_type")
        object.__setattr__(
            self,
            "properties",
            freeze_structured_mapping(self.properties, description="Entity properties"),
        )


@dataclass(frozen=True, slots=True)
class EntityUpdatedPayload:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entity_id: EntityId
    properties_after: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        object.__setattr__(
            self,
            "properties_after",
            freeze_structured_mapping(self.properties_after, description="Entity properties_after"),
        )


@dataclass(frozen=True, slots=True)
class EntityDeactivatedPayload:
    entity_id: EntityId

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")


@dataclass(frozen=True, slots=True)
class RelationCreatedPayload:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    relation_id: RelationId
    relation_type: str
    participants: frozenset[RelationParticipant]
    properties: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")
        _token(self.relation_type, "relation_type")
        _validate_participant_set(self.participants, "participants")
        object.__setattr__(
            self,
            "properties",
            freeze_structured_mapping(self.properties, description="Relation properties"),
        )


@dataclass(frozen=True, slots=True)
class RelationUpdatedPayload:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    relation_id: RelationId
    participants_after: frozenset[RelationParticipant]
    properties_after: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")
        _validate_participant_set(self.participants_after, "participants_after")
        object.__setattr__(
            self,
            "properties_after",
            freeze_structured_mapping(
                self.properties_after, description="Relation properties_after"
            ),
        )


@dataclass(frozen=True, slots=True)
class RelationDeactivatedPayload:
    relation_id: RelationId

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")


@dataclass(frozen=True, slots=True)
class ResourceChangedPayload:
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
            raise WorldEventPayloadError("quantity_after must be an integer or finite float")


@dataclass(frozen=True, slots=True)
class StateVariableChangedPayload:
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
            freeze_structured_value(self.value_after, description="StateVariable value_after"),
        )


WorldEventPayload: TypeAlias = (
    EntityCreatedPayload
    | EntityUpdatedPayload
    | EntityDeactivatedPayload
    | RelationCreatedPayload
    | RelationUpdatedPayload
    | RelationDeactivatedPayload
    | ResourceChangedPayload
    | StateVariableChangedPayload
)


def _require_fields(payload: Mapping[str, StructuredValue], expected: frozenset[str]) -> None:
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise WorldEventPayloadError(
            f"payload fields do not match schema; missing={missing}, extra={extra}"
        )


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or value == "":
        raise WorldEventPayloadError(f"{field_name} must be a non-empty string")
    return value


def _validate_participant_set(value: object, field_name: str) -> None:
    if type(value) is not frozenset or not value:
        raise WorldEventPayloadError(f"{field_name} must be a non-empty frozenset")
    if not all(type(item) is RelationParticipant for item in value):
        raise TypeError(f"{field_name} must contain RelationParticipant values")


def _mapping(value: object, field_name: str) -> Mapping[str, StructuredValue]:
    if not isinstance(value, Mapping):
        raise WorldEventPayloadError(f"{field_name} must be a mapping")
    if not all(type(key) is str for key in value):
        raise WorldEventPayloadError(f"{field_name} keys must be strings")
    return cast("Mapping[str, StructuredValue]", value)


def _participants(value: object, field_name: str) -> frozenset[RelationParticipant]:
    if type(value) is not tuple or not value:
        raise WorldEventPayloadError(f"{field_name} must be a non-empty sequence")
    participants: list[RelationParticipant] = []
    for item in value:
        participant = _mapping(item, field_name)
        _require_fields(participant, frozenset({"role", "entity_id"}))
        participants.append(
            RelationParticipant(
                role=_token(participant["role"], "role"),
                entity_id=EntityId(_token(participant["entity_id"], "entity_id")),
            )
        )
    frozen = frozenset(participants)
    if len(frozen) != len(participants):
        raise WorldEventPayloadError(f"{field_name} must not contain duplicate bindings")
    return frozen


def _scope(value: object) -> StateVariableScope:
    scope = _mapping(value, "scope")
    kind = scope.get("kind")
    if kind == "WORLD":
        _require_fields(scope, frozenset({"kind"}))
        return WorldScope()
    if kind == "ENTITY":
        _require_fields(scope, frozenset({"kind", "entity_id"}))
        return EntityScope(EntityId(_token(scope["entity_id"], "entity_id")))
    raise WorldEventPayloadError("scope.kind must be WORLD or ENTITY")


def decode_world_event(event: Event) -> WorldEventPayload:
    """Decode one known version-1 world Event into a typed payload."""

    if event.event_type not in WORLD_EVENT_TYPES:
        raise WorldEventPayloadError(f"unknown world Event type: {event.event_type}")
    if event.event_version != 1:
        raise WorldEventPayloadError(
            f"unsupported {event.event_type} version: {event.event_version}"
        )
    payload = event.payload

    if event.event_type == ENTITY_CREATED:
        _require_fields(payload, frozenset({"entity_id", "entity_type", "properties"}))
        return EntityCreatedPayload(
            entity_id=EntityId(_token(payload["entity_id"], "entity_id")),
            entity_type=_token(payload["entity_type"], "entity_type"),
            properties=_mapping(payload["properties"], "properties"),
        )
    if event.event_type == ENTITY_UPDATED:
        _require_fields(payload, frozenset({"entity_id", "properties_after"}))
        return EntityUpdatedPayload(
            entity_id=EntityId(_token(payload["entity_id"], "entity_id")),
            properties_after=_mapping(payload["properties_after"], "properties_after"),
        )
    if event.event_type == ENTITY_DEACTIVATED:
        _require_fields(payload, frozenset({"entity_id"}))
        return EntityDeactivatedPayload(
            entity_id=EntityId(_token(payload["entity_id"], "entity_id"))
        )
    if event.event_type == RELATION_CREATED:
        _require_fields(
            payload,
            frozenset({"relation_id", "relation_type", "participants", "properties"}),
        )
        return RelationCreatedPayload(
            relation_id=RelationId(_token(payload["relation_id"], "relation_id")),
            relation_type=_token(payload["relation_type"], "relation_type"),
            participants=_participants(payload["participants"], "participants"),
            properties=_mapping(payload["properties"], "properties"),
        )
    if event.event_type == RELATION_UPDATED:
        _require_fields(
            payload,
            frozenset({"relation_id", "participants_after", "properties_after"}),
        )
        return RelationUpdatedPayload(
            relation_id=RelationId(_token(payload["relation_id"], "relation_id")),
            participants_after=_participants(payload["participants_after"], "participants_after"),
            properties_after=_mapping(payload["properties_after"], "properties_after"),
        )
    if event.event_type == RELATION_DEACTIVATED:
        _require_fields(payload, frozenset({"relation_id"}))
        return RelationDeactivatedPayload(
            relation_id=RelationId(_token(payload["relation_id"], "relation_id"))
        )
    if event.event_type == RESOURCE_CHANGED:
        _require_fields(payload, frozenset({"entity_id", "resource_type", "quantity_after"}))
        quantity = payload["quantity_after"]
        if type(quantity) not in (int, float) or (
            type(quantity) is float and not isfinite(quantity)
        ):
            raise WorldEventPayloadError("quantity_after must be an integer or finite float")
        return ResourceChangedPayload(
            entity_id=EntityId(_token(payload["entity_id"], "entity_id")),
            resource_type=_token(payload["resource_type"], "resource_type"),
            quantity_after=cast("ResourceQuantity", quantity),
        )

    _require_fields(payload, frozenset({"scope", "state_variable_type", "value_after"}))
    return StateVariableChangedPayload(
        scope=_scope(payload["scope"]),
        state_variable_type=_token(payload["state_variable_type"], "state_variable_type"),
        value_after=payload["value_after"],
    )
