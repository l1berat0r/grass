# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import pytest

from grass.core import (
    ActionPrimitive,
    BinaryProgress,
    BranchId,
    DecisionInvocationResult,
    DecisionOutcomeKind,
    DecisionPointId,
    DecisionPointProposal,
    DecisionPointReason,
    DecisionPointScope,
    DecisionProposal,
    DecisionProviderBinding,
    DecisionProviderRouting,
    DecisionRequest,
    DecisionTriggerContext,
    DecisionTriggerPolicy,
    DecisionTriggerResult,
    EntityId,
    EventId,
    EventToCommit,
    InMemoryEventStore,
    JobId,
    JobStatus,
    LogicalDuration,
    LogicalTime,
    ObservationId,
    PlanId,
    PlanStep,
    PlanStepId,
    PlanStepOrigin,
    PlanStepRef,
    ProgressAnchor,
    ProposedPlan,
    Provenance,
    ProviderBindingConfiguration,
    ProviderBindingError,
    ProviderBindingId,
    ProviderExecutionLocation,
    ProviderInvocationReceipt,
    ResolutionOutcome,
    ResolutionProposal,
    ResolutionRequest,
    ScenarioOccurrenceResolutionProposal,
    ScenarioOccurrenceResolutionRequest,
    ScheduledResolution,
    ScheduleProjector,
    ScriptedDecisionProvider,
    ScriptedDecisionTriggerPolicy,
    SimulationRunConfig,
    SubjectResolutionOutcome,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    UpdateJobEffect,
    WorldDefinition,
    WorldResolutionProvider,
    build_genesis_transition,
    load_world_definition,
    prepare_decision_point_transition,
    replay_branch,
)
from grass.core.cognition_events import DECISION_POINT_CREATED, OBSERVATION_CREATED
from grass.core.decision_invocations import DecisionInvoker
from grass.core.event_store import StaleHistoryError
from grass.core.events import CommittedTransition
from grass.core.state import SimulationState
from grass.core.world_events import ENTITY_CREATED, ENTITY_UPDATED
from grass.providers import SyncDecisionProviderAdapter
from grass.runtime import (
    JobStartPolicy,
    JobStartProposal,
    PerceptionCandidate,
    PerceptionProjector,
    ReadyPlanStep,
    RuntimeStopReason,
    RuntimeWorkKind,
    SimulationEngine,
    UnsupportedRuntimeFrontierError,
    UnsupportedRuntimeStateError,
)

MINUTE = 60_000_000_000
ROOT = BranchId("root")
ACTOR = EntityId("actor")
OTHER_ACTOR = EntityId("other-actor")
BINDING_ID = ProviderBindingId("decision")


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def _next(self, kind: str) -> str:
        self.value += 1
        return f"runtime:{kind}:{self.value}"

    def transition_id(self, branch_id: BranchId, work_kind: RuntimeWorkKind, /) -> TransitionId:
        del branch_id
        return TransitionId(self._next(work_kind.value.lower()))

    def event_ids(self, count: int, /) -> tuple[EventId, ...]:
        return tuple(EventId(self._next("event")) for _ in range(count))

    def job_id(self, plan_step_ref: PlanStepRef, /) -> JobId:
        return JobId(self._next(plan_step_ref.step_id.value))

    def observation_id(self, source_event_id: EventId, actor_id: EntityId, /) -> ObservationId:
        del source_event_id, actor_id
        return ObservationId(self._next("observation"))

    def decision_point_id(self, observation_id: ObservationId, /) -> DecisionPointId:
        del observation_id
        return DecisionPointId(self._next("decision-point"))


class NoPerception:
    def project(
        self,
        source_transition: CommittedTransition,
        state_after_source: SimulationState,
        /,
    ) -> tuple[PerceptionCandidate, ...]:
        del source_transition, state_after_source
        return ()


class GenesisPerception:
    def __init__(self, actor_id: EntityId = ACTOR) -> None:
        self.actor_id = actor_id

    def project(
        self,
        source_transition: CommittedTransition,
        state_after_source: SimulationState,
        /,
    ) -> tuple[PerceptionCandidate, ...]:
        del state_after_source
        return tuple(
            PerceptionCandidate(event.event_id, self.actor_id, {"event": event.event_type})
            for event in source_transition.events
            if event.event_type == ENTITY_CREATED
            and event.payload["entity_id"] == self.actor_id.value
        )


