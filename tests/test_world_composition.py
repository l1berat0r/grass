# SPDX-License-Identifier: GPL-3.0-only

"""Focused tests for schema-v3 occurrence mechanics and runtime composition."""

from __future__ import annotations

import asyncio

import pytest

from grass.core import (
    BranchId,
    DeterministicScenarioOccurrenceResolutionIntegrityError,
    EventId,
    InMemoryEventStore,
    LogicalDuration,
    LogicalTime,
    ScenarioOccurrenceResolutionRequest,
    SetStateVariableEffect,
    SimulationRunConfig,
    StateVariableKey,
    TransitionId,
    TransitionRef,
    WorldDefinition,
    WorldDefinitionRef,
    WorldScope,
    build_genesis_transition,
    load_world_definition,
    project_scenario_occurrences,
    replay_branch,
)
from grass.runtime import UuidRuntimeIdentitySource
from grass.worlds.composition import WorldCompositionError, compose_occurrence_engine
from grass.worlds.mechanics import (
    DataDefinedScenarioOccurrenceResolver,
    WorldMechanicExecutionError,
)

ROOT = BranchId("root")


def _builtin_rule(rule_id: str, logical_time: int, value: object) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "trigger": {"kind": "AT_TIME", "logical_time": logical_time},
        "mechanic": {
            "kind": "BUILTIN",
            "usage": "SET_STATE_VARIABLE",
            "implementation": "CONSTANT",
            "target": {
                "scope": {"kind": "WORLD"},
                "state_variable_type": "counter",
            },
            "value": value,
        },
    }


def _gel_rule(rule_id: str, logical_time: int) -> dict[str, object]:
    integer_schema = {"type": "INTEGER", "minimum": -100, "maximum": 100}
    return {
        "rule_id": rule_id,
        "trigger": {"kind": "AT_TIME", "logical_time": logical_time},
        "mechanic": {
            "kind": "GEL",
            "usage": "SET_STATE_VARIABLE",
            "target": {
                "scope": {"kind": "WORLD"},
                "state_variable_type": "counter",
            },
            "program": {
                "source": "return {new_value: current_value + 3};",
                "language_version": 1,
                "input_schema": {
                    "type": "OBJECT",
                    "fields": {"current_value": integer_schema},
                },
                "output_schema": {
                    "type": "OBJECT",
                    "fields": {"new_value": integer_schema},
                },
            },
        },
    }


def _definition(rules: list[dict[str, object]], *, initial_value: object = 1) -> WorldDefinition:
    document: dict[str, object] = {
        "world_definition_id": "composed-world",
        "version": "1.0",
        "schema_version": 3,
        "vocabulary": {
            "entity_types": [],
            "relation_types": [],
            "resource_types": [],
            "state_variable_types": ["counter"],
        },
        "initial_conditions": {
            "logical_time": 0,
            "entities": [],
            "relations": [],
            "resources": [],
            "state_variables": [
                {
                    "scope": {"kind": "WORLD"},
                    "state_variable_type": "counter",
                    "value": initial_value,
                }
            ],
        },
        "metadata": {},
        "scenario_event_rules": rules,
    }
    return load_world_definition(document)


def _request(definition: WorldDefinition) -> ScenarioOccurrenceResolutionRequest:
    store = InMemoryEventStore()
    store.create_root_branch(ROOT)
    config = SimulationRunConfig(definition.ref)
    store.commit_transition(
        build_genesis_transition(
            definition,
            config,
            TransitionRef(ROOT, TransitionId("genesis")),
            (EventId("genesis:0"), EventId("genesis:1")),
        )
    )
    position = store.head_position(ROOT)
    state = replay_branch(store, position)
    candidate = project_scenario_occurrences(
        definition,
        LogicalTime(0),
        store.read_visible_transitions(position),
    )[0]
    rule = definition.scenario_event_rules[0]
    return ScenarioOccurrenceResolutionRequest(
        position,
        rule.logical_time,
        LogicalDuration(rule.logical_time.nanoseconds_from_origin),
        candidate.source_ref,
        rule,
        candidate,
        state,
    )


