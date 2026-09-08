# SPDX-License-Identifier: GPL-3.0-only

"""Strict versioned payload decoding for Plan and Job Events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias, TypeGuard, TypeVar, cast

from grass.core._structured_data import StructuredValue
from grass.core.events import Event
from grass.core.execution import (
    ActionPrimitive,
    BinaryProgress,
    BlueprintRef,
    Job,
    JobProgress,
    JobStatus,
    LinearProgress,
    Plan,
    PlanDependency,
    PlanDependencyCondition,
    PlanRef,
    PlanStep,
    PlanStepOrigin,
    PlanStepRef,
    ProgressNumber,
    initial_progress,
)
from grass.core.identifiers import (
    BlueprintId,
    EntityId,
    JobId,
    PlanId,
    PlanStepId,
)

PLAN_CREATED = "PlanCreated"
PLAN_REVISED = "PlanRevised"
PLAN_REPLACED = "PlanReplaced"
JOB_CREATED = "JobCreated"
JOB_ACTIVATED = "JobActivated"
JOB_PAUSED = "JobPaused"
JOB_PROGRESS_UPDATED = "JobProgressUpdated"
JOB_COMPLETED = "JobCompleted"
JOB_FAILED = "JobFailed"
JOB_CANCELLED = "JobCancelled"

EXECUTION_EVENT_TYPES = frozenset(
    {
        PLAN_CREATED,
        PLAN_REVISED,
        PLAN_REPLACED,
        JOB_CREATED,
        JOB_ACTIVATED,
        JOB_PAUSED,
        JOB_PROGRESS_UPDATED,
        JOB_COMPLETED,
        JOB_FAILED,
        JOB_CANCELLED,
    }
)


class ExecutionEventPayloadError(ValueError):
    """A known execution Event has an invalid version or payload."""


@dataclass(frozen=True, slots=True)
class PlanCreatedPayload:
    plan: Plan


@dataclass(frozen=True, slots=True)
class PlanRevisedPayload:
    plan: Plan


@dataclass(frozen=True, slots=True)
class PlanReplacedPayload:
    plan: Plan


@dataclass(frozen=True, slots=True)
class JobCreatedPayload:
    job: Job


@dataclass(frozen=True, slots=True)
class JobActivatedPayload:
    job_id: JobId


@dataclass(frozen=True, slots=True)
class JobPausedPayload:
    job_id: JobId


@dataclass(frozen=True, slots=True)
class JobProgressUpdatedPayload:
    job_id: JobId
    progress_after: JobProgress


@dataclass(frozen=True, slots=True)
class JobCompletedPayload:
    job_id: JobId


@dataclass(frozen=True, slots=True)
class JobFailedPayload:
    job_id: JobId


@dataclass(frozen=True, slots=True)
class JobCancelledPayload:
    job_id: JobId


PlanEventPayload: TypeAlias = PlanCreatedPayload | PlanRevisedPayload | PlanReplacedPayload
JobLifecyclePayload: TypeAlias = (
    JobActivatedPayload
    | JobPausedPayload
    | JobCompletedPayload
    | JobFailedPayload
    | JobCancelledPayload
)
JobEventPayload: TypeAlias = JobCreatedPayload | JobProgressUpdatedPayload | JobLifecyclePayload
ExecutionEventPayload: TypeAlias = PlanEventPayload | JobEventPayload
EnumT = TypeVar("EnumT", ActionPrimitive, PlanDependencyCondition, PlanStepOrigin)


def is_execution_event_payload(value: object) -> TypeGuard[ExecutionEventPayload]:
    return isinstance(
        value,
        (
            PlanCreatedPayload,
            PlanRevisedPayload,
            PlanReplacedPayload,
            JobCreatedPayload,
            JobActivatedPayload,
            JobPausedPayload,
            JobProgressUpdatedPayload,
            JobCompletedPayload,
            JobFailedPayload,
            JobCancelledPayload,
        ),
    )


def _mapping(value: object, field_name: str) -> Mapping[str, StructuredValue]:
    if not isinstance(value, Mapping):
        raise ExecutionEventPayloadError(f"{field_name} must be a mapping")
    if not all(type(key) is str for key in value):
        raise ExecutionEventPayloadError(f"{field_name} keys must be strings")
    return cast("Mapping[str, StructuredValue]", value)


def _fields(
    value: Mapping[str, StructuredValue], expected: frozenset[str], field_name: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ExecutionEventPayloadError(
            f"{field_name} fields do not match schema; missing={missing}, extra={extra}"
        )


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or value == "":
        raise ExecutionEventPayloadError(f"{field_name} must be a non-empty string")
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ExecutionEventPayloadError(f"{field_name} must be a positive integer")
    return value


def _plan_ref(value: object, field_name: str) -> PlanRef:
    ref = _mapping(value, field_name)
    _fields(ref, frozenset({"plan_id", "version"}), field_name)
    return PlanRef(
        PlanId(_token(ref["plan_id"], "plan_id")),
        _positive_integer(ref["version"], "Plan version"),
    )


def _plan_step_ref(value: object) -> PlanStepRef:
    ref = _mapping(value, "plan_step_ref")
    _fields(ref, frozenset({"plan_ref", "step_id"}), "plan_step_ref")
    return PlanStepRef(
        _plan_ref(ref["plan_ref"], "plan_ref"),
        PlanStepId(_token(ref["step_id"], "step_id")),
    )


def _blueprint_ref(value: object) -> BlueprintRef | None:
    if value is None:
        return None
    ref = _mapping(value, "blueprint_ref")
    _fields(ref, frozenset({"blueprint_id", "version"}), "blueprint_ref")
    return BlueprintRef(
        BlueprintId(_token(ref["blueprint_id"], "blueprint_id")),
        _positive_integer(ref["version"], "Blueprint version"),
    )


def _enum_value(enum_type: type[EnumT], value: object, field_name: str) -> EnumT:
    token = _token(value, field_name)
    try:
        return enum_type(token)
    except ValueError as error:
        raise ExecutionEventPayloadError(f"unsupported {field_name}: {token}") from error


def _progress(value: object, field_name: str) -> JobProgress:
    progress = _mapping(value, field_name)
    kind = progress.get("kind")
    if kind == "LINEAR":
        _fields(progress, frozenset({"kind", "completed", "total"}), field_name)
        completed = progress["completed"]
        total = progress["total"]
        if type(completed) not in (int, float) or type(total) not in (int, float):
            raise ExecutionEventPayloadError(
                "LINEAR completed and total must be integers or finite floats"
            )
        return LinearProgress(
            cast("ProgressNumber", completed),
            cast("ProgressNumber", total),
        )
    if kind == "BINARY":
        _fields(progress, frozenset({"kind", "complete"}), field_name)
        return BinaryProgress(cast("bool", progress["complete"]))
    raise ExecutionEventPayloadError("progress.kind must be LINEAR or BINARY")


def _dependencies(value: object) -> frozenset[PlanDependency]:
    if type(value) is not tuple:
        raise ExecutionEventPayloadError("dependencies must be a sequence")
    dependencies: list[PlanDependency] = []
    for raw in value:
        dependency = _mapping(raw, "dependency")
        _fields(dependency, frozenset({"step_id", "condition"}), "dependency")
        dependencies.append(
            PlanDependency(
                PlanStepId(_token(dependency["step_id"], "step_id")),
                _enum_value(
                    PlanDependencyCondition,
                    dependency["condition"],
                    "dependency condition",
                ),
            )
        )
    frozen = frozenset(dependencies)
    if len(frozen) != len(dependencies):
        raise ExecutionEventPayloadError("dependencies must not contain duplicates")
    return frozen


def _steps(value: object) -> tuple[PlanStep, ...]:
    if type(value) is not tuple:
        raise ExecutionEventPayloadError("steps must be a sequence")
    steps: list[PlanStep] = []
    for raw in value:
        step = _mapping(raw, "PlanStep")
        _fields(
            step,
            frozenset(
                {
                    "step_id",
                    "primitive",
                    "blueprint_ref",
                    "bindings",
                    "parameters",
                    "dependencies",
                    "origin",
                    "description",
                }
            ),
            "PlanStep",
        )
        description = step["description"]
        if description is not None:
            description = _token(description, "description")
        steps.append(
            PlanStep(
                step_id=PlanStepId(_token(step["step_id"], "step_id")),
                primitive=_enum_value(ActionPrimitive, step["primitive"], "primitive"),
                blueprint_ref=_blueprint_ref(step["blueprint_ref"]),
                bindings=_mapping(step["bindings"], "bindings"),
                parameters=_mapping(step["parameters"], "parameters"),
                dependencies=_dependencies(step["dependencies"]),
                origin=_enum_value(PlanStepOrigin, step["origin"], "origin"),
                description=description,
            )
        )
    return tuple(steps)


def _plan(event: Event) -> Plan:
    snapshot = _mapping(event.payload["plan"], "plan")
    _fields(
        snapshot,
        frozenset({"plan_id", "version", "actor_id", "objective", "steps", "replaces_plan_ref"}),
        "plan",
    )
    replaced = snapshot["replaces_plan_ref"]
    return Plan(
        plan_id=PlanId(_token(snapshot["plan_id"], "plan_id")),
        version=_positive_integer(snapshot["version"], "Plan version"),
        actor_id=EntityId(_token(snapshot["actor_id"], "actor_id")),
        objective=_token(snapshot["objective"], "objective"),
        steps=_steps(snapshot["steps"]),
        replaces_plan_ref=(None if replaced is None else _plan_ref(replaced, "replaces_plan_ref")),
        provenance=event.provenance,
        recorded_at=event.logical_time,
    )


def _job_created(event: Event) -> JobCreatedPayload:
    payload = event.payload
    _fields(payload, frozenset({"job_id", "plan_step_ref", "progress"}), "payload")
    job = Job(
        job_id=JobId(_token(payload["job_id"], "job_id")),
        plan_step_ref=_plan_step_ref(payload["plan_step_ref"]),
        status=JobStatus.PENDING,
        progress=_progress(payload["progress"], "progress"),
        creation_provenance=event.provenance,
        created_at=event.logical_time,
    )
    if not initial_progress(job.progress):
        raise ExecutionEventPayloadError("JobCreated progress must be initial")
    return JobCreatedPayload(job)


def _job_id_payload(event: Event) -> JobId:
    _fields(event.payload, frozenset({"job_id"}), "payload")
    return JobId(_token(event.payload["job_id"], "job_id"))


def _decode_execution_event(event: Event) -> ExecutionEventPayload:
    if event.event_type not in EXECUTION_EVENT_TYPES:
        raise ExecutionEventPayloadError(f"unknown execution Event type: {event.event_type}")
    if event.event_version != 1:
        raise ExecutionEventPayloadError(
            f"unsupported {event.event_type} version: {event.event_version}"
        )

    if event.event_type in {PLAN_CREATED, PLAN_REVISED, PLAN_REPLACED}:
        _fields(event.payload, frozenset({"plan"}), "payload")
        plan = _plan(event)
        if event.event_type == PLAN_CREATED:
            return PlanCreatedPayload(plan)
        if event.event_type == PLAN_REVISED:
            return PlanRevisedPayload(plan)
        return PlanReplacedPayload(plan)
    if event.event_type == JOB_CREATED:
        return _job_created(event)
    if event.event_type == JOB_PROGRESS_UPDATED:
        _fields(event.payload, frozenset({"job_id", "progress_after"}), "payload")
        return JobProgressUpdatedPayload(
            JobId(_token(event.payload["job_id"], "job_id")),
            _progress(event.payload["progress_after"], "progress_after"),
        )

    job_id = _job_id_payload(event)
    if event.event_type == JOB_ACTIVATED:
        return JobActivatedPayload(job_id)
    if event.event_type == JOB_PAUSED:
        return JobPausedPayload(job_id)
    if event.event_type == JOB_COMPLETED:
        return JobCompletedPayload(job_id)
    if event.event_type == JOB_FAILED:
        return JobFailedPayload(job_id)
    if event.event_type == JOB_CANCELLED:
        return JobCancelledPayload(job_id)
    raise AssertionError("unhandled execution Event type")


def decode_execution_event(event: Event) -> ExecutionEventPayload:
    """Decode one known version-1 execution Event into a typed payload."""

    if type(event) is not Event:
        raise TypeError("event must be an Event")
    try:
        return _decode_execution_event(event)
    except ExecutionEventPayloadError:
        raise
    except (TypeError, ValueError) as error:
        raise ExecutionEventPayloadError(str(error)) from error
