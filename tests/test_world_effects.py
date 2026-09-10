# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import (
    BinaryProgress,
    ChangeResourceEffect,
    CreateEntityEffect,
    CreateRelationEffect,
    DeactivateEntityEffect,
    DeactivateRelationEffect,
    EntityId,
    EntityScope,
    JobId,
    JobStatus,
    LinearProgress,
    RelationId,
    RelationParticipant,
    SetStateVariableEffect,
    UpdateEntityEffect,
    UpdateJobEffect,
    UpdateRelationEffect,
    WorldScope,
)
from grass.core._structured_data import StructuredValue


def test_effects_are_immutable_and_freeze_structured_values() -> None:
    nested: list[StructuredValue] = [1]
    effect = CreateEntityEffect(EntityId("entity"), "Person", {"nested": nested})

    nested.append(2)

    assert effect.properties == {"nested": (1,)}
    with pytest.raises(TypeError):
        cast(dict[str, StructuredValue], effect.properties)["other"] = True
    with pytest.raises(FrozenInstanceError):
        effect.entity_type = "Artifact"  # type: ignore[misc]


def test_closed_world_effect_variants_construct_with_resulting_state_values() -> None:
    participant = RelationParticipant("member", EntityId("entity"))

    effects = (
        CreateEntityEffect(EntityId("created"), "Person", {}),
        UpdateEntityEffect(EntityId("entity"), {"name": "after"}),
        DeactivateEntityEffect(EntityId("entity")),
        CreateRelationEffect(RelationId("created"), "member_of", frozenset({participant}), {}),
        UpdateRelationEffect(RelationId("relation"), frozenset({participant}), {"after": True}),
        DeactivateRelationEffect(RelationId("relation")),
        ChangeResourceEffect(EntityId("entity"), "capacity", -1),
        SetStateVariableEffect(WorldScope(), "weather", {"value": "clear"}),
        SetStateVariableEffect(EntityScope(EntityId("entity")), "stress", 2),
        UpdateJobEffect(JobId("job"), progress_after=LinearProgress(2, 10)),
    )

    assert effects[6].quantity_after == -1
    assert effects[9].progress_after == LinearProgress(2, 10)


def test_change_resource_requires_exact_finite_numeric_result() -> None:
    with pytest.raises(TypeError, match="integer or finite float"):
        ChangeResourceEffect(EntityId("entity"), "capacity", cast(int, True))
    with pytest.raises(TypeError, match="integer or finite float"):
        ChangeResourceEffect(EntityId("entity"), "capacity", float("inf"))


def test_update_job_requires_a_non_pending_resulting_field() -> None:
    with pytest.raises(ValueError, match="requires status_after or progress_after"):
        UpdateJobEffect(JobId("job"))
    with pytest.raises(ValueError, match="PENDING"):
        UpdateJobEffect(JobId("job"), status_after=JobStatus.PENDING)

    combined = UpdateJobEffect(
        JobId("job"),
        status_after=JobStatus.COMPLETED,
        progress_after=BinaryProgress(True),
    )
    assert combined.status_after is JobStatus.COMPLETED
    assert combined.progress_after == BinaryProgress(True)
