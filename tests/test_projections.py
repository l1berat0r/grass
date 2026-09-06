# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Sequence

import pytest

from grass.core import (
    BranchId,
    CommittedTransition,
    EntityId,
    EntityScope,
    Event,
    EventId,
    EventPayload,
    InMemoryEventStore,
    LogicalTime,
    ProjectionError,
    Provenance,
    RelationId,
    ResourceKey,
    SimulationState,
    StateVariableKey,
    TransitionId,
    WorldScope,
    project_transition,
    replay_transitions,
)
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
from tests.support import event_to_commit, rooted_store, transition_to_commit


def commit_world_transition(
    store: InMemoryEventStore,
    transition: str,
    logical_time: int,
    events: Sequence[tuple[str, EventPayload]],
    *,
    branch: str = "branch",
) -> CommittedTransition:
    records = [
        event_to_commit(
            f"{branch}:{transition}:{index}",
            event_type=event_type,
            payload=payload,
        )
        for index, (event_type, payload) in enumerate(events)
    ]
    return store.commit_transition(transition_to_commit(branch, transition, logical_time, records))


def entity_created(entity_id: str, **properties: str) -> tuple[str, EventPayload]:
    return (
        ENTITY_CREATED,
        {
            "entity_id": entity_id,
            "entity_type": "Person",
            "properties": properties,
        },
    )


def relation_created(relation_id: str, entity_id: str) -> tuple[str, EventPayload]:
    return (
        RELATION_CREATED,
        {
            "relation_id": relation_id,
            "relation_type": "Membership",
            "participants": [{"role": "member", "entity_id": entity_id}],
            "properties": {},
        },
    )


def test_projects_complete_transition_using_final_state_references() -> None:
    store = rooted_store("branch")
    transition = commit_world_transition(
        store,
        "genesis",
        10,
        [
            (
                RELATION_CREATED,
                {
                    "relation_id": "membership",
                    "relation_type": "Membership",
                    "participants": [
                        {"role": "member", "entity_id": "person"},
                        {"role": "group", "entity_id": "group"},
                    ],
                    "properties": {"since": 1},
                },
            ),
            (
                RESOURCE_CHANGED,
                {
                    "entity_id": "person",
                    "resource_type": "balance",
                    "quantity_after": -4,
                },
            ),
            (
                STATE_VARIABLE_CHANGED,
                {
                    "scope": {"kind": "ENTITY", "entity_id": "person"},
                    "state_variable_type": "condition",
                    "value_after": {"status": "ready"},
                },
            ),
            entity_created("person", name="Person"),
            entity_created("group", name="Group"),
        ],
    )

    state = project_transition(SimulationState.empty(BranchId("test:branch")), transition)

    person_id = EntityId("person")
    relation = state.world.relations[RelationId("membership")]
    assert state.position.last_transition_ref == transition.transition_ref
    assert state.position.last_sequence == 5
    assert state.position.logical_time == LogicalTime(10)
    assert state.world.entities[person_id].properties == {"name": "Person"}
    assert {item.entity_id for item in relation.participants} == {
        person_id,
        EntityId("group"),
    }
    assert state.world.resources[ResourceKey(person_id, "balance")] == -4
    variable_key = StateVariableKey(EntityScope(person_id), "condition")
    assert state.world.state_variables[variable_key] == {"status": "ready"}


