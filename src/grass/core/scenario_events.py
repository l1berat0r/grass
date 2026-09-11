# SPDX-License-Identifier: GPL-3.0-only

"""Strict versioned payload decoding for scenario occurrence Events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from grass.core._structured_data import StructuredValue
from grass.core.events import Event
from grass.core.identifiers import ScenarioEventRuleId, WorldDefinitionId
from grass.core.world_definitions import (
    ScenarioEventRuleRef,
    ScenarioOccurrenceRef,
    WorldDefinitionRef,
)

SCENARIO_OCCURRENCE_RESOLVED = "ScenarioOccurrenceResolved"
SCENARIO_EVENT_TYPES = frozenset({SCENARIO_OCCURRENCE_RESOLVED})


class ScenarioEventPayloadError(ValueError):
    """A known scenario Event has an invalid version or payload."""


@dataclass(frozen=True, slots=True)
class ScenarioOccurrenceResolvedPayload:
    occurrence_ref: ScenarioOccurrenceRef

    def __post_init__(self) -> None:
        if type(self.occurrence_ref) is not ScenarioOccurrenceRef:
            raise TypeError("occurrence_ref must be a ScenarioOccurrenceRef")


def _mapping(value: object, field_name: str) -> Mapping[str, StructuredValue]:
    if not isinstance(value, Mapping):
        raise ScenarioEventPayloadError(f"{field_name} must be a mapping")
    if not all(type(key) is str for key in value):
        raise ScenarioEventPayloadError(f"{field_name} keys must be strings")
    return cast("Mapping[str, StructuredValue]", value)


def _fields(
    value: Mapping[str, StructuredValue], expected: frozenset[str], field_name: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ScenarioEventPayloadError(
            f"{field_name} fields do not match schema; missing={missing}, extra={extra}"
        )


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or value == "":
        raise ScenarioEventPayloadError(f"{field_name} must be a non-empty string")
    return value


def scenario_occurrence_ref_payload(
    occurrence_ref: ScenarioOccurrenceRef,
) -> Mapping[str, StructuredValue]:
    """Encode one occurrence reference for a strict Event payload."""

    if type(occurrence_ref) is not ScenarioOccurrenceRef:
        raise TypeError("occurrence_ref must be a ScenarioOccurrenceRef")
    rule_ref = occurrence_ref.scenario_event_rule_ref
    definition_ref = rule_ref.world_definition_ref
    return {
        "scenario_event_rule_ref": {
            "world_definition_ref": {
                "world_definition_id": definition_ref.world_definition_id.value,
                "version": definition_ref.version,
            },
            "rule_id": rule_ref.rule_id.value,
        }
    }


def _scenario_occurrence_ref(value: object) -> ScenarioOccurrenceRef:
    occurrence = _mapping(value, "occurrence_ref")
    _fields(occurrence, frozenset({"scenario_event_rule_ref"}), "occurrence_ref")
    rule = _mapping(occurrence["scenario_event_rule_ref"], "scenario_event_rule_ref")
    _fields(
        rule,
        frozenset({"world_definition_ref", "rule_id"}),
        "scenario_event_rule_ref",
    )
    definition = _mapping(rule["world_definition_ref"], "world_definition_ref")
    _fields(
        definition,
        frozenset({"world_definition_id", "version"}),
        "world_definition_ref",
    )
    return ScenarioOccurrenceRef(
        ScenarioEventRuleRef(
            WorldDefinitionRef(
                WorldDefinitionId(_token(definition["world_definition_id"], "world_definition_id")),
                _token(definition["version"], "version"),
            ),
            ScenarioEventRuleId(_token(rule["rule_id"], "rule_id")),
        )
    )


def decode_scenario_event(event: Event) -> ScenarioOccurrenceResolvedPayload:
    """Decode one known version-1 scenario occurrence Event."""

    if type(event) is not Event:
        raise TypeError("event must be an Event")
    if event.event_type not in SCENARIO_EVENT_TYPES:
        raise ScenarioEventPayloadError(f"unknown scenario Event type: {event.event_type}")
    if event.event_version != 1:
        raise ScenarioEventPayloadError(
            f"unsupported {event.event_type} version: {event.event_version}"
        )
    _fields(event.payload, frozenset({"occurrence_ref"}), "payload")
    return ScenarioOccurrenceResolvedPayload(
        _scenario_occurrence_ref(event.payload["occurrence_ref"])
    )
