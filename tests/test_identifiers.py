# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import (
    BlueprintId,
    BranchId,
    CorrelationId,
    DecisionPointId,
    EntityId,
    EventId,
    JobId,
    ObservationId,
    PlanId,
    PlanStepId,
    RelationId,
    TransitionId,
    WorldDefinitionId,
)
from tests.support import stable_id


def test_identifier_preserves_opaque_value() -> None:
    identifier = EventId("opaque value/with:no-assumed-format")

    assert identifier.value == "opaque value/with:no-assumed-format"
    assert str(identifier) == identifier.value


def test_identifier_types_are_nominally_distinct() -> None:
    assert cast(object, EventId("same")) != BranchId("same")
    assert cast(object, BranchId("same")) != EntityId("same")
    assert cast(object, EntityId("same")) != RelationId("same")
    assert cast(object, RelationId("same")) != TransitionId("same")
    assert cast(object, TransitionId("same")) != CorrelationId("same")
    assert cast(object, CorrelationId("same")) != WorldDefinitionId("same")
    assert cast(object, WorldDefinitionId("same")) != PlanId("same")
    assert cast(object, PlanId("same")) != PlanStepId("same")
    assert cast(object, PlanStepId("same")) != JobId("same")
    assert cast(object, JobId("same")) != BlueprintId("same")
    assert cast(object, BlueprintId("same")) != ObservationId("same")
    assert cast(object, ObservationId("same")) != DecisionPointId("same")


@pytest.mark.parametrize(
    "identifier_type",
    [
        EventId,
        BranchId,
        EntityId,
        RelationId,
        TransitionId,
        CorrelationId,
        WorldDefinitionId,
        PlanId,
        PlanStepId,
        JobId,
        BlueprintId,
        ObservationId,
        DecisionPointId,
    ],
)
def test_identifier_rejects_empty_value(
    identifier_type: (
        type[EventId]
        | type[BranchId]
        | type[EntityId]
        | type[RelationId]
        | type[TransitionId]
        | type[CorrelationId]
        | type[WorldDefinitionId]
        | type[PlanId]
        | type[PlanStepId]
        | type[JobId]
        | type[BlueprintId]
        | type[ObservationId]
        | type[DecisionPointId]
    ),
) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        identifier_type("")


def test_identifier_rejects_non_string_value() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        EventId(cast(str, 7))


def test_identifier_rejects_string_subclasses_without_normalizing() -> None:
    class StringSubclass(str):
        pass

    with pytest.raises(TypeError, match="must be a string"):
        EventId(StringSubclass("event"))


def test_identifier_is_immutable_hashable_and_unordered() -> None:
    identifier = BranchId("branch")

    assert {identifier: "value"}[BranchId("branch")] == "value"
    with pytest.raises(FrozenInstanceError):
        identifier.value = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        _ = identifier < BranchId("other")  # type: ignore[operator]


def test_test_identifier_helper_is_stable_and_typed() -> None:
    assert stable_id(EventId, "event") == EventId("test:event")
    assert stable_id(BranchId, "branch") == BranchId("test:branch")
