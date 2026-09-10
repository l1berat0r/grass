# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic values shared by core tests."""

from collections.abc import Sequence
from typing import TypeVar

from grass.core import (
    BlueprintId,
    BranchId,
    CauseRef,
    CorrelationId,
    DecisionPointId,
    EntityId,
    EventId,
    EventPayload,
    EventToCommit,
    InMemoryEventStore,
    JobId,
    LogicalTime,
    ObservationId,
    PlanId,
    PlanStepId,
    Provenance,
    RelationId,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    WorldDefinitionId,
)

IdentifierT = TypeVar(
    "IdentifierT",
    EventId,
    BranchId,
    TransitionId,
    CorrelationId,
    EntityId,
    RelationId,
    WorldDefinitionId,
    PlanId,
    PlanStepId,
    JobId,
    BlueprintId,
    ObservationId,
    DecisionPointId,
)


def stable_id(identifier_type: type[IdentifierT], label: str) -> IdentifierT:
    """Construct a stable typed identifier without production ID generation."""

    return identifier_type(f"test:{label}")


FIXED_LOGICAL_TIME = LogicalTime(12_345_678_901)


def rooted_store(*branches: str) -> InMemoryEventStore:
    """Create a store with deterministic explicitly registered roots."""

    store = InMemoryEventStore()
    for branch in branches:
        store.create_root_branch(stable_id(BranchId, branch))
    return store


def event_to_commit(
    label: str,
    *,
    event_type: str = "TestFactRecorded",
    event_version: int = 1,
    payload: EventPayload | None = None,
    provenance: Provenance | None = None,
    causation_refs: Sequence[CauseRef] = (),
    correlation_id: CorrelationId | None = None,
) -> EventToCommit:
    """Build deterministic engine-authorized input for EventStore tests."""

    return EventToCommit(
        event_id=stable_id(EventId, label),
        event_type=event_type,
        event_version=event_version,
        payload={} if payload is None else payload,
        provenance=Provenance("ENGINE") if provenance is None else provenance,
        causation_refs=causation_refs,
        correlation_id=correlation_id,
    )


def transition_to_commit(
    branch: str,
    transition: str,
    logical_time: int,
    events: Sequence[EventToCommit],
) -> TransitionToCommit:
    """Build a deterministic transition without production ID generation."""

    return TransitionToCommit(
        transition_ref=TransitionRef(
            stable_id(BranchId, branch),
            stable_id(TransitionId, transition),
        ),
        logical_time=LogicalTime(logical_time),
        events=events,
    )
