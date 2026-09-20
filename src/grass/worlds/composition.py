# SPDX-License-Identifier: GPL-3.0-only

"""Occurrence-only composition for runnable schema-v3 worlds."""

from __future__ import annotations

from collections.abc import Mapping

from grass.core import (
    CommittedTransition,
    DecisionInvoker,
    DecisionTriggerContext,
    DecisionTriggerOutput,
    EventStore,
    JobId,
    LogicalTime,
    ProgressAnchor,
    ProviderBindingId,
    ResolutionProposal,
    ResolutionRequest,
    ScheduledResolution,
    SimulationRunConfig,
    SimulationState,
    WorldDefinition,
)
from grass.runtime import (
    JobStartProposal,
    PerceptionCandidate,
    ReadyPlanStep,
    RuntimeIdentitySource,
    SimulationEngine,
    UnsupportedRuntimeStateError,
)
from grass.worlds.mechanics import DataDefinedScenarioOccurrenceResolver


class WorldCompositionError(ValueError):
    """A WorldDefinition and run configuration cannot form this runtime."""


class _NoPerceptionProjector:
    def project(
        self,
        source_transition: CommittedTransition,
        state_after_source: SimulationState,
        /,
    ) -> tuple[PerceptionCandidate, ...]:
        del source_transition
        cognition = state_after_source.cognition
        if cognition.observations or cognition.decision_points or cognition.decisions:
            raise UnsupportedRuntimeStateError(
                "occurrence-only world composition does not support cognition state"
            )
        return ()


class _OccurrenceOnlyScheduleProjector:
    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> tuple[ScheduledResolution[JobId], ...]:
        del current_time, progress_anchors
        if state.execution.plans or state.execution.jobs:
            raise UnsupportedRuntimeStateError(
                "occurrence-only world composition does not support Plans or Jobs"
            )
        return ()


class _UnsupportedWorldResolver:
    def resolve(self, request: ResolutionRequest, /) -> ResolutionProposal:
        del request
        raise UnsupportedRuntimeStateError("occurrence-only world composition cannot resolve Jobs")


class _UnsupportedDecisionTriggerPolicy:
    def evaluate(self, context: DecisionTriggerContext, /) -> DecisionTriggerOutput:
        del context
        raise UnsupportedRuntimeStateError(
            "occurrence-only world composition does not support perception triggers"
        )


class _UnsupportedJobStartPolicy:
    def propose(
        self, ready_step: ReadyPlanStep, state: SimulationState, /
    ) -> JobStartProposal | None:
        del ready_step, state
        raise UnsupportedRuntimeStateError(
            "occurrence-only world composition does not support Job starts"
        )


def _jobs_do_not_conflict(
    left: ScheduledResolution[JobId], right: ScheduledResolution[JobId], /
) -> bool:
    del left, right
    return False


class OccurrenceRuntimeComposer:
    """Trusted adapter for the schema-v3 occurrence-only runtime subset."""

    def validate(
        self,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        /,
    ) -> None:
        if type(world_definition) is not WorldDefinition:
            raise TypeError("world_definition must be a WorldDefinition")
        if type(run_config) is not SimulationRunConfig:
            raise TypeError("run_config must be a SimulationRunConfig")
        if world_definition.schema_version != 3:
            raise WorldCompositionError("occurrence composition requires schema version 3")
        if run_config.world_definition_ref != world_definition.ref:
            raise WorldCompositionError("run_config must reference world_definition")
        occurrence_times = tuple(
            rule.logical_time for rule in world_definition.scenario_event_rules
        )
        if len(set(occurrence_times)) != len(occurrence_times):
            raise WorldCompositionError("duplicate scenario occurrence times are unsupported")

    def compose(
        self,
        *,
        event_store: EventStore,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        identity_source: RuntimeIdentitySource,
        decision_invokers: Mapping[ProviderBindingId, DecisionInvoker] | None = None,
    ) -> SimulationEngine:
        self.validate(world_definition, run_config)
        return SimulationEngine(
            event_store=event_store,
            world_definition=world_definition,
            run_config=run_config,
            identity_source=identity_source,
            schedule_projector=_OccurrenceOnlyScheduleProjector(),
            conflict_predicate=_jobs_do_not_conflict,
            world_resolution_provider=_UnsupportedWorldResolver(),
            scenario_occurrence_resolution_provider=DataDefinedScenarioOccurrenceResolver(
                world_definition
            ),
            perception_projector=_NoPerceptionProjector(),
            decision_trigger_policy=_UnsupportedDecisionTriggerPolicy(),
            decision_invokers={} if decision_invokers is None else decision_invokers,
            job_start_policy=_UnsupportedJobStartPolicy(),
        )


def compose_occurrence_engine(
    *,
    event_store: EventStore,
    world_definition: WorldDefinition,
    run_config: SimulationRunConfig,
    identity_source: RuntimeIdentitySource,
    decision_invokers: Mapping[ProviderBindingId, DecisionInvoker] | None = None,
) -> SimulationEngine:
    """Compose the existing engine for schema-v3 occurrence-only execution."""

    return OccurrenceRuntimeComposer().compose(
        event_store=event_store,
        world_definition=world_definition,
        run_config=run_config,
        identity_source=identity_source,
        decision_invokers=decision_invokers,
    )
