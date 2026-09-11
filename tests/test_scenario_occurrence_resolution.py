# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass

import pytest

from grass.core import (
    BranchId,
    DeterministicScenarioOccurrenceResolutionIntegrityError,
    EventId,
    InMemoryEventStore,
    LogicalDuration,
    LogicalTime,
    PreparedScenarioOccurrenceResolution,
    ScenarioOccurrenceResolutionProposal,
    ScenarioOccurrenceResolutionProvider,
    ScenarioOccurrenceResolutionRequest,
    ScenarioOccurrenceResolutionValidationError,
    SetStateVariableEffect,
    SimulationRunConfig,
    StaleHistoryError,
    StateVariableKey,
    TransitionId,
    TransitionRef,
    WorldDefinition,
    WorldScope,
    build_genesis_transition,
    load_world_definition,
    prepare_deterministic_scenario_occurrence_resolution,
    project_scenario_occurrences,
    replay_branch,
)
from grass.core.scenario_events import SCENARIO_OCCURRENCE_RESOLVED
from grass.core.world_events import STATE_VARIABLE_CHANGED
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def definition() -> WorldDefinition:
    return load_world_definition(
        {
            "world_definition_id": "world",
            "version": "1.0",
            "schema_version": 2,
            "vocabulary": {
                "entity_types": [],
                "relation_types": [],
                "resource_types": [],
                "state_variable_types": ["network_available"],
            },
            "initial_conditions": {
                "logical_time": 0,
                "entities": [],
                "relations": [],
                "resources": [],
                "state_variables": [
                    {
                        "scope": {"kind": "WORLD"},
                        "state_variable_type": "network_available",
                        "value": True,
                    }
                ],
            },
            "metadata": {},
            "scenario_event_rules": [
                {
                    "rule_id": "outage",
                    "trigger": {"kind": "AT_TIME", "logical_time": 10},
                }
            ],
        }
    )


def setup() -> tuple[
    WorldDefinition,
    InMemoryEventStore,
    ScenarioOccurrenceResolutionRequest,
]:
    world_definition = definition()
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    store.commit_transition(
        build_genesis_transition(
            world_definition,
            SimulationRunConfig(world_definition.ref),
            TransitionRef(root_id, stable_id(TransitionId, "genesis")),
            (stable_id(EventId, "genesis:0"), stable_id(EventId, "genesis:1")),
        )
    )
    position = store.head_position(root_id)
    history = store.read_visible_transitions(position)
    state = replay_branch(store, position)
    candidate = project_scenario_occurrences(world_definition, LogicalTime(0), history)[0]
    rule = world_definition.scenario_event_rules[0]
    request = ScenarioOccurrenceResolutionRequest(
        position,
        LogicalTime(10),
        LogicalDuration(10),
        candidate.source_ref,
        rule,
        candidate,
        state,
    )
    return world_definition, store, request


@dataclass
class StaticProvider:
    proposal: ScenarioOccurrenceResolutionProposal
    calls: int = 0

    def resolve(
        self, request: ScenarioOccurrenceResolutionRequest, /
    ) -> ScenarioOccurrenceResolutionProposal:
        assert (
            request.state.world.state_variables[StateVariableKey(WorldScope(), "network_available")]
            is True
        )
        self.calls += 1
        return self.proposal


def prepare(
    provider: ScenarioOccurrenceResolutionProvider,
    event_count: int,
) -> tuple[
    PreparedScenarioOccurrenceResolution,
    InMemoryEventStore,
    ScenarioOccurrenceResolutionRequest,
]:
    world_definition, store, request = setup()
    prepared = prepare_deterministic_scenario_occurrence_resolution(
        provider,
        request,
        world_definition,
        TransitionRef(request.base_history_position.branch_id, TransitionId("outage")),
        tuple(EventId(f"event-{index}") for index in range(event_count)),
        history_reader=store,
    )
    return prepared, store, request


def test_no_effect_occurrence_still_prepares_one_canonical_event() -> None:
    provider = StaticProvider(ScenarioOccurrenceResolutionProposal())
    prepared, store, request = prepare(provider, 1)

    transition = prepared.transition
    assert provider.calls == 1
    assert prepared.expected_head == request.base_history_position
    assert [event.event_type for event in transition.events] == [SCENARIO_OCCURRENCE_RESOLVED]
    assert transition.logical_time == LogicalTime(10)
    store.commit_transition(transition, expected_head=prepared.expected_head)


def test_occurrence_and_world_effect_commit_atomically_and_suppress_rebuild() -> None:
    provider = StaticProvider(
        ScenarioOccurrenceResolutionProposal(
            (SetStateVariableEffect(WorldScope(), "network_available", False),)
        )
    )
    prepared, store, request = prepare(provider, 2)
    transition = prepared.transition

    assert [event.event_type for event in transition.events] == [
        SCENARIO_OCCURRENCE_RESOLVED,
        STATE_VARIABLE_CHANGED,
    ]
    assert all(event.provenance.source_kind == "WORLD_RESOLVER" for event in transition.events)
    store.commit_transition(transition, expected_head=prepared.expected_head)
    state = replay_branch(store, store.head_position(request.base_history_position.branch_id))
    history = store.read_visible_transitions(
        store.head_position(request.base_history_position.branch_id)
    )

    assert state.world.state_variables[StateVariableKey(WorldScope(), "network_available")] is False
    assert project_scenario_occurrences(definition(), LogicalTime(10), history) == ()


