# SPDX-License-Identifier: GPL-3.0-only

import asyncio
from dataclasses import dataclass, field

import pytest

from grass.core import (
    BoundedReaction,
    BranchId,
    DecisionAcquisitionFailure,
    DecisionAcquisitionSuccess,
    DecisionInvocationResult,
    DecisionOutcomeKind,
    DecisionOutputError,
    DecisionPointId,
    DecisionProposal,
    DecisionProviderBinding,
    DecisionProviderRouting,
    EntityId,
    EventId,
    InMemoryEventStore,
    LogicalTime,
    ProviderBindingConfiguration,
    ProviderBindingId,
    ProviderExecutionLocation,
    ProviderFailureKind,
    ProviderInvocationError,
    ProviderInvocationReceipt,
    SimulationState,
    StaleDecisionContextError,
    TransitionId,
    TransitionRef,
    acquire_decisions,
    capture_decision_invocation_context,
    prepare_invoked_decision_transition,
    replay_branch,
)
from grass.core.cognition_events import DECISION_POINT_CREATED, DECISION_RECORDED
from grass.core.world_events import ENTITY_CREATED
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def configuration() -> ProviderBindingConfiguration:
    bindings = {
        ProviderBindingId("a-binding"): DecisionProviderBinding(
            ProviderBindingId("a-binding"),
            "a-invoker",
            ProviderExecutionLocation.SERVER_MANAGED,
        ),
        ProviderBindingId("b-binding"): DecisionProviderBinding(
            ProviderBindingId("b-binding"),
            "b-invoker",
            ProviderExecutionLocation.SERVER_MANAGED,
        ),
    }
    return ProviderBindingConfiguration(
        DecisionProviderRouting(
            ProviderBindingId("a-binding"),
            actor_bindings={EntityId("b"): ProviderBindingId("b-binding")},
        ),
        bindings,
        {},
    )


def state_with_two_points() -> tuple[InMemoryEventStore, SimulationState]:
    store = rooted_store("root")
    store.commit_transition(
        transition_to_commit(
            "root",
            "genesis",
            1,
            [
                event_to_commit(
                    "a",
                    event_type=ENTITY_CREATED,
                    payload={"entity_id": "a", "entity_type": "Person", "properties": {}},
                ),
                event_to_commit(
                    "b",
                    event_type=ENTITY_CREATED,
                    payload={"entity_id": "b", "entity_type": "Person", "properties": {}},
                ),
            ],
        )
    )
    store.commit_transition(
        transition_to_commit(
            "root",
            "points",
            1,
            [
                event_to_commit(
                    "point-b",
                    event_type=DECISION_POINT_CREATED,
                    payload={
                        "decision_point_id": "point-b",
                        "actor_id": "b",
                        "reason": "PLAN_REQUIRED",
                        "scope": "FULL",
                        "observation_ids": [],
                        "subject_plan_ref": None,
                    },
                ),
                event_to_commit(
                    "point-a",
                    event_type=DECISION_POINT_CREATED,
                    payload={
                        "decision_point_id": "point-a",
                        "actor_id": "a",
                        "reason": "PLAN_REQUIRED",
                        "scope": "FULL",
                        "observation_ids": [],
                        "subject_plan_ref": None,
                    },
                ),
            ],
        )
    )
    branch_id = stable_id(BranchId, "root")
    return store, replay_branch(store, store.head_position(branch_id))


@dataclass
class ConcurrentProbe:
    started: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    both_started: asyncio.Event = field(default_factory=asyncio.Event)
    b_completed: asyncio.Event = field(default_factory=asyncio.Event)


class ProbeInvoker:
    def __init__(self, actor: str, binding_id: ProviderBindingId, probe: ConcurrentProbe) -> None:
        self.actor = actor
        self.binding_id = binding_id
        self.probe = probe

    async def invoke(self, request: object, /) -> DecisionInvocationResult:
        self.probe.started.append(self.actor)
        if len(self.probe.started) == 2:
            self.probe.both_started.set()
        await asyncio.wait_for(self.probe.both_started.wait(), timeout=1)
        if self.actor == "a":
            await asyncio.wait_for(self.probe.b_completed.wait(), timeout=1)
        self.probe.completed.append(self.actor)
        if self.actor == "b":
            self.probe.b_completed.set()
        return DecisionInvocationResult(
            DecisionProposal(
                DecisionOutcomeKind.BOUNDED_REACTION,
                bounded_reaction=BoundedReaction(f"{self.actor} waits"),
            ),
            ProviderInvocationReceipt(
                self.binding_id,
                None,
                ProviderExecutionLocation.SERVER_MANAGED,
                f"{self.actor}-invoker",
                f"provider-{self.actor}",
            ),
        )


