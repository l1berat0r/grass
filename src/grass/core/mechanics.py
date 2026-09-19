# SPDX-License-Identifier: GPL-3.0-only

"""Data-defined scenario mechanic contracts for WorldDefinition schema v3."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, TypeAlias, cast

from grass.core._structured_data import StructuredValue, freeze_structured_value
from grass.core.gel import (
    GEL_V1_LIMITS,
    GelBooleanSchema,
    GelIntegerSchema,
    GelListSchema,
    GelObjectSchema,
    GelProgram,
    GelSchema,
    GelStringSchema,
    prepare_gel,
    prepared_gel_uses_random,
)
from grass.core.identifiers import EntityId
from grass.core.state import EntityScope, StateVariableKey, WorldScope


class MechanicDefinitionError(ValueError):
    """A data-defined scenario mechanic is malformed or unsupported."""


class MechanicKind(StrEnum):
    BUILTIN = "BUILTIN"
    GEL = "GEL"


class MechanicUsage(StrEnum):
    SET_STATE_VARIABLE = "SET_STATE_VARIABLE"


class BuiltinMechanicImplementation(StrEnum):
    CONSTANT = "CONSTANT"


@dataclass(frozen=True, slots=True)
class BuiltinSetStateVariableMechanic:
    """Set one StateVariable to one immutable configured value."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    target: StateVariableKey
    value: StructuredValue
    kind: MechanicKind = field(default=MechanicKind.BUILTIN, init=False)
    usage: MechanicUsage = field(default=MechanicUsage.SET_STATE_VARIABLE, init=False)
    implementation: BuiltinMechanicImplementation = field(
        default=BuiltinMechanicImplementation.CONSTANT, init=False
    )

    def __post_init__(self) -> None:
        if type(self.target) is not StateVariableKey:
            raise TypeError("target must be a StateVariableKey")
        object.__setattr__(
            self,
            "value",
            freeze_structured_value(self.value, description="constant mechanic value"),
        )


