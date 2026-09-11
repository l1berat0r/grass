# SPDX-License-Identifier: GPL-3.0-only

import pytest

from grass.core import (
    BranchId,
    EventId,
    InMemoryEventStore,
    LogicalTime,
    ScenarioEventRuleId,
    ScenarioOccurrenceHistoryError,
    ScenarioOccurrenceRef,
    SimulationRunConfig,
    TransitionId,
    TransitionRef,
    WorldDefinition,
    build_genesis_transition,
    derive_resolved_scenario_occurrences,
    load_world_definition,
    project_scenario_occurrences,
)
from grass.core.scenario_events import (
    SCENARIO_OCCURRENCE_RESOLVED,
    scenario_occurrence_ref_payload,
)
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def definition_document() -> dict[str, object]:
    return {
        "world_definition_id": "world",
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
        "scenario_event_rules": [
            {"rule_id": "outage", "trigger": {"kind": "AT_TIME", "logical_time": 10}}
        ],
    }


def setup_store() -> tuple[WorldDefinition, InMemoryEventStore, BranchId]:
    definition = load_world_definition(definition_document())
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    store.commit_transition(
        build_genesis_transition(
            definition,
            SimulationRunConfig(definition.ref),
            TransitionRef(root_id, stable_id(TransitionId, "genesis")),
            (stable_id(EventId, "genesis"),),
        )
    )
    return definition, store, root_id


def test_projects_one_ephemeral_at_time_candidate_and_rebuilds_identically() -> None:
    definition, store, root_id = setup_store()
    position = store.head_position(root_id)
    history = store.read_visible_transitions(position)

    first = project_scenario_occurrences(definition, LogicalTime(0), history)
    second = project_scenario_occurrences(definition, LogicalTime(0), history)

    assert first == second
    assert len(first) == 1
    assert first[0].logical_time == LogicalTime(10)
    assert first[0].kind == "SCENARIO_EVENT"
    assert type(first[0].source_ref) is ScenarioOccurrenceRef


def test_resolved_history_suppresses_rebuild_and_is_inherited_after_fork() -> None:
    definition, store, root_id = setup_store()
    genesis_position = store.head_position(root_id)
    before_child = stable_id(BranchId, "before")
    store.fork_branch(before_child, genesis_position)
    history = store.read_visible_transitions(genesis_position)
    candidate = project_scenario_occurrences(definition, LogicalTime(0), history)[0]
    occurrence_ref = candidate.source_ref
    store.commit_transition(
        transition_to_commit(
            "root",
            "outage",
            10,
            (
                event_to_commit(
                    "outage",
                    event_type=SCENARIO_OCCURRENCE_RESOLVED,
                    payload={"occurrence_ref": scenario_occurrence_ref_payload(occurrence_ref)},
                ),
            ),
        )
    )
    after_position = store.head_position(root_id)
    after_child = stable_id(BranchId, "after")
    store.fork_branch(after_child, after_position)

    root_history = store.read_visible_transitions(after_position)
    before_history = store.read_visible_transitions(store.head_position(before_child))
    after_history = store.read_visible_transitions(store.head_position(after_child))

    assert project_scenario_occurrences(definition, LogicalTime(10), root_history) == ()
    assert len(project_scenario_occurrences(definition, LogicalTime(0), before_history)) == 1
    assert project_scenario_occurrences(definition, LogicalTime(10), after_history) == ()
    assert derive_resolved_scenario_occurrences(root_history) == frozenset({occurrence_ref})


def test_duplicate_or_overdue_occurrences_fail_explicitly() -> None:
    definition, store, root_id = setup_store()
    genesis_position = store.head_position(root_id)
    history = store.read_visible_transitions(genesis_position)
    occurrence_ref = project_scenario_occurrences(definition, LogicalTime(0), history)[0].source_ref

    overdue_definition, overdue_store, overdue_root = setup_store()
    overdue_store.commit_transition(
        transition_to_commit("root", "advance", 11, (event_to_commit("advance"),))
    )
    overdue_position = overdue_store.head_position(overdue_root)
    with pytest.raises(ScenarioOccurrenceHistoryError, match="cannot precede"):
        project_scenario_occurrences(
            overdue_definition,
            LogicalTime(11),
            overdue_store.read_visible_transitions(overdue_position),
        )

    payload = {"occurrence_ref": scenario_occurrence_ref_payload(occurrence_ref)}
    first = store.commit_transition(
        transition_to_commit(
            "root",
            "first",
            10,
            (event_to_commit("first", event_type=SCENARIO_OCCURRENCE_RESOLVED, payload=payload),),
        )
    )
    second = store.commit_transition(
        transition_to_commit(
            "root",
            "second",
            10,
            (event_to_commit("second", event_type=SCENARIO_OCCURRENCE_RESOLVED, payload=payload),),
        )
    )
    with pytest.raises(ScenarioOccurrenceHistoryError, match="more than once"):
        derive_resolved_scenario_occurrences((first, second))


@pytest.mark.parametrize("resolved_time", [5, 11])
def test_projector_rejects_occurrence_resolved_outside_declared_time(
    resolved_time: int,
) -> None:
    definition, store, root_id = setup_store()
    genesis_position = store.head_position(root_id)
    occurrence_ref = project_scenario_occurrences(
        definition,
        LogicalTime(0),
        store.read_visible_transitions(genesis_position),
    )[0].source_ref
    store.commit_transition(
        transition_to_commit(
            "root",
            "outage",
            resolved_time,
            (
                event_to_commit(
                    "outage",
                    event_type=SCENARIO_OCCURRENCE_RESOLVED,
                    payload={"occurrence_ref": scenario_occurrence_ref_payload(occurrence_ref)},
                ),
            ),
        )
    )
    position = store.head_position(root_id)

    with pytest.raises(ScenarioOccurrenceHistoryError, match="declared AT_TIME"):
        project_scenario_occurrences(
            definition,
            LogicalTime(resolved_time),
            store.read_visible_transitions(position),
        )


def test_projector_rejects_wrong_world_definition() -> None:
    definition, store, root_id = setup_store()
    document = definition_document()
    document["world_definition_id"] = "other"
    other = load_world_definition(document)
    position = store.head_position(root_id)
    history = store.read_visible_transitions(position)

    with pytest.raises(ScenarioOccurrenceHistoryError, match="does not match"):
        project_scenario_occurrences(other, LogicalTime(0), history)

    assert definition.scenario_event_rule(ScenarioEventRuleId("missing")) is None