class ContinueTrigger:
    def evaluate(self, context: DecisionTriggerContext, /) -> DecisionTriggerResult:
        del context
        return DecisionTriggerResult.CONTINUE


class DecisionPointTrigger:
    def evaluate(self, context: DecisionTriggerContext, /) -> DecisionPointProposal:
        return DecisionPointProposal(
            DecisionPointReason.MATERIAL_OBSERVATION,
            DecisionPointScope.FULL,
            frozenset({context.observation.observation_id}),
        )


class NoSchedule:
    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> tuple[ScheduledResolution[JobId], ...]:
        del state, current_time, progress_anchors
        return ()


class CompletionSchedule:
    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> tuple[ScheduledResolution[JobId], ...]:
        del state, current_time
        return tuple(
            ScheduledResolution(
                anchor.anchor_time + LogicalDuration(5 * MINUTE),
                "JOB_EXPECTED_COMPLETION",
                job_id,
            )
            for job_id, anchor in progress_anchors.items()
        )


class NoJobStarts:
    def propose(
        self, ready_step: ReadyPlanStep, state: SimulationState, /
    ) -> JobStartProposal | None:
        del ready_step, state
        return None


class BinaryJobStarts:
    def propose(self, ready_step: ReadyPlanStep, state: SimulationState, /) -> JobStartProposal:
        del ready_step, state
        return JobStartProposal(BinaryProgress(False), activate=True)


class FailingWorldResolver:
    def resolve(self, request: ResolutionRequest, /) -> ResolutionProposal:
        del request
        raise AssertionError("world resolver must not be invoked")


class CompletionResolver:
    def __init__(self) -> None:
        self.requests: list[ResolutionRequest] = []

    def resolve(self, request: ResolutionRequest, /) -> ResolutionProposal:
        self.requests.append(request)
        outcomes = tuple(
            SubjectResolutionOutcome(subject.job_id, ResolutionOutcome.SUCCESS)
            for subject in request.subjects
        )
        effects = tuple(
            UpdateJobEffect(
                subject.job_id,
                status_after=JobStatus.COMPLETED,
                progress_after=BinaryProgress(True),
            )
            for subject in request.subjects
        )
        return ResolutionProposal(outcomes, effects)


class HeadAdvancingInvoker:
    def __init__(self, store: InMemoryEventStore) -> None:
        self.store = store

    async def invoke(self, request: DecisionRequest, /) -> DecisionInvocationResult:
        head = self.store.head_position(ROOT)
        self.store.commit_transition(
            TransitionToCommit(
                TransitionRef(ROOT, TransitionId("concurrent-update")),
                LogicalTime(0),
                (
                    EventToCommit(
                        EventId("concurrent-update"),
                        ENTITY_UPDATED,
                        1,
                        {"entity_id": ACTOR.value, "properties_after": {"changed": True}},
                        Provenance("ENGINE"),
                    ),
                ),
            ),
            expected_head=head,
        )
        return DecisionInvocationResult(
            DecisionProposal(DecisionOutcomeKind.REPLACE_PLAN, _plan(("wait",))),
            ProviderInvocationReceipt(
                BINDING_ID,
                None,
                ProviderExecutionLocation.SERVER_MANAGED,
                "scripted",
                "scripted",
            ),
        )


class NoScenarioResolver:
    def resolve(
        self, request: ScenarioOccurrenceResolutionRequest, /
    ) -> ScenarioOccurrenceResolutionProposal:
        del request
        return ScenarioOccurrenceResolutionProposal()


def _definition(
    *,
    occurrence_time: int | None = None,
    actor_ids: Sequence[str] = (ACTOR.value,),
) -> WorldDefinition:
    rules: list[dict[str, object]] = []
    if occurrence_time is not None:
        rules.append(
            {
                "rule_id": "occurrence",
                "trigger": {"kind": "AT_TIME", "logical_time": occurrence_time},
            }
        )
    return load_world_definition(
        {
            "world_definition_id": "runtime-world",
            "version": "1.0",
            "schema_version": 2,
            "vocabulary": {
                "entity_types": ["Person"],
                "relation_types": [],
                "resource_types": [],
                "state_variable_types": [],
            },
            "initial_conditions": {
                "logical_time": 0,
                "entities": [
                    {"entity_id": actor_id, "entity_type": "Person", "properties": {}}
                    for actor_id in actor_ids
                ],
                "relations": [],
                "resources": [],
                "state_variables": [],
            },
            "metadata": {},
            "scenario_event_rules": rules,
        }
    )


