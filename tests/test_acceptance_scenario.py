# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, cast

from grass.core import (
    ActionPrimitive,
    BoundedReaction,
    BoundedReactionDecision,
    BranchId,
    CommittedTransition,
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
    EntityId,
    EntityScope,
    Event,
    EventId,
    EventToCommit,
    InMemoryEventStore,
    JobId,
    JobResolutionSubject,
    JobStatus,
    LinearProgress,
    LogicalDuration,
    LogicalTime,
    ObservationId,
    ObservationProposal,
    PlanDependency,
    PlanDependencyCondition,
    PlanId,
    PlanRef,
    PlanStep,
    PlanStepId,
    PlanStepOrigin,
    PlanStepRef,
    PreparedCognitionTransition,
    ProgressAnchor,
    ProposedPlan,
    Provenance,
    ProviderBindingConfiguration,
    ProviderBindingId,
    ProviderExecutionLocation,
    ResolutionOutcome,
    ResolutionProposal,
    ResolutionRequest,
    ResourceKey,
    ScenarioOccurrenceRef,
    ScenarioOccurrenceResolutionProposal,
    ScenarioOccurrenceResolutionRequest,
    ScheduledResolution,
    ScheduledResolutionIndex,
    ScheduleProjector,
    SchedulerStep,
    ScriptedDecisionProvider,
    ScriptedDecisionTriggerPolicy,
    SetStateVariableEffect,
    SimulationRunConfig,
    SimulationState,
    StateVariableKey,
    SubjectResolutionOutcome,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    UpdateJobEffect,
    WorldDefinition,
    WorldScope,
    build_genesis_transition,
    decode_execution_event,
    decode_world_event,
    derive_progress_anchors,
    load_world_definition,
    prepare_decision_point_transition,
    prepare_decision_transition,
    prepare_deterministic_resolution,
    prepare_deterministic_scenario_occurrence_resolution,
    prepare_observation_transition,
    project_scenario_occurrences,
    project_transition,
    replay_branch,
)
from grass.core._structured_data import StructuredValue
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_COMPLETED,
    JOB_CREATED,
    JOB_FAILED,
    JobCompletedPayload,
    JobFailedPayload,
)
from grass.core.scenario_events import SCENARIO_OCCURRENCE_RESOLVED
from grass.core.world_events import STATE_VARIABLE_CHANGED, StateVariableChangedPayload
from grass.providers import SyncDecisionProviderAdapter
from grass.runtime import (
    JobStartProposal,
    PerceptionCandidate,
    ReadyPlanStep,
    RuntimeWorkKind,
    SimulationEngine,
)

MINUTE = 60_000_000_000
ScheduleSource: TypeAlias = JobId | ScenarioOccurrenceRef

ALICE = EntityId("alice")
BOB = EntityId("bob")
TEST_ENVIRONMENT = EntityId("test-environment")
ALICE_PLAN = PlanRef(PlanId("alice-plan"), 1)
BOB_PLAN = PlanRef(PlanId("bob-plan"), 1)


def scenario_document() -> dict[str, object]:
    return {
        "world_definition_id": "acceptance-world",
        "version": "slice-9",
        "schema_version": 2,
        "vocabulary": {
            "entity_types": ["Person", "Organization", "Location", "Artifact"],
            "relation_types": ["employed_by"],
            "resource_types": ["capacity"],
            "state_variable_types": ["stress", "location", "network_available"],
        },
        "initial_conditions": {
            "logical_time": 0,
            "entities": [
                {"entity_id": "alice", "entity_type": "Person", "properties": {}},
                {"entity_id": "bob", "entity_type": "Person", "properties": {}},
                {"entity_id": "acme", "entity_type": "Organization", "properties": {}},
                {"entity_id": "office", "entity_type": "Location", "properties": {}},
                {
                    "entity_id": "test-environment",
                    "entity_type": "Artifact",
                    "properties": {},
                },
            ],
            "relations": [
                {
                    "relation_id": "alice-employment",
                    "relation_type": "employed_by",
                    "participants": [
                        {"role": "employee", "entity_id": "alice"},
                        {"role": "employer", "entity_id": "acme"},
                    ],
                    "properties": {},
                },
                {
                    "relation_id": "bob-employment",
                    "relation_type": "employed_by",
                    "participants": [
                        {"role": "employee", "entity_id": "bob"},
                        {"role": "employer", "entity_id": "acme"},
                    ],
                    "properties": {},
                },
            ],
            "resources": [
                {
                    "entity_id": "test-environment",
                    "resource_type": "capacity",
                    "quantity": 1,
                }
            ],
            "state_variables": [
                {
                    "scope": {"kind": "ENTITY", "entity_id": "alice"},
                    "state_variable_type": "stress",
                    "value": 0,
                },
                {
                    "scope": {"kind": "ENTITY", "entity_id": "bob"},
                    "state_variable_type": "stress",
                    "value": 0,
                },
                {
                    "scope": {"kind": "ENTITY", "entity_id": "alice"},
                    "state_variable_type": "location",
                    "value": "remote",
                },
                {
                    "scope": {"kind": "WORLD"},
                    "state_variable_type": "network_available",
                    "value": True,
                },
            ],
        },
        "metadata": {"purpose": "Slice 9 acceptance integration"},
        "scenario_event_rules": [
            {
                "rule_id": "network-outage",
                "trigger": {"kind": "AT_TIME", "logical_time": 72 * MINUTE},
            }
        ],
    }