def test_concurrent_acquisition_ignores_completion_order_and_revalidates_each_commit() -> None:
    store, state = state_with_two_points()
    config = configuration()
    branch_id = stable_id(BranchId, "root")
    position = store.head_position(branch_id)
    contexts = (
        capture_decision_invocation_context(
            state,
            DecisionPointId("point-b"),
            config,
            position,
            base_history=store.read_visible_transitions(position),
        ),
        capture_decision_invocation_context(
            state,
            DecisionPointId("point-a"),
            config,
            position,
            base_history=store.read_visible_transitions(position),
        ),
    )
    probe = ConcurrentProbe()
    outcomes = asyncio.run(
        acquire_decisions(
            contexts,
            {
                ProviderBindingId("a-binding"): ProbeInvoker(
                    "a", ProviderBindingId("a-binding"), probe
                ),
                ProviderBindingId("b-binding"): ProbeInvoker(
                    "b", ProviderBindingId("b-binding"), probe
                ),
            },
        )
    )

    assert probe.completed == ["b", "a"]
    successes = tuple(item for item in outcomes if type(item) is DecisionAcquisitionSuccess)
    assert [item.context.decision_point.actor_id.value for item in successes] == ["a", "b"]

    current = state
    for index, acquisition in enumerate(successes, start=1):
        prepared = prepare_invoked_decision_transition(
            acquisition,
            current,
            config,
            TransitionRef(branch_id, TransitionId(f"decision-{index}")),
            (EventId(f"decision-{index}"),),
            base_history=store.read_visible_transitions(store.head_position(branch_id)),
        )
        store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
        current = replay_branch(store, store.head_position(branch_id))

    events = tuple(
        event
        for transition in store.read_visible_transitions(store.head_position(branch_id))
        for event in transition.events
    )
    assert [event.event_type for event in events[-2:]] == [
        DECISION_RECORDED,
        DECISION_RECORDED,
    ]
    assert probe.started == ["a", "b"]


class FailingInvoker:
    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, request: object, /) -> DecisionInvocationResult:
        self.calls += 1
        raise ProviderInvocationError(ProviderFailureKind.AUTHENTICATION, "authentication failed")