def _provider_configuration(
    location: ProviderExecutionLocation = ProviderExecutionLocation.SERVER_MANAGED,
) -> ProviderBindingConfiguration:
    binding = DecisionProviderBinding(BINDING_ID, "scripted", location)
    return ProviderBindingConfiguration(
        DecisionProviderRouting(BINDING_ID),
        {BINDING_ID: binding},
    )


def _store(definition: WorldDefinition, config: SimulationRunConfig) -> InMemoryEventStore:
    store = InMemoryEventStore()
    store.create_root_branch(ROOT)
    store.commit_transition(
        build_genesis_transition(
            definition,
            config,
            TransitionRef(ROOT, TransitionId("genesis")),
            tuple(
                EventId(f"genesis:{index}")
                for index in range(1 + len(definition.initial_conditions.entities))
            ),
        )
    )
    return store


def _plan(step_ids: Sequence[str]) -> ProposedPlan:
    steps = tuple(
        PlanStep(
            PlanStepId(step_id),
            ActionPrimitive.WAIT,
            None,
            {},
            {},
            frozenset(),
            PlanStepOrigin.ACTOR_INTENT,
        )
        for step_id in step_ids
    )
    return ProposedPlan(PlanId("plan"), 1, ACTOR, "Wait", steps, None)


def _add_plan_required_point(store: InMemoryEventStore) -> None:
    position = store.head_position(ROOT)
    state = replay_branch(store, position)
    prepared = prepare_decision_point_transition(
        state,
        ACTOR,
        DecisionPointId("plan-required"),
        DecisionPointProposal(
            DecisionPointReason.PLAN_REQUIRED,
            DecisionPointScope.FULL,
            frozenset(),
        ),
        TransitionRef(ROOT, TransitionId("plan-required")),
        EventId("plan-required"),
        base_history=store.read_visible_transitions(position),
    )
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)


def _engine(
    store: InMemoryEventStore,
    definition: WorldDefinition,
    config: SimulationRunConfig,
    *,
    schedule: ScheduleProjector[JobId] | None = None,
    resolver: WorldResolutionProvider | None = None,
    starts: JobStartPolicy | None = None,
    invokers: Mapping[ProviderBindingId, DecisionInvoker] | None = None,
    perception: PerceptionProjector | None = None,
    trigger: DecisionTriggerPolicy | None = None,
) -> SimulationEngine:
    return SimulationEngine(
        event_store=store,
        world_definition=definition,
        run_config=config,
        identity_source=SequentialIds(),
        schedule_projector=NoSchedule() if schedule is None else schedule,
        conflict_predicate=lambda _left, _right: False,
        world_resolution_provider=FailingWorldResolver() if resolver is None else resolver,
        scenario_occurrence_resolution_provider=NoScenarioResolver(),
        perception_projector=NoPerception() if perception is None else perception,
        decision_trigger_policy=(ScriptedDecisionTriggerPolicy({}) if trigger is None else trigger),
        decision_invokers={} if invokers is None else invokers,
        job_start_policy=NoJobStarts() if starts is None else starts,
    )