def alice_plan() -> ProposedPlan:
    move = PlanStep(
        PlanStepId("alice-move"),
        ActionPrimitive.MOVE,
        None,
        {"actor_id": "alice", "destination_id": "office"},
        {},
        frozenset(),
        PlanStepOrigin.ACTOR_INTENT,
        "Move to the office",
    )
    report = PlanStep(
        PlanStepId("alice-report"),
        ActionPrimitive.MODIFY,
        None,
        {"resource_entity_id": "test-environment"},
        {"work": "report"},
        frozenset({PlanDependency(PlanStepId("alice-move"), PlanDependencyCondition.SUCCESS)}),
        PlanStepOrigin.ACTOR_INTENT,
        "Write the report",
    )
    return ProposedPlan(PlanId("alice-plan"), 1, ALICE, "Write the report", (move, report), None)


def bob_plan() -> ProposedPlan:
    communicate = PlanStep(
        PlanStepId("bob-communicate"),
        ActionPrimitive.COMMUNICATE,
        None,
        {"recipient_id": "alice"},
        {"message": "Do you have a moment?"},
        frozenset(),
        PlanStepOrigin.ACTOR_INTENT,
    )
    test = PlanStep(
        PlanStepId("bob-test"),
        ActionPrimitive.MODIFY,
        None,
        {"resource_entity_id": "test-environment"},
        {"work": "test"},
        frozenset({PlanDependency(PlanStepId("bob-communicate"), PlanDependencyCondition.SUCCESS)}),
        PlanStepOrigin.ACTOR_INTENT,
    )
    return ProposedPlan(PlanId("bob-plan"), 1, BOB, "Ask Alice and test", (communicate, test), None)


def _progress_payload(progress: LinearProgress) -> Mapping[str, StructuredValue]:
    return {"kind": "LINEAR", "completed": progress.completed, "total": progress.total}


def _committed_candidate(
    state: SimulationState, transition: TransitionToCommit
) -> CommittedTransition:
    return CommittedTransition(
        tuple(
            Event(
                record.event_id,
                transition.transition_ref.branch_id,
                state.position.last_sequence + index + 1,
                transition.logical_time,
                transition.transition_ref.transition_id,
                record.event_type,
                record.event_version,
                record.payload,
                record.provenance,
                record.causation_refs,
                record.correlation_id,
            )
            for index, record in enumerate(transition.events)
        )
    )


def start_job(
    store: InMemoryEventStore,
    state: SimulationState,
    label: str,
    job_id: JobId,
    plan_step_ref: PlanStepRef,
    progress: LinearProgress,
) -> CommittedTransition:
    head = store.head_position(state.position.branch_id)
    transition = TransitionToCommit(
        TransitionRef(state.position.branch_id, TransitionId(label)),
        store.read_visible_transitions(head)[-1].logical_time,
        (
            EventToCommit(
                EventId(f"{label}:created"),
                JOB_CREATED,
                1,
                {
                    "job_id": job_id.value,
                    "plan_step_ref": {
                        "plan_ref": {
                            "plan_id": plan_step_ref.plan_ref.plan_id.value,
                            "version": plan_step_ref.plan_ref.version,
                        },
                        "step_id": plan_step_ref.step_id.value,
                    },
                    "progress": _progress_payload(progress),
                },
                Provenance("ENGINE"),
            ),
            EventToCommit(
                EventId(f"{label}:activated"),
                JOB_ACTIVATED,
                1,
                {"job_id": job_id.value},
                Provenance("ENGINE"),
            ),
        ),
    )
    project_transition(state, _committed_candidate(state, transition))
    return store.commit_transition(transition, expected_head=head)


class AcceptanceJobProjector:
    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> tuple[ScheduledResolution[ScheduleSource], ...]:
        del current_time
        candidates: list[ScheduledResolution[ScheduleSource]] = []
        for job_id, raw_anchor in progress_anchors.items():
            anchor = raw_anchor
            job = state.execution.jobs[job_id]
            if job_id == JobId("alice-move"):
                duration = 30 * MINUTE
                kind = "JOB_EXPECTED_COMPLETION"
            elif job_id == JobId("bob-communicate"):
                duration = 5 * MINUTE
                kind = "JOB_EXPECTED_COMPLETION"
            elif job_id == JobId("bob-test"):
                duration = 85 * MINUTE
                kind = "JOB_CHECKPOINT"
            elif job_id == JobId("alice-report"):
                if job.progress == LinearProgress(0, 2):
                    duration = 90 * MINUTE
                elif job.progress == LinearProgress(1, 2):
                    duration = 30 * MINUTE
                else:
                    raise AssertionError("unexpected Alice report progress")
                kind = "JOB_CHECKPOINT"
            else:
                raise AssertionError(f"unexpected Job: {job_id}")
            candidates.append(
                ScheduledResolution(
                    anchor.anchor_time + LogicalDuration(duration),
                    kind,
                    job_id,
                )
            )
        return tuple(candidates)


@dataclass
class AcceptanceJobResolver:
    requests: list[ResolutionRequest]

    def resolve(self, request: ResolutionRequest, /) -> ResolutionProposal:
        self.requests.append(request)
        job_ids = frozenset(subject.job_id for subject in request.subjects)
        if job_ids == frozenset({JobId("alice-move")}):
            return ResolutionProposal(
                (SubjectResolutionOutcome(JobId("alice-move"), ResolutionOutcome.SUCCESS),),
                (
                    SetStateVariableEffect(EntityScope(ALICE), "location", "office"),
                    UpdateJobEffect(
                        JobId("alice-move"),
                        status_after=JobStatus.COMPLETED,
                        progress_after=LinearProgress(1, 1),
                    ),
                ),
            )
        if job_ids == frozenset({JobId("bob-communicate")}):
            return ResolutionProposal(
                (SubjectResolutionOutcome(JobId("bob-communicate"), ResolutionOutcome.SUCCESS),),
                (
                    UpdateJobEffect(
                        JobId("bob-communicate"),
                        status_after=JobStatus.COMPLETED,
                        progress_after=LinearProgress(1, 1),
                    ),
                ),
            )
        if job_ids == frozenset({JobId("alice-report"), JobId("bob-test")}):
            assert request.state.world.resources[ResourceKey(TEST_ENVIRONMENT, "capacity")] == 1
            return ResolutionProposal(
                (
                    SubjectResolutionOutcome(JobId("alice-report"), ResolutionOutcome.PARTIAL),
                    SubjectResolutionOutcome(JobId("bob-test"), ResolutionOutcome.SUCCESS),
                ),
                (
                    UpdateJobEffect(JobId("alice-report"), progress_after=LinearProgress(1, 2)),
                    UpdateJobEffect(
                        JobId("bob-test"),
                        status_after=JobStatus.COMPLETED,
                        progress_after=LinearProgress(1, 1),
                    ),
                ),
            )
        if job_ids == frozenset({JobId("alice-report")}):
            assert (
                request.state.world.state_variables[
                    StateVariableKey(WorldScope(), "network_available")
                ]
                is False
            )
            return ResolutionProposal(
                (SubjectResolutionOutcome(JobId("alice-report"), ResolutionOutcome.FAILED),),
                (UpdateJobEffect(JobId("alice-report"), status_after=JobStatus.FAILED),),
            )
        raise AssertionError(f"unexpected resolution subjects: {job_ids}")


