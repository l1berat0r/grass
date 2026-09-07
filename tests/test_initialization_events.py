# SPDX-License-Identifier: GPL-3.0-only

import pytest

from grass.core import (
    BranchId,
    Event,
    EventPayload,
    InitializationEventPayloadError,
    ProjectionError,
    SimulationInitializedPayload,
    SimulationState,
    WorldDefinitionId,
    WorldDefinitionRef,
    decode_initialization_event,
    project_transition,
)
from grass.core.initialization_events import SIMULATION_INITIALIZED
from grass.core.world_events import ENTITY_CREATED
from tests.support import event_to_commit, rooted_store, transition_to_commit


def committed_initialization_event(payload: EventPayload, *, event_version: int = 1) -> Event:
    store = rooted_store("root")
    committed = store.commit_transition(
        transition_to_commit(
            "root",
            "genesis",
            0,
            [
                event_to_commit(
                    "initialized",
                    event_type=SIMULATION_INITIALIZED,
                    event_version=event_version,
                    payload=payload,
                )
            ],
        )
    )
    return committed.events[0]


def initialization_payload() -> EventPayload:
    return {
        "world_definition_ref": {
            "world_definition_id": "world",
            "version": "v1",
        },
        "world_definition_schema_version": 1,
    }


def test_decodes_simulation_initialized_payload() -> None:
    decoded = decode_initialization_event(committed_initialization_event(initialization_payload()))

    assert decoded == SimulationInitializedPayload(
        WorldDefinitionRef(WorldDefinitionId("world"), "v1"),
        1,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"world_definition_ref": {"world_definition_id": "world", "version": "v1"}},
        {
            "world_definition_ref": {
                "world_definition_id": "world",
                "version": "v1",
                "schema_version": 1,
            },
            "world_definition_schema_version": 1,
        },
        {
            "world_definition_ref": {"world_definition_id": "world"},
            "world_definition_schema_version": 1,
        },
    ],
)
def test_initialization_payload_schema_is_strict(payload: EventPayload) -> None:
    with pytest.raises(InitializationEventPayloadError, match="fields do not match schema"):
        decode_initialization_event(committed_initialization_event(payload))


def test_rejects_unsupported_initialization_event_version() -> None:
    event = committed_initialization_event(initialization_payload(), event_version=2)

    with pytest.raises(InitializationEventPayloadError, match="unsupported"):
        decode_initialization_event(event)


def test_projection_recognizes_initialization_without_mutating_world() -> None:
    store = rooted_store("root")
    transition = store.commit_transition(
        transition_to_commit(
            "root",
            "genesis",
            4,
            [
                event_to_commit(
                    "initialized",
                    event_type=SIMULATION_INITIALIZED,
                    payload=initialization_payload(),
                )
            ],
        )
    )

    state = project_transition(SimulationState.empty(BranchId("test:root")), transition)

    assert state.world == SimulationState.empty(BranchId("test:root")).world
    assert state.execution == SimulationState.empty(BranchId("test:root")).execution
    assert state.cognition == SimulationState.empty(BranchId("test:root")).cognition
    assert state.position.last_transition_ref == transition.transition_ref


def test_projection_requires_initialization_marker_to_be_first_and_unique() -> None:
    store = rooted_store("root")
    not_first = store.commit_transition(
        transition_to_commit(
            "root",
            "not-first",
            0,
            [
                event_to_commit(
                    "entity",
                    event_type=ENTITY_CREATED,
                    payload={"entity_id": "e", "entity_type": "Person", "properties": {}},
                ),
                event_to_commit(
                    "initialized",
                    event_type=SIMULATION_INITIALIZED,
                    payload=initialization_payload(),
                ),
            ],
        )
    )
    with pytest.raises(ProjectionError, match="first Event"):
        project_transition(SimulationState.empty(BranchId("test:root")), not_first)

    duplicate_store = rooted_store("root")
    duplicate = duplicate_store.commit_transition(
        transition_to_commit(
            "root",
            "duplicate",
            0,
            [
                event_to_commit(
                    "initialized-one",
                    event_type=SIMULATION_INITIALIZED,
                    payload=initialization_payload(),
                ),
                event_to_commit(
                    "initialized-two",
                    event_type=SIMULATION_INITIALIZED,
                    payload=initialization_payload(),
                ),
            ],
        )
    )
    with pytest.raises(ProjectionError, match="duplicate"):
        project_transition(SimulationState.empty(BranchId("test:root")), duplicate)


def test_projection_still_rejects_unknown_events() -> None:
    store = rooted_store("root")
    transition = store.commit_transition(
        transition_to_commit(
            "root",
            "unknown",
            0,
            [event_to_commit("unknown", event_type="UnknownSemanticEvent")],
        )
    )

    with pytest.raises(ProjectionError, match="unknown Event type"):
        project_transition(SimulationState.empty(BranchId("test:root")), transition)