def test_advance_stabilizes_decision_plan_job_and_target_resolution() -> None:
    definition = _definition()
    bindings = _provider_configuration()
    config = SimulationRunConfig(definition.ref, bindings)
    store = _store(definition, config)
    _add_plan_required_point(store)
    provider = ScriptedDecisionProvider(
        {
            DecisionPointId("plan-required"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                _plan(("wait",)),
            )
        }
    )
    adapter = SyncDecisionProviderAdapter(
        provider,
        bindings.decision_bindings[BINDING_ID],
        provider_name="scripted",
    )
    resolver = CompletionResolver()
    engine = _engine(
        store,
        definition,
        config,
        schedule=CompletionSchedule(),
        resolver=resolver,
        starts=BinaryJobStarts(),
        invokers={BINDING_ID: adapter},
    )

    result = asyncio.run(engine.advance(ROOT, target_time=LogicalTime(5 * MINUTE)))

    assert result.stop_reason is RuntimeStopReason.TARGET_REACHED
    assert result.committed_steps == 3
    assert result.logical_time == LogicalTime(5 * MINUTE)
    state = replay_branch(store, store.head_position(ROOT))
    assert tuple(state.execution.jobs.values())[0].status is JobStatus.COMPLETED
    assert len(provider.requests) == 1
    assert len(resolver.requests) == 1
    with pytest.raises(ValueError, match="must not precede"):
        asyncio.run(engine.advance(ROOT, target_time=LogicalTime(0), max_steps=0))


def test_client_managed_decision_waits_without_local_invoker() -> None:
    definition = _definition()
    bindings = _provider_configuration(ProviderExecutionLocation.CLIENT_MANAGED)
    config = SimulationRunConfig(definition.ref, bindings)
    store = _store(definition, config)
    _add_plan_required_point(store)
    engine = _engine(store, definition, config)
    before = store.head_position(ROOT)

    waiting = asyncio.run(engine.step(ROOT))

    assert waiting.stop_reason is RuntimeStopReason.WAITING_FOR_DECISION
    assert waiting.waiting_decision_point_ids == (DecisionPointId("plan-required"),)
    assert store.head_position(ROOT) == before


def test_client_managed_decision_does_not_invoke_configured_invoker() -> None:
    definition = _definition()
    bindings = _provider_configuration(ProviderExecutionLocation.CLIENT_MANAGED)
    config = SimulationRunConfig(definition.ref, bindings)
    store = _store(definition, config)
    _add_plan_required_point(store)
    provider = ScriptedDecisionProvider(
        {
            DecisionPointId("plan-required"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                _plan(("wait",)),
            )
        }
    )
    adapter = SyncDecisionProviderAdapter(
        provider,
        bindings.decision_bindings[BINDING_ID],
        provider_name="scripted",
    )
    engine = _engine(store, definition, config, invokers={BINDING_ID: adapter})

    waiting = asyncio.run(engine.step(ROOT))

    assert waiting.stop_reason is RuntimeStopReason.WAITING_FOR_DECISION
    assert provider.requests == ()


def test_server_managed_decision_without_invoker_fails_explicitly() -> None:
    definition = _definition()
    bindings = _provider_configuration(ProviderExecutionLocation.SERVER_MANAGED)
    config = SimulationRunConfig(definition.ref, bindings)
    store = _store(definition, config)
    _add_plan_required_point(store)
    engine = _engine(store, definition, config)
    before = store.head_position(ROOT)

    with pytest.raises(ProviderBindingError, match="no DecisionInvoker"):
        asyncio.run(engine.step(ROOT))

    assert store.head_position(ROOT) == before


def test_server_managed_decision_with_invoker_commits_normally() -> None:
    definition = _definition()
    bindings = _provider_configuration(ProviderExecutionLocation.SERVER_MANAGED)
    config = SimulationRunConfig(definition.ref, bindings)
    store = _store(definition, config)
    _add_plan_required_point(store)
    provider = ScriptedDecisionProvider(
        {
            DecisionPointId("plan-required"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                _plan(("wait",)),
            )
        }
    )
    adapter = SyncDecisionProviderAdapter(
        provider,
        bindings.decision_bindings[BINDING_ID],
        provider_name="scripted",
    )
    engine = _engine(store, definition, config, invokers={BINDING_ID: adapter})

    result = asyncio.run(engine.step(ROOT))

    assert result.work_kind is RuntimeWorkKind.DECISION
    assert (
        DecisionPointId("plan-required")
        in replay_branch(store, store.head_position(ROOT)).cognition.decisions
    )
    assert len(provider.requests) == 1


