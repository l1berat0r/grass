# SPDX-License-Identifier: GPL-3.0-only

"""Strict payload decoding for the SimulationInitialized Event."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from grass.core._structured_data import StructuredValue
from grass.core.events import Event
from grass.core.identifiers import WorldDefinitionId
from grass.core.world_definitions import WorldDefinitionRef

SIMULATION_INITIALIZED = "SimulationInitialized"


class InitializationEventPayloadError(ValueError):
    """A SimulationInitialized Event has an invalid version or payload."""


@dataclass(frozen=True, slots=True)
class SimulationInitializedPayload:
    world_definition_ref: WorldDefinitionRef
    world_definition_schema_version: int

    def __post_init__(self) -> None:
        if type(self.world_definition_ref) is not WorldDefinitionRef:
            raise TypeError("world_definition_ref must be a WorldDefinitionRef")
        if type(self.world_definition_schema_version) is not int:
            raise TypeError("world_definition_schema_version must be an integer")
        if self.world_definition_schema_version < 1:
            raise InitializationEventPayloadError(
                "world_definition_schema_version must be positive"
            )


def _mapping(value: object, field_name: str) -> Mapping[str, StructuredValue]:
    if not isinstance(value, Mapping):
        raise InitializationEventPayloadError(f"{field_name} must be a mapping")
    if not all(type(key) is str for key in value):
        raise InitializationEventPayloadError(f"{field_name} keys must be strings")
    return cast("Mapping[str, StructuredValue]", value)


def _fields(
    value: Mapping[str, StructuredValue], expected: frozenset[str], field_name: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise InitializationEventPayloadError(
            f"{field_name} fields do not match schema; missing={missing}, extra={extra}"
        )


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or value == "":
        raise InitializationEventPayloadError(f"{field_name} must be a non-empty string")
    return value


def decode_initialization_event(event: Event) -> SimulationInitializedPayload:
    """Decode one supported version-1 SimulationInitialized Event."""

    if event.event_type != SIMULATION_INITIALIZED:
        raise InitializationEventPayloadError(
            f"unknown initialization Event type: {event.event_type}"
        )
    if event.event_version != 1:
        raise InitializationEventPayloadError(
            f"unsupported SimulationInitialized version: {event.event_version}"
        )

    _fields(
        event.payload,
        frozenset({"world_definition_ref", "world_definition_schema_version"}),
        "payload",
    )
    ref = _mapping(event.payload["world_definition_ref"], "world_definition_ref")
    _fields(ref, frozenset({"world_definition_id", "version"}), "world_definition_ref")
    schema_version = event.payload["world_definition_schema_version"]
    if type(schema_version) is not int:
        raise InitializationEventPayloadError("world_definition_schema_version must be an integer")
    return SimulationInitializedPayload(
        world_definition_ref=WorldDefinitionRef(
            WorldDefinitionId(_token(ref["world_definition_id"], "world_definition_id")),
            _token(ref["version"], "version"),
        ),
        world_definition_schema_version=schema_version,
    )
