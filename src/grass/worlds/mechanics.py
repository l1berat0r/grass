# SPDX-License-Identifier: GPL-3.0-only

"""Execution adapters for data-defined scenario occurrence mechanics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import cast

from grass.core import (
    GEL_V1_INTEGER_MAX,
    GEL_V1_INTEGER_MIN,
    AtTimeScenarioEventRule,
    BuiltinSetStateVariableMechanic,
    GelError,
    GelInputValue,
    GelSetStateVariableMechanic,
    PreparedGelProgram,
    ScenarioOccurrenceRef,
    ScenarioOccurrenceResolutionProposal,
    ScenarioOccurrenceResolutionRequest,
    SetStateVariableEffect,
    WorldDefinition,
    execute_gel,
    prepare_gel,
)
from grass.core._structured_data import StructuredValue


class WorldMechanicExecutionError(RuntimeError):
    """A configured world mechanic cannot produce its candidate effect."""


def _gel_input_value(value: StructuredValue, /) -> GelInputValue:
    if type(value) is bool:
        return value
    if type(value) is int:
        if value < GEL_V1_INTEGER_MIN or value > GEL_V1_INTEGER_MAX:
            raise WorldMechanicExecutionError(
                "StateVariable integer is outside the GEL v1 integer domain"
            )
        return value
    if type(value) is str:
        return value
    if isinstance(value, Mapping):
        converted: dict[str, GelInputValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise WorldMechanicExecutionError("StateVariable mapping contains a non-string key")
            converted[key] = _gel_input_value(item)
        return converted
    if isinstance(value, Sequence):
        return [_gel_input_value(item) for item in value]
    if value is None:
        raise WorldMechanicExecutionError("GEL mechanics do not support null StateVariables")
    if type(value) is float:
        raise WorldMechanicExecutionError("GEL mechanics do not support float StateVariables")
    raise WorldMechanicExecutionError(
        f"GEL mechanic received an unsupported StateVariable value: {type(value).__name__}"
    )


class DataDefinedScenarioOccurrenceResolver:
    """Resolve schema-v3 occurrences through their exact configured mechanic."""

    def __init__(self, world_definition: WorldDefinition, /) -> None:
        if type(world_definition) is not WorldDefinition:
            raise TypeError("world_definition must be a WorldDefinition")
        if world_definition.schema_version != 3:
            raise ValueError("data-defined occurrence resolution requires schema version 3")

        rules: dict[ScenarioOccurrenceRef, AtTimeScenarioEventRule] = {}
        prepared: dict[ScenarioOccurrenceRef, PreparedGelProgram] = {}
        for rule in world_definition.scenario_event_rules:
            occurrence_ref = ScenarioOccurrenceRef(rule.ref(world_definition.ref))
            mechanic = rule.mechanic
            if type(mechanic) is BuiltinSetStateVariableMechanic:
                rules[occurrence_ref] = rule
            elif type(mechanic) is GelSetStateVariableMechanic:
                rules[occurrence_ref] = rule
                prepared[occurrence_ref] = prepare_gel(mechanic.program)
            else:  # pragma: no cover - WorldDefinition v3 enforces this invariant
                raise ValueError("schema version 3 rule has no supported mechanic")

        self._rules = MappingProxyType(rules)
        self._prepared_gel = MappingProxyType(prepared)

    def resolve(
        self, request: ScenarioOccurrenceResolutionRequest, /
    ) -> ScenarioOccurrenceResolutionProposal:
        """Propose exactly one effect for the request's exact configured rule."""

        if type(request) is not ScenarioOccurrenceResolutionRequest:
            raise TypeError("request must be a ScenarioOccurrenceResolutionRequest")
        rule = self._rules.get(request.occurrence_ref)
        if rule is None or request.rule != rule:
            raise WorldMechanicExecutionError(
                "occurrence request does not match a configured WorldDefinition rule"
            )

        mechanic = request.rule.mechanic
        if type(mechanic) is BuiltinSetStateVariableMechanic:
            value_after = mechanic.value
        elif type(mechanic) is GelSetStateVariableMechanic:
            try:
                current_value = request.state.world.state_variables[mechanic.target]
            except KeyError as error:
                raise WorldMechanicExecutionError(
                    "GEL mechanic target StateVariable does not exist"
                ) from error
            prepared = self._prepared_gel.get(request.occurrence_ref)
            if prepared is None:  # pragma: no cover - constructor builds the complete cache
                raise WorldMechanicExecutionError("GEL mechanic has no prepared program")
            inputs = {"current_value": _gel_input_value(current_value)}
            try:
                output = execute_gel(prepared, inputs)
            except GelError as error:
                raise WorldMechanicExecutionError("GEL mechanic execution failed") from error
            if not isinstance(output, Mapping) or set(output) != {"new_value"}:
                raise WorldMechanicExecutionError(
                    "GEL mechanic output must contain exactly new_value"
                )
            value_after = cast("StructuredValue", output["new_value"])
        else:
            raise WorldMechanicExecutionError("occurrence rule has no supported mechanic")

        return ScenarioOccurrenceResolutionProposal(
            (
                SetStateVariableEffect(
                    mechanic.target.scope,
                    mechanic.target.state_variable_type,
                    value_after,
                ),
            )
        )
