# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from grass.core import (
    BinaryProgress,
    BranchId,
    CauseRef,
    ChangeResourceEffect,
    CommittedTransition,
    CorrelationId,
    CreateEntityEffect,
    CreateRelationEffect,
    DeactivateEntityEffect,
    DeactivateRelationEffect,
    DeterministicResolutionIntegrityError,
    Entity,
    EntityId,
    EntityScope,
    Event,
    EventId,
    EventToCommit,
    ExecutionState,
    HistoryPosition,
    InitialConditions,
    InMemoryEventStore,
    Job,
    JobId,
    JobResolutionSubject,
    JobStatus,
    LogicalDuration,
    LogicalTime,
    Plan,
    PlanId,
    PlanStep,
    PlanStepId,
    PlanStepOrigin,
    PlanStepRef,
    PreparedResolution,
    ProjectionPosition,
    Provenance,
    ProvenanceSourceRef,
    Relation,
    RelationId,
    RelationParticipant,
    ResolutionOutcome,
    ResolutionProposal,
    ResolutionRequest,
    ResolutionValidationError,
    ScheduledResolution,
    SetStateVariableEffect,
    SimulationState,
    StaleHistoryError,
    SubjectResolutionOutcome,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    UpdateEntityEffect,
    UpdateJobEffect,
    UpdateRelationEffect,
    WorldDefinition,
    WorldDefinitionId,
    WorldScope,
    WorldState,
    WorldVocabulary,
    prepare_deterministic_resolution,
    validate_resolution_proposal,
)
from grass.core.execution import ActionPrimitive
from grass.core.execution_events import (
    JOB_COMPLETED,
    JOB_PROGRESS_UPDATED,
)
from grass.core.resolution_events import RESOLUTION_OUTCOME_RECORDED
from grass.core.world_events import (
    ENTITY_CREATED,
    ENTITY_DEACTIVATED,
    ENTITY_UPDATED,
    RELATION_CREATED,
    RELATION_DEACTIVATED,
    RELATION_UPDATED,
    RESOURCE_CHANGED,
    STATE_VARIABLE_CHANGED,
)


def definition() -> WorldDefinition:
    return WorldDefinition(
        WorldDefinitionId("world"),
        "1.0",
        1,
        WorldVocabulary(
            entity_types=frozenset({"Person", "Artifact"}),
            relation_types=frozenset({"linked"}),
            resource_types=frozenset({"capacity"}),
            state_variable_types=frozenset({"stress"}),
        ),
        InitialConditions(LogicalTime(0)),
    )


def simulation_state() -> SimulationState:
    actor_id = EntityId("actor")
    entities = {
        actor_id: Entity(actor_id, "Person", {}),
        EntityId("update-entity"): Entity(EntityId("update-entity"), "Artifact", {}),
        EntityId("deactivate-entity"): Entity(EntityId("deactivate-entity"), "Artifact", {}),
        EntityId("resource-owner"): Entity(EntityId("resource-owner"), "Artifact", {}),
    }
    participant = RelationParticipant("member", actor_id)
    relations = {
        RelationId("update-relation"): Relation(
            RelationId("update-relation"), "linked", frozenset({participant}), {}
        ),
        RelationId("deactivate-relation"): Relation(
            RelationId("deactivate-relation"), "linked", frozenset({participant}), {}
        ),
    }
    plan = Plan(
        PlanId("plan"),
        1,
        actor_id,
        "Complete work",
        (
            PlanStep(
                PlanStepId("step"),
                ActionPrimitive.WAIT,
                None,
                {},
                {},
                frozenset(),
                PlanStepOrigin.ACTOR_INTENT,
            ),
        ),
        None,
        Provenance("ACTOR"),
        LogicalTime(0),
    )
    job = Job(
        JobId("job"),
        PlanStepRef(plan.ref, PlanStepId("step")),
        JobStatus.ACTIVE,
        BinaryProgress(False),
        Provenance("ACTOR"),
        LogicalTime(0),
    )
    branch_id = BranchId("branch")
    return SimulationState(
        ProjectionPosition(
            branch_id,
            TransitionRef(branch_id, TransitionId("base")),
            4,
            LogicalTime(3),
        ),
        WorldState(entities=entities, relations=relations),
        ExecutionState(plans={plan.ref: plan}, jobs={job.job_id: job}),
    )