def test_update_payloads_replace_complete_values_and_deactivation_preserves_identity() -> None:
    store = rooted_store("branch")
    genesis = commit_world_transition(
        store,
        "genesis",
        1,
        [
            entity_created("person", old="discarded"),
            entity_created("group"),
            relation_created("membership", "person"),
        ],
    )
    updated = commit_world_transition(
        store,
        "update",
        2,
        [
            (
                ENTITY_UPDATED,
                {"entity_id": "person", "properties_after": {"new": "kept"}},
            ),
            (
                RELATION_UPDATED,
                {
                    "relation_id": "membership",
                    "participants_after": [{"role": "member", "entity_id": "group"}],
                    "properties_after": {"changed": True},
                },
            ),
            (
                RESOURCE_CHANGED,
                {
                    "entity_id": "person",
                    "resource_type": "balance",
                    "quantity_after": 8,
                },
            ),
            (
                STATE_VARIABLE_CHANGED,
                {
                    "scope": {"kind": "ENTITY", "entity_id": "person"},
                    "state_variable_type": "condition",
                    "value_after": "ready",
                },
            ),
        ],
    )
    deactivated = commit_world_transition(
        store,
        "deactivate",
        3,
        [
            (ENTITY_DEACTIVATED, {"entity_id": "person"}),
            (RELATION_DEACTIVATED, {"relation_id": "membership"}),
        ],
    )

    state = replay_transitions(BranchId("test:branch"), (genesis, updated, deactivated))

    entity = state.world.entities[EntityId("person")]
    relation = state.world.relations[RelationId("membership")]
    assert entity.entity_type == "Person"
    assert entity.properties == {"new": "kept"}
    assert not entity.active
    assert relation.relation_type == "Membership"
    assert relation.properties == {"changed": True}
    assert {item.entity_id for item in relation.participants} == {EntityId("group")}
    assert not relation.active
    assert state.world.resources[ResourceKey(EntityId("person"), "balance")] == 8
    assert (
        state.world.state_variables[StateVariableKey(EntityScope(EntityId("person")), "condition")]
        == "ready"
    )


@pytest.mark.parametrize(
    "invalid_event, message",
    [
        ((ENTITY_UPDATED, {"entity_id": "entity", "properties_after": {}}), "inactive"),
        ((ENTITY_DEACTIVATED, {"entity_id": "entity"}), "inactive"),
    ],
)
def test_inactive_entity_cannot_be_updated_or_deactivated_again(
    invalid_event: tuple[str, EventPayload], message: str
) -> None:
    store = rooted_store("branch")
    state = replay_transitions(
        BranchId("test:branch"),
        (
            commit_world_transition(store, "create", 1, [entity_created("entity")]),
            commit_world_transition(
                store,
                "deactivate",
                2,
                [(ENTITY_DEACTIVATED, {"entity_id": "entity"})],
            ),
        ),
    )
    invalid = commit_world_transition(store, "invalid", 3, [invalid_event])

    with pytest.raises(ProjectionError, match=message):
        project_transition(state, invalid)

    assert state.position.last_sequence == 2
    assert not state.world.entities[EntityId("entity")].active


@pytest.mark.parametrize(
    "invalid_event",
    [
        (
            RELATION_UPDATED,
            {
                "relation_id": "relation",
                "participants_after": [{"role": "member", "entity_id": "entity"}],
                "properties_after": {},
            },
        ),
        (RELATION_DEACTIVATED, {"relation_id": "relation"}),
    ],
)
def test_inactive_relation_cannot_be_updated_or_deactivated_again(
    invalid_event: tuple[str, EventPayload],
) -> None:
    store = rooted_store("branch")
    state = replay_transitions(
        BranchId("test:branch"),
        (
            commit_world_transition(
                store,
                "create",
                1,
                [entity_created("entity"), relation_created("relation", "entity")],
            ),
            commit_world_transition(
                store,
                "deactivate",
                2,
                [(RELATION_DEACTIVATED, {"relation_id": "relation"})],
            ),
        ),
    )
    invalid = commit_world_transition(store, "invalid", 3, [invalid_event])

    with pytest.raises(ProjectionError, match="inactive"):
        project_transition(state, invalid)


@pytest.mark.parametrize(
    "event",
    [
        (ENTITY_UPDATED, {"entity_id": "missing", "properties_after": {}}),
        (ENTITY_DEACTIVATED, {"entity_id": "missing"}),
        (
            RELATION_UPDATED,
            {
                "relation_id": "missing",
                "participants_after": [{"role": "member", "entity_id": "entity"}],
                "properties_after": {},
            },
        ),
        (RELATION_DEACTIVATED, {"relation_id": "missing"}),
    ],
)
def test_missing_entity_or_relation_cannot_be_updated_or_deactivated(
    event: tuple[str, EventPayload],
) -> None:
    store = rooted_store("branch")
    base_transition = commit_world_transition(store, "base", 1, [entity_created("entity")])
    state = project_transition(SimulationState.empty(BranchId("test:branch")), base_transition)
    invalid = commit_world_transition(store, "invalid", 2, [event])

    with pytest.raises(ProjectionError, match="does not exist"):
        project_transition(state, invalid)


