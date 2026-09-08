# SPDX-License-Identifier: GPL-3.0-only

from typing import cast

import pytest

from grass.core import (
    ActionPrimitive,
    BinaryProgress,
    BlueprintId,
    BlueprintRef,
    Event,
    EventPayload,
    ExecutionEventPayloadError,
    JobActivatedPayload,
    JobCancelledPayload,
    JobCompletedPayload,
    JobCreatedPayload,
    JobFailedPayload,
    JobId,
    JobPausedPayload,
    JobProgressUpdatedPayload,
    LinearProgress,
    LogicalTime,
    PlanCreatedPayload,
    PlanDependencyCondition,
    PlanId,
    PlanReplacedPayload,
    PlanRevisedPayload,
    PlanStepOrigin,
    Provenance,
    decode_execution_event,
)
from grass.core._structured_data import StructuredValue
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_CREATED,
    JOB_FAILED,
    JOB_PAUSED,
    JOB_PROGRESS_UPDATED,
    PLAN_CREATED,
    PLAN_REPLACED,
    PLAN_REVISED,
)
from tests.support import event_to_commit, rooted_store, transition_to_commit


def committed_event(
    event_type: str,
    payload: EventPayload,
    *,
    version: int = 1,
) -> Event:
    store = rooted_store("root")
    transition = store.commit_transition(
        transition_to_commit(
            "root",
            "transition",
            8,
            [
                event_to_commit(
                    "event",
                    event_type=event_type,
                    event_version=version,
                    payload=payload,
                    provenance=Provenance("ACTOR"),
                )
            ],
        )
    )
    return transition.events[0]


def plan_snapshot(
    *,
    plan_id: str = "plan",
    version: int = 1,
    replaces: EventPayload | None = None,
    dependencies: list[EventPayload] | None = None,
) -> EventPayload:
    dependency_values: list[StructuredValue] = [] if dependencies is None else list(dependencies)
    step: dict[str, StructuredValue] = {
        "step_id": "step",
        "primitive": "MOVE",
        "blueprint_ref": {"blueprint_id": "move-blueprint", "version": 2},
        "bindings": {"target": "office"},
        "parameters": {},
        "dependencies": dependency_values,
        "origin": "PLANNER_DERIVED",
        "description": "Move to office",
    }
    return {
        "plan_id": plan_id,
        "version": version,
        "actor_id": "actor",
        "objective": "Reach the office",
        "steps": [step],
        "replaces_plan_ref": replaces,
    }


@pytest.mark.parametrize(
    "event_type,payload_type",
    [
        (PLAN_CREATED, PlanCreatedPayload),
        (PLAN_REVISED, PlanRevisedPayload),
        (PLAN_REPLACED, PlanReplacedPayload),
    ],
)
def test_decodes_complete_plan_snapshots(
    event_type: str,
    payload_type: type[PlanCreatedPayload] | type[PlanRevisedPayload] | type[PlanReplacedPayload],
) -> None:
    decoded = decode_execution_event(committed_event(event_type, {"plan": plan_snapshot()}))

    assert isinstance(decoded, payload_type)
    assert decoded.plan.plan_id == PlanId("plan")
    assert decoded.plan.steps[0].primitive is ActionPrimitive.MOVE
    assert decoded.plan.steps[0].origin is PlanStepOrigin.PLANNER_DERIVED
    assert decoded.plan.steps[0].blueprint_ref == BlueprintRef(BlueprintId("move-blueprint"), 2)
    assert decoded.plan.provenance == Provenance("ACTOR")
    assert decoded.plan.recorded_at == LogicalTime(8)


def test_decodes_explicit_dependency_condition() -> None:
    snapshot = cast(dict[str, StructuredValue], plan_snapshot())
    steps = cast(list[dict[str, StructuredValue]], snapshot["steps"])
    steps.append(
        {
            "step_id": "later",
            "primitive": "WAIT",
            "blueprint_ref": None,
            "bindings": {},
            "parameters": {},
            "dependencies": [],
            "origin": "ACTOR_INTENT",
            "description": None,
        }
    )
    steps[0]["dependencies"] = [{"step_id": "later", "condition": "TERMINAL"}]

    decoded = decode_execution_event(committed_event(PLAN_CREATED, {"plan": snapshot}))

    assert isinstance(decoded, PlanCreatedPayload)
    dependency = next(iter(decoded.plan.steps[0].dependencies))
    assert dependency.condition is PlanDependencyCondition.TERMINAL


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("missing", "fields do not match schema"),
        ("extra", "fields do not match schema"),
        ("primitive", "unsupported primitive"),
        ("origin", "unsupported origin"),
        ("empty-description", "description must be a non-empty string"),
    ],
)
def test_plan_payload_schema_is_strict(mutation: str, message: str) -> None:
    snapshot = cast(dict[str, StructuredValue], plan_snapshot())
    step = cast(list[dict[str, StructuredValue]], snapshot["steps"])[0]
    if mutation == "missing":
        del step["bindings"]
    elif mutation == "extra":
        step["future"] = True
    elif mutation == "primitive":
        step["primitive"] = "PERFORM"
    elif mutation == "origin":
        step["origin"] = "SYSTEM"
    else:
        step["description"] = ""

    with pytest.raises(ExecutionEventPayloadError, match=message):
        decode_execution_event(committed_event(PLAN_CREATED, {"plan": snapshot}))


