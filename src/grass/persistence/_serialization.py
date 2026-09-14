# SPDX-License-Identifier: GPL-3.0-only

"""Strict canonical JSON codecs for durable local persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from grass.core._structured_data import StructuredValue, freeze_structured_mapping
from grass.core.events import CauseRef
from grass.core.identifiers import (
    EntityId,
    ModelProviderBindingId,
    ProviderBindingId,
)
from grass.core.provenance import Provenance, ProvenanceSourceRef
from grass.core.provider_bindings import (
    DecisionProviderBinding,
    DecisionProviderRouting,
    ModelProviderBinding,
    ProviderBindingConfiguration,
    ProviderExecutionLocation,
)
from grass.core.state import EntityScope, WorldScope
from grass.core.world_definitions import (
    WORLD_DEFINITION_SCHEMA_VERSION,
    SimulationRunConfig,
    WorldDefinition,
    WorldDefinitionRef,
    load_world_definition,
)
from grass.persistence.contracts import (
    PersistenceIntegrityError,
    UnsupportedStorageVersionError,
)

RUN_CONFIG_DOCUMENT_VERSION = 1


def _json_value(value: StructuredValue) -> object:
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_json_value(item) for item in value]
    raise TypeError("unsupported structured persistence value")


def _dumps(document: object) -> str:
    try:
        return json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise PersistenceIntegrityError("value cannot be encoded as canonical JSON") from error


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number is unsupported: {value}")


def _loads(value: str, description: str) -> object:
    if type(value) is not str:
        raise TypeError(f"{description} JSON must be a string")
    try:
        return json.loads(value, parse_constant=_reject_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise PersistenceIntegrityError(f"stored {description} JSON is invalid") from error


def _mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(type(key) is str for key in value):
        raise PersistenceIntegrityError(f"stored {description} must be an object")
    return cast("Mapping[str, object]", value)


def _sequence(value: object, description: str) -> Sequence[object]:
    if type(value) is not list:
        raise PersistenceIntegrityError(f"stored {description} must be an array")
    return cast("Sequence[object]", value)


def _fields(value: Mapping[str, object], expected: frozenset[str], description: str) -> None:
    if frozenset(value) != expected:
        raise PersistenceIntegrityError(f"stored {description} fields do not match schema")


def _token(value: object, description: str) -> str:
    if type(value) is not str or value == "":
        raise PersistenceIntegrityError(f"stored {description} must be a non-empty string")
    return value


def encode_structured_mapping(value: Mapping[str, StructuredValue]) -> str:
    return _dumps(_json_value(cast(StructuredValue, value)))


def decode_structured_mapping(value: str, description: str) -> Mapping[str, StructuredValue]:
    document = _mapping(_loads(value, description), description)
    try:
        return freeze_structured_mapping(
            cast("Mapping[str, StructuredValue]", document), description=description
        )
    except (TypeError, ValueError) as error:
        raise PersistenceIntegrityError(f"stored {description} is invalid") from error


def encode_provenance(value: Provenance) -> str:
    source_ref: object = None
    if value.source_ref is not None:
        source_ref = {"kind": value.source_ref.kind, "value": value.source_ref.value}
    return _dumps(
        {
            "source_kind": value.source_kind,
            "source_ref": source_ref,
            "metadata": _json_value(cast(StructuredValue, value.metadata)),
        }
    )


def decode_provenance(value: str) -> Provenance:
    document = _mapping(_loads(value, "provenance"), "provenance")
    _fields(document, frozenset({"source_kind", "source_ref", "metadata"}), "provenance")
    raw_ref = document["source_ref"]
    source_ref = None
    if raw_ref is not None:
        ref = _mapping(raw_ref, "provenance source_ref")
        _fields(ref, frozenset({"kind", "value"}), "provenance source_ref")
        source_ref = ProvenanceSourceRef(
            _token(ref["kind"], "provenance source_ref kind"),
            _token(ref["value"], "provenance source_ref value"),
        )
    metadata = _mapping(document["metadata"], "provenance metadata")
    try:
        return Provenance(
            _token(document["source_kind"], "provenance source_kind"),
            source_ref,
            cast("Mapping[str, StructuredValue]", metadata),
        )
    except (TypeError, ValueError) as error:
        raise PersistenceIntegrityError("stored provenance is invalid") from error


def encode_causes(values: Sequence[CauseRef]) -> str:
    return _dumps([{"kind": item.kind, "value": item.value} for item in values])


def decode_causes(value: str) -> tuple[CauseRef, ...]:
    causes: list[CauseRef] = []
    for raw in _sequence(_loads(value, "causation references"), "causation references"):
        item = _mapping(raw, "cause reference")
        _fields(item, frozenset({"kind", "value"}), "cause reference")
        try:
            causes.append(
                CauseRef(
                    _token(item["kind"], "cause kind"),
                    _token(item["value"], "cause value"),
                )
            )
        except (TypeError, ValueError) as error:
            raise PersistenceIntegrityError("stored cause reference is invalid") from error
    return tuple(causes)


def _scope_document(scope: WorldScope | EntityScope) -> Mapping[str, object]:
    if type(scope) is WorldScope:
        return {"kind": "WORLD"}
    if type(scope) is EntityScope:
        return {"kind": "ENTITY", "entity_id": scope.entity_id.value}
    raise TypeError("scope must be WorldScope or EntityScope")


def world_definition_document(value: WorldDefinition) -> Mapping[str, object]:
    initial = value.initial_conditions
    document: dict[str, object] = {
        "world_definition_id": value.world_definition_id.value,
        "version": value.version,
        "schema_version": value.schema_version,
        "vocabulary": {
            "entity_types": sorted(value.vocabulary.entity_types),
            "relation_types": sorted(value.vocabulary.relation_types),
            "resource_types": sorted(value.vocabulary.resource_types),
            "state_variable_types": sorted(value.vocabulary.state_variable_types),
        },
        "initial_conditions": {
            "logical_time": initial.logical_time.nanoseconds_from_origin,
            "entities": [
                {
                    "entity_id": item.entity_id.value,
                    "entity_type": item.entity_type,
                    "properties": _json_value(cast(StructuredValue, item.properties)),
                }
                for item in initial.entities
            ],
            "relations": [
                {
                    "relation_id": item.relation_id.value,
                    "relation_type": item.relation_type,
                    "participants": [
                        {"role": participant.role, "entity_id": participant.entity_id.value}
                        for participant in sorted(
                            item.participants,
                            key=lambda participant: (participant.role, participant.entity_id.value),
                        )
                    ],
                    "properties": _json_value(cast(StructuredValue, item.properties)),
                }
                for item in initial.relations
            ],
            "resources": [
                {
                    "entity_id": item.entity_id.value,
                    "resource_type": item.resource_type,
                    "quantity": item.quantity,
                }
                for item in initial.resources
            ],
            "state_variables": [
                {
                    "scope": _scope_document(item.scope),
                    "state_variable_type": item.state_variable_type,
                    "value": _json_value(item.value),
                }
                for item in initial.state_variables
            ],
        },
        "metadata": _json_value(cast(StructuredValue, value.metadata)),
    }
    if value.schema_version == 2:
        document["scenario_event_rules"] = [
            {
                "rule_id": rule.rule_id.value,
                "trigger": {
                    "kind": "AT_TIME",
                    "logical_time": rule.logical_time.nanoseconds_from_origin,
                },
            }
            for rule in value.scenario_event_rules
        ]
    return document


def encode_world_definition(value: WorldDefinition) -> str:
    if type(value) is not WorldDefinition:
        raise TypeError("value must be a WorldDefinition")
    return _dumps(world_definition_document(value))


def decode_world_definition(value: str) -> WorldDefinition:
    document = _mapping(_loads(value, "WorldDefinition"), "WorldDefinition")
    schema_version = document.get("schema_version")
    if type(schema_version) is not int:
        raise PersistenceIntegrityError("stored WorldDefinition schema_version must be an integer")
    if schema_version > WORLD_DEFINITION_SCHEMA_VERSION:
        raise UnsupportedStorageVersionError(
            f"unsupported WorldDefinition document version: {schema_version}"
        )
    try:
        return load_world_definition(document)
    except (TypeError, ValueError) as error:
        raise PersistenceIntegrityError("stored WorldDefinition is invalid") from error


def _world_ref_document(value: WorldDefinitionRef) -> Mapping[str, object]:
    return {
        "world_definition_id": value.world_definition_id.value,
        "version": value.version,
    }


def _decode_world_ref(value: object) -> WorldDefinitionRef:
    document = _mapping(value, "WorldDefinitionRef")
    _fields(
        document,
        frozenset({"world_definition_id", "version"}),
        "WorldDefinitionRef",
    )
    from grass.core.identifiers import WorldDefinitionId

    return WorldDefinitionRef(
        WorldDefinitionId(_token(document["world_definition_id"], "world_definition_id")),
        _token(document["version"], "WorldDefinition version"),
    )


def _provider_bindings_document(value: ProviderBindingConfiguration) -> Mapping[str, object]:
    routing = value.routing
    return {
        "routing": {
            "default_binding_id": routing.default_binding_id.value,
            "group_bindings": [
                {"group": group, "binding_id": binding_id.value}
                for group, binding_id in sorted(routing.group_bindings.items())
            ],
            "actor_group_assignments": [
                {"actor_id": actor_id.value, "group": group}
                for actor_id, group in sorted(
                    routing.actor_group_assignments.items(), key=lambda item: item[0].value
                )
            ],
            "actor_bindings": [
                {"actor_id": actor_id.value, "binding_id": binding_id.value}
                for actor_id, binding_id in sorted(
                    routing.actor_bindings.items(), key=lambda item: item[0].value
                )
            ],
        },
        "decision_bindings": [
            {
                "binding_id": binding.binding_id.value,
                "invoker_ref": binding.invoker_ref,
                "execution_location": binding.execution_location.value,
                "model_binding_id": (
                    None if binding.model_binding_id is None else binding.model_binding_id.value
                ),
            }
            for _, binding in sorted(
                value.decision_bindings.items(), key=lambda item: item[0].value
            )
        ],
        "model_bindings": [
            {
                "binding_id": binding.binding_id.value,
                "provider_ref": binding.provider_ref,
                "model": binding.model,
            }
            for _, binding in sorted(value.model_bindings.items(), key=lambda item: item[0].value)
        ],
    }


def encode_run_config(value: SimulationRunConfig) -> str:
    if type(value) is not SimulationRunConfig:
        raise TypeError("value must be a SimulationRunConfig")
    return _dumps(
        {
            "schema_version": RUN_CONFIG_DOCUMENT_VERSION,
            "world_definition_ref": _world_ref_document(value.world_definition_ref),
            "provider_bindings": (
                None
                if value.provider_bindings is None
                else _provider_bindings_document(value.provider_bindings)
            ),
        }
    )


def _entries(value: object, description: str) -> Sequence[Mapping[str, object]]:
    entries = tuple(_mapping(item, description) for item in _sequence(value, description))
    return entries


def _decode_provider_bindings(value: object) -> ProviderBindingConfiguration:
    document = _mapping(value, "provider bindings")
    _fields(
        document,
        frozenset({"routing", "decision_bindings", "model_bindings"}),
        "provider bindings",
    )
    routing_document = _mapping(document["routing"], "provider routing")
    _fields(
        routing_document,
        frozenset(
            {
                "default_binding_id",
                "group_bindings",
                "actor_group_assignments",
                "actor_bindings",
            }
        ),
        "provider routing",
    )

    group_bindings: dict[str, ProviderBindingId] = {}
    for item in _entries(routing_document["group_bindings"], "group binding"):
        _fields(item, frozenset({"group", "binding_id"}), "group binding")
        group = _token(item["group"], "routing group")
        if group in group_bindings:
            raise PersistenceIntegrityError("stored provider routing has a duplicate group")
        group_bindings[group] = ProviderBindingId(_token(item["binding_id"], "binding_id"))

    actor_groups: dict[EntityId, str] = {}
    for item in _entries(routing_document["actor_group_assignments"], "actor group assignment"):
        _fields(item, frozenset({"actor_id", "group"}), "actor group assignment")
        actor_id = EntityId(_token(item["actor_id"], "actor_id"))
        if actor_id in actor_groups:
            raise PersistenceIntegrityError("stored provider routing has a duplicate actor group")
        actor_groups[actor_id] = _token(item["group"], "routing group")

    actor_bindings: dict[EntityId, ProviderBindingId] = {}
    for item in _entries(routing_document["actor_bindings"], "actor binding"):
        _fields(item, frozenset({"actor_id", "binding_id"}), "actor binding")
        actor_id = EntityId(_token(item["actor_id"], "actor_id"))
        if actor_id in actor_bindings:
            raise PersistenceIntegrityError("stored provider routing has a duplicate actor binding")
        actor_bindings[actor_id] = ProviderBindingId(_token(item["binding_id"], "binding_id"))

    models: dict[ModelProviderBindingId, ModelProviderBinding] = {}
    for item in _entries(document["model_bindings"], "model binding"):
        _fields(
            item,
            frozenset({"binding_id", "provider_ref", "model"}),
            "model binding",
        )
        model_binding_id = ModelProviderBindingId(_token(item["binding_id"], "binding_id"))
        if model_binding_id in models:
            raise PersistenceIntegrityError("stored run config has a duplicate model binding")
        models[model_binding_id] = ModelProviderBinding(
            model_binding_id,
            _token(item["provider_ref"], "provider_ref"),
            _token(item["model"], "model"),
        )

    decisions: dict[ProviderBindingId, DecisionProviderBinding] = {}
    for item in _entries(document["decision_bindings"], "decision binding"):
        _fields(
            item,
            frozenset({"binding_id", "invoker_ref", "execution_location", "model_binding_id"}),
            "decision binding",
        )
        decision_binding_id = ProviderBindingId(_token(item["binding_id"], "binding_id"))
        if decision_binding_id in decisions:
            raise PersistenceIntegrityError("stored run config has a duplicate decision binding")
        raw_model_id = item["model_binding_id"]
        model_id = (
            None
            if raw_model_id is None
            else ModelProviderBindingId(_token(raw_model_id, "model_binding_id"))
        )
        try:
            location = ProviderExecutionLocation(
                _token(item["execution_location"], "execution_location")
            )
        except ValueError as error:
            raise PersistenceIntegrityError(
                "stored decision binding execution location is invalid"
            ) from error
        decisions[decision_binding_id] = DecisionProviderBinding(
            decision_binding_id,
            _token(item["invoker_ref"], "invoker_ref"),
            location,
            model_id,
        )

    try:
        return ProviderBindingConfiguration(
            DecisionProviderRouting(
                ProviderBindingId(
                    _token(routing_document["default_binding_id"], "default_binding_id")
                ),
                group_bindings,
                actor_groups,
                actor_bindings,
            ),
            decisions,
            models,
        )
    except (TypeError, ValueError) as error:
        raise PersistenceIntegrityError("stored provider bindings are invalid") from error


def decode_run_config(value: str) -> SimulationRunConfig:
    document = _mapping(_loads(value, "SimulationRunConfig"), "SimulationRunConfig")
    _fields(
        document,
        frozenset({"schema_version", "world_definition_ref", "provider_bindings"}),
        "SimulationRunConfig",
    )
    schema_version = document["schema_version"]
    if type(schema_version) is not int:
        raise PersistenceIntegrityError("stored run config schema_version must be an integer")
    if schema_version != RUN_CONFIG_DOCUMENT_VERSION:
        raise UnsupportedStorageVersionError(
            f"unsupported run config document version: {schema_version}"
        )
    world_ref = _decode_world_ref(document["world_definition_ref"])
    raw_bindings = document["provider_bindings"]
    bindings = None if raw_bindings is None else _decode_provider_bindings(raw_bindings)
    try:
        return SimulationRunConfig(world_ref, bindings)
    except (TypeError, ValueError) as error:
        raise PersistenceIntegrityError("stored SimulationRunConfig is invalid") from error


def encode_datetime(value: datetime) -> str:
    if type(value) is not datetime:
        raise TypeError("value must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def decode_datetime(value: str) -> datetime:
    if type(value) is not str:
        raise TypeError("stored datetime must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise PersistenceIntegrityError("stored operational datetime is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PersistenceIntegrityError("stored operational datetime must be timezone-aware")
    return parsed.astimezone(UTC)
