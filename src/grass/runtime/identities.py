# SPDX-License-Identifier: GPL-3.0-only

"""Default opaque identity allocation for local runtime execution."""

from uuid import uuid4

from grass.core.execution import PlanStepRef
from grass.core.identifiers import (
    BranchId,
    DecisionPointId,
    EntityId,
    EventId,
    JobId,
    ObservationId,
    TransitionId,
)
from grass.runtime.contracts import RuntimeWorkKind


class UuidRuntimeIdentitySource:
    """Allocate process-local candidates using random UUID strings."""

    def transition_id(self, branch_id: BranchId, work_kind: RuntimeWorkKind, /) -> TransitionId:
        del branch_id, work_kind
        return TransitionId(str(uuid4()))

    def event_ids(self, count: int, /) -> tuple[EventId, ...]:
        if type(count) is not int:
            raise TypeError("count must be an integer")
        if count < 1:
            raise ValueError("count must be positive")
        return tuple(EventId(str(uuid4())) for _ in range(count))

    def job_id(self, plan_step_ref: PlanStepRef, /) -> JobId:
        if type(plan_step_ref) is not PlanStepRef:
            raise TypeError("plan_step_ref must be a PlanStepRef")
        return JobId(str(uuid4()))

    def observation_id(self, source_event_id: EventId, actor_id: EntityId, /) -> ObservationId:
        if type(source_event_id) is not EventId:
            raise TypeError("source_event_id must be an EventId")
        if type(actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        return ObservationId(str(uuid4()))

    def decision_point_id(self, observation_id: ObservationId, /) -> DecisionPointId:
        if type(observation_id) is not ObservationId:
            raise TypeError("observation_id must be an ObservationId")
        return DecisionPointId(str(uuid4()))
