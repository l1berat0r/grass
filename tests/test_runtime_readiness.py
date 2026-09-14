# SPDX-License-Identifier: GPL-3.0-only

from grass.core.cognition import (
    DecisionPoint,
    DecisionPointReason,
    DecisionPointScope,
)
from grass.core.execution import (
    ActionPrimitive,
    BinaryProgress,
    Job,
    JobStatus,
    Plan,
    PlanDependency,
    PlanDependencyCondition,
    PlanRef,
    PlanStep,
    PlanStepOrigin,
    PlanStepRef,
)
from grass.core.identifiers import (
    BranchId,
    DecisionPointId,
    EntityId,
    JobId,
    PlanId,
    PlanStepId,
)
from grass.core.logical_time import LogicalTime
from grass.core.provenance import Provenance
from grass.core.state import (
    CognitionState,
    Entity,
    ExecutionState,
    ProjectionPosition,
    SimulationState,
    WorldState,
)
from grass.runtime.readiness import (
    JobStartProposal,
    ReadyPlanStep,
    UnsupportedRuntimeStateError,
    derive_ready_plan_steps,
)


def _step(
    step_id: str,
    *dependencies: tuple[str, PlanDependencyCondition],
) -> PlanStep:
    return PlanStep(
        PlanStepId(step_id),
        ActionPrimitive.WAIT,
        None,
        {},
        {},
        frozenset(
            PlanDependency(PlanStepId(target), condition) for target, condition in dependencies
        ),
        PlanStepOrigin.ACTOR_INTENT,
    )


def _plan(
    plan_id: str,
    actor_id: str,
    *steps: PlanStep,
    version: int = 1,
    replaces: PlanRef | None = None,
) -> Plan:
    return Plan(
        PlanId(plan_id),
        version,
        EntityId(actor_id),
        "Objective",
        steps,
        replaces,
        Provenance("ACTOR"),
        LogicalTime(version),
    )


def _job(
    job_id: str,
    plan: Plan,
    step_id: str,
    status: JobStatus,
) -> Job:
    complete = status is JobStatus.COMPLETED
    return Job(
        JobId(job_id),
        PlanStepRef(plan.ref, PlanStepId(step_id)),
        status,
        BinaryProgress(complete),
        Provenance("ENGINE"),
        LogicalTime(2),
    )


def _point(
    point_id: str,
    actor_id: str,
    subject: PlanRef | None,
) -> DecisionPoint:
    return DecisionPoint(
        DecisionPointId(point_id),
        EntityId(actor_id),
        DecisionPointReason.PLAN_BLOCKED,
        DecisionPointScope.FULL,
        frozenset(),
        subject,
    )


def _state(
    plans: tuple[Plan, ...],
    *,
    jobs: tuple[Job, ...] = (),
    points: tuple[DecisionPoint, ...] = (),
) -> SimulationState:
    actors = {plan.actor_id for plan in plans}.union(point.actor_id for point in points)
    return SimulationState(
        position=ProjectionPosition(BranchId("branch")),
        world=WorldState(entities={actor: Entity(actor, "Person", {}) for actor in actors}),
        execution=ExecutionState(
            plans={plan.ref: plan for plan in plans},
            jobs={job.job_id: job for job in jobs},
        ),
        cognition=CognitionState(
            decision_points={point.decision_point_id: point for point in points}
        ),
    )


def _refs(ready: tuple[ReadyPlanStep, ...]) -> tuple[tuple[str, str, int, str], ...]:
    return tuple(
        (
            item.actor_id.value,
            item.plan_id.value,
            item.version,
            item.step_id.value,
        )
        for item in ready
    )


def test_derives_all_unreplaced_latest_plans_in_canonical_order() -> None:
    alpha_v1 = _plan("z-plan", "b-actor", _step("old"))
    alpha_v2 = _plan("z-plan", "b-actor", _step("z-step"), version=2)
    beta = _plan("a-plan", "a-actor", _step("b-step"), _step("a-step"))

    ready = derive_ready_plan_steps(_state((alpha_v1, beta, alpha_v2)))

    assert _refs(ready) == (
        ("a-actor", "a-plan", 1, "a-step"),
        ("a-actor", "a-plan", 1, "b-step"),
        ("b-actor", "z-plan", 2, "z-step"),
    )


def test_replaced_plan_is_ignored_and_latest_replacement_version_is_used() -> None:
    old = _plan("old", "actor", _step("old-step"))
    replacement_v1 = _plan(
        "new",
        "actor",
        _step("new-v1-step"),
        replaces=old.ref,
    )
    replacement_v2 = _plan(
        "new",
        "actor",
        _step("new-v2-step"),
        version=2,
        replaces=old.ref,
    )

    assert _refs(derive_ready_plan_steps(_state((old, replacement_v1, replacement_v2)))) == (
        ("actor", "new", 2, "new-v2-step"),
    )


