# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass

import pytest

from grass.core import (
    ActionPrimitive,
    BoundedReaction,
    BoundedReactionDecision,
    BranchId,
    CauseRef,
    CognitionValidationError,
    DecisionOutcomeKind,
    DecisionPointId,
    DecisionPointProposal,
    DecisionPointReason,
    DecisionPointScope,
    DecisionProposal,
    DecisionRequest,
    DecisionTriggerIntegrityError,
    DecisionTriggerResult,
    DeterministicDecisionIntegrityError,
    EntityId,
    EventId,
    EventPayload,
    HistoryPosition,
    InMemoryEventStore,
    ObservationId,
    ObservationProposal,
    PlanId,
    PlanRef,
    PlanStep,
    PlanStepId,
    PlanStepOrigin,
    ProposedPlan,
    Provenance,
    ScriptedDecisionProvider,
    ScriptedDecisionTriggerPolicy,
    SimulationState,
    StaleHistoryError,
    StateCheckpoint,
    TransitionId,
    TransitionRef,
    build_decision_request,
    prepare_decision_point_transition,
    prepare_decision_transition,
    prepare_observation_transition,
    replay_branch,
)
from grass.core.cognition_events import (
    DECISION_POINT_CREATED,
    DECISION_RECORDED,
    OBSERVATION_CREATED,
)
from grass.core.execution_events import PLAN_CREATED, PLAN_REPLACED, PLAN_REVISED
from grass.core.world_events import ENTITY_CREATED, ENTITY_UPDATED
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def plan_snapshot(
    *,
    plan_id: str = "plan",
    version: int = 1,
    step_id: str = "step",
    replaces: EventPayload | None = None,
) -> EventPayload:
    return {
        "plan_id": plan_id,
        "version": version,
        "actor_id": "actor",
        "objective": "Complete objective",
        "steps": [
            {
                "step_id": step_id,
                "primitive": "WAIT",
                "blueprint_ref": None,
                "bindings": {},
                "parameters": {},
                "dependencies": [],
                "origin": "ACTOR_INTENT",
                "description": None,
            }
        ],
        "replaces_plan_ref": replaces,
    }


def step(step_id: str = "step") -> PlanStep:
    return PlanStep(
        PlanStepId(step_id),
        ActionPrimitive.WAIT,
        None,
        {},
        {},
        frozenset(),
        PlanStepOrigin.ACTOR_INTENT,
    )


def proposed_plan(
    *,
    plan_id: str = "plan",
    version: int = 1,
    step_id: str = "step",
    replaces: PlanRef | None = None,
    actor_id: str = "actor",
) -> ProposedPlan:
    return ProposedPlan(
        PlanId(plan_id),
        version,
        EntityId(actor_id),
        "Complete objective",
        (step(step_id),),
        replaces,
    )


def setup_state(*, with_plan: bool = False) -> tuple[InMemoryEventStore, SimulationState]:
    store = rooted_store("root")
    records = [
        event_to_commit(
            "actor",
            event_type=ENTITY_CREATED,
            payload={"entity_id": "actor", "entity_type": "Person", "properties": {}},
        )
    ]
    if with_plan:
        records.append(
            event_to_commit(
                "plan",
                event_type=PLAN_CREATED,
                payload={"plan": plan_snapshot()},
                provenance=Provenance("ACTOR"),
            )
        )
    store.commit_transition(transition_to_commit("root", "genesis", 1, records))
    branch_id = stable_id(BranchId, "root")
    return store, replay_branch(store, store.head_position(branch_id))


