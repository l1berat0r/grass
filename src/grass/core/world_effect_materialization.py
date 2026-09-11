# SPDX-License-Identifier: GPL-3.0-only

"""Shared validation and semantic Event encoding for closed WorldEffects."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias

from grass.core._structured_data import StructuredValue
from grass.core.execution import BinaryProgress, JobProgress, JobStatus, LinearProgress
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_PAUSED,
    JOB_PROGRESS_UPDATED,
)
from grass.core.state import EntityScope, RelationParticipant, WorldScope
from grass.core.world_definitions import WorldDefinition
from grass.core.world_effects import (
    WORLD_EFFECT_TYPES,
    ChangeResourceEffect,
    CreateEntityEffect,
    CreateRelationEffect,
    DeactivateEntityEffect,
    DeactivateRelationEffect,
    SetStateVariableEffect,
    UpdateEntityEffect,
    UpdateJobEffect,
    UpdateRelationEffect,
    WorldEffect,
)
from grass.core.world_events import (
    ENTITY_CREATED,
    ENTITY_DEACTIVATED,
    ENTITY_UPDATED,
    RELATION_CREATED,
    RELATION_DEACTIVATED,
    RELATION_UPDATED,
    RESOURCE_CHANGED,
    STATE_VARIABLE_CHANGED,
)

WorldEffectEventSpec: TypeAlias = tuple[str, Mapping[str, StructuredValue]]


class WorldEffectMaterializationError(ValueError):
    """A WorldEffect batch cannot be materialized under current contracts."""


def validate_world_effects(effects: Sequence[WorldEffect], /) -> tuple[WorldEffect, ...]:
    if not isinstance(effects, Sequence):
        raise TypeError("effects must be a sequence")
    frozen = tuple(effects)
    if not all(type(effect) in WORLD_EFFECT_TYPES for effect in frozen):
        raise TypeError("effects must contain only supported WorldEffect values")
    updated_jobs = tuple(effect.job_id for effect in frozen if type(effect) is UpdateJobEffect)
    if len(set(updated_jobs)) != len(updated_jobs):
        raise ValueError("a proposal may contain at most one UpdateJobEffect per Job")
    return frozen


def validate_world_effect_vocabulary(
    effects: Sequence[WorldEffect], world_definition: WorldDefinition, /
) -> None:
    if type(world_definition) is not WorldDefinition:
        raise TypeError("world_definition must be a WorldDefinition")
    vocabulary = world_definition.vocabulary
    for effect in effects:
        if type(effect) is CreateEntityEffect and effect.entity_type not in vocabulary.entity_types:
            raise WorldEffectMaterializationError(
                f"CreateEntityEffect uses undeclared entity_type: {effect.entity_type}"
            )
        if (
            type(effect) is CreateRelationEffect
            and effect.relation_type not in vocabulary.relation_types
        ):
            raise WorldEffectMaterializationError(
                f"CreateRelationEffect uses undeclared relation_type: {effect.relation_type}"
            )
        if (
            type(effect) is ChangeResourceEffect
            and effect.resource_type not in vocabulary.resource_types
        ):
            raise WorldEffectMaterializationError(
                f"ChangeResourceEffect uses undeclared resource_type: {effect.resource_type}"
            )
        if (
            type(effect) is SetStateVariableEffect
            and effect.state_variable_type not in vocabulary.state_variable_types
        ):
            raise WorldEffectMaterializationError(
                "SetStateVariableEffect uses undeclared state_variable_type: "
                f"{effect.state_variable_type}"
            )


def _scope_payload(scope: WorldScope | EntityScope) -> Mapping[str, StructuredValue]:
    if type(scope) is WorldScope:
        return {"kind": "WORLD"}
    if type(scope) is EntityScope:
        return {"kind": "ENTITY", "entity_id": scope.entity_id.value}
    raise AssertionError("unsupported StateVariable scope")


def _participants_payload(
    participants: frozenset[RelationParticipant],
) -> list[StructuredValue]:
    return [
        {"role": participant.role, "entity_id": participant.entity_id.value}
        for participant in sorted(
            participants,
            key=lambda participant: (participant.role, participant.entity_id.value),
        )
    ]


def _progress_payload(progress: JobProgress) -> Mapping[str, StructuredValue]:
    if type(progress) is LinearProgress:
        return {
            "kind": "LINEAR",
            "completed": progress.completed,
            "total": progress.total,
        }
    if type(progress) is BinaryProgress:
        return {"kind": "BINARY", "complete": progress.complete}
    raise AssertionError("unsupported Job progress")


_JOB_STATUS_EVENTS = {
    JobStatus.ACTIVE: JOB_ACTIVATED,
    JobStatus.PAUSED: JOB_PAUSED,
    JobStatus.COMPLETED: JOB_COMPLETED,
    JobStatus.FAILED: JOB_FAILED,
    JobStatus.CANCELLED: JOB_CANCELLED,
}


def world_effect_event_specs(effect: WorldEffect, /) -> tuple[WorldEffectEventSpec, ...]:
    """Encode one validated WorldEffect as existing semantic Event records."""

    if type(effect) is CreateEntityEffect:
        return (
            (
                ENTITY_CREATED,
                {
                    "entity_id": effect.entity_id.value,
                    "entity_type": effect.entity_type,
                    "properties": effect.properties,
                },
            ),
        )
    if type(effect) is UpdateEntityEffect:
        return (
            (
                ENTITY_UPDATED,
                {
                    "entity_id": effect.entity_id.value,
                    "properties_after": effect.properties_after,
                },
            ),
        )
    if type(effect) is DeactivateEntityEffect:
        return ((ENTITY_DEACTIVATED, {"entity_id": effect.entity_id.value}),)
    if type(effect) is CreateRelationEffect:
        return (
            (
                RELATION_CREATED,
                {
                    "relation_id": effect.relation_id.value,
                    "relation_type": effect.relation_type,
                    "participants": _participants_payload(effect.participants),
                    "properties": effect.properties,
                },
            ),
        )
    if type(effect) is UpdateRelationEffect:
        return (
            (
                RELATION_UPDATED,
                {
                    "relation_id": effect.relation_id.value,
                    "participants_after": _participants_payload(effect.participants_after),
                    "properties_after": effect.properties_after,
                },
            ),
        )
    if type(effect) is DeactivateRelationEffect:
        return ((RELATION_DEACTIVATED, {"relation_id": effect.relation_id.value}),)
    if type(effect) is ChangeResourceEffect:
        return (
            (
                RESOURCE_CHANGED,
                {
                    "entity_id": effect.entity_id.value,
                    "resource_type": effect.resource_type,
                    "quantity_after": effect.quantity_after,
                },
            ),
        )
    if type(effect) is SetStateVariableEffect:
        return (
            (
                STATE_VARIABLE_CHANGED,
                {
                    "scope": _scope_payload(effect.scope),
                    "state_variable_type": effect.state_variable_type,
                    "value_after": effect.value_after,
                },
            ),
        )
    if type(effect) is UpdateJobEffect:
        records: list[WorldEffectEventSpec] = []
        if effect.progress_after is not None:
            records.append(
                (
                    JOB_PROGRESS_UPDATED,
                    {
                        "job_id": effect.job_id.value,
                        "progress_after": _progress_payload(effect.progress_after),
                    },
                )
            )
        if effect.status_after is not None:
            records.append(
                (
                    _JOB_STATUS_EVENTS[effect.status_after],
                    {"job_id": effect.job_id.value},
                )
            )
        return tuple(records)
    raise AssertionError("unsupported WorldEffect")


def world_effects_event_specs(
    effects: Sequence[WorldEffect], /
) -> tuple[WorldEffectEventSpec, ...]:
    records: list[WorldEffectEventSpec] = []
    for effect in effects:
        records.extend(world_effect_event_specs(effect))
    return tuple(records)