@dataclass
class OutageResolver:
    requests: list[ScenarioOccurrenceResolutionRequest]

    def resolve(
        self, request: ScenarioOccurrenceResolutionRequest, /
    ) -> ScenarioOccurrenceResolutionProposal:
        self.requests.append(request)
        return ScenarioOccurrenceResolutionProposal(
            (SetStateVariableEffect(WorldScope(), "network_available", False),)
        )


@dataclass(frozen=True)
class AcceptanceResult:
    root_history: tuple[CommittedTransition, ...]
    before_history: tuple[CommittedTransition, ...]
    after_history: tuple[CommittedTransition, ...]
    root_state: SimulationState
    before_state: SimulationState
    after_state: SimulationState
    elapsed: tuple[LogicalDuration, ...]


class AcceptanceHarness:
    def __init__(self, *, rebuild_after_every_commit: bool) -> None:
        self.rebuild_after_every_commit = rebuild_after_every_commit
        self.definition = load_world_definition(scenario_document())
        self.store = InMemoryEventStore()
        self.root_id = BranchId("root")
        self.store.create_root_branch(self.root_id)
        self.index: ScheduledResolutionIndex[ScheduleSource] = ScheduledResolutionIndex()
        self.projector: ScheduleProjector[ScheduleSource] = AcceptanceJobProjector()
        self.job_resolver = AcceptanceJobResolver([])
        self.outage_resolver = OutageResolver([])
        self.projector_calls = 0
        self.current_time = LogicalTime(0)
        self.index_initialized = False
        self.elapsed: list[LogicalDuration] = []

    def state(self, branch_id: BranchId | None = None) -> SimulationState:
        selected = self.root_id if branch_id is None else branch_id
        return replay_branch(self.store, self.store.head_position(selected))

    def history(self, branch_id: BranchId | None = None) -> tuple[CommittedTransition, ...]:
        selected = self.root_id if branch_id is None else branch_id
        return self.store.read_visible_transitions(self.store.head_position(selected))

    def refresh(self) -> None:
        state = self.state()
        history = self.history()
        self.current_time = history[-1].logical_time
        anchors = derive_progress_anchors(state, self.current_time, history)
        projected = list(self.projector.project(state, self.current_time, anchors))
        projected.extend(
            ScheduledResolution(
                candidate.logical_time,
                candidate.kind,
                candidate.source_ref,
                candidate.metadata,
            )
            for candidate in project_scenario_occurrences(
                self.definition, self.current_time, history
            )
        )
        self.projector_calls += 1
        if self.rebuild_after_every_commit or not self.index_initialized:
            self.index.rebuild(self.current_time, projected)
            self.index_initialized = True
            return

        old_sources = {candidate.source_ref for candidate in self.index.snapshot(self.current_time)}
        new_sources = {candidate.source_ref for candidate in projected}
        for source_ref in sorted(old_sources | new_sources, key=_source_key):
            self.index.replace_source(
                self.current_time,
                source_ref,
                tuple(candidate for candidate in projected if candidate.source_ref == source_ref),
            )
        rebuilt: ScheduledResolutionIndex[ScheduleSource] = ScheduledResolutionIndex()
        rebuilt.rebuild(self.current_time, projected)
        assert _candidate_keys(self.index.snapshot(self.current_time)) == _candidate_keys(
            rebuilt.snapshot(self.current_time)
        )

    def commit_cognition(self, prepared: PreparedCognitionTransition) -> CommittedTransition:
        committed = self.store.commit_transition(
            prepared.transition, expected_head=prepared.expected_head
        )
        self.refresh()
        return committed

    def start(
        self,
        label: str,
        job_id: JobId,
        plan_step_ref: PlanStepRef,
        progress: LinearProgress,
    ) -> CommittedTransition:
        committed = start_job(self.store, self.state(), label, job_id, plan_step_ref, progress)
        self.refresh()
        return committed

    def next_step(self) -> SchedulerStep[ScheduleSource]:
        step = self.index.next_step(self.current_time, self.conflicts)
        assert step is not None
        self.elapsed.append(step.elapsed)
        return step

    def conflicts(
        self,
        left: ScheduledResolution[ScheduleSource],
        right: ScheduledResolution[ScheduleSource],
    ) -> bool:
        if type(left.source_ref) is not JobId or type(right.source_ref) is not JobId:
            return False
        state = self.state()
        left_job = state.execution.jobs[left.source_ref]
        right_job = state.execution.jobs[right.source_ref]
        left_plan = state.execution.plans[left_job.plan_step_ref.plan_ref]
        right_plan = state.execution.plans[right_job.plan_step_ref.plan_ref]
        left_step = left_plan.step(left_job.plan_step_ref.step_id)
        right_step = right_plan.step(right_job.plan_step_ref.step_id)
        assert left_step is not None and right_step is not None
        return (
            left_step.bindings.get("resource_entity_id") == TEST_ENVIRONMENT.value
            and right_step.bindings.get("resource_entity_id") == TEST_ENVIRONMENT.value
        )

    def resolve_jobs(
        self, step: SchedulerStep[ScheduleSource], event_count: int
    ) -> CommittedTransition:
        assert len(step.conflict_components) == 1
        grouped: dict[JobId, list[ScheduledResolution[JobId]]] = {}
        for candidate in step.conflict_components[0]:
            assert type(candidate.source_ref) is JobId
            grouped.setdefault(candidate.source_ref, []).append(
                ScheduledResolution(
                    candidate.logical_time,
                    candidate.kind,
                    candidate.source_ref,
                    candidate.metadata,
                )
            )
        subjects = tuple(
            JobResolutionSubject(job_id, candidates)
            for job_id, candidates in sorted(grouped.items(), key=lambda item: item[0].value)
        )
        base = self.store.head_position(self.root_id)
        request = ResolutionRequest(
            base,
            step.target_time,
            step.elapsed,
            subjects,
            self.state(),
        )
        label = f"job-resolution-{len(self.job_resolver.requests)}"
        prepared = prepare_deterministic_resolution(
            self.job_resolver,
            request,
            self.definition,
            TransitionRef(self.root_id, TransitionId(label)),
            tuple(EventId(f"{label}:{index}") for index in range(event_count)),
            base_history=self.history(),
        )
        committed = self.store.commit_transition(
            prepared.transition, expected_head=prepared.expected_head
        )
        self.refresh()
        return committed

    def resolve_occurrence(self, step: SchedulerStep[ScheduleSource]) -> CommittedTransition:
        assert len(step.due_candidates) == 1
        candidate = step.due_candidates[0]
        assert type(candidate.source_ref) is ScenarioOccurrenceRef
        occurrence_candidate = ScheduledResolution(
            candidate.logical_time,
            candidate.kind,
            candidate.source_ref,
            candidate.metadata,
        )
        rule_id = candidate.source_ref.scenario_event_rule_ref.rule_id
        rule = self.definition.scenario_event_rule(rule_id)
        assert rule is not None
        base = self.store.head_position(self.root_id)
        request = ScenarioOccurrenceResolutionRequest(
            base,
            step.target_time,
            step.elapsed,
            candidate.source_ref,
            rule,
            occurrence_candidate,
            self.state(),
        )
        prepared = prepare_deterministic_scenario_occurrence_resolution(
            self.outage_resolver,
            request,
            self.definition,
            TransitionRef(self.root_id, TransitionId("network-outage")),
            (EventId("network-outage:resolved"), EventId("network-outage:world")),
            history_reader=self.store,
        )
        committed = self.store.commit_transition(
            prepared.transition, expected_head=prepared.expected_head
        )
        self.refresh()
        return committed