def test_provider_failure_has_no_fallback_and_commits_nothing() -> None:
    store, state = state_with_two_points()
    config = configuration()
    branch_id = stable_id(BranchId, "root")
    context = capture_decision_invocation_context(
        state,
        DecisionPointId("point-a"),
        config,
        store.head_position(branch_id),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    invoker = FailingInvoker()
    before = store.read_visible_transitions(store.head_position(branch_id))

    outcomes = asyncio.run(acquire_decisions((context,), {ProviderBindingId("a-binding"): invoker}))

    assert len(outcomes) == 1
    assert type(outcomes[0]) is DecisionAcquisitionFailure
    assert isinstance(outcomes[0].error, ProviderInvocationError)
    assert outcomes[0].error.kind is ProviderFailureKind.AUTHENTICATION
    assert invoker.calls == 1
    assert store.read_visible_transitions(store.head_position(branch_id)) == before


class CancelledInvoker:
    async def invoke(self, request: object, /) -> DecisionInvocationResult:
        raise asyncio.CancelledError


def test_invocation_cancellation_is_not_reported_as_provider_failure() -> None:
    store, state = state_with_two_points()
    config = configuration()
    branch_id = stable_id(BranchId, "root")
    context = capture_decision_invocation_context(
        state,
        DecisionPointId("point-a"),
        config,
        store.head_position(branch_id),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            acquire_decisions((context,), {ProviderBindingId("a-binding"): CancelledInvoker()})
        )


def test_resolved_or_changed_context_cannot_prepare_stale_result() -> None:
    store, state = state_with_two_points()
    config = configuration()
    branch_id = stable_id(BranchId, "root")
    context = capture_decision_invocation_context(
        state,
        DecisionPointId("point-a"),
        config,
        store.head_position(branch_id),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    probe = ConcurrentProbe()
    probe.both_started.set()
    probe.b_completed.set()
    result = asyncio.run(
        ProbeInvoker("a", ProviderBindingId("a-binding"), probe).invoke(context.request)
    )
    acquisition = DecisionAcquisitionSuccess(context, result)
    competing = transition_to_commit(
        "root",
        "competing-decision",
        1,
        [
            event_to_commit(
                "competing-decision",
                event_type=DECISION_RECORDED,
                payload={
                    "decision_point_id": "point-a",
                    "outcome": {
                        "kind": "BOUNDED_REACTION",
                        "bounded_reaction": {"intent_description": "Other", "content": None},
                    },
                },
            )
        ],
    )
    store.commit_transition(competing)
    current = replay_branch(store, store.head_position(branch_id))

    with pytest.raises(StaleDecisionContextError):
        prepare_invoked_decision_transition(
            acquisition,
            current,
            config,
            TransitionRef(branch_id, TransitionId("stale")),
            (EventId("stale"),),
            base_history=store.read_visible_transitions(store.head_position(branch_id)),
        )


def test_unchanged_request_prepares_at_current_logical_time() -> None:
    store, state = state_with_two_points()
    config = configuration()
    branch_id = stable_id(BranchId, "root")
    position = store.head_position(branch_id)
    context = capture_decision_invocation_context(
        state,
        DecisionPointId("point-a"),
        config,
        position,
        base_history=store.read_visible_transitions(position),
    )
    result = DecisionInvocationResult(
        DecisionProposal(
            DecisionOutcomeKind.BOUNDED_REACTION,
            bounded_reaction=BoundedReaction("Wait"),
        ),
        ProviderInvocationReceipt(
            ProviderBindingId("a-binding"),
            None,
            ProviderExecutionLocation.SERVER_MANAGED,
            "a-invoker",
            "scripted",
        ),
    )
    store.commit_transition(
        transition_to_commit(
            "root",
            "unrelated",
            2,
            [
                event_to_commit(
                    "unrelated",
                    event_type=ENTITY_CREATED,
                    payload={
                        "entity_id": "unrelated",
                        "entity_type": "Artifact",
                        "properties": {},
                    },
                )
            ],
        )
    )
    current_position = store.head_position(branch_id)
    current = replay_branch(store, current_position)

    prepared = prepare_invoked_decision_transition(
        DecisionAcquisitionSuccess(context, result),
        current,
        config,
        TransitionRef(branch_id, TransitionId("current-time")),
        (EventId("current-time"),),
        base_history=store.read_visible_transitions(current_position),
    )

    assert prepared.transition.logical_time == LogicalTime(2)


def test_receipt_provenance_is_immutable_and_secret_free() -> None:
    store, state = state_with_two_points()
    config = configuration()
    branch_id = stable_id(BranchId, "root")
    context = capture_decision_invocation_context(
        state,
        DecisionPointId("point-a"),
        config,
        store.head_position(branch_id),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    result = DecisionInvocationResult(
        DecisionProposal(
            DecisionOutcomeKind.BOUNDED_REACTION,
            bounded_reaction=BoundedReaction("Wait"),
        ),
        ProviderInvocationReceipt(
            ProviderBindingId("a-binding"),
            None,
            ProviderExecutionLocation.SERVER_MANAGED,
            "a-invoker",
            "scripted",
            provider_request_id="safe-request-id",
        ),
    )
    prepared = prepare_invoked_decision_transition(
        DecisionAcquisitionSuccess(context, result),
        state,
        config,
        TransitionRef(branch_id, TransitionId("receipt")),
        (EventId("receipt"),),
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
    )
    provenance = prepared.transition.events[0].provenance

    assert provenance.source_ref is not None
    assert provenance.source_ref.value == "a-binding"
    assert provenance.metadata["provider_request_id"] == "safe-request-id"
    assert "credential" not in repr(provenance).lower()
    assert "authorization" not in repr(provenance).lower()
    with pytest.raises(TypeError):
        provenance.metadata["provider"] = "changed"  # type: ignore[index]


def test_pending_decision_can_be_invoked_on_child_but_result_cannot_cross_branches() -> None:
    store, root_state = state_with_two_points()
    config = configuration()
    root_id = stable_id(BranchId, "root")
    root_position = store.head_position(root_id)
    child_id = stable_id(BranchId, "child")
    store.fork_branch(child_id, root_position)
    child_position = store.head_position(child_id)
    child_state = replay_branch(store, child_position)

    child_context = capture_decision_invocation_context(
        child_state,
        DecisionPointId("point-a"),
        config,
        child_position,
        base_history=store.read_visible_transitions(child_position),
    )
    root_context = capture_decision_invocation_context(
        root_state,
        DecisionPointId("point-a"),
        config,
        root_position,
        base_history=store.read_visible_transitions(root_position),
    )
    result = DecisionInvocationResult(
        DecisionProposal(
            DecisionOutcomeKind.BOUNDED_REACTION,
            bounded_reaction=BoundedReaction("Wait"),
        ),
        ProviderInvocationReceipt(
            ProviderBindingId("a-binding"),
            None,
            ProviderExecutionLocation.SERVER_MANAGED,
            "a-invoker",
            "scripted",
        ),
    )

    assert child_context.base_position.branch_id == child_id
    with pytest.raises(StaleDecisionContextError, match="another branch"):
        prepare_invoked_decision_transition(
            DecisionAcquisitionSuccess(root_context, result),
            child_state,
            config,
            TransitionRef(child_id, TransitionId("cross-branch")),
            (EventId("cross-branch"),),
            base_history=store.read_visible_transitions(child_position),
        )


def test_receipt_must_match_execution_location_and_invoker() -> None:
    store, state = state_with_two_points()
    config = configuration()
    branch_id = stable_id(BranchId, "root")
    position = store.head_position(branch_id)
    context = capture_decision_invocation_context(
        state,
        DecisionPointId("point-a"),
        config,
        position,
        base_history=store.read_visible_transitions(position),
    )
    result = DecisionInvocationResult(
        DecisionProposal(
            DecisionOutcomeKind.BOUNDED_REACTION,
            bounded_reaction=BoundedReaction("Wait"),
        ),
        ProviderInvocationReceipt(
            ProviderBindingId("a-binding"),
            None,
            ProviderExecutionLocation.CLIENT_MANAGED,
            "wrong-invoker",
            "scripted",
        ),
    )

    with pytest.raises(DecisionOutputError):
        prepare_invoked_decision_transition(
            DecisionAcquisitionSuccess(context, result),
            state,
            config,
            TransitionRef(branch_id, TransitionId("mismatch")),
            (EventId("mismatch"),),
            base_history=store.read_visible_transitions(position),
        )
