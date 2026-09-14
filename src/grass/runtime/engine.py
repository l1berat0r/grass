# SPDX-License-Identifier: GPL-3.0-only

"""Production coordination of existing GRASS core transition boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, cast

from grass.core._structured_data import StructuredValue
from grass.core.branches import HistoryPosition
from grass.core.decision_invocations import (
    DecisionAcquisitionFailure,
    DecisionAcquisitionSuccess,
    DecisionInvoker,
    acquire_decisions,
    capture_decision_invocation_context,
    prepare_invoked_decision_transition,
)
from grass.core.decisions import (
    DecisionTriggerPolicy,
    ObservationProposal,
    evaluate_observation_trigger,
    prepare_evaluated_observation_transition,
)
from grass.core.event_store import EventStore
from grass.core.events import CauseRef, CommittedTransition
from grass.core.execution_commands import prepare_job_start_transition
from grass.core.identifiers import (
    BranchId,
    DecisionPointId,
    EventId,
    JobId,
    ProviderBindingId,
)
from grass.core.logical_time import LogicalTime
from grass.core.provider_bindings import ProviderBindingError, resolve_decision_provider_binding
from grass.core.references import TransitionRef
from grass.core.replay import replay_branch
from grass.core.scenario_occurrence_resolution import (
    ScenarioOccurrenceResolutionProvider,
    ScenarioOccurrenceResolutionRequest,
    acquire_deterministic_scenario_occurrence_resolution_proposal,
    prepare_scenario_occurrence_resolution_from_proposal,
    scenario_occurrence_resolution_event_count,
)
from grass.core.scenario_occurrences import project_scenario_occurrences
from grass.core.scheduler import (
    ScheduledResolution,
    ScheduledResolutionIndex,
    ScheduleProjector,
    SchedulerStep,
    derive_progress_anchors,
)
from grass.core.state import SimulationState
from grass.core.world_definitions import (
    ScenarioOccurrenceRef,
    SimulationRunConfig,
    WorldDefinition,
)
from grass.core.world_resolution import (
    JobResolutionSubject,
    ResolutionComponentProposal,
    ResolutionRequest,
    WorldResolutionProvider,
    acquire_deterministic_resolution_proposal,
    prepare_resolution_from_proposals,
    resolution_component_event_count,
)
from grass.runtime.contracts import (
    AdvanceResult,
    PerceptionProjector,
    RuntimeIdentitySource,
    RuntimeIntegrityError,
    RuntimeStopReason,
    RuntimeWorkKind,
    StepResult,
    UnsupportedRuntimeFrontierError,
)
from grass.runtime.perception import derive_outstanding_perception_candidates
from grass.runtime.readiness import (
    JobStartPolicy,
    JobStartProposal,
    derive_ready_plan_steps,
)

ScheduleSource: TypeAlias = JobId | ScenarioOccurrenceRef
JobConflictPredicate: TypeAlias = Callable[
    [ScheduledResolution[JobId], ScheduledResolution[JobId]], bool
]


@dataclass(frozen=True, slots=True)
class _Frontier:
    position: HistoryPosition
    history: tuple[CommittedTransition, ...]
    state: SimulationState
    current_time: LogicalTime


def _structured_key(value: StructuredValue) -> tuple[object, ...]:
    if value is None:
        return (0,)
    if type(value) is bool:
        return (1, value)
    if type(value) is int:
        return (2, value)
    if type(value) is float:
        return (3, value.hex())
    if type(value) is str:
        return (4, value)
    if isinstance(value, Mapping):
        return (5, tuple((key, _structured_key(value[key])) for key in sorted(value)))
    if isinstance(value, Sequence):
        return (6, tuple(_structured_key(item) for item in value))
    raise TypeError("unsupported structured scheduler metadata")


def _source_key(source: object) -> tuple[str, str, str]:
    if type(source) is JobId:
        return ("JOB", source.value, "")
    if type(source) is ScenarioOccurrenceRef:
        rule = source.scenario_event_rule_ref
        return (
            "SCENARIO",
            rule.world_definition_ref.world_definition_id.value,
            f"{rule.world_definition_ref.version}:{rule.rule_id.value}",
        )
    raise UnsupportedRuntimeFrontierError("scheduler source type is unsupported")


def _candidate_key(candidate: ScheduledResolution[ScheduleSource]) -> tuple[object, ...]:
    return (
        candidate.logical_time.nanoseconds_from_origin,
        _source_key(candidate.source_ref),
        candidate.kind,
        _structured_key(candidate.metadata),
    )


class SimulationEngine:
    """Coordinate one branch exclusively through validated core transitions."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        identity_source: RuntimeIdentitySource,
        schedule_projector: ScheduleProjector[JobId],
        conflict_predicate: JobConflictPredicate,
        world_resolution_provider: WorldResolutionProvider,
        scenario_occurrence_resolution_provider: ScenarioOccurrenceResolutionProvider,
        perception_projector: PerceptionProjector,
        decision_trigger_policy: DecisionTriggerPolicy,
        decision_invokers: Mapping[ProviderBindingId, DecisionInvoker],
        external_decision_bindings: frozenset[ProviderBindingId],
        job_start_policy: JobStartPolicy,
    ) -> None:
        if run_config.world_definition_ref != world_definition.ref:
            raise ValueError("run_config must reference world_definition")
        identity_methods = (
            "transition_id",
            "event_ids",
            "job_id",
            "observation_id",
            "decision_point_id",
        )
        if not all(callable(getattr(identity_source, name, None)) for name in identity_methods):
            raise TypeError("identity_source must implement RuntimeIdentitySource")
        if not callable(getattr(schedule_projector, "project", None)):
            raise TypeError("schedule_projector must provide project")
        if not callable(conflict_predicate):
            raise TypeError("conflict_predicate must be callable")
        if not callable(getattr(world_resolution_provider, "resolve", None)):
            raise TypeError("world_resolution_provider must provide resolve")
        if not callable(getattr(scenario_occurrence_resolution_provider, "resolve", None)):
            raise TypeError("scenario_occurrence_resolution_provider must provide resolve")
        if not callable(getattr(perception_projector, "project", None)):
            raise TypeError("perception_projector must provide project")
        if not callable(getattr(decision_trigger_policy, "evaluate", None)):
            raise TypeError("decision_trigger_policy must provide evaluate")
        if not callable(getattr(job_start_policy, "propose", None)):
            raise TypeError("job_start_policy must provide propose")
        invokers = dict(decision_invokers)
        if not all(type(key) is ProviderBindingId for key in invokers):
            raise TypeError("decision_invokers must use ProviderBindingId keys")
        if type(external_decision_bindings) is not frozenset or not all(
            type(item) is ProviderBindingId for item in external_decision_bindings
        ):
            raise TypeError("external_decision_bindings must be a frozenset of binding IDs")
        if set(invokers).intersection(external_decision_bindings):
            raise ValueError("decision bindings cannot be both inline and external")

        self._store = event_store
        self._definition = world_definition
        self._run_config = run_config
        self._ids = identity_source
        self._schedule_projector = schedule_projector
        self._conflicts = conflict_predicate
        self._world_resolver = world_resolution_provider
        self._scenario_resolver = scenario_occurrence_resolution_provider
        self._perception_projector = perception_projector
        self._trigger_policy = decision_trigger_policy
        self._decision_invokers = invokers
        self._external_decision_bindings = external_decision_bindings
        self._job_start_policy = job_start_policy

    def _frontier(self, branch_id: BranchId) -> _Frontier:
        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        position = self._store.head_position(branch_id)
        history = tuple(self._store.read_visible_transitions(position))
        if not history:
            raise RuntimeIntegrityError("SimulationEngine requires initialized history")
        if history[-1].transition_ref != position.transition_ref:
            raise RuntimeIntegrityError("visible history does not end at the captured head")
        state = replay_branch(self._store, position)
        return _Frontier(position, history, state, history[-1].logical_time)

    def _transition_ref(self, branch_id: BranchId, kind: RuntimeWorkKind) -> TransitionRef:
        transition_id = self._ids.transition_id(branch_id, kind)
        return TransitionRef(branch_id, transition_id)

    def _event_ids(self, count: int) -> tuple[EventId, ...]:
        values = tuple(self._ids.event_ids(count))
        if not all(type(value) is EventId for value in values):
            raise RuntimeIntegrityError("RuntimeIdentitySource returned invalid EventIds")
        if len(values) != count:
            raise RuntimeIntegrityError("RuntimeIdentitySource returned the wrong EventId count")
        return values

    def _committed_result(
        self,
        frontier: _Frontier,
        work_kind: RuntimeWorkKind,
        committed: CommittedTransition,
    ) -> StepResult:
        position = self._store.head_position(frontier.position.branch_id)
        if position.transition_ref != committed.transition_ref:
            raise RuntimeIntegrityError("guarded commit did not become the branch head")
        return StepResult(
            frontier.position,
            position,
            committed.logical_time,
            work_kind=work_kind,
            committed_transition=committed,
        )

    def _stop_result(
        self,
        frontier: _Frontier,
        reason: RuntimeStopReason,
        waiting: Sequence[DecisionPointId] = (),
    ) -> StepResult:
        return StepResult(
            frontier.position,
            frontier.position,
            frontier.current_time,
            stop_reason=reason,
            waiting_decision_point_ids=waiting,
        )

    def _pending_decisions(
        self, frontier: _Frontier
    ) -> tuple[tuple[DecisionPointId, ProviderBindingId, bool], ...]:
        pending = sorted(
            (
                point
                for point_id, point in frontier.state.cognition.decision_points.items()
                if point_id not in frontier.state.cognition.decisions
            ),
            key=lambda point: (point.actor_id.value, point.decision_point_id.value),
        )
        counts: dict[object, int] = {}
        for point in pending:
            counts[point.actor_id] = counts.get(point.actor_id, 0) + 1
        if any(count > 1 for count in counts.values()):
            from grass.runtime.readiness import UnsupportedRuntimeStateError

            raise UnsupportedRuntimeStateError(
                "more than one pending DecisionPoint for an actor is unsupported"
            )
        if not pending:
            return ()
        configuration = self._run_config.provider_bindings
        if configuration is None:
            raise ProviderBindingError("pending DecisionPoint has no provider routing")

        classified: list[tuple[DecisionPointId, ProviderBindingId, bool]] = []
        for point in pending:
            resolved = resolve_decision_provider_binding(configuration, point.actor_id)
            binding_id = resolved.binding.binding_id
            external = binding_id in self._external_decision_bindings
            if not external and binding_id not in self._decision_invokers:
                raise ProviderBindingError(
                    "no DecisionInvoker is configured for a resolved binding"
                )
            classified.append((point.decision_point_id, binding_id, external))
        return tuple(classified)

    def _schedule(self, frontier: _Frontier) -> SchedulerStep[ScheduleSource] | None:
        anchors = derive_progress_anchors(
            frontier.state,
            frontier.current_time,
            frontier.history,
        )
        projected_jobs = tuple(
            self._schedule_projector.project(
                frontier.state,
                frontier.current_time,
                anchors,
            )
        )
        if any(
            type(candidate) is not ScheduledResolution or type(candidate.source_ref) is not JobId
            for candidate in projected_jobs
        ):
            raise RuntimeIntegrityError("ScheduleProjector returned a non-Job candidate")
        occurrences = project_scenario_occurrences(
            self._definition,
            frontier.current_time,
            frontier.history,
        )
        candidates = tuple(
            sorted(
                (
                    *(cast(ScheduledResolution[ScheduleSource], item) for item in projected_jobs),
                    *(cast(ScheduledResolution[ScheduleSource], item) for item in occurrences),
                ),
                key=_candidate_key,
            )
        )
        index: ScheduledResolutionIndex[ScheduleSource] = ScheduledResolutionIndex()
        index.rebuild(frontier.current_time, candidates)

        def conflicts(
            left: ScheduledResolution[ScheduleSource],
            right: ScheduledResolution[ScheduleSource],
        ) -> bool:
            if type(left.source_ref) is not JobId or type(right.source_ref) is not JobId:
                return False
            return self._conflicts(
                cast(ScheduledResolution[JobId], left),
                cast(ScheduledResolution[JobId], right),
            )

        return index.next_step(frontier.current_time, conflicts)

    def _commit_perception(self, frontier: _Frontier) -> StepResult | None:
        candidates = derive_outstanding_perception_candidates(
            self._store,
            frontier.position,
            self._perception_projector,
        )
        if not candidates:
            return None
        candidate = candidates[0]
        observation_id = self._ids.observation_id(
            candidate.source_event_id,
            candidate.actor_id,
        )
        evaluated = evaluate_observation_trigger(
            self._trigger_policy,
            frontier.state,
            ObservationProposal(observation_id, candidate.actor_id, candidate.content),
            candidate.subject_plan_ref,
            base_history=frontier.history,
        )
        decision_point_id = (
            None
            if evaluated.decision_point_proposal is None
            else self._ids.decision_point_id(observation_id)
        )
        kind = RuntimeWorkKind.PERCEPTION
        prepared = prepare_evaluated_observation_transition(
            evaluated,
            frontier.state,
            decision_point_id,
            self._transition_ref(frontier.position.branch_id, kind),
            self._event_ids(evaluated.event_count),
            base_history=frontier.history,
            causation_refs=(CauseRef("event", candidate.source_event_id.value),),
        )
        committed = self._store.commit_transition(
            prepared.transition,
            expected_head=prepared.expected_head,
        )
        return self._committed_result(frontier, kind, committed)

    async def _commit_decision(
        self,
        frontier: _Frontier,
        classified: Sequence[tuple[DecisionPointId, ProviderBindingId, bool]],
    ) -> StepResult | None:
        inline = next((item for item in classified if not item[2]), None)
        if inline is None:
            return None
        configuration = self._run_config.provider_bindings
        if configuration is None:  # pragma: no cover - classified only with configuration
            raise AssertionError("missing provider configuration")
        point_id, _, _ = inline
        context = capture_decision_invocation_context(
            frontier.state,
            point_id,
            configuration,
            frontier.position,
            base_history=frontier.history,
        )
        outcomes = await acquire_decisions((context,), self._decision_invokers)
        outcome = outcomes[0]
        if type(outcome) is DecisionAcquisitionFailure:
            raise outcome.error
        if type(outcome) is not DecisionAcquisitionSuccess:
            raise RuntimeIntegrityError("decision acquisition returned unsupported output")
        event_count = 1 if outcome.result.proposal.proposed_plan is None else 2
        kind = RuntimeWorkKind.DECISION
        prepared = prepare_invoked_decision_transition(
            outcome,
            frontier.state,
            configuration,
            self._transition_ref(frontier.position.branch_id, kind),
            self._event_ids(event_count),
            base_history=frontier.history,
        )
        committed = self._store.commit_transition(
            prepared.transition,
            expected_head=prepared.expected_head,
        )
        return self._committed_result(frontier, kind, committed)

    def _commit_job_start(self, frontier: _Frontier) -> StepResult | None:
        for ready in derive_ready_plan_steps(frontier.state):
            proposal = self._job_start_policy.propose(ready, frontier.state)
            if proposal is None:
                continue
            if type(proposal) is not JobStartProposal:
                raise RuntimeIntegrityError("JobStartPolicy returned invalid output")
            kind = RuntimeWorkKind.JOB_START
            prepared = prepare_job_start_transition(
                frontier.state,
                ready.plan_step_ref,
                self._ids.job_id(ready.plan_step_ref),
                proposal.initial_progress,
                self._transition_ref(frontier.position.branch_id, kind),
                self._event_ids(2 if proposal.activate else 1),
                base_history=frontier.history,
                activate=proposal.activate,
            )
            committed = self._store.commit_transition(
                prepared.transition,
                expected_head=prepared.expected_head,
            )
            return self._committed_result(frontier, kind, committed)
        return None

    def _commit_job_frontier(
        self,
        frontier: _Frontier,
        step: SchedulerStep[ScheduleSource],
    ) -> StepResult:
        component_proposals: list[ResolutionComponentProposal] = []
        for component in step.conflict_components:
            grouped: dict[JobId, list[ScheduledResolution[JobId]]] = {}
            for candidate in component:
                if type(candidate.source_ref) is not JobId:
                    raise UnsupportedRuntimeFrontierError(
                        "mixed Job and scenario occurrence frontier is unsupported"
                    )
                grouped.setdefault(candidate.source_ref, []).append(
                    cast(ScheduledResolution[JobId], candidate)
                )
            subjects = tuple(
                JobResolutionSubject(
                    job_id,
                    tuple(
                        sorted(
                            candidates,
                            key=lambda item: _candidate_key(
                                cast(ScheduledResolution[ScheduleSource], item)
                            ),
                        )
                    ),
                )
                for job_id, candidates in sorted(grouped.items(), key=lambda item: item[0].value)
            )
            request = ResolutionRequest(
                frontier.position,
                step.target_time,
                step.elapsed,
                subjects,
                frontier.state,
            )
            proposal = acquire_deterministic_resolution_proposal(
                self._world_resolver,
                request,
                self._definition,
            )
            component_proposals.append((request, proposal))

        count = resolution_component_event_count(component_proposals)
        kind = RuntimeWorkKind.JOB_RESOLUTION_FRONTIER
        prepared = prepare_resolution_from_proposals(
            component_proposals,
            self._definition,
            self._transition_ref(frontier.position.branch_id, kind),
            self._event_ids(count),
            base_history=frontier.history,
        )
        committed = self._store.commit_transition(
            prepared.transition,
            expected_head=prepared.expected_head,
        )
        return self._committed_result(frontier, kind, committed)

    def _commit_scenario_occurrence(
        self,
        frontier: _Frontier,
        step: SchedulerStep[ScheduleSource],
        candidate: ScheduledResolution[ScenarioOccurrenceRef],
    ) -> StepResult:
        rule_id = candidate.source_ref.scenario_event_rule_ref.rule_id
        rule = self._definition.scenario_event_rule(rule_id)
        if rule is None:
            raise RuntimeIntegrityError("scheduled occurrence rule is not in WorldDefinition")
        request = ScenarioOccurrenceResolutionRequest(
            frontier.position,
            step.target_time,
            step.elapsed,
            candidate.source_ref,
            rule,
            candidate,
            frontier.state,
        )
        proposal = acquire_deterministic_scenario_occurrence_resolution_proposal(
            self._scenario_resolver,
            request,
            self._definition,
        )
        count = scenario_occurrence_resolution_event_count(request, proposal)
        kind = RuntimeWorkKind.SCENARIO_OCCURRENCE
        prepared = prepare_scenario_occurrence_resolution_from_proposal(
            request,
            proposal,
            self._definition,
            self._transition_ref(frontier.position.branch_id, kind),
            self._event_ids(count),
            history_reader=self._store,
        )
        committed = self._store.commit_transition(
            prepared.transition,
            expected_head=prepared.expected_head,
        )
        return self._committed_result(frontier, kind, committed)

    def _commit_scheduler_frontier(
        self,
        frontier: _Frontier,
        step: SchedulerStep[ScheduleSource],
    ) -> StepResult:
        job_candidates = tuple(
            candidate for candidate in step.due_candidates if type(candidate.source_ref) is JobId
        )
        occurrence_candidates = tuple(
            candidate
            for candidate in step.due_candidates
            if type(candidate.source_ref) is ScenarioOccurrenceRef
        )
        if len(job_candidates) + len(occurrence_candidates) != len(step.due_candidates):
            raise UnsupportedRuntimeFrontierError("scheduler source type is unsupported")
        if job_candidates and occurrence_candidates:
            raise UnsupportedRuntimeFrontierError(
                "mixed Job and scenario occurrence frontier is unsupported"
            )
        if job_candidates:
            return self._commit_job_frontier(frontier, step)
        if len(occurrence_candidates) != 1:
            raise UnsupportedRuntimeFrontierError(
                "multiple same-time scenario occurrences are unsupported"
            )
        return self._commit_scenario_occurrence(
            frontier,
            step,
            cast(ScheduledResolution[ScenarioOccurrenceRef], occurrence_candidates[0]),
        )

    async def step(
        self,
        branch_id: BranchId,
        *,
        target_time: LogicalTime | None = None,
    ) -> StepResult:
        """Commit exactly one transition or return one explicit no-commit stop."""

        if target_time is not None and type(target_time) is not LogicalTime:
            raise TypeError("target_time must be a LogicalTime or None")
        frontier = self._frontier(branch_id)
        if target_time is not None and target_time < frontier.current_time:
            raise ValueError("target_time must not precede current LogicalTime")

        result = self._commit_perception(frontier)
        if result is not None:
            return result
        classified = self._pending_decisions(frontier)
        result = await self._commit_decision(frontier, classified)
        if result is not None:
            return result
        result = self._commit_job_start(frontier)
        if result is not None:
            return result

        scheduler_step = self._schedule(frontier)
        if scheduler_step is not None and scheduler_step.target_time == frontier.current_time:
            return self._commit_scheduler_frontier(frontier, scheduler_step)

        waiting = tuple(point_id for point_id, _, external in classified if external)
        if waiting:
            return self._stop_result(
                frontier,
                RuntimeStopReason.WAITING_FOR_DECISION,
                waiting,
            )
        if target_time is not None and target_time == frontier.current_time:
            return self._stop_result(frontier, RuntimeStopReason.TARGET_REACHED)
        if scheduler_step is None:
            return self._stop_result(frontier, RuntimeStopReason.QUIESCENT)
        if target_time is not None and scheduler_step.target_time > target_time:
            return self._stop_result(frontier, RuntimeStopReason.TARGET_REACHED)
        return self._commit_scheduler_frontier(frontier, scheduler_step)

    async def advance(
        self,
        branch_id: BranchId,
        *,
        target_time: LogicalTime | None = None,
        max_steps: int = 1000,
    ) -> AdvanceResult:
        """Repeat bounded engine work until an explicit non-failure stop."""

        if target_time is not None and type(target_time) is not LogicalTime:
            raise TypeError("target_time must be a LogicalTime or None")
        if type(max_steps) is not int:
            raise TypeError("max_steps must be an integer")
        if max_steps < 0:
            raise ValueError("max_steps must not be negative")
        if max_steps == 0:
            frontier = self._frontier(branch_id)
            if target_time is not None and target_time < frontier.current_time:
                raise ValueError("target_time must not precede current LogicalTime")
            return AdvanceResult(
                frontier.position,
                frontier.current_time,
                0,
                RuntimeStopReason.STEP_BUDGET_EXHAUSTED,
            )
        committed_steps = 0
        while committed_steps < max_steps:
            result = await self.step(branch_id, target_time=target_time)
            if result.committed_transition is not None:
                committed_steps += 1
                continue
            reason = result.stop_reason
            if reason is None:  # pragma: no cover - StepResult enforces this
                raise AssertionError("stopped step has no reason")
            return AdvanceResult(
                result.position_after,
                result.logical_time,
                committed_steps,
                reason,
                result.waiting_decision_point_ids,
            )
        frontier = self._frontier(branch_id)
        return AdvanceResult(
            frontier.position,
            frontier.current_time,
            committed_steps,
            RuntimeStopReason.STEP_BUDGET_EXHAUSTED,
        )