def _source_key(source: ScheduleSource) -> tuple[str, str]:
    if type(source) is JobId:
        return ("JOB", source.value)
    assert type(source) is ScenarioOccurrenceRef
    rule_ref = source.scenario_event_rule_ref
    return ("SCENARIO", rule_ref.rule_id.value)


def _candidate_keys(
    candidates: Sequence[ScheduledResolution[ScheduleSource]],
) -> frozenset[tuple[int, str, tuple[str, str]]]:
    return frozenset(
        (
            candidate.logical_time.nanoseconds_from_origin,
            candidate.kind,
            _source_key(candidate.source_ref),
        )
        for candidate in candidates
    )


def run_acceptance(*, rebuild_after_every_commit: bool) -> AcceptanceResult:
    harness = AcceptanceHarness(rebuild_after_every_commit=rebuild_after_every_commit)
    definition = harness.definition
    genesis_count = 1 + 5 + 2 + 1 + 4
    harness.store.commit_transition(
        build_genesis_transition(
            definition,
            SimulationRunConfig(definition.ref),
            TransitionRef(harness.root_id, TransitionId("genesis")),
            tuple(EventId(f"genesis:{index}") for index in range(genesis_count)),
        )
    )
    harness.refresh()

    initial_point = prepare_decision_point_transition(
        harness.state(),
        ALICE,
        DecisionPointId("alice-plan-required"),
        DecisionPointProposal(
            DecisionPointReason.PLAN_REQUIRED,
            DecisionPointScope.FULL,
            frozenset(),
        ),
        TransitionRef(harness.root_id, TransitionId("alice-plan-required")),
        EventId("alice-plan-required"),
        base_history=harness.history(),
    )
    harness.commit_cognition(initial_point)
    alice_provider = ScriptedDecisionProvider(
        {
            DecisionPointId("alice-plan-required"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN, alice_plan()
            )
        }
    )
    harness.commit_cognition(
        prepare_decision_transition(
            alice_provider,
            harness.state(),
            DecisionPointId("alice-plan-required"),
            TransitionRef(harness.root_id, TransitionId("alice-plan")),
            (EventId("alice-plan:decision"), EventId("alice-plan:plan")),
            base_history=harness.history(),
        )
    )
    harness.start(
        "alice-move-start",
        JobId("alice-move"),
        PlanStepRef(ALICE_PLAN, PlanStepId("alice-move")),
        LinearProgress(0, 1),
    )

    move_step = harness.next_step()
    assert move_step.target_time == LogicalTime(30 * MINUTE)
    move_transition = harness.resolve_jobs(move_step, 4)
    assert (
        harness.state().world.state_variables[StateVariableKey(EntityScope(ALICE), "location")]
        == "office"
    )

    bob_observation_id = ObservationId("bob-saw-alice")
    bob_trigger = ScriptedDecisionTriggerPolicy(
        {
            bob_observation_id: DecisionPointProposal(
                DecisionPointReason.MATERIAL_OBSERVATION,
                DecisionPointScope.FULL,
                frozenset({bob_observation_id}),
            )
        }
    )
    harness.commit_cognition(
        prepare_observation_transition(
            bob_trigger,
            harness.state(),
            ObservationProposal(
                bob_observation_id,
                BOB,
                {"observed": "Alice entered the office"},
            ),
            None,
            DecisionPointId("bob-interaction"),
            TransitionRef(harness.root_id, TransitionId("bob-observation")),
            (EventId("bob-observation"), EventId("bob-point")),
            base_history=harness.history(),
            causation_refs=(),
        )
    )
    bob_provider = ScriptedDecisionProvider(
        {
            DecisionPointId("bob-interaction"): DecisionProposal(
                DecisionOutcomeKind.REPLACE_PLAN, bob_plan()
            )
        }
    )
    harness.commit_cognition(
        prepare_decision_transition(
            bob_provider,
            harness.state(),
            DecisionPointId("bob-interaction"),
            TransitionRef(harness.root_id, TransitionId("bob-plan")),
            (EventId("bob-plan:decision"), EventId("bob-plan:plan")),
            base_history=harness.history(),
        )
    )
    harness.start(
        "alice-report-start",
        JobId("alice-report"),
        PlanStepRef(ALICE_PLAN, PlanStepId("alice-report")),
        LinearProgress(0, 2),
    )
    harness.start(
        "bob-communicate-start",
        JobId("bob-communicate"),
        PlanStepRef(BOB_PLAN, PlanStepId("bob-communicate")),
        LinearProgress(0, 1),
    )

    communicate_step = harness.next_step()
    assert communicate_step.target_time == LogicalTime(35 * MINUTE)
    communicate_transition = harness.resolve_jobs(communicate_step, 3)
    alice_observation_id = ObservationId("alice-heard-bob")
    alice_trigger = ScriptedDecisionTriggerPolicy(
        {
            alice_observation_id: DecisionPointProposal(
                DecisionPointReason.INTERACTION_REQUEST,
                DecisionPointScope.BOUNDED,
                frozenset({alice_observation_id}),
                ALICE_PLAN,
            )
        }
    )
    harness.commit_cognition(
        prepare_observation_transition(
            alice_trigger,
            harness.state(),
            ObservationProposal(
                alice_observation_id,
                ALICE,
                {"sender": "bob", "message": "Do you have a moment?"},
            ),
            ALICE_PLAN,
            DecisionPointId("alice-bounded-reaction"),
            TransitionRef(harness.root_id, TransitionId("alice-observation")),
            (EventId("alice-observation"), EventId("alice-bounded-point")),
            base_history=harness.history(),
            causation_refs=(),
        )
    )
    before_decision_position = harness.store.head_position(harness.root_id)
    before_child_id = BranchId("before-bounded-decision")
    harness.store.fork_branch(before_child_id, before_decision_position)

    root_bounded_provider = ScriptedDecisionProvider(
        {
            DecisionPointId("alice-bounded-reaction"): DecisionProposal(
                DecisionOutcomeKind.BOUNDED_REACTION,
                bounded_reaction=BoundedReaction(
                    "Answer Bob without replacing the report Plan",
                    {"message": "Yes, but only for five minutes."},
                ),
            )
        }
    )
    harness.commit_cognition(
        prepare_decision_transition(
            root_bounded_provider,
            harness.state(),
            DecisionPointId("alice-bounded-reaction"),
            TransitionRef(harness.root_id, TransitionId("alice-bounded-decision")),
            (EventId("alice-bounded-decision"),),
            base_history=harness.history(),
        )
    )
    after_decision_position = harness.store.head_position(harness.root_id)
    after_child_id = BranchId("after-bounded-decision")
    harness.store.fork_branch(after_child_id, after_decision_position)

    root_history_before_child = harness.history()
    before_state = harness.state(before_child_id)
    child_provider = ScriptedDecisionProvider(
        {
            DecisionPointId("alice-bounded-reaction"): DecisionProposal(
                DecisionOutcomeKind.BOUNDED_REACTION,
                bounded_reaction=BoundedReaction(
                    "Refuse and continue report work", {"message": "Not right now."}
                ),
            )
        }
    )
    child_prepared = prepare_decision_transition(
        child_provider,
        before_state,
        DecisionPointId("alice-bounded-reaction"),
        TransitionRef(before_child_id, TransitionId("different-bounded-decision")),
        (EventId("child-bounded-decision"),),
        base_history=harness.history(before_child_id),
    )
    harness.store.commit_transition(
        child_prepared.transition, expected_head=child_prepared.expected_head
    )
    assert harness.history() == root_history_before_child
    inherited_after_state = harness.state(after_child_id)
    assert DecisionPointId("alice-bounded-reaction") in inherited_after_state.cognition.decisions

    harness.start(
        "bob-test-start",
        JobId("bob-test"),
        PlanStepRef(BOB_PLAN, PlanStepId("bob-test")),
        LinearProgress(0, 1),
    )

    outage_step = harness.next_step()
    assert outage_step.target_time == LogicalTime(72 * MINUTE)
    outage_transition = harness.resolve_occurrence(outage_step)
    assert outage_transition.events[0].event_type == SCENARIO_OCCURRENCE_RESOLVED

    conflict_step = harness.next_step()
    assert conflict_step.target_time == LogicalTime(120 * MINUTE)
    assert len(conflict_step.due_candidates) == 2
    assert len(conflict_step.conflict_components) == 1
    conflict_transition = harness.resolve_jobs(conflict_step, 5)
    assert len(conflict_transition.events) == 5
    assert len(harness.job_resolver.requests[-1].subjects) == 2

    failure_step = harness.next_step()
    assert failure_step.target_time == LogicalTime(150 * MINUTE)
    failure_transition = harness.resolve_jobs(failure_step, 2)
    assert any(event.event_type == JOB_FAILED for event in failure_transition.events)

    failure_observation_id = ObservationId("alice-job-failed")
    failure_trigger = ScriptedDecisionTriggerPolicy(
        {
            failure_observation_id: DecisionPointProposal(
                DecisionPointReason.JOB_FAILED,
                DecisionPointScope.FULL,
                frozenset({failure_observation_id}),
                ALICE_PLAN,
            )
        }
    )
    harness.commit_cognition(
        prepare_observation_transition(
            failure_trigger,
            harness.state(),
            ObservationProposal(
                failure_observation_id,
                ALICE,
                {"job_id": "alice-report", "status": "FAILED"},
            ),
            ALICE_PLAN,
            DecisionPointId("alice-job-failed-point"),
            TransitionRef(harness.root_id, TransitionId("alice-job-failed-observation")),
            (EventId("alice-job-failed-observation"), EventId("alice-job-failed-point")),
            base_history=harness.history(),
        )
    )

    assert harness.index.next_step(harness.current_time, harness.conflicts) is None
    root_state = harness.state()
    before_final = harness.state(before_child_id)
    after_final = harness.state(after_child_id)
    producer_counts = (
        len(alice_provider.requests),
        len(bob_provider.requests),
        len(root_bounded_provider.requests),
        len(child_provider.requests),
        len(bob_trigger.requests),
        len(alice_trigger.requests),
        len(failure_trigger.requests),
        len(harness.job_resolver.requests),
        len(harness.outage_resolver.requests),
        harness.projector_calls,
    )
    assert replay_branch(harness.store, harness.store.head_position(harness.root_id)) == root_state
    assert (
        replay_branch(harness.store, harness.store.head_position(before_child_id)) == before_final
    )
    assert replay_branch(harness.store, harness.store.head_position(after_child_id)) == after_final
    assert producer_counts == (
        len(alice_provider.requests),
        len(bob_provider.requests),
        len(root_bounded_provider.requests),
        len(child_provider.requests),
        len(bob_trigger.requests),
        len(alice_trigger.requests),
        len(failure_trigger.requests),
        len(harness.job_resolver.requests),
        len(harness.outage_resolver.requests),
        harness.projector_calls,
    )
    root_decision = root_state.cognition.decisions[DecisionPointId("alice-bounded-reaction")]
    child_decision = before_final.cognition.decisions[DecisionPointId("alice-bounded-reaction")]
    assert type(root_decision.outcome) is BoundedReactionDecision
    assert type(child_decision.outcome) is BoundedReactionDecision
    assert root_decision.outcome != child_decision.outcome
    assert root_state.execution.plans[ALICE_PLAN] == after_final.execution.plans[ALICE_PLAN]
    assert (
        root_state.cognition.decisions[DecisionPointId("alice-bounded-reaction")]
        == after_final.cognition.decisions[DecisionPointId("alice-bounded-reaction")]
    )
    assert all(
        event.event_type not in {"Tick", "ScheduledResolution"}
        for transition in harness.history()
        for event in transition.events
    )
    assert move_transition.logical_time == LogicalTime(30 * MINUTE)
    assert communicate_transition.logical_time == LogicalTime(35 * MINUTE)

    return AcceptanceResult(
        harness.history(),
        harness.history(before_child_id),
        harness.history(after_child_id),
        root_state,
        before_final,
        after_final,
        tuple(harness.elapsed),
    )