def test_multiple_independent_job_components_publish_one_transition() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = _store(definition, config)
    point_config = _provider_configuration()
    configured = SimulationRunConfig(definition.ref, point_config)
    _add_plan_required_point(store)
    provider = ScriptedDecisionProvider(
        {
            DecisionPointId("plan-required"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                _plan(("one", "two")),
            )
        }
    )
    adapter = SyncDecisionProviderAdapter(
        provider,
        point_config.decision_bindings[BINDING_ID],
        provider_name="scripted",
    )
    resolver = CompletionResolver()
    engine = _engine(
        store,
        definition,
        configured,
        schedule=CompletionSchedule(),
        resolver=resolver,
        starts=BinaryJobStarts(),
        invokers={BINDING_ID: adapter},
    )

    assert asyncio.run(engine.step(ROOT)).work_kind is RuntimeWorkKind.DECISION
    assert asyncio.run(engine.step(ROOT)).work_kind is RuntimeWorkKind.JOB_START
    assert asyncio.run(engine.step(ROOT)).work_kind is RuntimeWorkKind.JOB_START
    before_resolution = store.head_position(ROOT)
    resolved = asyncio.run(engine.step(ROOT))

    assert resolved.work_kind is RuntimeWorkKind.JOB_RESOLUTION_FRONTIER
    assert resolved.position_before == before_resolution
    assert len(resolver.requests) == 2
    assert resolver.requests[0].base_history_position == before_resolution
    assert resolver.requests[1].base_history_position == before_resolution
    assert resolver.requests[0].state == resolver.requests[1].state
    assert resolved.committed_transition is not None
    assert len(resolved.committed_transition.events) == 6
    assert all(
        job.status is JobStatus.COMPLETED
        for job in replay_branch(store, store.head_position(ROOT)).execution.jobs.values()
    )


def test_target_before_next_candidate_stops_without_clock_event() -> None:
    definition = _definition()
    bindings = _provider_configuration()
    config = SimulationRunConfig(definition.ref, bindings)
    store = _store(definition, config)
    _add_plan_required_point(store)
    provider = ScriptedDecisionProvider(
        {
            DecisionPointId("plan-required"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                _plan(("wait",)),
            )
        }
    )
    adapter = SyncDecisionProviderAdapter(
        provider,
        bindings.decision_bindings[BINDING_ID],
        provider_name="scripted",
    )
    engine = _engine(
        store,
        definition,
        config,
        schedule=CompletionSchedule(),
        resolver=CompletionResolver(),
        starts=BinaryJobStarts(),
        invokers={BINDING_ID: adapter},
    )
    asyncio.run(engine.step(ROOT))
    asyncio.run(engine.step(ROOT))
    before = store.head_position(ROOT)

    result = asyncio.run(engine.step(ROOT, target_time=LogicalTime(4 * MINUTE)))

    assert result.stop_reason is RuntimeStopReason.TARGET_REACHED
    assert result.logical_time == LogicalTime(0)
    assert store.head_position(ROOT) == before


def test_mixed_job_and_scenario_frontier_is_explicitly_unsupported() -> None:
    definition = _definition(occurrence_time=5 * MINUTE)
    bindings = _provider_configuration()
    config = SimulationRunConfig(definition.ref, bindings)
    store = _store(definition, config)
    _add_plan_required_point(store)
    provider = ScriptedDecisionProvider(
        {
            DecisionPointId("plan-required"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN,
                _plan(("wait",)),
            )
        }
    )
    adapter = SyncDecisionProviderAdapter(
        provider,
        bindings.decision_bindings[BINDING_ID],
        provider_name="scripted",
    )
    resolver = CompletionResolver()
    engine = _engine(
        store,
        definition,
        config,
        schedule=CompletionSchedule(),
        resolver=resolver,
        starts=BinaryJobStarts(),
        invokers={BINDING_ID: adapter},
    )
    asyncio.run(engine.step(ROOT))
    asyncio.run(engine.step(ROOT))
    before = store.head_position(ROOT)

    with pytest.raises(UnsupportedRuntimeFrontierError, match="mixed Job"):
        asyncio.run(engine.step(ROOT))

    assert store.head_position(ROOT) == before
    assert resolver.requests == []


def test_quiescent_and_step_budget_are_non_authoritative_results() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = _store(definition, config)
    engine = _engine(store, definition, config)

    quiescent = asyncio.run(engine.step(ROOT))
    budget = asyncio.run(engine.advance(ROOT, max_steps=0))

    assert quiescent.stop_reason is RuntimeStopReason.QUIESCENT
    assert budget.stop_reason is RuntimeStopReason.STEP_BUDGET_EXHAUSTED
    assert len(store.read_transitions(ROOT)) == 1

    with pytest.raises(TypeError, match="target_time"):
        asyncio.run(engine.advance(ROOT, target_time=0, max_steps=0))  # type: ignore[arg-type]


