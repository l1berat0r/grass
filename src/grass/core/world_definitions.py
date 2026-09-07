# SPDX-License-Identifier: GPL-3.0-only

"""Immutable minimal WorldDefinition and run-configuration contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import ClassVar, cast

from grass.core._structured_data import (
    StructuredValue,
    freeze_structured_mapping,
    freeze_structured_value,
)
from grass.core.identifiers import EntityId, RelationId, WorldDefinitionId
from grass.core.logical_time import LogicalTime
from grass.core.state import (
    EntityScope,
    RelationParticipant,
    ResourceKey,
    ResourceQuantity,
    StateVariableKey,
    StateVariableScope,
    WorldScope,
)

WORLD_DEFINITION_SCHEMA_VERSION = 1


class WorldDefinitionError(ValueError):
    """A WorldDefinition document or semantic declaration is invalid."""


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or value == "":
        raise WorldDefinitionError(f"{field_name} must be a non-empty string")
    return value


def _exact_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorldDefinitionError(f"{field_name} must be a mapping")
    if not all(type(key) is str for key in value):
        raise WorldDefinitionError(f"{field_name} keys must be strings")
    return cast("Mapping[str, object]", value)


def _fields(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise WorldDefinitionError(
            f"{field_name} fields do not match schema; missing={missing}, extra={extra}"
        )


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if type(value) not in (list, tuple):
        raise WorldDefinitionError(f"{field_name} must be a sequence")
    return cast("Sequence[object]", value)


def _structured_mapping(value: object, field_name: str) -> Mapping[str, StructuredValue]:
    mapping = _exact_mapping(value, field_name)
    return cast("Mapping[str, StructuredValue]", mapping)


def _structured_value(value: object) -> StructuredValue:
    return cast("StructuredValue", value)


def _unique_values(values: Sequence[object], field_name: str) -> frozenset[str]:
    names = tuple(_token(value, field_name) for value in values)
    if len(set(names)) != len(names):
        raise WorldDefinitionError(f"{field_name} must not contain duplicate names")
    return frozenset(names)


@dataclass(frozen=True, slots=True)
class WorldDefinitionRef:
    """Semantic identity of one immutable WorldDefinition version."""

    world_definition_id: WorldDefinitionId
    version: str

    def __post_init__(self) -> None:
        if type(self.world_definition_id) is not WorldDefinitionId:
            raise TypeError("world_definition_id must be a WorldDefinitionId")
        _token(self.version, "version")


@dataclass(frozen=True, slots=True)
class WorldVocabulary:
    """Legal scenario type names without schemas or mechanics."""

    entity_types: frozenset[str] = frozenset()
    relation_types: frozenset[str] = frozenset()
    resource_types: frozenset[str] = frozenset()
    state_variable_types: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for field_name in (
            "entity_types",
            "relation_types",
            "resource_types",
            "state_variable_types",
        ):
            values = getattr(self, field_name)
            if type(values) is not frozenset:
                raise TypeError(f"{field_name} must be a frozenset")
            for value in values:
                _token(value, field_name)


@dataclass(frozen=True, slots=True)
class InitialEntity:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entity_id: EntityId
    entity_type: str
    properties: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _token(self.entity_type, "entity_type")
        if not isinstance(self.properties, Mapping):
            raise TypeError("properties must be a mapping")
        object.__setattr__(
            self,
            "properties",
            freeze_structured_mapping(self.properties, description="initial Entity properties"),
        )


@dataclass(frozen=True, slots=True)
class InitialRelation:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    relation_id: RelationId
    relation_type: str
    participants: frozenset[RelationParticipant]
    properties: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")
        _token(self.relation_type, "relation_type")
        if type(self.participants) is not frozenset:
            raise TypeError("participants must be a frozenset")
        if not self.participants:
            raise WorldDefinitionError("participants must not be empty")
        if not all(type(item) is RelationParticipant for item in self.participants):
            raise TypeError("participants must contain RelationParticipant values")
        if not isinstance(self.properties, Mapping):
            raise TypeError("properties must be a mapping")
        object.__setattr__(
            self,
            "properties",
            freeze_structured_mapping(self.properties, description="initial Relation properties"),
        )


@dataclass(frozen=True, slots=True)
class InitialResource:
    entity_id: EntityId
    resource_type: str
    quantity: ResourceQuantity

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _token(self.resource_type, "resource_type")
        if type(self.quantity) not in (int, float) or (
            type(self.quantity) is float and not isfinite(self.quantity)
        ):
            raise WorldDefinitionError("quantity must be an integer or finite float")


@dataclass(frozen=True, slots=True)
class InitialStateVariable:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    scope: StateVariableScope
    state_variable_type: str
    value: StructuredValue

    def __post_init__(self) -> None:
        if type(self.scope) not in (WorldScope, EntityScope):
            raise TypeError("scope must be a WorldScope or EntityScope")
        _token(self.state_variable_type, "state_variable_type")
        object.__setattr__(
            self,
            "value",
            freeze_structured_value(self.value, description="initial StateVariable value"),
        )


@dataclass(frozen=True, slots=True)
class InitialConditions:
    """Ordered declarations materialized by one genesis transition."""

    logical_time: LogicalTime
    entities: Sequence[InitialEntity] = ()
    relations: Sequence[InitialRelation] = ()
    resources: Sequence[InitialResource] = ()
    state_variables: Sequence[InitialStateVariable] = ()

    def __post_init__(self) -> None:
        if type(self.logical_time) is not LogicalTime:
            raise TypeError("logical_time must be LogicalTime")
        for field_name, item_type in (
            ("entities", InitialEntity),
            ("relations", InitialRelation),
            ("resources", InitialResource),
            ("state_variables", InitialStateVariable),
        ):
            values = tuple(getattr(self, field_name))
            if not all(type(value) is item_type for value in values):
                raise TypeError(f"{field_name} must contain only {item_type.__name__} values")
            object.__setattr__(self, field_name, values)


@dataclass(frozen=True, slots=True)
class WorldDefinition:
    """One immutable minimal scenario definition."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    world_definition_id: WorldDefinitionId
    version: str
    schema_version: int
    vocabulary: WorldVocabulary
    initial_conditions: InitialConditions
    metadata: Mapping[str, StructuredValue] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if type(self.world_definition_id) is not WorldDefinitionId:
            raise TypeError("world_definition_id must be a WorldDefinitionId")
        _token(self.version, "version")
        if type(self.schema_version) is not int:
            raise TypeError("schema_version must be an integer")
        if self.schema_version < 1:
            raise WorldDefinitionError("schema_version must be positive")
        if self.schema_version != WORLD_DEFINITION_SCHEMA_VERSION:
            raise WorldDefinitionError(
                f"unsupported WorldDefinition schema_version: {self.schema_version}"
            )
        if type(self.vocabulary) is not WorldVocabulary:
            raise TypeError("vocabulary must be a WorldVocabulary")
        if type(self.initial_conditions) is not InitialConditions:
            raise TypeError("initial_conditions must be InitialConditions")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(
            self,
            "metadata",
            freeze_structured_mapping(self.metadata, description="WorldDefinition metadata"),
        )
        self._validate_initial_conditions()

    @property
    def ref(self) -> WorldDefinitionRef:
        return WorldDefinitionRef(self.world_definition_id, self.version)

    def _validate_initial_conditions(self) -> None:
        initial = self.initial_conditions
        entity_ids = tuple(item.entity_id for item in initial.entities)
        relation_ids = tuple(item.relation_id for item in initial.relations)
        resource_keys = tuple(
            ResourceKey(item.entity_id, item.resource_type) for item in initial.resources
        )
        variable_keys = tuple(
            StateVariableKey(item.scope, item.state_variable_type)
            for item in initial.state_variables
        )

        _reject_duplicates(entity_ids, "initial Entity IDs")
        _reject_duplicates(relation_ids, "initial Relation IDs")
        _reject_duplicates(resource_keys, "initial Resource keys")
        _reject_duplicates(variable_keys, "initial StateVariable keys")

        existing_entities = frozenset(entity_ids)
        for entity in initial.entities:
            if entity.entity_type not in self.vocabulary.entity_types:
                raise WorldDefinitionError(
                    f"initial Entity uses undeclared entity_type: {entity.entity_type}"
                )
        for relation in initial.relations:
            if relation.relation_type not in self.vocabulary.relation_types:
                raise WorldDefinitionError(
                    f"initial Relation uses undeclared relation_type: {relation.relation_type}"
                )
            if any(item.entity_id not in existing_entities for item in relation.participants):
                raise WorldDefinitionError(
                    "initial Relation participants must reference initial Entities"
                )
        for resource in initial.resources:
            if resource.resource_type not in self.vocabulary.resource_types:
                raise WorldDefinitionError(
                    f"initial Resource uses undeclared resource_type: {resource.resource_type}"
                )
            if resource.entity_id not in existing_entities:
                raise WorldDefinitionError("initial Resources must reference initial Entities")
        for variable in initial.state_variables:
            if variable.state_variable_type not in self.vocabulary.state_variable_types:
                raise WorldDefinitionError(
                    "initial StateVariable uses undeclared state_variable_type: "
                    f"{variable.state_variable_type}"
                )
            if (
                type(variable.scope) is EntityScope
                and variable.scope.entity_id not in existing_entities
            ):
                raise WorldDefinitionError(
                    "initial Entity-scoped StateVariables must reference initial Entities"
                )


