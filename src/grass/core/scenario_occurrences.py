# SPDX-License-Identifier: GPL-3.0-only

"""History-aware projection of one-shot scenario occurrence scheduling."""

from __future__ import annotations

from collections.abc import Sequence

from grass.core.events import CommittedTransition
from grass.core.initialization_events import (
    SIMULATION_INITIALIZED,
    InitializationEventPayloadError,
    SimulationInitializedPayload,
    decode_initialization_event,
)
from grass.core.logical_time import LogicalTime
from grass.core.scenario_events import (
    SCENARIO_OCCURRENCE_RESOLVED,
    ScenarioEventPayloadError,
    decode_scenario_event,
)
from grass.core.scheduler import ScheduledResolution
from grass.core.world_definitions import ScenarioOccurrenceRef, WorldDefinition


class ScenarioOccurrenceHistoryError(ValueError):
    """Canonical history cannot produce coherent scenario occurrence scheduling."""


def _history(
    visible_history: Sequence[CommittedTransition], current_time: LogicalTime
) -> tuple[CommittedTransition, ...]:
    if not isinstance(visible_history, Sequence):
        raise TypeError("visible_history must be a sequence")
    history = tuple(visible_history)
    if not history:
        raise ScenarioOccurrenceHistoryError("scenario occurrence scheduling requires history")
    if not all(type(item) is CommittedTransition for item in history):
        raise TypeError("visible_history must contain CommittedTransition values")
    if history[-1].logical_time != current_time:
        raise ScenarioOccurrenceHistoryError(
            "current_time must equal the branch-visible history position time"
        )
    if any(
        later.logical_time < earlier.logical_time
        for earlier, later in zip(history, history[1:], strict=False)
    ):
        raise ScenarioOccurrenceHistoryError("branch-visible history time must be nondecreasing")
    return history


def _initialized_definition(
    history: tuple[CommittedTransition, ...],
) -> SimulationInitializedPayload:
    initialized = tuple(
        event
        for transition in history
        for event in transition.events
        if event.event_type == SIMULATION_INITIALIZED
    )
    if len(initialized) != 1:
        raise ScenarioOccurrenceHistoryError(
            "scenario occurrence scheduling requires exactly one SimulationInitialized Event"
        )
    try:
        return decode_initialization_event(initialized[0])
    except InitializationEventPayloadError as error:
        raise ScenarioOccurrenceHistoryError(str(error)) from error


def derive_resolved_scenario_occurrences(
    visible_history: Sequence[CommittedTransition],
) -> frozenset[ScenarioOccurrenceRef]:
    """Derive consumed occurrence identities from complete branch-visible history."""

    return frozenset(_derive_resolved_scenario_occurrence_times(visible_history))


def _derive_resolved_scenario_occurrence_times(
    visible_history: Sequence[CommittedTransition],
) -> dict[ScenarioOccurrenceRef, LogicalTime]:
    """Derive each consumed occurrence and its authoritative resolution time."""

    if not isinstance(visible_history, Sequence):
        raise TypeError("visible_history must be a sequence")
    resolved: dict[ScenarioOccurrenceRef, LogicalTime] = {}
    for transition in visible_history:
        if type(transition) is not CommittedTransition:
            raise TypeError("visible_history must contain CommittedTransition values")
        for event in transition.events:
            if event.event_type != SCENARIO_OCCURRENCE_RESOLVED:
                continue
            try:
                occurrence_ref = decode_scenario_event(event).occurrence_ref
            except ScenarioEventPayloadError as error:
                raise ScenarioOccurrenceHistoryError(str(error)) from error
            if occurrence_ref in resolved:
                raise ScenarioOccurrenceHistoryError(
                    "scenario occurrence was resolved more than once in visible history"
                )
            resolved[occurrence_ref] = event.logical_time
    return resolved


def project_scenario_occurrences(
    world_definition: WorldDefinition,
    current_time: LogicalTime,
    visible_history: Sequence[CommittedTransition],
    /,
) -> tuple[ScheduledResolution[ScenarioOccurrenceRef], ...]:
    """Project every unresolved one-shot AT_TIME occurrence from canonical inputs."""

    if type(world_definition) is not WorldDefinition:
        raise TypeError("world_definition must be a WorldDefinition")
    if type(current_time) is not LogicalTime:
        raise TypeError("current_time must be a LogicalTime")
    history = _history(visible_history, current_time)
    initialized = _initialized_definition(history)
    if (
        initialized.world_definition_ref != world_definition.ref
        or initialized.world_definition_schema_version != world_definition.schema_version
    ):
        raise ScenarioOccurrenceHistoryError(
            "WorldDefinition does not match SimulationInitialized history"
        )

    resolved_times = _derive_resolved_scenario_occurrence_times(history)
    known = {
        ScenarioOccurrenceRef(rule.ref(world_definition.ref)): rule
        for rule in world_definition.scenario_event_rules
    }
    if any(occurrence_ref not in known for occurrence_ref in resolved_times):
        raise ScenarioOccurrenceHistoryError(
            "resolved scenario occurrence does not belong to the WorldDefinition"
        )
    for occurrence_ref, resolved_time in resolved_times.items():
        if resolved_time != known[occurrence_ref].logical_time:
            raise ScenarioOccurrenceHistoryError(
                "scenario occurrence must resolve at its declared AT_TIME logical_time"
            )

    candidates: list[ScheduledResolution[ScenarioOccurrenceRef]] = []
    for occurrence_ref, rule in known.items():
        if occurrence_ref in resolved_times:
            continue
        if rule.logical_time < current_time:
            raise ScenarioOccurrenceHistoryError(
                "unresolved scenario occurrence cannot precede current_time"
            )
        candidates.append(ScheduledResolution(rule.logical_time, "SCENARIO_EVENT", occurrence_ref))
    return tuple(candidates)
