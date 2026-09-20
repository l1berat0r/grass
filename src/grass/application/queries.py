# SPDX-License-Identifier: GPL-3.0-only

"""Read-only exact-position projections over canonical local run history."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from grass.application._material import (
    LoadedRunMaterial,
    LocalSimulationStorage,
    load_run_material,
)
from grass.application.contracts import (
    ActorHistoryAttribution,
    ActorHistoryAttributionKind,
    ActorHistoryEntry,
    ActorMembershipEvidence,
    ActorView,
    BranchView,
    DecisionStatus,
    DecisionView,
    HistoryScope,
    HistoryView,
    JobView,
    QueryError,
    QueryNotFoundError,
    QueryPosition,
    RunView,
    StateView,
)
from grass.core.branches import Branch, HistoryPosition
from grass.core.cognition import Observation
from grass.core.cognition_events import (
    COGNITION_EVENT_TYPES,
    DecisionPointCreatedPayload,
    DecisionRecordedPayload,
    ObservationCreatedPayload,
    decode_cognition_event,
)
from grass.core.decision_invocations import DecisionInvoker
from grass.core.event_store import EventStore
from grass.core.events import CommittedTransition, Event
from grass.core.execution import Plan
from grass.core.execution_events import (
    EXECUTION_EVENT_TYPES,
    JobActivatedPayload,
    JobCancelledPayload,
    JobCompletedPayload,
    JobCreatedPayload,
    JobFailedPayload,
    JobPausedPayload,
    JobProgressUpdatedPayload,
    PlanCreatedPayload,
    PlanReplacedPayload,
    PlanRevisedPayload,
    decode_execution_event,
)
from grass.core.identifiers import (
    BranchId,
    DecisionPointId,
    EntityId,
    JobId,
    ProviderBindingId,
)
from grass.core.replay import replay_branch
from grass.core.resolution_events import RESOLUTION_EVENT_TYPES, decode_resolution_event
from grass.core.state import SimulationState
from grass.persistence.contracts import RunId, RunNotFoundError
from grass.runtime.composition import RuntimeComposer
from grass.runtime.contracts import RunStatus, RuntimeIdentitySource
from grass.worlds.snapshots import FilesystemWorldSnapshotStore


@dataclass(frozen=True, slots=True)
class _CapturedBranch:
    store: EventStore
    branch: Branch
    position: QueryPosition
    history: tuple[CommittedTransition, ...]
    state: SimulationState


_JobPayload = (
    JobCreatedPayload
    | JobActivatedPayload
    | JobPausedPayload
    | JobProgressUpdatedPayload
    | JobCompletedPayload
    | JobFailedPayload
    | JobCancelledPayload
)


def _job_payload_id(payload: _JobPayload) -> JobId:
    if isinstance(payload, JobCreatedPayload):
        return payload.job.job_id
    return payload.job_id


class LocalSimulationQueries:
    """Build immutable application views without committing or initializing history."""

    def __init__(
        self,
        storage: LocalSimulationStorage,
        snapshot_store: FilesystemWorldSnapshotStore,
        *,
        composer: RuntimeComposer,
        identity_source_factory: Callable[[], RuntimeIdentitySource],
        decision_invokers: Mapping[ProviderBindingId, DecisionInvoker],
    ) -> None:
        self._storage = storage
        self._snapshot_store = snapshot_store
        self._composer = composer
        self._identity_source_factory = identity_source_factory
        self._decision_invokers = dict(decision_invokers)

    def _material(self, run_id: RunId) -> LoadedRunMaterial:
        try:
            return load_run_material(self._storage, self._snapshot_store, run_id)
        except RunNotFoundError as error:
            raise QueryNotFoundError(f"simulation run does not exist: {run_id.value}") from error

    def list_runs(self) -> tuple[RunView, ...]:
        records = tuple(self._storage.list_runs())
        return tuple(self.get_run(record.run_id) for record in records)

    def get_run(self, run_id: RunId) -> RunView:
        material = self._material(run_id)
        try:
            return RunView(material.record, material.definition, material.config)
        except ValueError as error:
            raise QueryError("persisted run material is inconsistent") from error

    def _branch_id(self, run_id: RunId, branch_id: BranchId | None) -> BranchId:
        if branch_id is not None:
            if type(branch_id) is not BranchId:
                raise TypeError("branch_id must be a BranchId or None")
            return branch_id
        return self._material(run_id).record.root_branch_id

    def _capture(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        position: HistoryPosition | None,
    ) -> _CapturedBranch:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        viewed_branch_id = self._branch_id(run_id, branch_id)
        if position is not None:
            if type(position) is not HistoryPosition:
                raise TypeError("position must be a HistoryPosition or None")
            if position.branch_id != viewed_branch_id:
                raise QueryError("explicit position branch must equal the viewed branch")
        material = self._material(run_id)
        store = self._storage.event_store(run_id)
        try:
            branch = store.read_branch(viewed_branch_id)
            captured = store.head_position(viewed_branch_id) if position is None else position
            history = tuple(store.read_visible_transitions(captured))
        except ValueError as error:
            raise QueryNotFoundError(
                f"branch or history position does not exist: {viewed_branch_id.value}"
            ) from error
        if not history or captured.transition_ref is None:
            raise QueryError("branch is empty or uninitialized")
        if history[-1].transition_ref != captured.transition_ref:
            raise QueryError("visible history does not end at the requested position")
        try:
            state = replay_branch(store, captured)
        except (TypeError, ValueError, RuntimeError) as error:
            raise QueryError("branch history cannot be replayed") from error
        del material
        query_position = QueryPosition(run_id, captured, history[-1].logical_time)
        return _CapturedBranch(store, branch, query_position, history, state)

    def get_status(self, run_id: RunId, branch_id: BranchId | None = None) -> RunStatus:
        """Delegate allocation-free status derivation to a freshly composed engine."""

        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        viewed_branch_id = self._branch_id(run_id, branch_id)
        material = self._material(run_id)
        self._composer.validate(material.definition, material.config)
        engine = self._composer.compose(
            event_store=self._storage.event_store(run_id),
            world_definition=material.definition,
            run_config=material.config,
            identity_source=self._identity_source_factory(),
            decision_invokers=self._decision_invokers,
        )
        return engine.inspect_status(viewed_branch_id)

    def list_branches(self, run_id: RunId) -> tuple[BranchView, ...]:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        self._material(run_id)
        store = self._storage.event_store(run_id)
        branches = tuple(store.list_branches())
        return tuple(
            self.get_branch(run_id, branch.branch_id)
            for branch in sorted(branches, key=lambda item: item.branch_id.value)
        )

    def get_branch(
        self,
        run_id: RunId,
        branch_id: BranchId | None = None,
        *,
        position: HistoryPosition | None = None,
    ) -> BranchView:
        captured = self._capture(run_id, branch_id, position)
        origin_count = sum(
            transition.branch_id == captured.branch.branch_id for transition in captured.history
        )
        return BranchView(
            captured.position,
            captured.branch,
            len(captured.history),
            origin_count,
        )

    def get_history(
        self,
        run_id: RunId,
        branch_id: BranchId | None = None,
        *,
        position: HistoryPosition | None = None,
        scope: HistoryScope = HistoryScope.VISIBLE,
    ) -> HistoryView:
        if type(scope) is not HistoryScope:
            raise TypeError("scope must be a HistoryScope")
        captured = self._capture(run_id, branch_id, position)
        transitions = captured.history
        if scope is HistoryScope.BRANCH_ORIGIN:
            viewed_branch_id = captured.position.history_position.branch_id
            transitions = tuple(
                transition for transition in transitions if transition.branch_id == viewed_branch_id
            )
        return HistoryView(captured.position, scope, transitions)

    def get_state(
        self,
        run_id: RunId,
        branch_id: BranchId | None = None,
        *,
        position: HistoryPosition | None = None,
    ) -> StateView:
        captured = self._capture(run_id, branch_id, position)
        return StateView(captured.position, captured.state)

    @staticmethod
    def _job_view(captured: _CapturedBranch, job_id: JobId) -> JobView:
        job = captured.state.execution.jobs.get(job_id)
        if job is None:
            raise QueryNotFoundError(f"Job does not exist at position: {job_id.value}")
        plan = captured.state.execution.plans.get(job.plan_step_ref.plan_ref)
        if plan is None:
            raise QueryError("Job references a missing exact Plan")
        step = plan.step(job.plan_step_ref.step_id)
        if step is None:
            raise QueryError("Job references a missing exact PlanStep")
        return JobView(captured.position, job, plan, step)

    def get_jobs(
        self,
        run_id: RunId,
        branch_id: BranchId | None = None,
        *,
        position: HistoryPosition | None = None,
    ) -> tuple[JobView, ...]:
        captured = self._capture(run_id, branch_id, position)
        return tuple(
            self._job_view(captured, job_id)
            for job_id in sorted(captured.state.execution.jobs, key=lambda item: item.value)
        )

    def get_job(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        job_id: JobId,
        *,
        position: HistoryPosition | None = None,
    ) -> JobView:
        if type(job_id) is not JobId:
            raise TypeError("job_id must be a JobId")
        return self._job_view(self._capture(run_id, branch_id, position), job_id)

    @staticmethod
    def _decision_view(
        captured: _CapturedBranch, decision_point_id: DecisionPointId
    ) -> DecisionView:
        point = captured.state.cognition.decision_points.get(decision_point_id)
        if point is None:
            raise QueryNotFoundError(
                f"DecisionPoint does not exist at position: {decision_point_id.value}"
            )
        decision = captured.state.cognition.decisions.get(decision_point_id)
        status = DecisionStatus.PENDING if decision is None else DecisionStatus.RESOLVED
        return DecisionView(captured.position, point, status, decision)

    def get_decisions(
        self,
        run_id: RunId,
        branch_id: BranchId | None = None,
        *,
        position: HistoryPosition | None = None,
    ) -> tuple[DecisionView, ...]:
        captured = self._capture(run_id, branch_id, position)
        return tuple(
            self._decision_view(captured, point_id)
            for point_id in sorted(
                captured.state.cognition.decision_points, key=lambda item: item.value
            )
        )

    def get_decision(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        decision_point_id: DecisionPointId,
        *,
        position: HistoryPosition | None = None,
    ) -> DecisionView:
        if type(decision_point_id) is not DecisionPointId:
            raise TypeError("decision_point_id must be a DecisionPointId")
        return self._decision_view(self._capture(run_id, branch_id, position), decision_point_id)

    @staticmethod
    def _actor_ids(state: SimulationState) -> tuple[EntityId, ...]:
        actor_ids = {
            *(plan.actor_id for plan in state.execution.plans.values()),
            *(observation.actor_id for observation in state.cognition.observations.values()),
            *(point.actor_id for point in state.cognition.decision_points.values()),
        }
        return tuple(sorted(actor_ids, key=lambda item: item.value))

    @classmethod
    def _actor_view(cls, captured: _CapturedBranch, actor_id: EntityId) -> ActorView:
        if actor_id not in cls._actor_ids(captured.state):
            raise QueryNotFoundError(f"actor does not exist at position: {actor_id.value}")
        entity = captured.state.world.entities.get(actor_id)
        if entity is None:
            raise QueryError("actor evidence references a missing Entity")
        plans = tuple(
            sorted(
                (
                    plan
                    for plan in captured.state.execution.plans.values()
                    if plan.actor_id == actor_id
                ),
                key=lambda item: (item.plan_id.value, item.version),
            )
        )
        observations = tuple(
            sorted(
                (
                    observation
                    for observation in captured.state.cognition.observations.values()
                    if observation.actor_id == actor_id
                ),
                key=lambda item: item.observation_id.value,
            )
        )
        point_ids = tuple(
            sorted(
                (
                    point_id
                    for point_id, point in captured.state.cognition.decision_points.items()
                    if point.actor_id == actor_id
                ),
                key=lambda item: item.value,
            )
        )
        decisions = tuple(cls._decision_view(captured, point_id) for point_id in point_ids)
        jobs = tuple(
            cls._job_view(captured, job.job_id)
            for job in sorted(
                captured.state.execution.jobs.values(), key=lambda item: item.job_id.value
            )
            if captured.state.execution.plans[job.plan_step_ref.plan_ref].actor_id == actor_id
        )
        evidence = tuple(
            item
            for item, present in (
                (ActorMembershipEvidence.PLAN, bool(plans)),
                (ActorMembershipEvidence.OBSERVATION, bool(observations)),
                (ActorMembershipEvidence.DECISION_POINT, bool(point_ids)),
            )
            if present
        )
        return ActorView(
            captured.position,
            entity,
            evidence,
            plans,
            observations,
            decisions,
            jobs,
        )

    def get_actors(
        self,
        run_id: RunId,
        branch_id: BranchId | None = None,
        *,
        position: HistoryPosition | None = None,
    ) -> tuple[ActorView, ...]:
        captured = self._capture(run_id, branch_id, position)
        return tuple(
            self._actor_view(captured, actor_id) for actor_id in self._actor_ids(captured.state)
        )

    def get_actor(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        actor_id: EntityId,
        *,
        position: HistoryPosition | None = None,
    ) -> ActorView:
        if type(actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        return self._actor_view(self._capture(run_id, branch_id, position), actor_id)

    def get_actor_observations(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        actor_id: EntityId,
        *,
        position: HistoryPosition | None = None,
    ) -> tuple[Observation, ...]:
        return tuple(self.get_actor(run_id, branch_id, actor_id, position=position).observations)

    def get_actor_decisions(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        actor_id: EntityId,
        *,
        position: HistoryPosition | None = None,
    ) -> tuple[DecisionView, ...]:
        return tuple(self.get_actor(run_id, branch_id, actor_id, position=position).decisions)

    def get_actor_plans(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        actor_id: EntityId,
        *,
        position: HistoryPosition | None = None,
    ) -> tuple[Plan, ...]:
        return tuple(self.get_actor(run_id, branch_id, actor_id, position=position).plans)

    def get_actor_jobs(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        actor_id: EntityId,
        *,
        position: HistoryPosition | None = None,
    ) -> tuple[JobView, ...]:
        return tuple(self.get_actor(run_id, branch_id, actor_id, position=position).jobs)

    @staticmethod
    def _plan_actor(state: SimulationState, plan: Plan) -> EntityId:
        exact = state.execution.plans.get(plan.ref)
        if exact is None or exact != plan:
            raise QueryError("Plan Event does not map to the exact projected Plan")
        return exact.actor_id

    @staticmethod
    def _job_actor(state: SimulationState, job_id: JobId) -> EntityId:
        job = state.execution.jobs.get(job_id)
        if job is None:
            raise QueryError("Job Event does not map to a projected Job")
        plan = state.execution.plans.get(job.plan_step_ref.plan_ref)
        if plan is None or plan.step(job.plan_step_ref.step_id) is None:
            raise QueryError("Job Event does not map through an exact PlanStep")
        return plan.actor_id

    @classmethod
    def _event_attribution(
        cls, event: Event, actor_id: EntityId, state: SimulationState
    ) -> ActorHistoryAttribution | None:
        kind: ActorHistoryAttributionKind | None = None
        attributed_actor: EntityId | None = None
        if event.event_type in COGNITION_EVENT_TYPES:
            cognition_payload = decode_cognition_event(event)
            if type(cognition_payload) is ObservationCreatedPayload:
                attributed_actor = cognition_payload.observation.actor_id
                kind = ActorHistoryAttributionKind.OBSERVATION
            elif type(cognition_payload) is DecisionPointCreatedPayload:
                attributed_actor = cognition_payload.decision_point.actor_id
                kind = ActorHistoryAttributionKind.DECISION_POINT
            elif type(cognition_payload) is DecisionRecordedPayload:
                point = state.cognition.decision_points.get(
                    cognition_payload.decision.decision_point_id
                )
                if point is None:
                    raise QueryError("Decision Event references a missing DecisionPoint")
                attributed_actor = point.actor_id
                kind = ActorHistoryAttributionKind.DECISION
        elif event.event_type in EXECUTION_EVENT_TYPES:
            execution_payload = decode_execution_event(event)
            if isinstance(
                execution_payload,
                (PlanCreatedPayload, PlanRevisedPayload, PlanReplacedPayload),
            ):
                attributed_actor = cls._plan_actor(state, execution_payload.plan)
                kind = ActorHistoryAttributionKind.PLAN
            else:
                attributed_actor = cls._job_actor(state, _job_payload_id(execution_payload))
                kind = ActorHistoryAttributionKind.JOB
        elif event.event_type in RESOLUTION_EVENT_TYPES:
            resolution_payload = decode_resolution_event(event)
            attributed_actor = cls._job_actor(state, resolution_payload.job_id)
            kind = ActorHistoryAttributionKind.JOB_RESOLUTION
        if attributed_actor != actor_id or kind is None:
            return None
        return ActorHistoryAttribution(event.event_id, kind)

    def get_actor_history(
        self,
        run_id: RunId,
        branch_id: BranchId | None,
        actor_id: EntityId,
        *,
        position: HistoryPosition | None = None,
    ) -> tuple[ActorHistoryEntry, ...]:
        if type(actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        captured = self._capture(run_id, branch_id, position)
        self._actor_view(captured, actor_id)
        entries: list[ActorHistoryEntry] = []
        for transition in captured.history:
            attributions = tuple(
                attribution
                for event in transition.events
                if (attribution := self._event_attribution(event, actor_id, captured.state))
                is not None
            )
            if attributions:
                entries.append(ActorHistoryEntry(transition, attributions))
        return tuple(entries)