@dataclass(frozen=True, slots=True)
class SimulationRunConfig:
    """Slice 4 run configuration containing only the selected world version."""

    world_definition_ref: WorldDefinitionRef

    def __post_init__(self) -> None:
        if type(self.world_definition_ref) is not WorldDefinitionRef:
            raise TypeError("world_definition_ref must be a WorldDefinitionRef")


def _reject_duplicates(values: Sequence[object], description: str) -> None:
    if len(set(values)) != len(values):
        raise WorldDefinitionError(f"{description} must be unique")


def _load_vocabulary(value: object) -> WorldVocabulary:
    document = _exact_mapping(value, "vocabulary")
    fields = frozenset({"entity_types", "relation_types", "resource_types", "state_variable_types"})
    _fields(document, fields, "vocabulary")
    return WorldVocabulary(
        entity_types=_unique_values(
            _sequence(document["entity_types"], "entity_types"), "entity_types"
        ),
        relation_types=_unique_values(
            _sequence(document["relation_types"], "relation_types"), "relation_types"
        ),
        resource_types=_unique_values(
            _sequence(document["resource_types"], "resource_types"), "resource_types"
        ),
        state_variable_types=_unique_values(
            _sequence(document["state_variable_types"], "state_variable_types"),
            "state_variable_types",
        ),
    )


