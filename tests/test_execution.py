# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import (
    ActionPrimitive,
    BinaryProgress,
    BlueprintId,
    BlueprintRef,
    EntityId,
    ExecutionState,
    Job,
    JobId,
    JobStatus,
    LinearProgress,
    LogicalTime,
    Plan,
    PlanDependency,
    PlanDependencyCondition,
    PlanId,
    PlanRef,
    PlanStep,
    PlanStepId,
    PlanStepOrigin,
    PlanStepRef,
    Provenance,
)
from grass.core._structured_data import StructuredValue


def step(
    label: str,
    *,
    primitive: ActionPrimitive = ActionPrimitive.WAIT,
    dependencies: frozenset[PlanDependency] = frozenset(),
) -> PlanStep:
    return PlanStep(
        step_id=PlanStepId(label),
        primitive=primitive,
        blueprint_ref=None,
        bindings={},
        parameters={},
        dependencies=dependencies,
        origin=PlanStepOrigin.ACTOR_INTENT,
    )


def plan(
    plan_id: str,
    version: int,
    steps: tuple[PlanStep, ...],
    *,
    replaces: PlanRef | None = None,
) -> Plan:
    return Plan(
        plan_id=PlanId(plan_id),
        version=version,
        actor_id=EntityId("actor"),
        objective="Complete work",
        steps=steps,
        replaces_plan_ref=replaces,
        provenance=Provenance("ENGINE"),
        recorded_at=LogicalTime(version),
    )


def test_reference_versions_are_positive_and_nominal() -> None:
    assert PlanRef(PlanId("plan"), 1).version == 1
    assert BlueprintRef(BlueprintId("blueprint"), 2).version == 2

    with pytest.raises(ValueError, match="positive"):
        PlanRef(PlanId("plan"), 0)
    with pytest.raises(TypeError, match="integer"):
        BlueprintRef(BlueprintId("blueprint"), cast(int, True))


def test_plan_step_freezes_structured_values_and_preserves_blueprint_identity() -> None:
    target_values: list[StructuredValue] = ["one"]
    bindings: dict[str, StructuredValue] = {"target": target_values}
    plan_step = PlanStep(
        PlanStepId("step"),
        ActionPrimitive.MODIFY,
        BlueprintRef(BlueprintId("blueprint"), 3),
        bindings,
        {"amount": 2},
        frozenset(),
        PlanStepOrigin.PLANNER_DERIVED,
        "Update target",
    )

    target_values.append("two")

    assert plan_step.bindings == {"target": ("one",)}
    assert plan_step.blueprint_ref == BlueprintRef(BlueprintId("blueprint"), 3)
    with pytest.raises(TypeError):
        cast(dict[str, object], plan_step.parameters)["new"] = True
    with pytest.raises(FrozenInstanceError):
        plan_step.description = "changed"  # type: ignore[misc]


def test_plan_accepts_later_listed_dependencies_and_preserves_authored_order() -> None:
    second = step("second")
    first = step(
        "first",
        dependencies=frozenset({PlanDependency(second.step_id, PlanDependencyCondition.TERMINAL)}),
    )

    value = plan("plan", 1, (first, second))

    assert tuple(item.step_id for item in value.steps) == (
        PlanStepId("first"),
        PlanStepId("second"),
    )


def test_plan_rejects_empty_duplicate_missing_self_and_cyclic_steps() -> None:
    with pytest.raises(ValueError, match="at least one"):
        plan("plan", 1, ())
    duplicate = step("duplicate")
    with pytest.raises(ValueError, match="unique"):
        plan("plan", 1, (duplicate, duplicate))
    with pytest.raises(ValueError, match="same Plan version"):
        plan(
            "plan",
            1,
            (
                step(
                    "step",
                    dependencies=frozenset({PlanDependency(PlanStepId("missing"))}),
                ),
            ),
        )
    with pytest.raises(ValueError, match="itself"):
        step(
            "self",
            dependencies=frozenset({PlanDependency(PlanStepId("self"))}),
        )
    with pytest.raises(ValueError, match="DAG"):
        plan(
            "plan",
            1,
            (
                step("one", dependencies=frozenset({PlanDependency(PlanStepId("two"))})),
                step("two", dependencies=frozenset({PlanDependency(PlanStepId("one"))})),
            ),
        )


def test_execution_state_allows_step_content_changes_within_same_plan() -> None:
    version_one = plan("plan", 1, (step("logical", primitive=ActionPrimitive.WAIT),))
    version_two = plan("plan", 2, (step("logical", primitive=ActionPrimitive.MOVE),))

    state = ExecutionState(plans={version_one.ref: version_one, version_two.ref: version_two})

    assert state.plans[version_one.ref].steps[0].primitive is ActionPrimitive.WAIT
    assert state.plans[version_two.ref].steps[0].primitive is ActionPrimitive.MOVE


def test_execution_state_rejects_step_identity_reuse_across_plan_ids() -> None:
    one = plan("one", 1, (step("shared"),))
    two = plan("two", 1, (step("shared"),))

    with pytest.raises(ValueError, match="more than one PlanId"):
        ExecutionState(plans={one.ref: one, two.ref: two})


def test_execution_state_rejects_noncontiguous_versions_and_changed_replacement_ref() -> None:
    first = plan("plan", 1, (step("one"),))
    third = plan("plan", 3, (step("one"),))
    with pytest.raises(ValueError, match="contiguous"):
        ExecutionState(plans={first.ref: first, third.ref: third})

    replaced = PlanRef(PlanId("old"), 1)
    old = plan("old", 1, (step("old-step"),))
    replacement = plan("new", 1, (step("new-step"),), replaces=replaced)
    changed = plan("new", 2, (step("new-step"),), replaces=None)
    with pytest.raises(ValueError, match="preserve"):
        ExecutionState(
            plans={
                old.ref: old,
                replacement.ref: replacement,
                changed.ref: changed,
            }
        )


@pytest.mark.parametrize(
    "completed,total",
    [(0, 1), (0.0, 1.5), (1, 1), (1.5, 2.0)],
)
def test_linear_progress_accepts_exact_finite_bounded_numbers(
    completed: int | float, total: int | float
) -> None:
    assert LinearProgress(completed, total).completed == completed


@pytest.mark.parametrize(
    "completed,total",
    [(True, 1), (0, True), (-1, 1), (2, 1), (0, 0), (float("nan"), 1)],
)
def test_linear_progress_rejects_invalid_values(completed: object, total: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        LinearProgress(cast(int | float, completed), cast(int | float, total))


def test_binary_progress_requires_boolean() -> None:
    assert BinaryProgress(False).terminal is False
    assert BinaryProgress(True).terminal is True
    with pytest.raises(TypeError, match="boolean"):
        BinaryProgress(cast(bool, 1))


def test_completed_job_requires_terminal_progress() -> None:
    plan_ref = PlanRef(PlanId("plan"), 1)
    with pytest.raises(ValueError, match="terminal progress"):
        Job(
            JobId("job"),
            PlanStepRef(plan_ref, PlanStepId("step")),
            JobStatus.COMPLETED,
            BinaryProgress(False),
            Provenance("ENGINE"),
            LogicalTime(1),
        )