def request(*, candidates: Sequence[ScheduledResolution[JobId]] | None = None) -> ResolutionRequest:
    state = simulation_state()
    branch_id = state.position.branch_id
    due = (
        (
            ScheduledResolution(LogicalTime(10), "JOB_CHECKPOINT", JobId("job")),
            ScheduledResolution(LogicalTime(10), "JOB_EXPECTED_COMPLETION", JobId("job")),
        )
        if candidates is None
        else tuple(candidates)
    )
    return ResolutionRequest(
        HistoryPosition(branch_id, state.position.last_transition_ref),
        LogicalTime(10),
        LogicalDuration(7),
        (JobResolutionSubject(JobId("job"), due),),
        state,
    )


def base_transition() -> CommittedTransition:
    return CommittedTransition(
        (
            Event(
                EventId("base-event"),
                BranchId("branch"),
                4,
                LogicalTime(3),
                TransitionId("base"),
                "BaseStateRecorded",
                1,
                {},
                Provenance("ENGINE"),
            ),
        )
    )


@dataclass
class StaticProvider:
    proposal: ResolutionProposal
    calls: int = 0

    def resolve(self, resolution_request: ResolutionRequest, /) -> ResolutionProposal:
        assert isinstance(resolution_request.state, SimulationState)
        self.calls += 1
        return self.proposal


def outcome(
    result: ResolutionOutcome = ResolutionOutcome.SUCCESS,
) -> SubjectResolutionOutcome:
    return SubjectResolutionOutcome(JobId("job"), result)


def prepare(
    proposal: ResolutionProposal,
    event_count: int,
    *,
    base_history: Sequence[CommittedTransition] | None = None,
    **kwargs: object,
) -> tuple[PreparedResolution, StaticProvider]:
    provider = StaticProvider(proposal)
    prepared = prepare_deterministic_resolution(
        provider,
        request(),
        definition(),
        TransitionRef(BranchId("branch"), TransitionId("resolution")),
        tuple(EventId(f"event-{index}") for index in range(event_count)),
        base_history=(base_transition(),) if base_history is None else base_history,
        **kwargs,  # type: ignore[arg-type]
    )
    return prepared, provider


def test_request_groups_multiple_due_candidates_under_one_unique_job_subject() -> None:
    resolution_request = request()

    assert len(resolution_request.subjects) == 1
    assert len(resolution_request.subjects[0].due_candidates) == 2
    assert resolution_request.subjects[0].job_id == JobId("job")

    with pytest.raises(ValueError, match="subjects must be unique"):
        ResolutionRequest(
            resolution_request.base_history_position,
            resolution_request.target_logical_time,
            resolution_request.elapsed,
            (resolution_request.subjects[0], resolution_request.subjects[0]),
            resolution_request.state,
        )


def test_request_rejects_wrong_job_or_time_and_inconsistent_elapsed() -> None:
    with pytest.raises(ValueError, match="reference the subject Job"):
        JobResolutionSubject(
            JobId("job"),
            (ScheduledResolution(LogicalTime(10), "CHECK", JobId("other")),),
        )
    with pytest.raises(ValueError, match="share target_logical_time"):
        request(candidates=(ScheduledResolution(LogicalTime(11), "CHECK", JobId("job")),))
    state = simulation_state()
    with pytest.raises(ValueError, match="elapsed must begin"):
        ResolutionRequest(
            HistoryPosition(state.position.branch_id, state.position.last_transition_ref),
            LogicalTime(10),
            LogicalDuration(6),
            (
                JobResolutionSubject(
                    JobId("job"),
                    (ScheduledResolution(LogicalTime(10), "CHECK", JobId("job")),),
                ),
            ),
            state,
        )