@dataclass(frozen=True, slots=True)
class GelSetStateVariableMechanic:
    """Compute one StateVariable's resulting value through a canonical GEL program."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    target: StateVariableKey
    program: GelProgram
    kind: MechanicKind = field(default=MechanicKind.GEL, init=False)
    usage: MechanicUsage = field(default=MechanicUsage.SET_STATE_VARIABLE, init=False)

    def __post_init__(self) -> None:
        if type(self.target) is not StateVariableKey:
            raise TypeError("target must be a StateVariableKey")
        if type(self.program) is not GelProgram:
            raise TypeError("program must be a GelProgram")
        inputs = self.program.input_schema.fields
        output = self.program.output_schema
        if tuple(inputs) != ("current_value",):
            raise MechanicDefinitionError(
                "SET_STATE_VARIABLE GEL input_schema must contain only current_value"
            )
        if type(output) is not GelObjectSchema or tuple(output.fields) != ("new_value",):
            raise MechanicDefinitionError(
                "SET_STATE_VARIABLE GEL output_schema must contain only new_value"
            )
        if inputs["current_value"] != output.fields["new_value"]:
            raise MechanicDefinitionError(
                "SET_STATE_VARIABLE current_value and new_value schemas must match"
            )
        prepared = prepare_gel(self.program)
        if prepared_gel_uses_random(prepared):
            raise MechanicDefinitionError(
                "Slice 14 SET_STATE_VARIABLE GEL mechanics cannot use random_int"
            )


ScenarioEventMechanic: TypeAlias = BuiltinSetStateVariableMechanic | GelSetStateVariableMechanic


def _mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(type(key) is str for key in value):
        raise MechanicDefinitionError(f"{description} must be an object")
    return cast("Mapping[str, object]", value)


def _fields(value: Mapping[str, object], expected: frozenset[str], description: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise MechanicDefinitionError(
            f"{description} fields do not match schema; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _token(value: object, description: str) -> str:
    if type(value) is not str or value == "":
        raise MechanicDefinitionError(f"{description} must be a non-empty string")
    return value


@dataclass(slots=True)
class _SchemaLoadBudget:
    remaining_nodes: int


def _load_gel_schema(
    value: object,
    *,
    budget: _SchemaLoadBudget,
    depth: int,
) -> GelSchema:
    if depth > GEL_V1_LIMITS.structured_depth:
        raise MechanicDefinitionError("GEL schema depth limit exceeded")
    budget.remaining_nodes -= 1
    if budget.remaining_nodes < 0:
        raise MechanicDefinitionError("GEL schema node limit exceeded")

    document = _mapping(value, "GEL schema")
    schema_type = document.get("type")
    if schema_type == "BOOLEAN":
        _fields(document, frozenset({"type"}), "BOOLEAN GEL schema")
        return GelBooleanSchema()
    if schema_type == "INTEGER":
        _fields(document, frozenset({"type", "minimum", "maximum"}), "INTEGER GEL schema")
        minimum = document["minimum"]
        maximum = document["maximum"]
        if type(minimum) is not int or type(maximum) is not int:
            raise MechanicDefinitionError("INTEGER GEL schema bounds must be integers")
        return GelIntegerSchema(minimum, maximum)
    if schema_type == "STRING":
        _fields(document, frozenset({"type", "max_length"}), "STRING GEL schema")
        max_length = document["max_length"]
        if type(max_length) is not int:
            raise MechanicDefinitionError("STRING GEL schema max_length must be an integer")
        return GelStringSchema(max_length)
    if schema_type == "LIST":
        _fields(document, frozenset({"type", "item_schema", "max_items"}), "LIST GEL schema")
        max_items = document["max_items"]
        if type(max_items) is not int:
            raise MechanicDefinitionError("LIST GEL schema max_items must be an integer")
        return GelListSchema(
            _load_gel_schema(
                document["item_schema"],
                budget=budget,
                depth=depth + 1,
            ),
            max_items,
        )
    if schema_type == "OBJECT":
        _fields(document, frozenset({"type", "fields"}), "OBJECT GEL schema")
        raw_fields = _mapping(document["fields"], "OBJECT GEL schema fields")
        return GelObjectSchema(
            {
                name: _load_gel_schema(schema, budget=budget, depth=depth + 1)
                for name, schema in raw_fields.items()
            }
        )
    raise MechanicDefinitionError("GEL schema type is unsupported")


def load_gel_schema(value: object, /) -> GelSchema:
    """Strictly load one canonical GEL schema document within v1 input limits."""

    return _load_gel_schema(
        value,
        budget=_SchemaLoadBudget(GEL_V1_LIMITS.input_nodes),
        depth=1,
    )


def gel_schema_document(value: GelSchema, /) -> Mapping[str, object]:
    """Encode one GEL schema into its canonical JSON-compatible document."""

    if type(value) is GelBooleanSchema:
        return {"type": "BOOLEAN"}
    if type(value) is GelIntegerSchema:
        return {"type": "INTEGER", "minimum": value.minimum, "maximum": value.maximum}
    if type(value) is GelStringSchema:
        return {"type": "STRING", "max_length": value.max_length}
    if type(value) is GelListSchema:
        return {
            "type": "LIST",
            "item_schema": gel_schema_document(value.item_schema),
            "max_items": value.max_items,
        }
    if type(value) is GelObjectSchema:
        return {
            "type": "OBJECT",
            "fields": {name: gel_schema_document(schema) for name, schema in value.fields.items()},
        }
    raise TypeError("value must be a GEL schema")


def _load_target(value: object) -> StateVariableKey:
    document = _mapping(value, "mechanic target")
    _fields(document, frozenset({"scope", "state_variable_type"}), "mechanic target")
    scope_document = _mapping(document["scope"], "mechanic target scope")
    scope: WorldScope | EntityScope
    if scope_document.get("kind") == "WORLD":
        _fields(scope_document, frozenset({"kind"}), "WORLD mechanic target scope")
        scope = WorldScope()
    elif scope_document.get("kind") == "ENTITY":
        _fields(
            scope_document,
            frozenset({"kind", "entity_id"}),
            "ENTITY mechanic target scope",
        )
        scope = EntityScope(EntityId(_token(scope_document["entity_id"], "entity_id")))
    else:
        raise MechanicDefinitionError("mechanic target scope kind must be WORLD or ENTITY")
    return StateVariableKey(
        scope,
        _token(document["state_variable_type"], "state_variable_type"),
    )


def _target_document(value: StateVariableKey) -> Mapping[str, object]:
    scope: Mapping[str, object]
    if type(value.scope) is WorldScope:
        scope = {"kind": "WORLD"}
    elif type(value.scope) is EntityScope:
        scope = {"kind": "ENTITY", "entity_id": value.scope.entity_id.value}
    else:  # pragma: no cover - StateVariableKey validates this
        raise TypeError("unsupported StateVariable scope")
    return {"scope": scope, "state_variable_type": value.state_variable_type}


def load_scenario_event_mechanic(value: object, /) -> ScenarioEventMechanic:
    """Strictly load one canonical schema-v3 scenario mechanic."""

    document = _mapping(value, "scenario mechanic")
    kind = document.get("kind")
    usage = document.get("usage")
    if usage != MechanicUsage.SET_STATE_VARIABLE:
        raise MechanicDefinitionError("scenario mechanic usage must be SET_STATE_VARIABLE")
    target = _load_target(document.get("target"))
    if kind == MechanicKind.BUILTIN:
        _fields(
            document,
            frozenset({"kind", "usage", "implementation", "target", "value"}),
            "BUILTIN scenario mechanic",
        )
        if document["implementation"] != BuiltinMechanicImplementation.CONSTANT:
            raise MechanicDefinitionError("BUILTIN implementation must be CONSTANT")
        return BuiltinSetStateVariableMechanic(
            target,
            cast("StructuredValue", document["value"]),
        )
    if kind == MechanicKind.GEL:
        _fields(
            document,
            frozenset({"kind", "usage", "target", "program"}),
            "GEL scenario mechanic",
        )
        program_document = _mapping(document["program"], "GEL program")
        _fields(
            program_document,
            frozenset({"source", "language_version", "input_schema", "output_schema"}),
            "GEL program",
        )
        source = program_document["source"]
        language_version = program_document["language_version"]
        if type(source) is not str:
            raise MechanicDefinitionError("GEL program source must be a string")
        if type(language_version) is not int:
            raise MechanicDefinitionError("GEL program language_version must be an integer")
        input_schema = _load_gel_schema(
            program_document["input_schema"],
            budget=_SchemaLoadBudget(GEL_V1_LIMITS.input_nodes),
            depth=1,
        )
        if type(input_schema) is not GelObjectSchema:
            raise MechanicDefinitionError("GEL program input_schema must be an OBJECT schema")
        return GelSetStateVariableMechanic(
            target,
            GelProgram(
                source,
                language_version,
                input_schema,
                _load_gel_schema(
                    program_document["output_schema"],
                    budget=_SchemaLoadBudget(GEL_V1_LIMITS.result_nodes),
                    depth=1,
                ),
            ),
        )
    raise MechanicDefinitionError("scenario mechanic kind must be BUILTIN or GEL")


def scenario_event_mechanic_document(value: ScenarioEventMechanic, /) -> Mapping[str, object]:
    """Encode one schema-v3 scenario mechanic canonically."""

    if type(value) is BuiltinSetStateVariableMechanic:
        return {
            "kind": value.kind.value,
            "usage": value.usage.value,
            "implementation": value.implementation.value,
            "target": _target_document(value.target),
            "value": value.value,
        }
    if type(value) is GelSetStateVariableMechanic:
        return {
            "kind": value.kind.value,
            "usage": value.usage.value,
            "target": _target_document(value.target),
            "program": {
                "source": value.program.source,
                "language_version": value.program.language_version,
                "input_schema": gel_schema_document(value.program.input_schema),
                "output_schema": gel_schema_document(value.program.output_schema),
            },
        }
    raise TypeError("value must be a supported ScenarioEventMechanic")