def test_acceptance_scenario_incremental_and_rebuild_execution_are_equivalent() -> None:
    incremental = run_acceptance(rebuild_after_every_commit=False)
    rebuilt = run_acceptance(rebuild_after_every_commit=True)

    assert incremental == rebuilt
    assert incremental.elapsed == (
        LogicalDuration(30 * MINUTE),
        LogicalDuration(5 * MINUTE),
        LogicalDuration(37 * MINUTE),
        LogicalDuration(48 * MINUTE),
        LogicalDuration(30 * MINUTE),
    )


class AcceptanceRuntimeIds:
    def __init__(self) -> None:
        self._next_value = 0

    def _next(self, kind: str) -> str:
        self._next_value += 1
        return f"acceptance:{kind}:{self._next_value}"

    def transition_id(self, branch_id: BranchId, work_kind: RuntimeWorkKind, /) -> TransitionId:
        return TransitionId(self._next(f"{branch_id.value}:{work_kind.value.lower()}"))

    def event_ids(self, count: int, /) -> tuple[EventId, ...]:
        return tuple(EventId(self._next("event")) for _ in range(count))

    def job_id(self, plan_step_ref: PlanStepRef, /) -> JobId:
        return JobId(plan_step_ref.step_id.value)

    def observation_id(self, source_event_id: EventId, actor_id: EntityId, /) -> ObservationId:
        return ObservationId(f"observation:{source_event_id.value}:{actor_id.value}")

    def decision_point_id(self, observation_id: ObservationId, /) -> DecisionPointId:
        return DecisionPointId(f"decision-point:{observation_id.value}")