def test_request_position_matches_local_state_and_allows_inherited_child_state() -> None:
    state = simulation_state()
    subject = JobResolutionSubject(
        JobId("job"),
        (ScheduledResolution(LogicalTime(10), "CHECK", JobId("job")),),
    )
    with pytest.raises(ValueError, match="does not match base history"):
        ResolutionRequest(
            HistoryPosition(
                state.position.branch_id,
                TransitionRef(state.position.branch_id, TransitionId("other")),
            ),
            LogicalTime(10),
            LogicalDuration(7),
            (subject,),
            state,
        )

    child_id = BranchId("child")
    child_state = SimulationState(
        ProjectionPosition(child_id),
        state.world,
        state.execution,
        state.cognition,
    )
    inherited = ResolutionRequest(
        HistoryPosition(
            child_id,
            TransitionRef(BranchId("parent"), TransitionId("fork")),
        ),
        LogicalTime(10),
        LogicalDuration(7),
        (
            JobResolutionSubject(
                JobId("job"),
                (ScheduledResolution(LogicalTime(10), "CHECK", JobId("job")),),
            ),
        ),
        child_state,
    )
    assert inherited.state.position == ProjectionPosition(child_id)


def test_each_job_subject_receives_one_independent_outcome_event() -> None:
    state = simulation_state()
    first_plan = next(iter(state.execution.plans.values()))
    second_plan = Plan(
        PlanId("second-plan"),
        1,
        EntityId("actor"),
        "Second work item",
        (
            PlanStep(
                PlanStepId("second-step"),
                ActionPrimitive.WAIT,
                None,
                {},
                {},
                frozenset(),
                PlanStepOrigin.ACTOR_INTENT,
            ),
        ),
        None,
        Provenance("ACTOR"),
        LogicalTime(0),
    )
    second_job = Job(
        JobId("second-job"),
        PlanStepRef(second_plan.ref, PlanStepId("second-step")),
        JobStatus.ACTIVE,
        BinaryProgress(False),
        Provenance("ACTOR"),
        LogicalTime(0),
    )
    state = SimulationState(
        state.position,
        state.world,
        ExecutionState(
            plans={first_plan.ref: first_plan, second_plan.ref: second_plan},
            jobs={**state.execution.jobs, second_job.job_id: second_job},
        ),
    )
    subjects = tuple(
        JobResolutionSubject(
            JobId(job_id),
            (ScheduledResolution(LogicalTime(10), "CHECK", JobId(job_id)),),
        )
        for job_id in ("job", "second-job")
    )
    resolution_request = ResolutionRequest(
        HistoryPosition(state.position.branch_id, state.position.last_transition_ref),
        LogicalTime(10),
        LogicalDuration(7),
        subjects,
        state,
    )
    proposal = ResolutionProposal(
        (
            SubjectResolutionOutcome(JobId("second-job"), ResolutionOutcome.BLOCKED),
            SubjectResolutionOutcome(JobId("job"), ResolutionOutcome.SUCCESS),
        )
    )

    prepared = prepare_deterministic_resolution(
        StaticProvider(proposal),
        resolution_request,
        definition(),
        TransitionRef(BranchId("branch"), TransitionId("two-subjects")),
        (EventId("first-outcome"), EventId("second-outcome")),
        base_history=(base_transition(),),
    )

    assert [event.payload for event in prepared.transition.events] == [
        {"job_id": "job", "outcome": "SUCCESS"},
        {"job_id": "second-job", "outcome": "BLOCKED"},
    ]


def test_no_effect_failed_outcome_prepares_non_empty_history_without_job_change() -> None:
    prepared, provider = prepare(
        ResolutionProposal((outcome(ResolutionOutcome.FAILED),)),
        1,
    )

    assert provider.calls == 1
    assert prepared.expected_head == request().base_history_position
    assert [event.event_type for event in prepared.transition.events] == [
        RESOLUTION_OUTCOME_RECORDED
    ]
    assert prepared.transition.events[0].payload == {
        "job_id": "job",
        "outcome": "FAILED",
    }


