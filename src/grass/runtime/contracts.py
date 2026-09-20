# SPDX-License-Identifier: GPL-3.0-only

"""Public contracts for bounded local simulation runtime orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol

from grass.core._structured_data import StructuredValue, freeze_structured_mapping
from grass.core.branches import HistoryPosition
from grass.core.events import CommittedTransition
from grass.core.execution import PlanRef, PlanStepRef
from grass.core.identifiers import (
    BranchId,
    DecisionPointId,
    EntityId,
    EventId,
    JobId,
    ObservationId,
    TransitionId,
)
from grass.core.logical_time import LogicalTime
from grass.core.state import SimulationState


class RuntimeIntegrityError(RuntimeError):
    """Canonical history cannot produce a coherent runtime frontier."""


class UnsupportedRuntimeFrontierError(RuntimeError):
    """A valid scheduler frontier is outside the supported Slice 12 subset."""


class RuntimeWorkKind(StrEnum):
    INITIALIZATION = "INITIALIZATION"
    PERCEPTION = "PERCEPTION"
    DECISION = "DECISION"
    JOB_START = "JOB_START"
    JOB_RESOLUTION_FRONTIER = "JOB_RESOLUTION_FRONTIER"
    SCENARIO_OCCURRENCE = "SCENARIO_OCCURRENCE"


class RuntimeStopReason(StrEnum):
    QUIESCENT = "QUIESCENT"
    WAITING_FOR_DECISION = "WAITING_FOR_DECISION"
    TARGET_REACHED = "TARGET_REACHED"
    STEP_BUDGET_EXHAUSTED = "STEP_BUDGET_EXHAUSTED"


class RunStatus(StrEnum):
    """Purely derived availability of work at one initialized branch head."""

    READY = "READY"
    WAITING_FOR_DECISION = "WAITING_FOR_DECISION"
    QUIESCENT = "QUIESCENT"


@dataclass(frozen=True, slots=True)
class StepResult:
    """One committed engine transition or one explicit no-commit stop."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position_before: HistoryPosition
    position_after: HistoryPosition
    logical_time: LogicalTime
    work_kind: RuntimeWorkKind | None = None
    committed_transition: CommittedTransition | None = None
    stop_reason: RuntimeStopReason | None = None
    waiting_decision_point_ids: Sequence[DecisionPointId] = ()

    def __post_init__(self) -> None:
        if type(self.position_before) is not HistoryPosition:
            raise TypeError("position_before must be a HistoryPosition")
        if type(self.position_after) is not HistoryPosition:
            raise TypeError("position_after must be a HistoryPosition")
        if type(self.logical_time) is not LogicalTime:
            raise TypeError("logical_time must be a LogicalTime")
        committed = self.committed_transition is not None
        stopped = self.stop_reason is not None
        if committed == stopped:
            raise ValueError("StepResult requires exactly one transition or stop reason")
        if committed:
            if type(self.committed_transition) is not CommittedTransition:
                raise TypeError("committed_transition must be a CommittedTransition")
            if type(self.work_kind) is not RuntimeWorkKind:
                raise TypeError("a committed step requires work_kind")
            if self.position_before == self.position_after:
                raise ValueError("a committed step must advance the history position")
        elif self.work_kind is not None:
            raise ValueError("a stopped step must not contain work_kind")
        waiting = tuple(self.waiting_decision_point_ids)
        if not all(type(item) is DecisionPointId for item in waiting):
            raise TypeError("waiting_decision_point_ids must contain DecisionPointId values")
        if len(set(waiting)) != len(waiting):
            raise ValueError("waiting_decision_point_ids must be unique")
        if bool(waiting) != (self.stop_reason is RuntimeStopReason.WAITING_FOR_DECISION):
            raise ValueError("only WAITING_FOR_DECISION contains waiting DecisionPoints")
        object.__setattr__(self, "waiting_decision_point_ids", waiting)


@dataclass(frozen=True, slots=True)
class AdvanceResult:
    """Final outcome of repeatedly executing bounded engine steps."""

    position: HistoryPosition
    logical_time: LogicalTime
    committed_steps: int
    stop_reason: RuntimeStopReason
    waiting_decision_point_ids: Sequence[DecisionPointId] = ()

    def __post_init__(self) -> None:
        if type(self.position) is not HistoryPosition:
            raise TypeError("position must be a HistoryPosition")
        if type(self.logical_time) is not LogicalTime:
            raise TypeError("logical_time must be a LogicalTime")
        if type(self.committed_steps) is not int:
            raise TypeError("committed_steps must be an integer")
        if self.committed_steps < 0:
            raise ValueError("committed_steps must not be negative")
        if type(self.stop_reason) is not RuntimeStopReason:
            raise TypeError("stop_reason must be a RuntimeStopReason")
        waiting = tuple(self.waiting_decision_point_ids)
        if not all(type(item) is DecisionPointId for item in waiting):
            raise TypeError("waiting_decision_point_ids must contain DecisionPointId values")
        if len(set(waiting)) != len(waiting):
            raise ValueError("waiting_decision_point_ids must be unique")
        if bool(waiting) != (self.stop_reason is RuntimeStopReason.WAITING_FOR_DECISION):
            raise ValueError("only WAITING_FOR_DECISION contains waiting DecisionPoints")
        object.__setattr__(self, "waiting_decision_point_ids", waiting)


class RuntimeIdentitySource(Protocol):
    """Allocate opaque identities after non-authoritative output is known."""

    def transition_id(self, branch_id: BranchId, work_kind: RuntimeWorkKind, /) -> TransitionId: ...

    def event_ids(self, count: int, /) -> Sequence[EventId]: ...

    def job_id(self, plan_step_ref: PlanStepRef, /) -> JobId: ...

    def observation_id(self, source_event_id: EventId, actor_id: EntityId, /) -> ObservationId: ...

    def decision_point_id(self, observation_id: ObservationId, /) -> DecisionPointId: ...


@dataclass(frozen=True, slots=True)
class PerceptionCandidate:
    """One rebuildable actor-relative consequence of a committed source Event."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    source_event_id: EventId
    actor_id: EntityId
    content: Mapping[str, StructuredValue]
    subject_plan_ref: PlanRef | None = None

    def __post_init__(self) -> None:
        if type(self.source_event_id) is not EventId:
            raise TypeError("source_event_id must be an EventId")
        if type(self.actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        if not isinstance(self.content, Mapping):
            raise TypeError("content must be a mapping")
        if self.subject_plan_ref is not None and type(self.subject_plan_ref) is not PlanRef:
            raise TypeError("subject_plan_ref must be a PlanRef or None")
        object.__setattr__(
            self,
            "content",
            freeze_structured_mapping(self.content, description="PerceptionCandidate content"),
        )


class PerceptionProjector(Protocol):
    """Pure deterministic derivation of perception from one committed transition."""

    def project(
        self,
        source_transition: CommittedTransition,
        state_after_source: SimulationState,
        /,
    ) -> Sequence[PerceptionCandidate]: ...