class AcceptancePerceptionProjector:
    def project(
        self,
        source_transition: CommittedTransition,
        state_after_source: SimulationState,
        /,
    ) -> tuple[PerceptionCandidate, ...]:
        del state_after_source
        candidates: list[PerceptionCandidate] = []
        for event in source_transition.events:
            if event.event_type == STATE_VARIABLE_CHANGED:
                world_payload = decode_world_event(event)
                if (
                    type(world_payload) is StateVariableChangedPayload
                    and world_payload.scope == EntityScope(ALICE)
                    and world_payload.state_variable_type == "location"
                    and world_payload.value_after == "office"
                ):
                    candidates.append(
                        PerceptionCandidate(
                            event.event_id,
                            BOB,
                            {"kind": "alice-arrived"},
                        )
                    )
            elif event.event_type == JOB_COMPLETED:
                execution_payload = decode_execution_event(event)
                if type(
                    execution_payload
                ) is JobCompletedPayload and execution_payload.job_id == JobId("bob-communicate"):
                    candidates.append(
                        PerceptionCandidate(
                            event.event_id,
                            ALICE,
                            {"kind": "bob-asked", "message": "Do you have a moment?"},
                            ALICE_PLAN,
                        )
                    )
            elif event.event_type == JOB_FAILED:
                execution_payload = decode_execution_event(event)
                if type(
                    execution_payload
                ) is JobFailedPayload and execution_payload.job_id == JobId("alice-report"):
                    candidates.append(
                        PerceptionCandidate(
                            event.event_id,
                            ALICE,
                            {"kind": "report-failed", "job_id": "alice-report"},
                            ALICE_PLAN,
                        )
                    )
        return tuple(candidates)