def test_every_world_effect_materializes_to_existing_semantic_events() -> None:
    actor = RelationParticipant("member", EntityId("actor"))
    effects = (
        CreateEntityEffect(EntityId("new"), "Artifact", {"created": True}),
        UpdateEntityEffect(EntityId("update-entity"), {"updated": True}),
        DeactivateEntityEffect(EntityId("deactivate-entity")),
        CreateRelationEffect(
            RelationId("new-relation"),
            "linked",
            frozenset({actor, RelationParticipant("artifact", EntityId("new"))}),
            {},
        ),
        UpdateRelationEffect(RelationId("update-relation"), frozenset({actor}), {"updated": True}),
        DeactivateRelationEffect(RelationId("deactivate-relation")),
        ChangeResourceEffect(EntityId("resource-owner"), "capacity", 0),
        SetStateVariableEffect(EntityScope(EntityId("actor")), "stress", 4),
        UpdateJobEffect(
            JobId("job"),
            status_after=JobStatus.COMPLETED,
            progress_after=BinaryProgress(True),
        ),
    )

    prepared, _ = prepare(ResolutionProposal((outcome(),), effects), 11)

    assert [event.event_type for event in prepared.transition.events] == [
        RESOLUTION_OUTCOME_RECORDED,
        ENTITY_CREATED,
        ENTITY_UPDATED,
        ENTITY_DEACTIVATED,
        RELATION_CREATED,
        RELATION_UPDATED,
        RELATION_DEACTIVATED,
        RESOURCE_CHANGED,
        STATE_VARIABLE_CHANGED,
        JOB_PROGRESS_UPDATED,
        JOB_COMPLETED,
    ]


def test_materialization_uses_only_trusted_envelope_inputs() -> None:
    source = ProvenanceSourceRef("RESOLVER", "deterministic:test")
    cause = CauseRef("scheduler", "due-batch")
    correlation = CorrelationId("work")

    prepared, _ = prepare(
        ResolutionProposal((outcome(),), (SetStateVariableEffect(WorldScope(), "stress", 1),)),
        2,
        resolver_source_ref=source,
        resolver_metadata={"implementation": "test"},
        causation_refs=(cause,),
        correlation_id=correlation,
    )

    for event in prepared.transition.events:
        assert event.provenance == Provenance("WORLD_RESOLVER", source, {"implementation": "test"})
        assert event.causation_refs == (cause,)
        assert event.correlation_id == correlation


@pytest.mark.parametrize(
    "proposal,message",
    [
        (ResolutionProposal(()), "missing=['job']"),
        (
            ResolutionProposal(
                (
                    outcome(),
                    SubjectResolutionOutcome(JobId("extra"), ResolutionOutcome.SUCCESS),
                )
            ),
            "extra=['extra']",
        ),
        (
            ResolutionProposal(
                (outcome(),),
                (CreateEntityEffect(EntityId("new"), "Undeclared", {}),),
            ),
            "undeclared entity_type",
        ),
        (
            ResolutionProposal(
                (outcome(),),
                (UpdateEntityEffect(EntityId("missing"), {}),),
            ),
            "Entity does not exist",
        ),
        (
            ResolutionProposal(
                (outcome(),),
                (UpdateJobEffect(JobId("job"), status_after=JobStatus.ACTIVE),),
            ),
            "invalid Job status transition",
        ),
        (
            ResolutionProposal(
                (outcome(),),
                (
                    UpdateEntityEffect(EntityId("update-entity"), {"first": True}),
                    UpdateEntityEffect(EntityId("update-entity"), {"second": True}),
                ),
            ),
            "duplicate Entity write",
        ),
    ],
)
def test_invalid_deterministic_proposals_are_integrity_failures(
    proposal: ResolutionProposal, message: str
) -> None:
    with pytest.raises(DeterministicResolutionIntegrityError) as captured:
        prepare(proposal, 20)

    assert captured.value.__cause__ is not None
    assert message in str(captured.value.__cause__)


def test_provider_failure_and_malformed_return_are_integrity_failures() -> None:
    class FailingProvider:
        def resolve(self, resolution_request: ResolutionRequest, /) -> ResolutionProposal:
            del resolution_request
            raise RuntimeError("mechanic failed")

    class MalformedProvider:
        def resolve(self, resolution_request: ResolutionRequest, /) -> ResolutionProposal:
            del resolution_request
            return "not a proposal"  # type: ignore[return-value]

    inputs = (
        request(),
        definition(),
        TransitionRef(BranchId("branch"), TransitionId("resolution")),
        (EventId("event"),),
    )
    with pytest.raises(DeterministicResolutionIntegrityError, match="failed"):
        prepare_deterministic_resolution(
            FailingProvider(), *inputs, base_history=(base_transition(),)
        )
    with pytest.raises(DeterministicResolutionIntegrityError, match="invalid proposal"):
        prepare_deterministic_resolution(
            MalformedProvider(), *inputs, base_history=(base_transition(),)
        )


