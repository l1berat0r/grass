# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import (
    BoundedReaction,
    BoundedReactionDecision,
    BranchId,
    CognitionEventPayloadError,
    CognitionState,
    Decision,
    DecisionPoint,
    DecisionPointId,
    DecisionPointReason,
    DecisionPointScope,
    Entity,
    EntityId,
    Event,
    EventId,
    EventPayload,
    InMemoryEventStore,
    LogicalTime,
    Observation,
    ObservationCreatedPayload,
    ObservationId,
    PlanId,
    PlanRef,
    ProjectionError,
    Provenance,
    RevisePlanDecision,
    SimulationState,
    TransitionId,
    WorldState,
    decode_cognition_event,
    project_transition,
)
from grass.core._structured_data import StructuredValue
from grass.core.cognition_events import (
    DECISION_POINT_CREATED,
    DECISION_RECORDED,
    OBSERVATION_CREATED,
)
from grass.core.world_events import ENTITY_CREATED
from tests.support import event_to_commit, rooted_store, transition_to_commit


def committed_event(
    event_type: str,
    payload: EventPayload,
    *,
    version: int = 1,
    sequence: int = 1,
) -> Event:
    return Event(
        EventId(f"event-{sequence}"),
        BranchId("branch"),
        sequence,
        LogicalTime(7),
        TransitionId("transition"),
        event_type,
        version,
        payload,
        Provenance("ACTOR"),
    )


def observation_payload(actor: str = "actor") -> EventPayload:
    return {
        "observation_id": "observation",
        "actor_id": actor,
        "content": {"message": "door opened", "confidence": 0.8},
    }


def decision_point_payload(
    *,
    actor: str = "actor",
    observations: list[StructuredValue] | None = None,
    subject: StructuredValue = None,
) -> EventPayload:
    return {
        "decision_point_id": "decision-point",
        "actor_id": actor,
        "reason": "MATERIAL_OBSERVATION",
        "scope": "BOUNDED",
        "observation_ids": ["observation"] if observations is None else observations,
        "subject_plan_ref": subject,
    }


def actor_state() -> tuple[InMemoryEventStore, SimulationState]:
    store = rooted_store("root")
    committed = store.commit_transition(
        transition_to_commit(
            "root",
            "actor",
            1,
            [
                event_to_commit(
                    "actor",
                    event_type=ENTITY_CREATED,
                    payload={
                        "entity_id": "actor",
                        "entity_type": "Person",
                        "properties": {},
                    },
                )
            ],
        )
    )
    return store, project_transition(SimulationState.empty(BranchId("test:root")), committed)


def test_observation_and_bounded_reaction_recursively_freeze_content() -> None:
    content: dict[str, StructuredValue] = {"nested": {"values": [1, 2]}}
    observation = Observation(
        ObservationId("observation"),
        EntityId("actor"),
        content,
        Provenance("PERCEPTION"),
        LogicalTime(3),
    )
    reaction_content: dict[str, StructuredValue] = {"reply": ["yes"]}
    reaction = BoundedReaction("Reply locally", reaction_content)
    content["changed"] = True
    reaction_content["changed"] = True

    assert observation.content == {"nested": {"values": (1, 2)}}
    assert reaction.content == {"reply": ("yes",)}
    with pytest.raises(TypeError):
        cast(dict[str, StructuredValue], observation.content)["new"] = True
    with pytest.raises(FrozenInstanceError):
        reaction.intent_description = "changed"  # type: ignore[misc]


def test_closed_reason_scope_and_outcome_vocabularies() -> None:
    assert {item.value for item in DecisionPointReason} == {
        "PLAN_REQUIRED",
        "PLAN_EXHAUSTED",
        "PLAN_BLOCKED",
        "INTERACTION_REQUEST",
        "JOB_FAILED",
        "JOB_PAUSED",
        "ASSUMPTION_INVALIDATED",
        "MATERIAL_OBSERVATION",
        "EXTERNAL_EVENT",
        "OPERATOR_INTERVENTION",
    }
    assert {item.value for item in DecisionPointScope} == {"FULL", "BOUNDED"}


