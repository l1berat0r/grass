# SPDX-License-Identifier: GPL-3.0-only

import pytest

from grass.core import (
    BinaryProgress,
    BranchId,
    CommittedTransition,
    Entity,
    EntityId,
    Event,
    EventId,
    ExecutionState,
    Job,
    JobId,
    JobStatus,
    LogicalTime,
    Plan,
    PlanId,
    PlanRef,
    PlanStep,
    PlanStepId,
    PlanStepOrigin,
    PlanStepRef,
    ProjectionError,
    ProjectionPosition,
    Provenance,
    ResolutionEventPayloadError,
    ResolutionOutcome,
    ResolutionOutcomeRecordedPayload,
    SimulationState,
    TransitionId,
    TransitionRef,
    WorldState,
    decode_resolution_event,
    project_transition,
)
from grass.core.execution import ActionPrimitive
from grass.core.resolution_events import RESOLUTION_OUTCOME_RECORDED


def resolution_event(
    payload: dict[str, object],
    *,
    sequence: int = 2,
    version: int = 1,
) -> Event:
    return Event(
        EventId(f"event-{sequence}"),
        BranchId("branch"),
        sequence,
        LogicalTime(2),
        TransitionId("resolution"),
        RESOLUTION_OUTCOME_RECORDED,
        version,
        payload,  # type: ignore[arg-type]
        Provenance("WORLD_RESOLVER"),
    )


def state_with_job() -> SimulationState:
    plan = Plan(
        PlanId("plan"),
        1,
        EntityId("actor"),
        "Wait",
        (
            PlanStep(
                PlanStepId("step"),
                ActionPrimitive.WAIT,
                None,
                {},
                {},
                frozenset(),
                PlanStepOrigin.ACTOR_INTENT,
            ),
        ),
        None,
        Provenance("ACTOR"),
        LogicalTime(0),
    )
    job = Job(
        JobId("job"),
        PlanStepRef(plan.ref, PlanStepId("step")),
        JobStatus.ACTIVE,
        BinaryProgress(False),
        Provenance("ACTOR"),
        LogicalTime(0),
    )
    return SimulationState(
        ProjectionPosition(
            BranchId("branch"),
            TransitionRef(BranchId("branch"), TransitionId("base")),
            1,
            LogicalTime(1),
        ),
        WorldState(entities={EntityId("actor"): Entity(EntityId("actor"), "Person", {})}),
        ExecutionState(plans={PlanRef(PlanId("plan"), 1): plan}, jobs={JobId("job"): job}),
    )


def test_resolution_outcome_event_decodes_strict_version_one_payload() -> None:
    payload = decode_resolution_event(resolution_event({"job_id": "job", "outcome": "BLOCKED"}))

    assert payload == ResolutionOutcomeRecordedPayload(JobId("job"), ResolutionOutcome.BLOCKED)


@pytest.mark.parametrize(
    "payload,version,message",
    [
        ({"job_id": "job"}, 1, "fields do not match"),
        ({"job_id": "job", "outcome": "BLOCKED", "extra": True}, 1, "fields do not match"),
        ({"job_id": "job", "outcome": "UNKNOWN"}, 1, "unsupported resolution outcome"),
        ({"job_id": "job", "outcome": "BLOCKED"}, 2, "unsupported"),
    ],
)
def test_resolution_outcome_event_rejects_invalid_payloads(
    payload: dict[str, object], version: int, message: str
) -> None:
    with pytest.raises(ResolutionEventPayloadError, match=message):
        decode_resolution_event(resolution_event(payload, version=version))


def test_projection_recognizes_outcome_without_mutating_world_or_execution() -> None:
    state = state_with_job()
    transition = CommittedTransition((resolution_event({"job_id": "job", "outcome": "PARTIAL"}),))

    projected = project_transition(state, transition)

    assert projected.world == state.world
    assert projected.execution == state.execution
    assert projected.position.last_transition_ref == transition.transition_ref


def test_projection_rejects_missing_job_and_duplicate_job_outcomes() -> None:
    state = state_with_job()
    missing = CommittedTransition((resolution_event({"job_id": "missing", "outcome": "FAILED"}),))
    duplicate = CommittedTransition(
        (
            resolution_event({"job_id": "job", "outcome": "PARTIAL"}),
            resolution_event({"job_id": "job", "outcome": "SUCCESS"}, sequence=3),
        )
    )

    with pytest.raises(ProjectionError, match="existing Job"):
        project_transition(state, missing)
    with pytest.raises(ProjectionError, match="duplicate Resolution outcome"):
        project_transition(state, duplicate)
