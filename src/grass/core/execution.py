# SPDX-License-Identifier: GPL-3.0-only

"""Immutable Plan, PlanStep, and Job value contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import ClassVar, TypeAlias

from grass.core._structured_data import StructuredValue, freeze_structured_mapping
from grass.core.identifiers import (
    BlueprintId,
    EntityId,
    JobId,
    PlanId,
    PlanStepId,
)
from grass.core.logical_time import LogicalTime
from grass.core.provenance import Provenance


def _positive_version(value: object, field_name: str) -> None:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    if value < 1:
        raise ValueError(f"{field_name} must be positive")


def _non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


class ActionPrimitive(StrEnum):
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    RELATE = "RELATE"
    TRANSFER = "TRANSFER"
    MOVE = "MOVE"
    COMMUNICATE = "COMMUNICATE"
    OBSERVE = "OBSERVE"
    WAIT = "WAIT"
    REST = "REST"


class PlanStepOrigin(StrEnum):
    ACTOR_INTENT = "ACTOR_INTENT"
    PLANNER_DERIVED = "PLANNER_DERIVED"


class PlanDependencyCondition(StrEnum):
    SUCCESS = "SUCCESS"
    TERMINAL = "TERMINAL"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in (self.COMPLETED, self.FAILED, self.CANCELLED)


@dataclass(frozen=True, slots=True)
class PlanRef:
    plan_id: PlanId
    version: int

    def __post_init__(self) -> None:
        if type(self.plan_id) is not PlanId:
            raise TypeError("plan_id must be a PlanId")
        _positive_version(self.version, "Plan version")


@dataclass(frozen=True, slots=True)
class PlanStepRef:
    plan_ref: PlanRef
    step_id: PlanStepId

    def __post_init__(self) -> None:
        if type(self.plan_ref) is not PlanRef:
            raise TypeError("plan_ref must be a PlanRef")
        if type(self.step_id) is not PlanStepId:
            raise TypeError("step_id must be a PlanStepId")


@dataclass(frozen=True, slots=True)
class BlueprintRef:
    blueprint_id: BlueprintId
    version: int

    def __post_init__(self) -> None:
        if type(self.blueprint_id) is not BlueprintId:
            raise TypeError("blueprint_id must be a BlueprintId")
        _positive_version(self.version, "Blueprint version")


@dataclass(frozen=True, slots=True)
class PlanDependency:
    step_id: PlanStepId
    condition: PlanDependencyCondition = PlanDependencyCondition.SUCCESS

    def __post_init__(self) -> None:
        if type(self.step_id) is not PlanStepId:
            raise TypeError("step_id must be a PlanStepId")
        if type(self.condition) is not PlanDependencyCondition:
            raise TypeError("condition must be a PlanDependencyCondition")


@dataclass(frozen=True, slots=True)
class PlanStep:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    step_id: PlanStepId
    primitive: ActionPrimitive
    blueprint_ref: BlueprintRef | None
    bindings: Mapping[str, StructuredValue]
    parameters: Mapping[str, StructuredValue]
    dependencies: frozenset[PlanDependency]
    origin: PlanStepOrigin
    description: str | None = None

    def __post_init__(self) -> None:
        if type(self.step_id) is not PlanStepId:
            raise TypeError("step_id must be a PlanStepId")
        if type(self.primitive) is not ActionPrimitive:
            raise TypeError("primitive must be an ActionPrimitive")
        if self.blueprint_ref is not None and type(self.blueprint_ref) is not BlueprintRef:
            raise TypeError("blueprint_ref must be a BlueprintRef or None")
        if not isinstance(self.bindings, Mapping):
            raise TypeError("bindings must be a mapping")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters must be a mapping")
        if type(self.dependencies) is not frozenset:
            raise TypeError("dependencies must be a frozenset")
        if not all(type(item) is PlanDependency for item in self.dependencies):
            raise TypeError("dependencies must contain PlanDependency values")
        if self.step_id in {item.step_id for item in self.dependencies}:
            raise ValueError("a PlanStep cannot depend on itself")
        if type(self.origin) is not PlanStepOrigin:
            raise TypeError("origin must be a PlanStepOrigin")
        if self.description is not None:
            _non_empty_string(self.description, "description")
        object.__setattr__(
            self,
            "bindings",
            freeze_structured_mapping(self.bindings, description="PlanStep bindings"),
        )
        object.__setattr__(
            self,
            "parameters",
            freeze_structured_mapping(self.parameters, description="PlanStep parameters"),
        )


def _validate_plan_steps(steps: tuple[PlanStep, ...]) -> None:
    if not steps:
        raise ValueError("a Plan must contain at least one PlanStep")
    step_ids = tuple(step.step_id for step in steps)
    if len(set(step_ids)) != len(step_ids):
        raise ValueError("PlanStepId values must be unique within a Plan version")
    known = frozenset(step_ids)
    for step in steps:
        if any(dependency.step_id not in known for dependency in step.dependencies):
            raise ValueError("Plan dependencies must target steps in the same Plan version")

    dependencies = {
        step.step_id: frozenset(item.step_id for item in step.dependencies) for step in steps
    }
    visiting: set[PlanStepId] = set()
    visited: set[PlanStepId] = set()

    def visit(step_id: PlanStepId) -> None:
        if step_id in visiting:
            raise ValueError("Plan dependencies must form a DAG")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency_id in dependencies[step_id]:
            visit(dependency_id)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in step_ids:
        visit(step_id)


@dataclass(frozen=True, slots=True)
class Plan:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    plan_id: PlanId
    version: int
    actor_id: EntityId
    objective: str
    steps: Sequence[PlanStep]
    replaces_plan_ref: PlanRef | None
    provenance: Provenance
    recorded_at: LogicalTime

    def __post_init__(self) -> None:
        if type(self.plan_id) is not PlanId:
            raise TypeError("plan_id must be a PlanId")
        _positive_version(self.version, "Plan version")
        if type(self.actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        _non_empty_string(self.objective, "objective")
        frozen_steps = tuple(self.steps)
        if not all(type(step) is PlanStep for step in frozen_steps):
            raise TypeError("steps must contain only PlanStep values")
        _validate_plan_steps(frozen_steps)
        if self.replaces_plan_ref is not None and type(self.replaces_plan_ref) is not PlanRef:
            raise TypeError("replaces_plan_ref must be a PlanRef or None")
        if self.replaces_plan_ref is not None and self.replaces_plan_ref.plan_id == self.plan_id:
            raise ValueError("a Plan cannot replace its own PlanId")
        if type(self.provenance) is not Provenance:
            raise TypeError("provenance must be Provenance")
        if type(self.recorded_at) is not LogicalTime:
            raise TypeError("recorded_at must be LogicalTime")
        object.__setattr__(self, "steps", frozen_steps)

    @property
    def ref(self) -> PlanRef:
        return PlanRef(self.plan_id, self.version)

    def step(self, step_id: PlanStepId) -> PlanStep | None:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None


ProgressNumber: TypeAlias = int | float


def _progress_number(value: object, field_name: str) -> None:
    if type(value) not in (int, float) or (type(value) is float and not isfinite(value)):
        raise TypeError(f"{field_name} must be an integer or finite float")


@dataclass(frozen=True, slots=True)
class LinearProgress:
    completed: ProgressNumber
    total: ProgressNumber

    def __post_init__(self) -> None:
        _progress_number(self.completed, "completed")
        _progress_number(self.total, "total")
        if self.total <= 0:
            raise ValueError("LINEAR total must be positive")
        if self.completed < 0 or self.completed > self.total:
            raise ValueError("LINEAR completed must be between zero and total")

    @property
    def terminal(self) -> bool:
        return self.completed == self.total


@dataclass(frozen=True, slots=True)
class BinaryProgress:
    complete: bool

    def __post_init__(self) -> None:
        if type(self.complete) is not bool:
            raise TypeError("complete must be a boolean")

    @property
    def terminal(self) -> bool:
        return self.complete


JobProgress: TypeAlias = LinearProgress | BinaryProgress


def initial_progress(progress: JobProgress) -> bool:
    if type(progress) is LinearProgress:
        return progress.completed == 0
    if type(progress) is BinaryProgress:
        return not progress.complete
    raise TypeError("progress must be LinearProgress or BinaryProgress")


def progress_is_monotonic(previous: JobProgress, current: JobProgress) -> bool:
    if type(previous) is not type(current):
        return False
    if type(previous) is LinearProgress and type(current) is LinearProgress:
        return previous.total == current.total and current.completed >= previous.completed
    if type(previous) is BinaryProgress and type(current) is BinaryProgress:
        return previous.complete is False or current.complete is True
    raise AssertionError("unsupported progress model")


def terminal_progress(progress: JobProgress) -> bool:
    if type(progress) is LinearProgress:
        return progress.terminal
    if type(progress) is BinaryProgress:
        return progress.terminal
    raise TypeError("progress must be LinearProgress or BinaryProgress")


@dataclass(frozen=True, slots=True)
class Job:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    job_id: JobId
    plan_step_ref: PlanStepRef
    status: JobStatus
    progress: JobProgress
    creation_provenance: Provenance
    created_at: LogicalTime

    def __post_init__(self) -> None:
        if type(self.job_id) is not JobId:
            raise TypeError("job_id must be a JobId")
        if type(self.plan_step_ref) is not PlanStepRef:
            raise TypeError("plan_step_ref must be a PlanStepRef")
        if type(self.status) is not JobStatus:
            raise TypeError("status must be a JobStatus")
        if type(self.progress) not in (LinearProgress, BinaryProgress):
            raise TypeError("progress must be LinearProgress or BinaryProgress")
        if self.status is JobStatus.COMPLETED and not terminal_progress(self.progress):
            raise ValueError("COMPLETED Job requires terminal progress")
        if type(self.creation_provenance) is not Provenance:
            raise TypeError("creation_provenance must be Provenance")
        if type(self.created_at) is not LogicalTime:
            raise TypeError("created_at must be LogicalTime")