def test_invalid_or_failed_provider_commits_nothing() -> None:
    class FailingProvider:
        def resolve(
            self, request: ScenarioOccurrenceResolutionRequest, /
        ) -> ScenarioOccurrenceResolutionProposal:
            del request
            raise RuntimeError("broken")

    class MalformedProvider:
        def resolve(
            self, request: ScenarioOccurrenceResolutionRequest, /
        ) -> ScenarioOccurrenceResolutionProposal:
            del request
            return "invalid"  # type: ignore[return-value]

    for provider in (FailingProvider(), MalformedProvider()):
        world_definition, store, request = setup()
        before = store.read_transitions(request.base_history_position.branch_id)
        with pytest.raises(DeterministicScenarioOccurrenceResolutionIntegrityError):
            prepare_deterministic_scenario_occurrence_resolution(
                provider,
                request,
                world_definition,
                TransitionRef(request.base_history_position.branch_id, TransitionId("outage")),
                (EventId("event"),),
                history_reader=store,
            )
        assert store.read_transitions(request.base_history_position.branch_id) == before


def test_invalid_effect_is_an_integrity_error_and_event_count_is_validation_error() -> None:
    provider = StaticProvider(
        ScenarioOccurrenceResolutionProposal(
            (SetStateVariableEffect(WorldScope(), "undeclared", False),)
        )
    )
    with pytest.raises(
        DeterministicScenarioOccurrenceResolutionIntegrityError,
        match="invalid proposal",
    ):
        prepare(provider, 2)

    with pytest.raises(ScenarioOccurrenceResolutionValidationError, match="exactly 1"):
        prepare(StaticProvider(ScenarioOccurrenceResolutionProposal()), 0)


def test_stale_prepared_occurrence_and_second_resolution_are_rejected() -> None:
    world_definition, store, request = setup()
    provider = StaticProvider(ScenarioOccurrenceResolutionProposal())
    prepared = prepare_deterministic_scenario_occurrence_resolution(
        provider,
        request,
        world_definition,
        TransitionRef(request.base_history_position.branch_id, TransitionId("outage")),
        (EventId("outage-event"),),
        history_reader=store,
    )
    store.commit_transition(
        transition_to_commit("root", "advance", 1, (event_to_commit("advance"),))
    )
    with pytest.raises(StaleHistoryError):
        store.commit_transition(prepared.transition, expected_head=prepared.expected_head)

    world_definition, store, request = setup()
    prepared = prepare_deterministic_scenario_occurrence_resolution(
        provider,
        request,
        world_definition,
        TransitionRef(request.base_history_position.branch_id, TransitionId("outage")),
        (EventId("resolved-event"),),
        history_reader=store,
    )
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    resolved_position = store.head_position(request.base_history_position.branch_id)
    resolved_state = replay_branch(store, resolved_position)
    resolved_candidate = request.due_candidate
    second_request = ScenarioOccurrenceResolutionRequest(
        resolved_position,
        LogicalTime(10),
        LogicalDuration(0),
        request.occurrence_ref,
        request.rule,
        resolved_candidate,
        resolved_state,
    )
    calls = provider.calls
    with pytest.raises(ScenarioOccurrenceResolutionValidationError, match="resolved"):
        prepare_deterministic_scenario_occurrence_resolution(
            provider,
            second_request,
            world_definition,
            TransitionRef(request.base_history_position.branch_id, TransitionId("again")),
            (EventId("again-event"),),
            history_reader=store,
        )
    assert provider.calls == calls


def test_preparation_reads_inherited_occurrence_consumption_from_store() -> None:
    world_definition, store, request = setup()
    prepared = prepare_deterministic_scenario_occurrence_resolution(
        StaticProvider(ScenarioOccurrenceResolutionProposal()),
        request,
        world_definition,
        TransitionRef(request.base_history_position.branch_id, TransitionId("resolved")),
        (EventId("resolved-event"),),
        history_reader=store,
    )
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    parent_position = store.head_position(request.base_history_position.branch_id)
    child_id = stable_id(BranchId, "child")
    store.fork_branch(child_id, parent_position)
    store.commit_transition(
        transition_to_commit(
            "child",
            "latest",
            10,
            (
                event_to_commit(
                    "latest",
                    event_type=STATE_VARIABLE_CHANGED,
                    payload={
                        "scope": {"kind": "WORLD"},
                        "state_variable_type": "network_available",
                        "value_after": True,
                    },
                ),
            ),
        )
    )
    position = store.head_position(child_id)
    second_request = ScenarioOccurrenceResolutionRequest(
        position,
        LogicalTime(10),
        LogicalDuration(0),
        request.occurrence_ref,
        request.rule,
        request.due_candidate,
        replay_branch(store, position),
    )
    provider = StaticProvider(ScenarioOccurrenceResolutionProposal())

    with pytest.raises(ScenarioOccurrenceResolutionValidationError, match="resolved"):
        prepare_deterministic_scenario_occurrence_resolution(
            provider,
            second_request,
            world_definition,
            TransitionRef(position.branch_id, TransitionId("duplicate")),
            (EventId("duplicate-event"),),
            history_reader=store,
        )
    assert provider.calls == 0