def add_point(
    store: InMemoryEventStore,
    state: SimulationState,
    *,
    subject: PlanRef | None = None,
    point_id: str = "point",
) -> SimulationState:
    branch_id = state.position.branch_id
    prepared = prepare_decision_point_transition(
        state,
        EntityId("actor"),
        DecisionPointId(point_id),
        DecisionPointProposal(
            DecisionPointReason.PLAN_REQUIRED
            if subject is None
            else DecisionPointReason.PLAN_BLOCKED,
            DecisionPointScope.FULL,
            frozenset(),
            subject,
        ),
        TransitionRef(branch_id, TransitionId(f"{point_id}-transition")),
        EventId(f"{point_id}-point-event"),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    return replay_branch(store, store.head_position(branch_id))


def test_trigger_continue_persists_observation_without_decision_point_or_provider_call() -> None:
    store, state = setup_state()
    observation_id = ObservationId("observation")
    policy = ScriptedDecisionTriggerPolicy({observation_id: DecisionTriggerResult.CONTINUE})
    provider = ScriptedDecisionProvider({})
    branch_id = state.position.branch_id

    prepared = prepare_observation_transition(
        policy,
        state,
        ObservationProposal(observation_id, EntityId("actor"), {"signal": "passive"}),
        None,
        None,
        TransitionRef(branch_id, TransitionId("perception")),
        (EventId("observation-event"),),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
        causation_refs=(CauseRef("event", "source-event"),),
    )

    assert [event.event_type for event in prepared.transition.events] == [OBSERVATION_CREATED]
    assert prepared.transition.events[0].causation_refs == (CauseRef("event", "source-event"),)
    assert len(policy.requests) == 1
    assert provider.requests == ()


def test_triggered_point_commits_before_provider_and_request_is_actor_relative() -> None:
    store, state = setup_state(with_plan=True)
    branch_id = state.position.branch_id
    observation_id = ObservationId("observation")
    point_id = DecisionPointId("point")
    subject = PlanRef(PlanId("plan"), 1)
    policy = ScriptedDecisionTriggerPolicy(
        {
            observation_id: DecisionPointProposal(
                DecisionPointReason.MATERIAL_OBSERVATION,
                DecisionPointScope.BOUNDED,
                frozenset({observation_id}),
                subject,
            )
        }
    )
    prepared = prepare_observation_transition(
        policy,
        state,
        ObservationProposal(observation_id, EntityId("actor"), {"signal": "material"}),
        subject,
        point_id,
        TransitionRef(branch_id, TransitionId("perception")),
        (EventId("observation-event"), EventId("point-event")),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )

    assert [event.event_type for event in prepared.transition.events] == [
        OBSERVATION_CREATED,
        DECISION_POINT_CREATED,
    ]
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    state = replay_branch(store, store.head_position(branch_id))
    request = build_decision_request(state, point_id)

    assert isinstance(request, DecisionRequest)
    assert tuple(item.observation_id for item in request.observations) == (observation_id,)
    assert request.subject_plan is state.execution.plans[subject]
    assert not hasattr(request, "state")
    assert not hasattr(request, "jobs")


def test_invalid_trigger_references_are_integrity_failures() -> None:
    store, state = setup_state()
    observation_id = ObservationId("observation")
    policy = ScriptedDecisionTriggerPolicy(
        {
            observation_id: DecisionPointProposal(
                DecisionPointReason.MATERIAL_OBSERVATION,
                DecisionPointScope.FULL,
                frozenset({ObservationId("unavailable")}),
            )
        }
    )
    branch_id = state.position.branch_id

    with pytest.raises(DecisionTriggerIntegrityError, match="actor cognition"):
        prepare_observation_transition(
            policy,
            state,
            ObservationProposal(observation_id, EntityId("actor"), {}),
            None,
            DecisionPointId("point"),
            TransitionRef(branch_id, TransitionId("invalid-trigger")),
            (EventId("observation-event"), EventId("point-event")),
            base_history=store.read_visible_transitions(store.head_position(branch_id)),
        )


@pytest.mark.parametrize(
    "with_plan,subject,proposal,expected_event",
    [
        (
            False,
            None,
            DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                proposed_plan(plan_id="adopted", step_id="adopted-step"),
            ),
            PLAN_CREATED,
        ),
        (
            True,
            PlanRef(PlanId("plan"), 1),
            DecisionProposal(
                DecisionOutcomeKind.REVISE_PLAN,
                proposed_plan(version=2, step_id="revised-step"),
            ),
            PLAN_REVISED,
        ),
        (
            True,
            PlanRef(PlanId("plan"), 1),
            DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                proposed_plan(
                    plan_id="replacement",
                    step_id="replacement-step",
                    replaces=PlanRef(PlanId("plan"), 1),
                ),
            ),
            PLAN_REPLACED,
        ),
    ],
)
def test_plan_decisions_atomically_materialize_existing_plan_events(
    with_plan: bool,
    subject: PlanRef | None,
    proposal: DecisionProposal,
    expected_event: str,
) -> None:
    store, state = setup_state(with_plan=with_plan)
    state = add_point(store, state, subject=subject)
    branch_id = state.position.branch_id
    provider = ScriptedDecisionProvider({DecisionPointId("point"): proposal})
    prepared = prepare_decision_transition(
        provider,
        state,
        DecisionPointId("point"),
        TransitionRef(branch_id, TransitionId("decision")),
        (EventId("decision-event"), EventId("plan-event")),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )

    assert [event.event_type for event in prepared.transition.events] == [
        DECISION_RECORDED,
        expected_event,
    ]
    assert prepared.transition.events[1].causation_refs == (CauseRef("event", "decision-event"),)
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    replayed = replay_branch(store, store.head_position(branch_id))

    decision = replayed.cognition.decisions[DecisionPointId("point")]
    assert decision.outcome.resulting_plan_ref == proposal.proposed_plan.ref  # type: ignore[union-attr]
    assert proposal.proposed_plan.ref in replayed.execution.plans  # type: ignore[union-attr]


