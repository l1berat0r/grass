# SPDX-License-Identifier: GPL-3.0-only

"""Ephemeral runtime derivation of dependency-ready unstarted PlanSteps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol

from grass.core.execution import (
    BinaryProgress,
    JobProgress,
    JobStatus,
    LinearProgress,
    Plan,
    PlanDependencyCondition,
    PlanRef,
    PlanStepRef,
    initial_progress,
)
from grass.core.identifiers import EntityId, PlanId, PlanStepId
from grass.core.state import SimulationState


class UnsupportedRuntimeStateError(RuntimeError):
    """Authoritative state is valid but unsupported by the current runtime."""


@dataclass(frozen=True, slots=True)
class ReadyPlanStep:
    """One exact unstarted PlanStep whose dependencies permit a Job start."""

    actor_id: EntityId
    plan_step_ref: PlanStepRef

    def __post_init__(self) -> None:
        if type(self.actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        if type(self.plan_step_ref) is not PlanStepRef:
            raise TypeError("plan_step_ref must be a PlanStepRef")

    @property
    def plan_ref(self) -> PlanRef:
        return self.plan_step_ref.plan_ref

    @property
    def plan_id(self) -> PlanId:
        return self.plan_ref.plan_id

    @property
    def version(self) -> int:
        return self.plan_ref.version

    @property
    def step_id(self) -> PlanStepId:
        return self.plan_step_ref.step_id


@dataclass(frozen=True, slots=True)
class JobStartProposal:
    """Mechanic-selected initial lifecycle for one ready step."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    initial_progress: JobProgress
    activate: bool = False

    def __post_init__(self) -> None:
        if type(self.initial_progress) not in (LinearProgress, BinaryProgress):
            raise TypeError("initial_progress must be LinearProgress or BinaryProgress")
        if not initial_progress(self.initial_progress):
            raise ValueError("initial_progress must be initial")
        if type(self.activate) is not bool:
            raise TypeError("activate must be a boolean")


class JobStartPolicy(Protocol):
    """Select trusted Job-start details for one already-derived ready step."""

    def propose(
        self, ready_step: ReadyPlanStep, state: SimulationState, /
    ) -> JobStartProposal | None:
        """Return initial Job details, or decline this currently ready step."""

        ...


def _latest_plans(state: SimulationState) -> dict[PlanId, Plan]:
    latest: dict[PlanId, Plan] = {}
    for plan in state.execution.plans.values():
        previous = latest.get(plan.plan_id)
        if previous is None or plan.version > previous.version:
            latest[plan.plan_id] = plan
    return latest


def _blocked_plan_ids(
    plan: Plan,
    subject_plan_ref: PlanRef | None,
    parents: dict[PlanId, PlanId],
) -> bool:
    if subject_plan_ref is None:
        return True
    current = plan.plan_id
    while True:
        if current == subject_plan_ref.plan_id:
            return True
        parent = parents.get(current)
        if parent is None:
            return False
        current = parent


def derive_ready_plan_steps(state: SimulationState, /) -> tuple[ReadyPlanStep, ...]:
    """Derive canonical ready starts from current authoritative state."""

    if type(state) is not SimulationState:
        raise TypeError("state must be a SimulationState")

    pending_by_actor: dict[EntityId, list[PlanRef | None]] = {}
    for point_id, point in state.cognition.decision_points.items():
        if point_id not in state.cognition.decisions:
            pending_by_actor.setdefault(point.actor_id, []).append(point.subject_plan_ref)
    for actor_id, subjects in sorted(pending_by_actor.items(), key=lambda item: item[0].value):
        if len(subjects) > 1:
            raise UnsupportedRuntimeStateError(
                f"actor {actor_id.value} has more than one pending DecisionPoint"
            )

    latest = _latest_plans(state)
    replaced_plan_ids = {
        plan.replaces_plan_ref.plan_id
        for plan in latest.values()
        if plan.replaces_plan_ref is not None
    }
    parents = {
        plan.plan_id: plan.replaces_plan_ref.plan_id
        for plan in latest.values()
        if plan.replaces_plan_ref is not None
    }
    jobs_by_step = {job.plan_step_ref.step_id: job for job in state.execution.jobs.values()}

    ready: list[ReadyPlanStep] = []
    for plan in latest.values():
        if plan.plan_id in replaced_plan_ids:
            continue
        pending_subjects = pending_by_actor.get(plan.actor_id)
        if pending_subjects and _blocked_plan_ids(plan, pending_subjects[0], parents):
            continue
        for step in plan.steps:
            if step.step_id in jobs_by_step:
                continue
            dependencies_satisfied = True
            for dependency in step.dependencies:
                job = jobs_by_step.get(dependency.step_id)
                if job is None:
                    dependencies_satisfied = False
                    break
                if (
                    dependency.condition is PlanDependencyCondition.SUCCESS
                    and job.status is not JobStatus.COMPLETED
                ):
                    dependencies_satisfied = False
                    break
                if (
                    dependency.condition is PlanDependencyCondition.TERMINAL
                    and not job.status.terminal
                ):
                    dependencies_satisfied = False
                    break
            if dependencies_satisfied:
                ready.append(ReadyPlanStep(plan.actor_id, PlanStepRef(plan.ref, step.step_id)))

    return tuple(
        sorted(
            ready,
            key=lambda item: (
                item.actor_id.value,
                item.plan_id.value,
                item.version,
                item.step_id.value,
            ),
        )
    )