def test_existing_job_by_logical_step_means_started_across_revisions() -> None:
    first = _plan("plan", "actor", _step("same"), _step("removed"))
    second = _plan("plan", "actor", _step("same"), _step("new"), version=2)
    existing = _job("job", first, "same", JobStatus.ACTIVE)

    assert _refs(derive_ready_plan_steps(_state((first, second), jobs=(existing,)))) == (
        ("actor", "plan", 2, "new"),
    )


def test_success_dependency_requires_completed_job() -> None:
    first = _step("first")
    dependent = _step("dependent", ("first", PlanDependencyCondition.SUCCESS))
    plan = _plan("plan", "actor", first, dependent)

    for status in (
        JobStatus.PENDING,
        JobStatus.ACTIVE,
        JobStatus.PAUSED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    ):
        existing = _job("job", plan, "first", status)
        assert derive_ready_plan_steps(_state((plan,), jobs=(existing,))) == ()

    completed = _job("job", plan, "first", JobStatus.COMPLETED)
    assert _refs(derive_ready_plan_steps(_state((plan,), jobs=(completed,)))) == (
        ("actor", "plan", 1, "dependent"),
    )


def test_terminal_dependency_accepts_every_terminal_status_but_not_missing_or_active() -> None:
    first = _step("first")
    dependent = _step("dependent", ("first", PlanDependencyCondition.TERMINAL))
    plan = _plan("plan", "actor", first, dependent)

    assert _refs(derive_ready_plan_steps(_state((plan,)))) == (("actor", "plan", 1, "first"),)
    active = _job("job", plan, "first", JobStatus.ACTIVE)
    assert derive_ready_plan_steps(_state((plan,), jobs=(active,))) == ()
    for status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        terminal = _job("job", plan, "first", status)
        assert _refs(derive_ready_plan_steps(_state((plan,), jobs=(terminal,)))) == (
            ("actor", "plan", 1, "dependent"),
        )


def test_subjectless_pending_point_blocks_actor_but_not_other_actors() -> None:
    blocked = _plan("blocked", "actor", _step("blocked-step"))
    other = _plan("other", "other", _step("other-step"))
    point = _point("point", "actor", None)

    assert _refs(derive_ready_plan_steps(_state((blocked, other), points=(point,)))) == (
        ("other", "other", 1, "other-step"),
    )


def test_subject_point_blocks_its_replacement_descendants_not_independent_plan() -> None:
    old = _plan("old", "actor", _step("old-step"))
    child = _plan("child", "actor", _step("child-step"), replaces=old.ref)
    grandchild = _plan(
        "grandchild",
        "actor",
        _step("grandchild-step"),
        replaces=child.ref,
    )
    independent = _plan("independent", "actor", _step("independent-step"))
    point = _point("point", "actor", old.ref)

    assert _refs(
        derive_ready_plan_steps(_state((old, child, grandchild, independent), points=(point,)))
    ) == (("actor", "independent", 1, "independent-step"),)


def test_pending_point_does_not_modify_or_remove_existing_jobs() -> None:
    plan = _plan("plan", "actor", _step("running"), _step("unstarted"))
    running = _job("job", plan, "running", JobStatus.ACTIVE)
    point = _point("point", "actor", None)
    state = _state((plan,), jobs=(running,), points=(point,))

    assert derive_ready_plan_steps(state) == ()
    assert state.execution.jobs[JobId("job")] is running
    assert running.status is JobStatus.ACTIVE


def test_multiple_pending_points_for_one_actor_are_typed_unsupported_state() -> None:
    plan = _plan("plan", "actor", _step("step"))
    state = _state(
        (plan,),
        points=(
            _point("one", "actor", plan.ref),
            _point("two", "actor", None),
        ),
    )

    try:
        derive_ready_plan_steps(state)
    except UnsupportedRuntimeStateError as error:
        assert "actor" in str(error)
    else:
        raise AssertionError("expected UnsupportedRuntimeStateError")


def test_job_start_proposal_requires_initial_progress() -> None:
    proposal = JobStartProposal(BinaryProgress(False), activate=True)
    assert proposal.activate is True

    try:
        JobStartProposal(BinaryProgress(True))
    except ValueError as error:
        assert "initial" in str(error)
    else:
        raise AssertionError("expected invalid initial progress")
