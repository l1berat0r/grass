# SPDX-License-Identifier: GPL-3.0-only

import pytest

from grass.core import (
    BranchId,
    CauseRef,
    CommittedTransition,
    EntityId,
    Event,
    HistoryPosition,
    InMemoryEventStore,
    ObservationId,
    SimulationState,
)
from grass.core.cognition_events import OBSERVATION_CREATED
from grass.core.world_events import ENTITY_CREATED, ENTITY_UPDATED
from grass.runtime import (
    PerceptionCandidate,
    RuntimeIntegrityError,
    derive_outstanding_perception_candidates,
)
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


class EntityPerceptionProjector:
    def project(
        self,
        source_transition: CommittedTransition,
        state_after_source: SimulationState,
        /,
    ) -> tuple[PerceptionCandidate, ...]:
        del state_after_source
        return tuple(
            PerceptionCandidate(event.event_id, EntityId("actor"), {"event": event.event_type})
            for event in source_transition.events
            if event.event_type == ENTITY_UPDATED
        )


def _history_with_source() -> tuple[InMemoryEventStore, Event]:
    store = rooted_store("root")
    store.commit_transition(
        transition_to_commit(
            "root",
            "create",
            0,
            [
                event_to_commit(
                    "actor",
                    event_type=ENTITY_CREATED,
                    payload={"entity_id": "actor", "entity_type": "Person", "properties": {}},
                )
            ],
        )
    )
    source = store.commit_transition(
        transition_to_commit(
            "root",
            "source",
            1,
            [
                event_to_commit(
                    "source",
                    event_type=ENTITY_UPDATED,
                    payload={"entity_id": "actor", "properties_after": {"seen": True}},
                )
            ],
        )
    )
    return store, source.events[0]


def test_consumed_perception_is_rebuilt_from_observation_causation() -> None:
    store, source = _history_with_source()
    root = stable_id(BranchId, "root")
    position = store.head_position(root)
    projector = EntityPerceptionProjector()

    assert derive_outstanding_perception_candidates(store, position, projector) == (
        PerceptionCandidate(source.event_id, EntityId("actor"), {"event": ENTITY_UPDATED}),
    )

    store.commit_transition(
        transition_to_commit(
            "root",
            "observation",
            1,
            [
                event_to_commit(
                    "observation",
                    event_type=OBSERVATION_CREATED,
                    payload={
                        "observation_id": "observation",
                        "actor_id": "actor",
                        "content": {"event": ENTITY_UPDATED},
                    },
                    causation_refs=(CauseRef("event", source.event_id.value),),
                )
            ],
        )
    )

    assert (
        derive_outstanding_perception_candidates(
            store,
            store.head_position(root),
            projector,
        )
        == ()
    )


def test_perception_consumption_is_inherited_but_prefork_candidate_is_independent() -> None:
    store, source = _history_with_source()
    root = stable_id(BranchId, "root")
    before = store.head_position(root)
    before_child = BranchId("before-child")
    store.fork_branch(before_child, before)
    store.commit_transition(
        transition_to_commit(
            "root",
            "observation",
            1,
            [
                event_to_commit(
                    "observation",
                    event_type=OBSERVATION_CREATED,
                    payload={
                        "observation_id": ObservationId("observation").value,
                        "actor_id": "actor",
                        "content": {},
                    },
                    causation_refs=(CauseRef("event", source.event_id.value),),
                )
            ],
        )
    )
    after_child = BranchId("after-child")
    store.fork_branch(after_child, store.head_position(root))

    assert (
        len(
            derive_outstanding_perception_candidates(
                store, store.head_position(before_child), EntityPerceptionProjector()
            )
        )
        == 1
    )
    assert (
        derive_outstanding_perception_candidates(
            store, store.head_position(after_child), EntityPerceptionProjector()
        )
        == ()
    )


def test_missed_historical_perception_is_an_integrity_error() -> None:
    store, _ = _history_with_source()
    store.commit_transition(
        transition_to_commit(
            "root",
            "later",
            2,
            [
                event_to_commit(
                    "later",
                    event_type=ENTITY_UPDATED,
                    payload={"entity_id": "actor", "properties_after": {"later": True}},
                )
            ],
        )
    )
    position = store.head_position(stable_id(BranchId, "root"))

    with pytest.raises(RuntimeIntegrityError, match="missed historical perception"):
        derive_outstanding_perception_candidates(
            store,
            HistoryPosition(position.branch_id, position.transition_ref),
            EntityPerceptionProjector(),
        )


def test_duplicate_observation_for_source_actor_is_an_integrity_error() -> None:
    store, source = _history_with_source()
    store.commit_transition(
        transition_to_commit(
            "root",
            "observations",
            1,
            [
                event_to_commit(
                    label,
                    event_type=OBSERVATION_CREATED,
                    payload={
                        "observation_id": label,
                        "actor_id": "actor",
                        "content": {},
                    },
                    causation_refs=(CauseRef("event", source.event_id.value),),
                )
                for label in ("one", "two")
            ],
        )
    )

    with pytest.raises(RuntimeIntegrityError, match="more than one Observation"):
        derive_outstanding_perception_candidates(
            store,
            store.head_position(stable_id(BranchId, "root")),
            EntityPerceptionProjector(),
        )