def test_pure_validator_and_event_id_count_report_separate_validation_errors() -> None:
    proposal = ResolutionProposal((outcome(),))
    validate_resolution_proposal(request(), proposal, definition())

    with pytest.raises(ResolutionValidationError, match="exactly 1 EventId"):
        prepare(proposal, 0)


def test_duplicate_job_effects_are_rejected_before_order_can_choose_truth() -> None:
    with pytest.raises(ValueError, match="at most one UpdateJobEffect"):
        ResolutionProposal(
            (outcome(),),
            (
                UpdateJobEffect(JobId("job"), progress_after=BinaryProgress(False)),
                UpdateJobEffect(JobId("job"), status_after=JobStatus.FAILED),
            ),
        )


def test_unordered_effect_and_event_id_inputs_are_rejected() -> None:
    with pytest.raises(TypeError, match="effects must be a sequence"):
        ResolutionProposal(
            (outcome(),),
            {UpdateJobEffect(JobId("job"), status_after=JobStatus.FAILED)},  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="event_ids must be a sequence"):
        prepare_deterministic_resolution(
            StaticProvider(ResolutionProposal((outcome(),))),
            request(),
            definition(),
            TransitionRef(BranchId("branch"), TransitionId("resolution")),
            {EventId("event")},  # type: ignore[arg-type]
            base_history=(base_transition(),),
        )


def test_inherited_branch_elapsed_is_checked_against_visible_base_history() -> None:
    parent_state = simulation_state()
    child_id = BranchId("child")
    child_state = SimulationState(
        ProjectionPosition(child_id),
        parent_state.world,
        parent_state.execution,
        parent_state.cognition,
    )
    inherited_ref = TransitionRef(BranchId("parent"), TransitionId("fork"))
    resolution_request = ResolutionRequest(
        HistoryPosition(child_id, inherited_ref),
        LogicalTime(10),
        LogicalDuration(1),
        (
            JobResolutionSubject(
                JobId("job"),
                (ScheduledResolution(LogicalTime(10), "CHECK", JobId("job")),),
            ),
        ),
        child_state,
    )
    inherited_history = (
        CommittedTransition(
            (
                Event(
                    EventId("fork-event"),
                    BranchId("parent"),
                    1,
                    LogicalTime(3),
                    TransitionId("fork"),
                    "ForkStateRecorded",
                    1,
                    {},
                    Provenance("ENGINE"),
                ),
            )
        ),
    )
    provider = StaticProvider(ResolutionProposal((outcome(),)))

    with pytest.raises(ResolutionValidationError, match="base history position"):
        prepare_deterministic_resolution(
            provider,
            resolution_request,
            definition(),
            TransitionRef(child_id, TransitionId("resolution")),
            (EventId("outcome"),),
            base_history=inherited_history,
        )
    assert provider.calls == 0


def test_prepared_resolution_is_rejected_after_branch_head_advances() -> None:
    store = InMemoryEventStore()
    branch_id = BranchId("branch")
    store.create_root_branch(branch_id)
    base = store.commit_transition(
        TransitionToCommit(
            TransitionRef(branch_id, TransitionId("base")),
            LogicalTime(3),
            tuple(
                EventToCommit(
                    EventId(f"base-event-{index}"),
                    "BaseStateRecorded",
                    1,
                    {"index": index},
                    Provenance("ENGINE"),
                )
                for index in range(4)
            ),
        )
    )
    prepared, _ = prepare(
        ResolutionProposal((outcome(),)),
        1,
        base_history=(base,),
    )
    store.commit_transition(
        TransitionToCommit(
            TransitionRef(branch_id, TransitionId("advance")),
            LogicalTime(4),
            (
                EventToCommit(
                    EventId("advance-event"),
                    "BranchAdvanced",
                    1,
                    {},
                    Provenance("ENGINE"),
                ),
            ),
        )
    )
    before_rejection = store.read_transitions(branch_id)

    with pytest.raises(StaleHistoryError):
        store.commit_transition(
            prepared.transition,
            expected_head=prepared.expected_head,
        )
    assert store.read_transitions(branch_id) == before_rejection