def test_existing_entity_and_relation_cannot_be_created_again() -> None:
    entity_store = rooted_store("branch")
    entity_state = project_transition(
        SimulationState.empty(BranchId("test:branch")),
        commit_world_transition(
            entity_store,
            "base",
            1,
            [entity_created("entity")],
        ),
    )
    duplicate_entity = commit_world_transition(
        entity_store, "duplicate-entity", 2, [entity_created("entity")]
    )
    with pytest.raises(ProjectionError, match="Entity already exists"):
        project_transition(entity_state, duplicate_entity)

    relation_store = rooted_store("branch")
    relation_state = project_transition(
        SimulationState.empty(BranchId("test:branch")),
        commit_world_transition(
            relation_store,
            "base",
            1,
            [entity_created("entity"), relation_created("relation", "entity")],
        ),
    )
    duplicate_relation = commit_world_transition(
        relation_store,
        "duplicate-relation",
        2,
        [relation_created("relation", "entity")],
    )
    with pytest.raises(ProjectionError, match="Relation already exists"):
        project_transition(relation_state, duplicate_relation)


@pytest.mark.parametrize(
    "events, message",
    [
        (
            [entity_created("duplicate"), entity_created("duplicate")],
            "duplicate Entity write",
        ),
        (
            [
                entity_created("entity"),
                relation_created("duplicate", "entity"),
                relation_created("duplicate", "entity"),
            ],
            "duplicate Relation write",
        ),
        (
            [
                entity_created("entity"),
                (
                    RESOURCE_CHANGED,
                    {
                        "entity_id": "entity",
                        "resource_type": "balance",
                        "quantity_after": 1,
                    },
                ),
                (
                    RESOURCE_CHANGED,
                    {
                        "entity_id": "entity",
                        "resource_type": "balance",
                        "quantity_after": 2,
                    },
                ),
            ],
            "duplicate Resource write",
        ),
        (
            [
                (
                    STATE_VARIABLE_CHANGED,
                    {
                        "scope": {"kind": "WORLD"},
                        "state_variable_type": "weather",
                        "value_after": "rain",
                    },
                ),
                (
                    STATE_VARIABLE_CHANGED,
                    {
                        "scope": {"kind": "WORLD"},
                        "state_variable_type": "weather",
                        "value_after": "sun",
                    },
                ),
            ],
            "duplicate StateVariable write",
        ),
    ],
)
def test_duplicate_target_writes_fail_without_publishing_partial_state(
    events: Sequence[tuple[str, EventPayload]], message: str
) -> None:
    store = rooted_store("branch")
    transition = commit_world_transition(store, "invalid", 1, events)
    original = SimulationState.empty(BranchId("test:branch"))

    with pytest.raises(ProjectionError, match=message):
        project_transition(original, transition)

    assert original == SimulationState.empty(BranchId("test:branch"))


def test_unknown_or_malformed_event_fails_complete_transition_atomically() -> None:
    store = rooted_store("branch")
    original = SimulationState.empty(BranchId("test:branch"))
    unknown = commit_world_transition(
        store,
        "unknown",
        1,
        [entity_created("would-have-been-created"), ("FutureEvent", {})],
    )

    with pytest.raises(ProjectionError, match="unknown Event type"):
        project_transition(original, unknown)
    assert original.world.entities == {}
    assert original.position.last_sequence == 0

    malformed_store = rooted_store("branch")
    malformed = commit_world_transition(
        malformed_store,
        "malformed",
        1,
        [(ENTITY_CREATED, {"entity_id": "missing-fields"})],
    )
    with pytest.raises(ProjectionError, match="fields do not match schema"):
        project_transition(original, malformed)