def test_continue_plan_and_bounded_reaction_create_no_plan_events() -> None:
    store, state = setup_state(with_plan=True)
    subject = PlanRef(PlanId("plan"), 1)
    state = add_point(store, state, subject=subject, point_id="continue")
    branch_id = state.position.branch_id
    continuing = prepare_decision_transition(
        ScriptedDecisionProvider(
            {DecisionPointId("continue"): DecisionProposal(DecisionOutcomeKind.CONTINUE_PLAN)}
        ),
        state,
        DecisionPointId("continue"),
        TransitionRef(branch_id, TransitionId("continue-decision")),
        (EventId("continue-event"),),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    assert [event.event_type for event in continuing.transition.events] == [DECISION_RECORDED]
    committed = store.commit_transition(
        continuing.transition, expected_head=continuing.expected_head
    )
    state = replay_branch(store, HistoryPosition(branch_id, committed.transition_ref))
    state = add_point(store, state, point_id="bounded")
    bounded = prepare_decision_transition(
        ScriptedDecisionProvider(
            {
                DecisionPointId("bounded"): DecisionProposal(
                    DecisionOutcomeKind.BOUNDED_REACTION,
                    bounded_reaction=BoundedReaction("Reply", {"message": "yes"}),
                )
            }
        ),
        state,
        DecisionPointId("bounded"),
        TransitionRef(branch_id, TransitionId("bounded-decision")),
        (EventId("bounded-event"),),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    store.commit_transition(bounded.transition, expected_head=bounded.expected_head)
    state = replay_branch(store, store.head_position(branch_id))

    outcome = state.cognition.decisions[DecisionPointId("bounded")].outcome
    assert isinstance(outcome, BoundedReactionDecision)
    assert outcome.bounded_reaction.content == {"message": "yes"}
    assert len(state.execution.plans) == 1


@dataclass
class InvalidProvider:
    value: object
    calls: int = 0

    def decide(self, request: DecisionRequest, /) -> object:
        self.calls += 1
        return self.value


def test_provider_failure_malformed_output_and_invalid_plan_commit_nothing() -> None:
    store, state = setup_state()
    state = add_point(store, state)
    branch_id = state.position.branch_id
    initial_history = store.read_visible_transitions(store.head_position(branch_id))

    with pytest.raises(DeterministicDecisionIntegrityError, match="invalid output"):
        prepare_decision_transition(
            InvalidProvider(object()),  # type: ignore[arg-type]
            state,
            DecisionPointId("point"),
            TransitionRef(branch_id, TransitionId("malformed")),
            (EventId("malformed-event"),),
            base_history=initial_history,
        )
    invalid_plan = DecisionProposal(
        DecisionOutcomeKind.REPLACE_PLAN,
        proposed_plan(actor_id="other", plan_id="invalid"),
    )
    with pytest.raises(DeterministicDecisionIntegrityError, match="invalid proposal"):
        prepare_decision_transition(
            ScriptedDecisionProvider({DecisionPointId("point"): invalid_plan}),
            state,
            DecisionPointId("point"),
            TransitionRef(branch_id, TransitionId("invalid-plan")),
            (EventId("invalid-decision"), EventId("invalid-plan")),
            base_history=initial_history,
        )

    assert store.read_visible_transitions(store.head_position(branch_id)) == initial_history


def test_missing_script_is_explicit_and_duplicate_decision_is_rejected_before_provider() -> None:
    store, state = setup_state()
    state = add_point(store, state)
    branch_id = state.position.branch_id
    with pytest.raises(DeterministicDecisionIntegrityError, match="failed"):
        prepare_decision_transition(
            ScriptedDecisionProvider({}),
            state,
            DecisionPointId("point"),
            TransitionRef(branch_id, TransitionId("missing")),
            (EventId("missing-event"),),
            base_history=store.read_visible_transitions(store.head_position(branch_id)),
        )

    provider = ScriptedDecisionProvider(
        {
            DecisionPointId("point"): DecisionProposal(
                DecisionOutcomeKind.BOUNDED_REACTION,
                bounded_reaction=BoundedReaction("Wait"),
            )
        }
    )
    prepared = prepare_decision_transition(
        provider,
        state,
        DecisionPointId("point"),
        TransitionRef(branch_id, TransitionId("accepted")),
        (EventId("accepted-event"),),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    resolved = replay_branch(store, store.head_position(branch_id))
    calls = len(provider.requests)

    with pytest.raises(CognitionValidationError, match="already resolved"):
        prepare_decision_transition(
            provider,
            resolved,
            DecisionPointId("point"),
            TransitionRef(branch_id, TransitionId("duplicate")),
            (EventId("duplicate-event"),),
            base_history=store.read_visible_transitions(store.head_position(branch_id)),
        )
    assert len(provider.requests) == calls


def test_stale_expected_head_rejects_prepared_decision_without_consuming_ids() -> None:
    store, state = setup_state()
    state = add_point(store, state)
    branch_id = state.position.branch_id
    prepared = prepare_decision_transition(
        ScriptedDecisionProvider(
            {
                DecisionPointId("point"): DecisionProposal(
                    DecisionOutcomeKind.BOUNDED_REACTION,
                    bounded_reaction=BoundedReaction("Wait"),
                )
            }
        ),
        state,
        DecisionPointId("point"),
        TransitionRef(branch_id, TransitionId("decision")),
        (EventId("reusable-event"),),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    store.commit_transition(
        transition_to_commit(
            "root",
            "advance",
            1,
            [
                event_to_commit(
                    "advance",
                    event_type=ENTITY_UPDATED,
                    payload={"entity_id": "actor", "properties_after": {"advanced": True}},
                )
            ],
        )
    )

    with pytest.raises(StaleHistoryError):
        store.commit_transition(prepared.transition, expected_head=prepared.expected_head)

    replacement = prepare_decision_transition(
        ScriptedDecisionProvider(
            {
                DecisionPointId("point"): DecisionProposal(
                    DecisionOutcomeKind.BOUNDED_REACTION,
                    bounded_reaction=BoundedReaction("Wait"),
                )
            }
        ),
        replay_branch(store, store.head_position(branch_id)),
        DecisionPointId("point"),
        TransitionRef(branch_id, TransitionId("decision")),
        (EventId("reusable-event"),),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    store.commit_transition(replacement.transition, expected_head=replacement.expected_head)


class StaticCheckpointLoader:
    def __init__(self, checkpoint: StateCheckpoint) -> None:
        self.checkpoint = checkpoint

    def load_checkpoint(self, target: HistoryPosition, /) -> StateCheckpoint:
        return self.checkpoint


def test_forked_pending_point_decides_independently_and_replay_never_calls_provider() -> None:
    store, state = setup_state()
    state = add_point(store, state)
    root_id = state.position.branch_id
    point_position = store.head_position(root_id)
    child_id = stable_id(BranchId, "child")
    store.fork_branch(child_id, point_position)

    root_provider = ScriptedDecisionProvider(
        {
            DecisionPointId("point"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                proposed_plan(plan_id="root-plan", step_id="root-step"),
            )
        }
    )
    root_prepared = prepare_decision_transition(
        root_provider,
        state,
        DecisionPointId("point"),
        TransitionRef(root_id, TransitionId("root-decision")),
        (EventId("root-decision-event"), EventId("root-plan-event")),
        base_history=store.read_visible_transitions(point_position),
    )
    root_decision = store.commit_transition(
        root_prepared.transition, expected_head=root_prepared.expected_head
    )

    child_state = replay_branch(store, store.head_position(child_id))
    child_provider = ScriptedDecisionProvider(
        {
            DecisionPointId("point"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                proposed_plan(plan_id="child-plan", step_id="child-step"),
            )
        }
    )
    child_prepared = prepare_decision_transition(
        child_provider,
        child_state,
        DecisionPointId("point"),
        TransitionRef(child_id, TransitionId("child-decision")),
        (EventId("child-decision-event"), EventId("child-plan-event")),
        base_history=store.read_visible_transitions(store.head_position(child_id)),
    )
    store.commit_transition(child_prepared.transition, expected_head=child_prepared.expected_head)

    provider_calls = (len(root_provider.requests), len(child_provider.requests))
    root_replayed = replay_branch(store, store.head_position(root_id))
    child_replayed = replay_branch(store, store.head_position(child_id))
    assert PlanRef(PlanId("root-plan"), 1) in root_replayed.execution.plans
    assert PlanRef(PlanId("child-plan"), 1) in child_replayed.execution.plans
    assert PlanRef(PlanId("child-plan"), 1) not in root_replayed.execution.plans
    assert PlanRef(PlanId("root-plan"), 1) not in child_replayed.execution.plans
    assert (len(root_provider.requests), len(child_provider.requests)) == provider_calls

    checkpoint = StateCheckpoint(point_position, state)
    assert (
        replay_branch(
            store,
            HistoryPosition(root_id, root_decision.transition_ref),
            StaticCheckpointLoader(checkpoint),
        )
        == root_replayed
    )

    post_decision_id = stable_id(BranchId, "post-decision")
    store.fork_branch(post_decision_id, store.head_position(root_id))
    inherited = replay_branch(store, store.head_position(post_decision_id))
    assert DecisionPointId("point") in inherited.cognition.decisions
    assert PlanRef(PlanId("root-plan"), 1) in inherited.execution.plans
    assert (len(root_provider.requests), len(child_provider.requests)) == provider_calls