def test_decodes_observation_with_envelope_provenance_and_time() -> None:
    decoded = decode_cognition_event(committed_event(OBSERVATION_CREATED, observation_payload()))

    assert isinstance(decoded, ObservationCreatedPayload)
    assert decoded.observation.observation_id == ObservationId("observation")
    assert decoded.observation.provenance == Provenance("ACTOR")
    assert decoded.observation.observed_at == LogicalTime(7)
    assert decoded.observation.content == {"message": "door opened", "confidence": 0.8}


@pytest.mark.parametrize(
    "event_type,payload,version,message",
    [
        (OBSERVATION_CREATED, {"observation_id": "id"}, 1, "fields do not match schema"),
        (
            DECISION_POINT_CREATED,
            {**decision_point_payload(), "future": True},
            1,
            "fields do not match schema",
        ),
        (
            DECISION_POINT_CREATED,
            {**decision_point_payload(), "scope": "GLOBAL"},
            1,
            "unsupported scope",
        ),
        (
            DECISION_RECORDED,
            {
                "decision_point_id": "decision-point",
                "outcome": {"kind": "BOUNDED_REACTION", "bounded_reaction": {}},
            },
            1,
            "fields do not match schema",
        ),
        (OBSERVATION_CREATED, observation_payload(), 2, "unsupported ObservationCreated version"),
    ],
)
def test_cognition_event_schemas_are_strict(
    event_type: str,
    payload: EventPayload,
    version: int,
    message: str,
) -> None:
    with pytest.raises(CognitionEventPayloadError, match=message):
        decode_cognition_event(committed_event(event_type, payload, version=version))


def test_projects_observation_then_pending_and_resolved_decision_point() -> None:
    store, state = actor_state()
    perception = store.commit_transition(
        transition_to_commit(
            "root",
            "perception",
            1,
            [
                event_to_commit(
                    "point",
                    event_type=DECISION_POINT_CREATED,
                    payload=decision_point_payload(),
                ),
                event_to_commit(
                    "observation",
                    event_type=OBSERVATION_CREATED,
                    payload=observation_payload(),
                    provenance=Provenance("PERCEPTION"),
                ),
            ],
        )
    )
    state = project_transition(state, perception)
    point_id = DecisionPointId("decision-point")

    assert state.cognition.is_pending(point_id)
    assert state.cognition.decision_points[point_id].observation_ids == frozenset(
        {ObservationId("observation")}
    )

    decision = store.commit_transition(
        transition_to_commit(
            "root",
            "decision",
            1,
            [
                event_to_commit(
                    "decision",
                    event_type=DECISION_RECORDED,
                    payload={
                        "decision_point_id": "decision-point",
                        "outcome": {
                            "kind": "BOUNDED_REACTION",
                            "bounded_reaction": {
                                "intent_description": "Acknowledge the request",
                                "content": {"message": "Understood"},
                            },
                        },
                    },
                    provenance=Provenance("DECISION_PROVIDER"),
                )
            ],
        )
    )
    state = project_transition(state, decision)

    assert not state.cognition.is_pending(point_id)
    outcome = state.cognition.decisions[point_id].outcome
    assert isinstance(outcome, BoundedReactionDecision)
    assert outcome.bounded_reaction.intent_description == "Acknowledge the request"


def test_cognition_state_is_immutable_and_validates_references() -> None:
    observation = Observation(
        ObservationId("observation"),
        EntityId("actor"),
        {},
        Provenance("PERCEPTION"),
        LogicalTime(1),
    )
    values = {observation.observation_id: observation}
    state = CognitionState(observations=values)
    values.clear()

    assert state.observations == {ObservationId("observation"): observation}
    with pytest.raises(TypeError):
        cast(dict[ObservationId, Observation], state.observations)[ObservationId("new")] = (
            observation
        )

    other_actor = Observation(
        ObservationId("other"),
        EntityId("other-actor"),
        {},
        Provenance("PERCEPTION"),
        LogicalTime(1),
    )
    point = DecisionPoint(
        DecisionPointId("point"),
        EntityId("actor"),
        DecisionPointReason.MATERIAL_OBSERVATION,
        DecisionPointScope.FULL,
        frozenset({other_actor.observation_id}),
    )
    with pytest.raises(ValueError, match="belong to its actor"):
        CognitionState(
            observations={other_actor.observation_id: other_actor},
            decision_points={point.decision_point_id: point},
        )


