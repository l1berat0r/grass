# SPDX-License-Identifier: GPL-3.0-only

"""Rebuild automatic perception work from canonical branch-visible history."""

from __future__ import annotations

from collections.abc import Sequence

from grass.core.branches import HistoryPosition
from grass.core.cognition_events import (
    COGNITION_EVENT_TYPES,
    OBSERVATION_CREATED,
    ObservationCreatedPayload,
    decode_cognition_event,
)
from grass.core.event_store import EventStore
from grass.core.events import CommittedTransition, Event
from grass.core.identifiers import EntityId, EventId
from grass.core.replay import replay_branch
from grass.runtime.contracts import (
    PerceptionCandidate,
    PerceptionProjector,
    RuntimeIntegrityError,
)

PerceptionKey = tuple[EventId, EntityId]


def _event_locations(
    history: Sequence[CommittedTransition],
) -> dict[EventId, tuple[int, int, Event]]:
    return {
        event.event_id: (transition_index, event_index, event)
        for transition_index, transition in enumerate(history)
        for event_index, event in enumerate(transition.events)
    }


def _consumed_perceptions(
    history: Sequence[CommittedTransition],
    locations: dict[EventId, tuple[int, int, Event]],
) -> frozenset[PerceptionKey]:
    consumed: set[PerceptionKey] = set()
    for transition_index, transition in enumerate(history):
        for event in transition.events:
            if event.event_type != OBSERVATION_CREATED:
                continue
            payload = decode_cognition_event(event)
            if type(payload) is not ObservationCreatedPayload:  # pragma: no cover - routed above
                raise AssertionError("unexpected cognition payload")
            observation = payload.observation
            for cause in event.causation_refs:
                if cause.kind != "event":
                    continue
                source_id = EventId(cause.value)
                source = locations.get(source_id)
                if source is None or source[0] >= transition_index:
                    raise RuntimeIntegrityError(
                        "Observation source Event must precede it in visible history"
                    )
                key = (source_id, observation.actor_id)
                if key in consumed:
                    raise RuntimeIntegrityError(
                        "more than one Observation consumed one source Event and actor"
                    )
                consumed.add(key)
    return frozenset(consumed)


def derive_outstanding_perception_candidates(
    store: EventStore,
    position: HistoryPosition,
    projector: PerceptionProjector,
    /,
) -> tuple[PerceptionCandidate, ...]:
    """Derive unconsumed candidates and reject perception missed before the head time."""

    if type(position) is not HistoryPosition:
        raise TypeError("position must be a HistoryPosition")
    if not callable(getattr(projector, "project", None)):
        raise TypeError("projector must provide project")
    history = tuple(store.read_visible_transitions(position))
    if not history:
        raise RuntimeIntegrityError("runtime perception requires non-empty history")
    locations = _event_locations(history)
    consumed = _consumed_perceptions(history, locations)
    current_time = history[-1].logical_time
    derived: dict[PerceptionKey, tuple[int, int, PerceptionCandidate]] = {}

    for transition_index, transition in enumerate(history):
        state_after_source = replay_branch(
            store,
            HistoryPosition(position.branch_id, transition.transition_ref),
        )
        candidates = projector.project(transition, state_after_source)
        if not isinstance(candidates, Sequence):
            raise TypeError("PerceptionProjector must return a sequence")
        source_offsets = {
            event.event_id: event_index for event_index, event in enumerate(transition.events)
        }
        for candidate in candidates:
            if type(candidate) is not PerceptionCandidate:
                raise TypeError("PerceptionProjector must return PerceptionCandidate values")
            source_offset = source_offsets.get(candidate.source_event_id)
            if source_offset is None:
                raise RuntimeIntegrityError(
                    "PerceptionCandidate must reference an Event in its source transition"
                )
            source_event = transition.events[source_offset]
            if source_event.event_type in COGNITION_EVENT_TYPES:
                raise RuntimeIntegrityError(
                    "cognition Events cannot be automatic perception sources"
                )
            if candidate.actor_id not in state_after_source.world.entities:
                raise RuntimeIntegrityError("PerceptionCandidate actor must exist after its source")
            if candidate.subject_plan_ref is not None:
                plan = state_after_source.execution.plans.get(candidate.subject_plan_ref)
                if plan is None or plan.actor_id != candidate.actor_id:
                    raise RuntimeIntegrityError(
                        "PerceptionCandidate subject Plan must exist and belong to its actor"
                    )
            key = (candidate.source_event_id, candidate.actor_id)
            if key in derived:
                raise RuntimeIntegrityError(
                    "PerceptionProjector produced duplicate source Event and actor candidates"
                )
            derived[key] = (transition_index, source_offset, candidate)

    outstanding = [value for key, value in derived.items() if key not in consumed]
    if any(history[index].logical_time < current_time for index, _, _ in outstanding):
        raise RuntimeIntegrityError("canonical history contains missed historical perception")
    return tuple(
        candidate
        for _, _, candidate in sorted(
            outstanding,
            key=lambda item: (item[0], item[1], item[2].actor_id.value),
        )
    )