def test_rejects_duplicate_dependencies_and_blueprint_primitive_field() -> None:
    duplicate = {"step_id": "other", "condition": "SUCCESS"}
    snapshot = cast(dict[str, StructuredValue], plan_snapshot())
    steps = cast(list[dict[str, StructuredValue]], snapshot["steps"])
    steps.append(
        {
            "step_id": "other",
            "primitive": "WAIT",
            "blueprint_ref": None,
            "bindings": {},
            "parameters": {},
            "dependencies": [],
            "origin": "ACTOR_INTENT",
            "description": None,
        }
    )
    steps[0]["dependencies"] = [duplicate, duplicate]
    with pytest.raises(ExecutionEventPayloadError, match="duplicates"):
        decode_execution_event(committed_event(PLAN_CREATED, {"plan": snapshot}))

    blueprint_snapshot = cast(dict[str, StructuredValue], plan_snapshot())
    blueprint_step = cast(list[dict[str, StructuredValue]], blueprint_snapshot["steps"])[0]
    blueprint = cast(dict[str, StructuredValue], blueprint_step["blueprint_ref"])
    blueprint["primitive"] = "MOVE"
    with pytest.raises(ExecutionEventPayloadError, match="fields do not match schema"):
        decode_execution_event(committed_event(PLAN_CREATED, {"plan": blueprint_snapshot}))


@pytest.mark.parametrize(
    "progress,expected",
    [
        (
            {"kind": "LINEAR", "completed": 0, "total": 4},
            LinearProgress(0, 4),
        ),
        ({"kind": "BINARY", "complete": False}, BinaryProgress(False)),
    ],
)
def test_decodes_job_created_with_initial_progress(
    progress: EventPayload, expected: LinearProgress | BinaryProgress
) -> None:
    decoded = decode_execution_event(
        committed_event(
            JOB_CREATED,
            {
                "job_id": "job",
                "plan_step_ref": {
                    "plan_ref": {"plan_id": "plan", "version": 1},
                    "step_id": "step",
                },
                "progress": progress,
            },
        )
    )

    assert isinstance(decoded, JobCreatedPayload)
    assert decoded.job.job_id == JobId("job")
    assert decoded.job.progress == expected
    assert decoded.job.created_at == LogicalTime(8)
    assert decoded.job.creation_provenance == Provenance("ACTOR")


@pytest.mark.parametrize(
    "progress",
    [
        {"kind": "LINEAR", "completed": 1, "total": 4},
        {"kind": "BINARY", "complete": True},
    ],
)
def test_job_created_requires_initial_progress(progress: EventPayload) -> None:
    with pytest.raises(ExecutionEventPayloadError, match="must be initial"):
        decode_execution_event(
            committed_event(
                JOB_CREATED,
                {
                    "job_id": "job",
                    "plan_step_ref": {
                        "plan_ref": {"plan_id": "plan", "version": 1},
                        "step_id": "step",
                    },
                    "progress": progress,
                },
            )
        )


def test_decodes_complete_progress_after() -> None:
    decoded = decode_execution_event(
        committed_event(
            JOB_PROGRESS_UPDATED,
            {
                "job_id": "job",
                "progress_after": {"kind": "BINARY", "complete": True},
            },
        )
    )

    assert decoded == JobProgressUpdatedPayload(JobId("job"), BinaryProgress(True))


@pytest.mark.parametrize(
    "event_type,payload_type",
    [
        (JOB_ACTIVATED, JobActivatedPayload),
        (JOB_PAUSED, JobPausedPayload),
        (JOB_COMPLETED, JobCompletedPayload),
        (JOB_FAILED, JobFailedPayload),
        (JOB_CANCELLED, JobCancelledPayload),
    ],
)
def test_decodes_minimal_job_lifecycle_payloads(
    event_type: str,
    payload_type: (
        type[JobActivatedPayload]
        | type[JobPausedPayload]
        | type[JobCompletedPayload]
        | type[JobFailedPayload]
        | type[JobCancelledPayload]
    ),
) -> None:
    decoded = decode_execution_event(committed_event(event_type, {"job_id": "job"}))

    assert isinstance(decoded, payload_type)
    assert decoded.job_id == JobId("job")


def test_rejects_extra_job_fields_and_unsupported_versions() -> None:
    with pytest.raises(ExecutionEventPayloadError, match="extra"):
        decode_execution_event(committed_event(JOB_FAILED, {"job_id": "job", "reason": "deferred"}))
    with pytest.raises(ExecutionEventPayloadError, match="unsupported"):
        decode_execution_event(committed_event(JOB_FAILED, {"job_id": "job"}, version=2))
