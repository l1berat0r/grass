# SPDX-License-Identifier: GPL-3.0-only

"""Atomic deterministic projection of Plan and Job Events."""

from __future__ import annotations

from dataclasses import dataclass

from grass.core.execution import (
    Job,
    JobProgress,
    JobStatus,
    Plan,
    PlanRef,
    progress_is_monotonic,
    terminal_progress,
)
from grass.core.execution_events import (
    JobActivatedPayload,
    JobCancelledPayload,
    JobCompletedPayload,
    JobCreatedPayload,
    JobEventPayload,
    JobFailedPayload,
    JobLifecyclePayload,
    JobPausedPayload,
    JobProgressUpdatedPayload,
    PlanCreatedPayload,
    PlanEventPayload,
    PlanReplacedPayload,
    PlanRevisedPayload,
)
from grass.core.identifiers import EntityId, JobId, PlanId
from grass.core.state import ExecutionState


class ExecutionProjectionError(ValueError):
    """Committed execution history violates the Slice 5 contracts."""


def _latest_plan(plans: dict[PlanRef, Plan], plan_id: PlanId) -> Plan | None:
    matches = tuple(plan for plan in plans.values() if plan.plan_id == plan_id)
    if not matches:
        return None
    return max(matches, key=lambda plan: plan.version)


def _is_replaced(plans: dict[PlanRef, Plan], plan_id: PlanId) -> bool:
    return any(
        plan.version == 1
        and plan.replaces_plan_ref is not None
        and plan.replaces_plan_ref.plan_id == plan_id
        for plan in plans.values()
    )


def _affected_plan_ids(payload: PlanEventPayload) -> frozenset[PlanId]:
    plan = payload.plan
    if type(payload) is not PlanReplacedPayload:
        return frozenset({plan.plan_id})
    if plan.replaces_plan_ref is None:
        raise ExecutionProjectionError("PlanReplaced requires replaces_plan_ref")
    return frozenset({plan.plan_id, plan.replaces_plan_ref.plan_id})


def _project_plans(
    current: ExecutionState, payloads: tuple[PlanEventPayload, ...]
) -> dict[PlanRef, Plan]:
    preexisting = dict(current.plans)
    plans = preexisting.copy()
    affected: set[PlanId] = set()

    for payload in payloads:
        operation_ids = _affected_plan_ids(payload)
        if affected.intersection(operation_ids):
            raise ExecutionProjectionError(
                "at most one Plan operation may affect a PlanId in one transition"
            )
        affected.update(operation_ids)

    for payload in payloads:
        plan = payload.plan
        if plan.ref in plans:
            raise ExecutionProjectionError("Plan version already exists")

        if type(payload) is PlanCreatedPayload:
            if plan.version != 1 or plan.replaces_plan_ref is not None:
                raise ExecutionProjectionError(
                    "PlanCreated requires version 1 and no replaces_plan_ref"
                )
            if _latest_plan(preexisting, plan.plan_id) is not None:
                raise ExecutionProjectionError("PlanCreated requires a new PlanId")
        elif type(payload) is PlanRevisedPayload:
            previous = _latest_plan(preexisting, plan.plan_id)
            if previous is None:
                raise ExecutionProjectionError("PlanRevised requires an existing Plan")
            if _is_replaced(preexisting, plan.plan_id):
                raise ExecutionProjectionError("a replaced Plan cannot be revised")
            if plan.version != previous.version + 1:
                raise ExecutionProjectionError("PlanRevised requires the exact next version")
            if plan.replaces_plan_ref != previous.replaces_plan_ref:
                raise ExecutionProjectionError("PlanRevised must preserve replaces_plan_ref")
        elif type(payload) is PlanReplacedPayload:
            replaced_ref = plan.replaces_plan_ref
            if plan.version != 1 or replaced_ref is None:
                raise ExecutionProjectionError(
                    "PlanReplaced requires new version 1 and replaces_plan_ref"
                )
            if _latest_plan(preexisting, plan.plan_id) is not None:
                raise ExecutionProjectionError("PlanReplaced requires a new PlanId")
            replaced = _latest_plan(preexisting, replaced_ref.plan_id)
            if replaced is None or replaced.ref != replaced_ref:
                raise ExecutionProjectionError(
                    "PlanReplaced must target the latest pre-transition Plan version"
                )
            if _is_replaced(preexisting, replaced.plan_id):
                raise ExecutionProjectionError("a replaced Plan cannot be replaced again")
        else:  # pragma: no cover - closed payload union
            raise AssertionError("unhandled Plan Event payload")

        plans[plan.ref] = plan

    return plans


@dataclass(slots=True)
class _JobChanges:
    created: Job | None = None
    lifecycle: JobLifecyclePayload | None = None
    progress_after: JobProgress | None = None


def _job_id(payload: JobEventPayload) -> JobId:
    if isinstance(payload, JobCreatedPayload):
        return payload.job.job_id
    return payload.job_id


