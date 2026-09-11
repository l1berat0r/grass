# SPDX-License-Identifier: GPL-3.0-only

import pytest

from grass.core import (
    BranchId,
    CommittedTransition,
    Event,
    EventId,
    LogicalTime,
    ProjectionError,
    Provenance,
    ScenarioEventPayloadError,
    ScenarioEventRuleId,
    ScenarioEventRuleRef,
    ScenarioOccurrenceRef,
    ScenarioOccurrenceResolvedPayload,
    SimulationState,
    TransitionId,
    WorldDefinitionId,
    WorldDefinitionRef,
    decode_scenario_event,
    project_transition,
)
from grass.core.scenario_events import (
    SCENARIO_OCCURRENCE_RESOLVED,
    scenario_occurrence_ref_payload,
)


def occurrence_ref() -> ScenarioOccurrenceRef:
    return ScenarioOccurrenceRef(
        ScenarioEventRuleRef(
            WorldDefinitionRef(WorldDefinitionId("world"), "1.0"),
            ScenarioEventRuleId("outage"),
        )
    )


def occurrence_event(*, sequence: int = 1, version: int = 1) -> Event:
    return Event(
        EventId(f"event-{sequence}"),
        BranchId("branch"),
        sequence,
        LogicalTime(10),
        TransitionId("occurrence"),
        SCENARIO_OCCURRENCE_RESOLVED,
        version,
        {"occurrence_ref": scenario_occurrence_ref_payload(occurrence_ref())},
        Provenance("WORLD_RESOLVER"),
    )


def test_decodes_strict_version_one_occurrence_reference() -> None:
    assert decode_scenario_event(occurrence_event()) == ScenarioOccurrenceResolvedPayload(
        occurrence_ref()
    )


@pytest.mark.parametrize(
    "payload,version,message",
    [
        ({}, 1, "fields do not match"),
        ({"occurrence_ref": {}, "extra": True}, 1, "fields do not match"),
        ({"occurrence_ref": {}}, 1, "scenario_event_rule_ref"),
        (
            {"occurrence_ref": scenario_occurrence_ref_payload(occurrence_ref())},
            2,
            "unsupported",
        ),
    ],
)
def test_rejects_invalid_occurrence_event_payloads(
    payload: dict[str, object], version: int, message: str
) -> None:
    event = occurrence_event(version=version)
    invalid = Event(
        event.event_id,
        event.branch_id,
        event.sequence,
        event.logical_time,
        event.transition_id,
        event.event_type,
        event.event_version,
        payload,  # type: ignore[arg-type]
        event.provenance,
    )

    with pytest.raises(ScenarioEventPayloadError, match=message):
        decode_scenario_event(invalid)


def test_projection_recognizes_occurrence_without_mutating_state() -> None:
    state = SimulationState.empty(BranchId("branch"))
    transition = CommittedTransition((occurrence_event(),))

    projected = project_transition(state, transition)

    assert projected.world == state.world
    assert projected.execution == state.execution
    assert projected.cognition == state.cognition
    assert projected.position.last_transition_ref == transition.transition_ref


def test_projection_rejects_duplicate_occurrence_in_one_transition() -> None:
    transition = CommittedTransition((occurrence_event(), occurrence_event(sequence=2)))

    with pytest.raises(ProjectionError, match="duplicate Scenario occurrence resolution"):
        project_transition(SimulationState.empty(BranchId("branch")), transition)