class AcceptanceTriggerPolicy:
    def evaluate(self, context: DecisionTriggerContext, /) -> DecisionPointProposal:
        observation = context.observation
        kind = observation.content["kind"]
        if kind == "alice-arrived":
            return DecisionPointProposal(
                DecisionPointReason.MATERIAL_OBSERVATION,
                DecisionPointScope.FULL,
                frozenset({observation.observation_id}),
            )
        if kind == "bob-asked":
            return DecisionPointProposal(
                DecisionPointReason.INTERACTION_REQUEST,
                DecisionPointScope.BOUNDED,
                frozenset({observation.observation_id}),
                ALICE_PLAN,
            )
        if kind == "report-failed":
            return DecisionPointProposal(
                DecisionPointReason.JOB_FAILED,
                DecisionPointScope.FULL,
                frozenset({observation.observation_id}),
                ALICE_PLAN,
            )
        raise AssertionError(f"unexpected perception kind: {kind}")


class AcceptanceJobStartPolicy:
    def propose(self, ready_step: ReadyPlanStep, state: SimulationState, /) -> JobStartProposal:
        del state
        totals = {
            PlanStepId("alice-move"): 1,
            PlanStepId("alice-report"): 2,
            PlanStepId("bob-communicate"): 1,
            PlanStepId("bob-test"): 1,
        }
        return JobStartProposal(LinearProgress(0, totals[ready_step.step_id]), activate=True)


class RuntimeAcceptanceJobProjector:
    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> tuple[ScheduledResolution[JobId], ...]:
        candidates = AcceptanceJobProjector().project(state, current_time, progress_anchors)
        return tuple(cast(ScheduledResolution[JobId], candidate) for candidate in candidates)


class AcceptanceDecisionProvider:
    def __init__(self, *, accepts_interaction: bool) -> None:
        self.accepts_interaction = accepts_interaction
        self.requests: list[DecisionRequest] = []

    def decide(self, request: DecisionRequest, /) -> DecisionProposal:
        self.requests.append(request)
        point = request.decision_point
        if point.reason is DecisionPointReason.PLAN_REQUIRED and point.actor_id == ALICE:
            return DecisionProposal(DecisionOutcomeKind.REPLACE_PLAN, alice_plan())
        if point.reason is DecisionPointReason.MATERIAL_OBSERVATION and point.actor_id == BOB:
            return DecisionProposal(DecisionOutcomeKind.REPLACE_PLAN, bob_plan())
        if point.reason is DecisionPointReason.INTERACTION_REQUEST and point.actor_id == ALICE:
            if self.accepts_interaction:
                intent = "Answer Bob without replacing the report Plan"
                message = "Yes, but only for five minutes."
            else:
                intent = "Refuse and continue report work"
                message = "Not right now."
            return DecisionProposal(
                DecisionOutcomeKind.BOUNDED_REACTION,
                bounded_reaction=BoundedReaction(intent, {"message": message}),
            )
        raise AssertionError(f"unexpected DecisionPoint: {point}")


def _runtime_engine(
    *,
    store: InMemoryEventStore,
    definition: WorldDefinition,
    config: SimulationRunConfig,
    ids: AcceptanceRuntimeIds,
    provider: AcceptanceDecisionProvider,
    job_resolver: AcceptanceJobResolver,
    outage_resolver: OutageResolver,
) -> SimulationEngine:
    binding_config = config.provider_bindings
    assert binding_config is not None
    binding = binding_config.decision_bindings[ProviderBindingId("acceptance")]
    return SimulationEngine(
        event_store=store,
        world_definition=definition,
        run_config=config,
        identity_source=ids,
        schedule_projector=RuntimeAcceptanceJobProjector(),
        conflict_predicate=lambda left, right: (
            frozenset({left.source_ref, right.source_ref})
            == frozenset({JobId("alice-report"), JobId("bob-test")})
        ),
        world_resolution_provider=job_resolver,
        scenario_occurrence_resolution_provider=outage_resolver,
        perception_projector=AcceptancePerceptionProjector(),
        decision_trigger_policy=AcceptanceTriggerPolicy(),
        decision_invokers={
            binding.binding_id: SyncDecisionProviderAdapter(
                provider,
                binding,
                provider_name="acceptance-script",
            )
        },
        external_decision_bindings=frozenset(),
        job_start_policy=AcceptanceJobStartPolicy(),
    )