def _collect_job_changes(
    payloads: tuple[JobEventPayload, ...],
) -> dict[JobId, _JobChanges]:
    changes: dict[JobId, _JobChanges] = {}
    for payload in payloads:
        job_changes = changes.setdefault(_job_id(payload), _JobChanges())
        if type(payload) is JobCreatedPayload:
            if job_changes.created is not None:
                raise ExecutionProjectionError(
                    "at most one JobCreated is allowed per Job in one transition"
                )
            job_changes.created = payload.job
        elif type(payload) is JobProgressUpdatedPayload:
            if job_changes.progress_after is not None:
                raise ExecutionProjectionError(
                    "at most one JobProgressUpdated is allowed per Job in one transition"
                )
            job_changes.progress_after = payload.progress_after
        else:
            if not isinstance(
                payload,
                (
                    JobActivatedPayload,
                    JobPausedPayload,
                    JobCompletedPayload,
                    JobFailedPayload,
                    JobCancelledPayload,
                ),
            ):
                raise AssertionError("unhandled Job Event payload")
            if job_changes.lifecycle is not None:
                raise ExecutionProjectionError(
                    "at most one lifecycle Event is allowed per Job in one transition"
                )
            job_changes.lifecycle = payload
    return changes


def _target_status(payload: JobLifecyclePayload) -> JobStatus:
    if type(payload) is JobActivatedPayload:
        return JobStatus.ACTIVE
    if type(payload) is JobPausedPayload:
        return JobStatus.PAUSED
    if type(payload) is JobCompletedPayload:
        return JobStatus.COMPLETED
    if type(payload) is JobFailedPayload:
        return JobStatus.FAILED
    if type(payload) is JobCancelledPayload:
        return JobStatus.CANCELLED
    raise AssertionError("unhandled Job lifecycle payload")


_LEGAL_STATUS_TARGETS = {
    JobStatus.PENDING: frozenset(
        {JobStatus.ACTIVE, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.ACTIVE: frozenset(
        {JobStatus.PAUSED, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.PAUSED: frozenset({JobStatus.ACTIVE, JobStatus.FAILED, JobStatus.CANCELLED}),
}


def _progress_update_is_eligible(
    previous_status: JobStatus,
    final_status: JobStatus,
    lifecycle: JobLifecyclePayload | None,
) -> bool:
    if previous_status is JobStatus.ACTIVE:
        return True
    if final_status is JobStatus.ACTIVE and previous_status in (
        JobStatus.PENDING,
        JobStatus.PAUSED,
    ):
        return True
    return (
        previous_status is JobStatus.PENDING
        and final_status is JobStatus.COMPLETED
        and lifecycle is not None
    )


def _project_one_job(current_jobs: dict[JobId, Job], job_id: JobId, changes: _JobChanges) -> Job:
    existing = current_jobs.get(job_id)
    if changes.created is not None:
        if existing is not None:
            raise ExecutionProjectionError("Job already exists")
        previous = changes.created
    else:
        if existing is None:
            raise ExecutionProjectionError("Job does not exist")
        previous = existing

    if previous.status.terminal and (
        changes.lifecycle is not None or changes.progress_after is not None
    ):
        raise ExecutionProjectionError("terminal Job cannot change")

    final_status = previous.status
    if changes.lifecycle is not None:
        final_status = _target_status(changes.lifecycle)
        if final_status not in _LEGAL_STATUS_TARGETS.get(previous.status, frozenset()):
            raise ExecutionProjectionError(
                f"invalid Job status transition: {previous.status} -> {final_status}"
            )

    final_progress = previous.progress
    if changes.progress_after is not None:
        final_progress = changes.progress_after
        if not progress_is_monotonic(previous.progress, final_progress):
            raise ExecutionProjectionError(
                "Job progress must preserve its model and advance monotonically"
            )
        if not _progress_update_is_eligible(previous.status, final_status, changes.lifecycle):
            raise ExecutionProjectionError(
                "Job progress requires active work or atomic PENDING completion"
            )

    if final_status is JobStatus.COMPLETED and not terminal_progress(final_progress):
        raise ExecutionProjectionError("JobCompleted requires terminal progress")

    return Job(
        job_id=previous.job_id,
        plan_step_ref=previous.plan_step_ref,
        status=final_status,
        progress=final_progress,
        creation_provenance=previous.creation_provenance,
        created_at=previous.created_at,
    )


def project_execution_state(
    current: ExecutionState,
    payloads: tuple[PlanEventPayload | JobEventPayload, ...],
    final_entity_ids: frozenset[EntityId],
) -> ExecutionState:
    """Apply all execution Events as one atomic candidate."""

    if type(current) is not ExecutionState:
        raise TypeError("current must be an ExecutionState")
    plan_payload_list: list[PlanEventPayload] = []
    job_payload_list: list[JobEventPayload] = []
    for payload in payloads:
        if isinstance(payload, (PlanCreatedPayload, PlanRevisedPayload, PlanReplacedPayload)):
            plan_payload_list.append(payload)
        else:
            job_payload_list.append(payload)
    plan_payloads = tuple(plan_payload_list)
    job_payloads = tuple(job_payload_list)

    plans = _project_plans(current, plan_payloads)
    if any(plan.actor_id not in final_entity_ids for plan in plans.values()):
        raise ExecutionProjectionError("Plan actors must reference existing Entities")

    jobs = dict(current.jobs)
    for job_id, changes in _collect_job_changes(job_payloads).items():
        jobs[job_id] = _project_one_job(dict(current.jobs), job_id, changes)

    try:
        return ExecutionState(plans=plans, jobs=jobs)
    except (TypeError, ValueError) as error:
        raise ExecutionProjectionError(str(error)) from error