@pytest.mark.parametrize(
    "event",
    [
        relation_created("relation", "missing"),
        (
            RESOURCE_CHANGED,
            {
                "entity_id": "missing",
                "resource_type": "balance",
                "quantity_after": 1,
            },
        ),
        (
            STATE_VARIABLE_CHANGED,
            {
                "scope": {"kind": "ENTITY", "entity_id": "missing"},
                "state_variable_type": "condition",
                "value_after": True,
            },
        ),
    ],
)
def test_dangling_final_state_references_fail_atomically(
    event: tuple[str, EventPayload],
) -> None:
    store = rooted_store("branch")
    original = SimulationState.empty(BranchId("test:branch"))
    transition = commit_world_transition(store, "dangling", 1, [event])

    with pytest.raises(ProjectionError, match="existing Entities"):
        project_transition(original, transition)

    assert original == SimulationState.empty(BranchId("test:branch"))


def test_projection_rejects_unsupported_known_event_version() -> None:
    store = rooted_store("branch")
    transition = store.commit_transition(
        transition_to_commit(
            "branch",
            "unsupported",
            1,
            [
                event_to_commit(
                    "unsupported",
                    event_type=ENTITY_CREATED,
                    event_version=2,
                    payload={
                        "entity_id": "entity",
                        "entity_type": "Person",
                        "properties": {},
                    },
                )
            ],
        )
    )

    with pytest.raises(ProjectionError, match="unsupported EntityCreated version"):
        project_transition(SimulationState.empty(BranchId("test:branch")), transition)


def test_projection_rejects_wrong_branch_sequence_gap_and_decreasing_time() -> None:
    store = rooted_store("branch")
    first = commit_world_transition(store, "first", 10, [entity_created("one")])
    second = commit_world_transition(store, "second", 10, [entity_created("two")])
    state = project_transition(SimulationState.empty(BranchId("test:branch")), first)

    with pytest.raises(ProjectionError, match="expected Event sequence 1"):
        project_transition(SimulationState.empty(BranchId("test:branch")), second)

    other_store = rooted_store("other")
    other = commit_world_transition(
        other_store, "other", 10, [entity_created("other")], branch="other"
    )
    with pytest.raises(ProjectionError, match="branch does not match"):
        project_transition(state, other)

    decreasing = CommittedTransition(
        (
            Event(
                event_id=EventId("decreasing"),
                branch_id=BranchId("test:branch"),
                sequence=2,
                logical_time=LogicalTime(9),
                transition_id=TransitionId("decreasing"),
                event_type=ENTITY_CREATED,
                event_version=1,
                payload={
                    "entity_id": "later",
                    "entity_type": "Person",
                    "properties": {},
                },
                provenance=Provenance("ENGINE"),
            ),
        )
    )
    with pytest.raises(ProjectionError, match="nondecreasing"):
        project_transition(state, decreasing)


def test_incremental_projection_matches_full_replay() -> None:
    store = rooted_store("branch")
    transitions = (
        commit_world_transition(store, "create", 1, [entity_created("entity")]),
        commit_world_transition(
            store,
            "update",
            2,
            [
                (
                    ENTITY_UPDATED,
                    {
                        "entity_id": "entity",
                        "properties_after": {"phase": "updated"},
                    },
                ),
                (
                    RESOURCE_CHANGED,
                    {
                        "entity_id": "entity",
                        "resource_type": "balance",
                        "quantity_after": 4,
                    },
                ),
            ],
        ),
        commit_world_transition(
            store,
            "variable",
            3,
            [
                (
                    STATE_VARIABLE_CHANGED,
                    {
                        "scope": {"kind": "WORLD"},
                        "state_variable_type": "weather",
                        "value_after": "clear",
                    },
                )
            ],
        ),
    )
    branch_id = BranchId("test:branch")
    incremental = SimulationState.empty(branch_id)
    for transition in transitions:
        incremental = project_transition(incremental, transition)

    replayed = replay_transitions(branch_id, transitions)

    assert incremental == replayed
    assert replayed.world.state_variables[StateVariableKey(WorldScope(), "weather")] == "clear"