def test_composed_engine_executes_builtin_then_gel_occurrences() -> None:
    definition = _definition([_builtin_rule("constant", 5, 4), _gel_rule("increment", 10)])
    config = SimulationRunConfig(definition.ref)
    store = InMemoryEventStore()
    store.create_root_branch(ROOT)
    store.commit_transition(
        build_genesis_transition(
            definition,
            config,
            TransitionRef(ROOT, TransitionId("genesis")),
            (EventId("genesis:0"), EventId("genesis:1")),
        )
    )
    engine = compose_occurrence_engine(
        event_store=store,
        world_definition=definition,
        run_config=config,
        identity_source=UuidRuntimeIdentitySource(),
    )

    result = asyncio.run(engine.advance(ROOT, target_time=LogicalTime(10)))
    state = replay_branch(store, store.head_position(ROOT))

    assert result.committed_steps == 2
    assert state.world.state_variables[StateVariableKey(WorldScope(), "counter")] == 7


@pytest.mark.parametrize("value", [None, 1.5, 2**63])
def test_gel_mechanic_rejects_values_outside_supported_subset(value: object) -> None:
    definition = _definition([_gel_rule("gel", 5)], initial_value=value)
    resolver = DataDefinedScenarioOccurrenceResolver(definition)

    with pytest.raises(WorldMechanicExecutionError):
        resolver.resolve(_request(definition))


def test_resolver_rejects_request_for_changed_exact_rule() -> None:
    configured = _definition([_builtin_rule("constant", 5, 1)])
    changed = _definition([_builtin_rule("constant", 5, 2)])

    with pytest.raises(WorldMechanicExecutionError, match="does not match"):
        DataDefinedScenarioOccurrenceResolver(configured).resolve(_request(changed))


def test_composition_rejects_duplicate_times_and_mismatched_config() -> None:
    duplicate_times = _definition([_builtin_rule("first", 5, 1), _builtin_rule("second", 5, 2)])
    store = InMemoryEventStore()
    identity_source = UuidRuntimeIdentitySource()

    with pytest.raises(WorldCompositionError, match="duplicate"):
        compose_occurrence_engine(
            event_store=store,
            world_definition=duplicate_times,
            run_config=SimulationRunConfig(duplicate_times.ref),
            identity_source=identity_source,
        )

    with pytest.raises(WorldCompositionError, match="reference"):
        compose_occurrence_engine(
            event_store=store,
            world_definition=duplicate_times,
            run_config=SimulationRunConfig(
                WorldDefinitionRef(duplicate_times.world_definition_id, "different")
            ),
            identity_source=identity_source,
        )


def test_composition_rejects_pre_v3_world_definition() -> None:
    document: dict[str, object] = {
        "world_definition_id": "legacy-world",
        "version": "1.0",
        "schema_version": 2,
        "vocabulary": {
            "entity_types": [],
            "relation_types": [],
            "resource_types": [],
            "state_variable_types": [],
        },
        "initial_conditions": {
            "logical_time": 0,
            "entities": [],
            "relations": [],
            "resources": [],
            "state_variables": [],
        },
        "metadata": {},
        "scenario_event_rules": [],
    }
    definition = load_world_definition(document)

    with pytest.raises(WorldCompositionError, match="schema version 3"):
        compose_occurrence_engine(
            event_store=InMemoryEventStore(),
            world_definition=definition,
            run_config=SimulationRunConfig(definition.ref),
            identity_source=UuidRuntimeIdentitySource(),
        )


def test_builtin_resolver_always_emits_one_set_effect() -> None:
    definition = _definition([_builtin_rule("constant", 5, {"value": [1, True]})])

    proposal = DataDefinedScenarioOccurrenceResolver(definition).resolve(_request(definition))

    assert len(proposal.effects) == 1
    assert type(proposal.effects[0]) is SetStateVariableEffect
    assert proposal.effects[0].value_after == {"value": (1, True)}


def test_gel_failure_through_engine_commits_nothing() -> None:
    definition = _definition([_gel_rule("gel", 5)], initial_value=100)
    config = SimulationRunConfig(definition.ref)
    store = InMemoryEventStore()
    store.create_root_branch(ROOT)
    store.commit_transition(
        build_genesis_transition(
            definition,
            config,
            TransitionRef(ROOT, TransitionId("genesis")),
            (EventId("genesis:0"), EventId("genesis:1")),
        )
    )
    before_position = store.head_position(ROOT)
    before_history = store.read_transitions(ROOT)
    engine = compose_occurrence_engine(
        event_store=store,
        world_definition=definition,
        run_config=config,
        identity_source=UuidRuntimeIdentitySource(),
    )

    with pytest.raises(DeterministicScenarioOccurrenceResolutionIntegrityError):
        asyncio.run(engine.step(ROOT))

    assert store.head_position(ROOT) == before_position
    assert store.read_transitions(ROOT) == before_history
