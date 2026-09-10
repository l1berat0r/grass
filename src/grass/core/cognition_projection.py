# SPDX-License-Identifier: GPL-3.0-only

"""Atomic deterministic projection of cognition Events."""

from __future__ import annotations

from collections.abc import Mapping

from grass.core.cognition import (
    BoundedReactionDecision,
    ContinuePlanDecision,
    Decision,
    DecisionPoint,
    ReplacePlanDecision,
    RevisePlanDecision,
)
from grass.core.cognition_events import (
    CognitionEventPayload,
    DecisionPointCreatedPayload,
    DecisionRecordedPayload,
    ObservationCreatedPayload,
)
from grass.core.execution import Plan, PlanRef
from grass.core.execution_events import (
    PlanCreatedPayload,
    PlanEventPayload,
    PlanReplacedPayload,
    PlanRevisedPayload,
)
from grass.core.identifiers import EntityId
from grass.core.state import CognitionState


class CognitionProjectionError(ValueError):
    """Committed cognition history violates the Slice 8 contracts."""


def _matching_plan_event(
    resulting_ref: PlanRef, plan_payloads: tuple[PlanEventPayload, ...]
) -> PlanEventPayload:
    matches = tuple(payload for payload in plan_payloads if payload.plan.ref == resulting_ref)
    if len(matches) != 1:
        raise CognitionProjectionError(
            "a Plan decision must match exactly one Plan Event in the same transition"
        )
    return matches[0]


def _validate_outcome(
    decision: Decision,
    point: DecisionPoint,
    plans: Mapping[PlanRef, Plan],
    plan_payloads: tuple[PlanEventPayload, ...],
) -> None:
    outcome = decision.outcome
    subject = point.subject_plan_ref
    if type(outcome) is ContinuePlanDecision:
        if subject is None or subject not in plans:
            raise CognitionProjectionError("CONTINUE_PLAN requires an existing subject Plan")
        return
    if type(outcome) is BoundedReactionDecision:
        return

    if type(outcome) is RevisePlanDecision:
        if subject is None:
            raise CognitionProjectionError("REVISE_PLAN requires subject_plan_ref")
        if outcome.resulting_plan_ref != PlanRef(subject.plan_id, subject.version + 1):
            raise CognitionProjectionError("REVISE_PLAN must produce the exact next Plan version")
        payload = _matching_plan_event(outcome.resulting_plan_ref, plan_payloads)
        if type(payload) is not PlanRevisedPayload:
            raise CognitionProjectionError("REVISE_PLAN requires PlanRevised")
    elif type(outcome) is ReplacePlanDecision:
        payload = _matching_plan_event(outcome.resulting_plan_ref, plan_payloads)
        if subject is None:
            if type(payload) is not PlanCreatedPayload:
                raise CognitionProjectionError(
                    "REPLACE_PLAN without a subject requires PlanCreated"
                )
        elif type(payload) is not PlanReplacedPayload:
            raise CognitionProjectionError("REPLACE_PLAN with a subject requires PlanReplaced")
    else:  # pragma: no cover - closed DecisionOutcome union
        raise AssertionError("unsupported DecisionOutcome")

    plan = plans.get(outcome.resulting_plan_ref)
    if plan is None:
        raise CognitionProjectionError("Decision resulting Plan must exist")
    if plan.actor_id != point.actor_id:
        raise CognitionProjectionError("Decision resulting Plan actor must match DecisionPoint")
    if type(outcome) is ReplacePlanDecision and plan.replaces_plan_ref != subject:
        raise CognitionProjectionError("replacement Plan must target the exact subject Plan")


def project_cognition_state(
    current: CognitionState,
    payloads: tuple[CognitionEventPayload, ...],
    final_entity_ids: frozenset[EntityId],
    final_plans: Mapping[PlanRef, Plan],
    plan_payloads: tuple[PlanEventPayload, ...],
) -> CognitionState:
    """Apply all cognition Events as one atomic candidate."""

    if type(current) is not CognitionState:
        raise TypeError("current must be a CognitionState")

    observations = dict(current.observations)
    points = dict(current.decision_points)
    decisions = dict(current.decisions)

    for payload in payloads:
        if type(payload) is not ObservationCreatedPayload:
            continue
        observation = payload.observation
        if observation.observation_id in observations:
            raise CognitionProjectionError("Observation already exists")
        observations[observation.observation_id] = observation

    for payload in payloads:
        if type(payload) is not DecisionPointCreatedPayload:
            continue
        point = payload.decision_point
        if point.decision_point_id in points:
            raise CognitionProjectionError("DecisionPoint already exists")
        for observation_id in point.observation_ids:
            referenced_observation = observations.get(observation_id)
            if referenced_observation is None:
                raise CognitionProjectionError(
                    "DecisionPoint must reference an existing Observation"
                )
            if referenced_observation.actor_id != point.actor_id:
                raise CognitionProjectionError(
                    "DecisionPoint and referenced Observations must share one actor"
                )
        subject = point.subject_plan_ref
        if subject is not None:
            plan = final_plans.get(subject)
            if plan is None:
                raise CognitionProjectionError("DecisionPoint subject Plan must exist")
            if plan.actor_id != point.actor_id:
                raise CognitionProjectionError(
                    "DecisionPoint and subject Plan must share one actor"
                )
        points[point.decision_point_id] = point

    for payload in payloads:
        if type(payload) is not DecisionRecordedPayload:
            continue
        decision = payload.decision
        existing_point = current.decision_points.get(decision.decision_point_id)
        if existing_point is None:
            raise CognitionProjectionError("DecisionRecorded requires a preexisting DecisionPoint")
        if decision.decision_point_id in decisions:
            raise CognitionProjectionError("DecisionPoint is already resolved")
        _validate_outcome(decision, existing_point, final_plans, plan_payloads)
        decisions[decision.decision_point_id] = decision

    if any(observation.actor_id not in final_entity_ids for observation in observations.values()):
        raise CognitionProjectionError("Observation actors must reference existing Entities")
    if any(point.actor_id not in final_entity_ids for point in points.values()):
        raise CognitionProjectionError("DecisionPoint actors must reference existing Entities")

    try:
        return CognitionState(
            observations=observations,
            decision_points=points,
            decisions=decisions,
        )
    except (TypeError, ValueError) as error:
        raise CognitionProjectionError(str(error)) from error