def _load_participants(value: object) -> frozenset[RelationParticipant]:
    participants: list[RelationParticipant] = []
    for value_item in _sequence(value, "participants"):
        item = _exact_mapping(value_item, "participant")
        _fields(item, frozenset({"role", "entity_id"}), "participant")
        participants.append(
            RelationParticipant(
                role=_token(item["role"], "role"),
                entity_id=EntityId(_token(item["entity_id"], "entity_id")),
            )
        )
    if not participants:
        raise WorldDefinitionError("participants must not be empty")
    frozen = frozenset(participants)
    if len(frozen) != len(participants):
        raise WorldDefinitionError("participants must not contain duplicate bindings")
    return frozen


def _load_scope(value: object) -> StateVariableScope:
    scope = _exact_mapping(value, "scope")
    kind = scope.get("kind")
    if kind == "WORLD":
        _fields(scope, frozenset({"kind"}), "scope")
        return WorldScope()
    if kind == "ENTITY":
        _fields(scope, frozenset({"kind", "entity_id"}), "scope")
        return EntityScope(EntityId(_token(scope["entity_id"], "entity_id")))
    raise WorldDefinitionError("scope.kind must be WORLD or ENTITY")


def _load_initial_conditions(value: object) -> InitialConditions:
    document = _exact_mapping(value, "initial_conditions")
    _fields(
        document,
        frozenset({"logical_time", "entities", "relations", "resources", "state_variables"}),
        "initial_conditions",
    )

    logical_time = document["logical_time"]
    if type(logical_time) is not int:
        raise WorldDefinitionError("logical_time must be an integer")
    try:
        time = LogicalTime(logical_time)
    except (TypeError, ValueError) as error:
        raise WorldDefinitionError(str(error)) from error

    entities: list[InitialEntity] = []
    for raw in _sequence(document["entities"], "entities"):
        item = _exact_mapping(raw, "initial Entity")
        _fields(item, frozenset({"entity_id", "entity_type", "properties"}), "initial Entity")
        entities.append(
            InitialEntity(
                EntityId(_token(item["entity_id"], "entity_id")),
                _token(item["entity_type"], "entity_type"),
                _structured_mapping(item["properties"], "properties"),
            )
        )

    relations: list[InitialRelation] = []
    for raw in _sequence(document["relations"], "relations"):
        item = _exact_mapping(raw, "initial Relation")
        _fields(
            item,
            frozenset({"relation_id", "relation_type", "participants", "properties"}),
            "initial Relation",
        )
        relations.append(
            InitialRelation(
                RelationId(_token(item["relation_id"], "relation_id")),
                _token(item["relation_type"], "relation_type"),
                _load_participants(item["participants"]),
                _structured_mapping(item["properties"], "properties"),
            )
        )

    resources: list[InitialResource] = []
    for raw in _sequence(document["resources"], "resources"):
        item = _exact_mapping(raw, "initial Resource")
        _fields(
            item,
            frozenset({"entity_id", "resource_type", "quantity"}),
            "initial Resource",
        )
        quantity = item["quantity"]
        if type(quantity) not in (int, float):
            raise WorldDefinitionError("quantity must be an integer or finite float")
        resources.append(
            InitialResource(
                EntityId(_token(item["entity_id"], "entity_id")),
                _token(item["resource_type"], "resource_type"),
                cast("ResourceQuantity", quantity),
            )
        )

    state_variables: list[InitialStateVariable] = []
    for raw in _sequence(document["state_variables"], "state_variables"):
        item = _exact_mapping(raw, "initial StateVariable")
        _fields(
            item,
            frozenset({"scope", "state_variable_type", "value"}),
            "initial StateVariable",
        )
        state_variables.append(
            InitialStateVariable(
                _load_scope(item["scope"]),
                _token(item["state_variable_type"], "state_variable_type"),
                _structured_value(item["value"]),
            )
        )

    return InitialConditions(time, entities, relations, resources, state_variables)


def load_world_definition(document: Mapping[str, object]) -> WorldDefinition:
    """Strictly load schema version 1 from an already parsed mapping."""

    root = _exact_mapping(document, "WorldDefinition")
    _fields(
        root,
        frozenset(
            {
                "world_definition_id",
                "version",
                "schema_version",
                "vocabulary",
                "initial_conditions",
                "metadata",
            }
        ),
        "WorldDefinition",
    )
    schema_version = root["schema_version"]
    if type(schema_version) is not int:
        raise WorldDefinitionError("schema_version must be an integer")

    try:
        return WorldDefinition(
            world_definition_id=WorldDefinitionId(
                _token(root["world_definition_id"], "world_definition_id")
            ),
            version=_token(root["version"], "version"),
            schema_version=schema_version,
            vocabulary=_load_vocabulary(root["vocabulary"]),
            initial_conditions=_load_initial_conditions(root["initial_conditions"]),
            metadata=_structured_mapping(root["metadata"], "metadata"),
        )
    except WorldDefinitionError:
        raise
    except (TypeError, ValueError) as error:
        raise WorldDefinitionError(str(error)) from error