def test_simulation_engine_executes_acceptance_frontiers_and_branches() -> None:
    definition = load_world_definition(scenario_document())
    binding_id = ProviderBindingId("acceptance")
    binding = DecisionProviderBinding(
        binding_id,
        "acceptance-script",
        ProviderExecutionLocation.SERVER_MANAGED,
    )
    provider_config = ProviderBindingConfiguration(
        DecisionProviderRouting(binding_id),
        {binding_id: binding},
    )
    config = SimulationRunConfig(definition.ref, provider_config)
    store = InMemoryEventStore()
    store.create_root_branch(BranchId("runtime-root"))
    genesis_count = 1 + 5 + 2 + 1 + 4
    store.commit_transition(
        build_genesis_transition(
            definition,
            config,
            TransitionRef(BranchId("runtime-root"), TransitionId("runtime-genesis")),
            tuple(EventId(f"runtime-genesis:{index}") for index in range(genesis_count)),
        )
    )
    initial_state = replay_branch(store, store.head_position(BranchId("runtime-root")))
    initial_point = prepare_decision_point_transition(
        initial_state,
        ALICE,
        DecisionPointId("runtime-alice-plan-required"),
        DecisionPointProposal(
            DecisionPointReason.PLAN_REQUIRED,
            DecisionPointScope.FULL,
            frozenset(),
        ),
        TransitionRef(BranchId("runtime-root"), TransitionId("runtime-plan-required")),
        EventId("runtime-plan-required"),
        base_history=store.read_visible_transitions(store.head_position(BranchId("runtime-root"))),
    )
    store.commit_transition(initial_point.transition, expected_head=initial_point.expected_head)

    ids = AcceptanceRuntimeIds()
    root_provider = AcceptanceDecisionProvider(accepts_interaction=True)
    job_resolver = AcceptanceJobResolver([])
    outage_resolver = OutageResolver([])
    root_engine = _runtime_engine(
        store=store,
        definition=definition,
        config=config,
        ids=ids,
        provider=root_provider,
        job_resolver=job_resolver,
        outage_resolver=outage_resolver,
    )
    root_id = BranchId("runtime-root")

    expected_prefix = (
        RuntimeWorkKind.DECISION,
        RuntimeWorkKind.JOB_START,
        RuntimeWorkKind.JOB_RESOLUTION_FRONTIER,
        RuntimeWorkKind.PERCEPTION,
        RuntimeWorkKind.DECISION,
        RuntimeWorkKind.JOB_START,
        RuntimeWorkKind.JOB_START,
        RuntimeWorkKind.JOB_RESOLUTION_FRONTIER,
        RuntimeWorkKind.PERCEPTION,
    )
    assert (
        tuple(asyncio.run(root_engine.step(root_id)).work_kind for _ in range(len(expected_prefix)))
        == expected_prefix
    )
    root_history = store.read_visible_transitions(store.head_position(root_id))
    assert root_history[-1].logical_time == LogicalTime(35 * MINUTE)

    before_id = BranchId("runtime-before-decision")
    store.fork_branch(before_id, store.head_position(root_id))
    root_decision = asyncio.run(root_engine.step(root_id))
    assert root_decision.work_kind is RuntimeWorkKind.DECISION
    after_id = BranchId("runtime-after-decision")
    store.fork_branch(after_id, store.head_position(root_id))
    root_history_before_child = store.read_visible_transitions(store.head_position(root_id))

    child_provider = AcceptanceDecisionProvider(accepts_interaction=False)
    child_engine = _runtime_engine(
        store=store,
        definition=definition,
        config=config,
        ids=ids,
        provider=child_provider,
        job_resolver=job_resolver,
        outage_resolver=outage_resolver,
    )
    child_decision = asyncio.run(child_engine.step(before_id))
    assert child_decision.work_kind is RuntimeWorkKind.DECISION
    assert store.read_visible_transitions(store.head_position(root_id)) == root_history_before_child

    inherited_provider = AcceptanceDecisionProvider(accepts_interaction=False)
    inherited_engine = _runtime_engine(
        store=store,
        definition=definition,
        config=config,
        ids=ids,
        provider=inherited_provider,
        job_resolver=job_resolver,
        outage_resolver=outage_resolver,
    )
    assert asyncio.run(inherited_engine.step(after_id)).work_kind is RuntimeWorkKind.JOB_START
    assert inherited_provider.requests == []

    expected_suffix = (
        RuntimeWorkKind.JOB_START,
        RuntimeWorkKind.SCENARIO_OCCURRENCE,
        RuntimeWorkKind.JOB_RESOLUTION_FRONTIER,
        RuntimeWorkKind.JOB_RESOLUTION_FRONTIER,
        RuntimeWorkKind.PERCEPTION,
    )
    suffix = tuple(asyncio.run(root_engine.step(root_id)).work_kind for _ in expected_suffix)
    assert suffix == expected_suffix

    root_state = replay_branch(store, store.head_position(root_id))
    before_state = replay_branch(store, store.head_position(before_id))
    after_state = replay_branch(store, store.head_position(after_id))
    bounded_id = next(
        point_id
        for point_id, point in root_state.cognition.decision_points.items()
        if point.reason is DecisionPointReason.INTERACTION_REQUEST
    )
    root_bounded = root_state.cognition.decisions[bounded_id]
    child_bounded = before_state.cognition.decisions[bounded_id]
    assert type(root_bounded.outcome) is BoundedReactionDecision
    assert type(child_bounded.outcome) is BoundedReactionDecision
    assert root_bounded.outcome != child_bounded.outcome
    assert root_state.cognition.decisions[bounded_id] == after_state.cognition.decisions[bounded_id]
    assert any(
        point.reason is DecisionPointReason.JOB_FAILED
        and point.decision_point_id not in root_state.cognition.decisions
        for point in root_state.cognition.decision_points.values()
    )
    assert root_state.execution.jobs[JobId("alice-report")].status is JobStatus.FAILED
    assert root_state.execution.jobs[JobId("bob-test")].status is JobStatus.COMPLETED
    assert len(root_provider.requests) == 3
    assert len(child_provider.requests) == 1
    assert len(job_resolver.requests) == 4
    assert len(outage_resolver.requests) == 1
    assert all(
        event.event_type not in {"Tick", "ScheduledResolution"}
        for transition in store.read_visible_transitions(store.head_position(root_id))
        for event in transition.events
    )