def test_provider_race_cannot_commit_a_decision_against_a_stale_head() -> None:
    definition = _definition()
    bindings = _provider_configuration()
    config = SimulationRunConfig(definition.ref, bindings)
    store = _store(definition, config)
    _add_plan_required_point(store)
    engine = _engine(
        store,
        definition,
        config,
        invokers={BINDING_ID: HeadAdvancingInvoker(store)},
    )

    with pytest.raises(StaleHistoryError, match="current visible head"):
        asyncio.run(engine.step(ROOT))

    state = replay_branch(store, store.head_position(ROOT))
    assert DecisionPointId("plan-required") not in state.cognition.decisions
    assert len(store.read_transitions(ROOT)) == 3


def test_outstanding_perception_precedes_pending_decision_configuration_failure() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = _store(definition, config)
    _add_plan_required_point(store)
    engine = _engine(
        store,
        definition,
        config,
        perception=GenesisPerception(),
        trigger=ContinueTrigger(),
    )

    result = asyncio.run(engine.step(ROOT))

    assert result.work_kind is RuntimeWorkKind.PERCEPTION
    with pytest.raises(ProviderBindingError, match="no provider routing"):
        asyncio.run(engine.step(ROOT))


def test_automatic_perception_cannot_create_second_pending_point_for_actor() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = _store(definition, config)
    _add_plan_required_point(store)
    engine = _engine(
        store,
        definition,
        config,
        perception=GenesisPerception(),
        trigger=DecisionPointTrigger(),
    )
    before_head = store.head_position(ROOT)
    before_history = tuple(store.read_transitions(ROOT))

    with pytest.raises(UnsupportedRuntimeStateError, match="already has a pending"):
        asyncio.run(engine.step(ROOT))

    assert store.head_position(ROOT) == before_head
    assert tuple(store.read_transitions(ROOT)) == before_history
    state = replay_branch(store, before_head)
    assert state.cognition.observations == {}
    assert tuple(state.cognition.decision_points) == (DecisionPointId("plan-required"),)


def test_pending_point_for_one_actor_does_not_block_perception_for_another() -> None:
    definition = _definition(actor_ids=(ACTOR.value, OTHER_ACTOR.value))
    config = SimulationRunConfig(definition.ref)
    store = _store(definition, config)
    _add_plan_required_point(store)
    engine = _engine(
        store,
        definition,
        config,
        perception=GenesisPerception(OTHER_ACTOR),
        trigger=DecisionPointTrigger(),
    )

    result = asyncio.run(engine.step(ROOT))

    assert result.work_kind is RuntimeWorkKind.PERCEPTION
    assert result.committed_transition is not None
    assert tuple(event.event_type for event in result.committed_transition.events) == (
        OBSERVATION_CREATED,
        DECISION_POINT_CREATED,
    )
    state = replay_branch(store, store.head_position(ROOT))
    assert {point.actor_id for point in state.cognition.decision_points.values()} == {
        ACTOR,
        OTHER_ACTOR,
    }
    assert {observation.actor_id for observation in state.cognition.observations.values()} == {
        OTHER_ACTOR
    }


def test_automatic_perception_creates_one_pending_point_normally() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = _store(definition, config)
    engine = _engine(
        store,
        definition,
        config,
        perception=GenesisPerception(),
        trigger=DecisionPointTrigger(),
    )

    result = asyncio.run(engine.step(ROOT))

    assert result.work_kind is RuntimeWorkKind.PERCEPTION
    assert result.committed_transition is not None
    assert tuple(event.event_type for event in result.committed_transition.events) == (
        OBSERVATION_CREATED,
        DECISION_POINT_CREATED,
    )
    state = replay_branch(store, store.head_position(ROOT))
    assert len(state.cognition.observations) == 1
    assert len(state.cognition.decision_points) == 1
    point_id = next(iter(state.cognition.decision_points))
    assert state.cognition.is_pending(point_id)