def test_simulation_state_rejects_invalid_checkpoint_decision_plan_relationships() -> None:
    point = DecisionPoint(
        DecisionPointId("point"),
        EntityId("actor"),
        DecisionPointReason.PLAN_REQUIRED,
        DecisionPointScope.FULL,
        frozenset(),
    )
    decision = Decision(
        point.decision_point_id,
        RevisePlanDecision(PlanRef(PlanId("missing"), 2)),
        Provenance("DECISION_PROVIDER"),
        LogicalTime(1),
    )
    cognition = CognitionState(
        decision_points={point.decision_point_id: point},
        decisions={point.decision_point_id: decision},
    )

    with pytest.raises(ValueError, match="resulting Plan"):
        SimulationState(
            SimulationState.empty(BranchId("branch")).position,
            world=WorldState(entities={EntityId("actor"): Entity(EntityId("actor"), "Person", {})}),
            cognition=cognition,
        )


def test_invalid_actor_fails_without_mutating_previous_state() -> None:
    store, state = actor_state()
    wrong_actor = store.commit_transition(
        transition_to_commit(
            "root",
            "wrong-actor",
            1,
            [
                event_to_commit(
                    "wrong-observation",
                    event_type=OBSERVATION_CREATED,
                    payload=observation_payload("missing"),
                )
            ],
        )
    )

    with pytest.raises(ProjectionError, match="Observation actors"):
        project_transition(state, wrong_actor)
    assert state.cognition == CognitionState()


def test_decision_recorded_requires_a_preexisting_branch_visible_decision_point() -> None:
    store, state = actor_state()
    transition = store.commit_transition(
        transition_to_commit(
            "root",
            "combined-cognition",
            1,
            [
                event_to_commit(
                    "point",
                    event_type=DECISION_POINT_CREATED,
                    payload=decision_point_payload(observations=[]),
                ),
                event_to_commit(
                    "decision",
                    event_type=DECISION_RECORDED,
                    payload={
                        "decision_point_id": "decision-point",
                        "outcome": {
                            "kind": "BOUNDED_REACTION",
                            "bounded_reaction": {
                                "intent_description": "Wait",
                                "content": None,
                            },
                        },
                    },
                ),
            ],
        )
    )

    with pytest.raises(ProjectionError, match="preexisting DecisionPoint"):
        project_transition(state, transition)


def pending_point_state() -> tuple[InMemoryEventStore, SimulationState]:
    store, state = actor_state()
    transition = store.commit_transition(
        transition_to_commit(
            "root",
            "point",
            1,
            [
                event_to_commit(
                    "point",
                    event_type=DECISION_POINT_CREATED,
                    payload=decision_point_payload(observations=[]),
                )
            ],
        )
    )
    return store, project_transition(state, transition)


def test_plan_decision_requires_matching_plan_event_in_same_transition() -> None:
    store, state = pending_point_state()
    transition = store.commit_transition(
        transition_to_commit(
            "root",
            "decision-without-plan",
            1,
            [
                event_to_commit(
                    "decision",
                    event_type=DECISION_RECORDED,
                    payload={
                        "decision_point_id": "decision-point",
                        "outcome": {
                            "kind": "REPLACE_PLAN",
                            "resulting_plan_ref": {"plan_id": "missing", "version": 1},
                        },
                    },
                )
            ],
        )
    )

    with pytest.raises(ProjectionError, match="exactly one Plan Event"):
        project_transition(state, transition)


def test_duplicate_decisions_in_one_transition_fail_atomically() -> None:
    store, state = pending_point_state()
    decision_payload: EventPayload = {
        "decision_point_id": "decision-point",
        "outcome": {
            "kind": "BOUNDED_REACTION",
            "bounded_reaction": {"intent_description": "Wait", "content": None},
        },
    }
    transition = store.commit_transition(
        transition_to_commit(
            "root",
            "duplicate-decisions",
            1,
            [
                event_to_commit(
                    "first-decision",
                    event_type=DECISION_RECORDED,
                    payload=decision_payload,
                ),
                event_to_commit(
                    "second-decision",
                    event_type=DECISION_RECORDED,
                    payload=decision_payload,
                ),
            ],
        )
    )

    with pytest.raises(ProjectionError, match="already resolved"):
        project_transition(state, transition)
    assert state.cognition.is_pending(DecisionPointId("decision-point"))
