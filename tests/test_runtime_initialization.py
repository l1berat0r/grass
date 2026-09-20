# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import pytest

from grass.core import (
    BranchId,
    CommittedTransition,
    EventId,
    EventToCommit,
    HistoryPosition,
    InMemoryEventStore,
    LogicalTime,
    Provenance,
    SimulationRunConfig,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    WorldDefinition,
    build_genesis_transition,
    load_world_definition,
)
from grass.core.initialization_events import SIMULATION_INITIALIZED
from grass.runtime import (
    InitializationResult,
    RuntimeIntegrityError,
    RuntimeWorkKind,
    UuidRuntimeIdentitySource,
    initialize_root,
)

ROOT = BranchId("root")


def _definition() -> WorldDefinition:
    return load_world_definition(
        {
            "world_definition_id": "initialization-world",
            "version": "1.0",
            "schema_version": 1,
            "vocabulary": {
                "entity_types": [],
                "relation_types": [],
                "resource_types": [],
                "state_variable_types": [],
            },
            "initial_conditions": {
                "logical_time": 3,
                "entities": [],
                "relations": [],
                "resources": [],
                "state_variables": [],
            },
            "metadata": {},
        }
    )


def test_initialize_root_is_exact_and_idempotent() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = InMemoryEventStore()
    store.create_root_branch(ROOT)
    identities = UuidRuntimeIdentitySource()

    first = initialize_root(
        event_store=store,
        branch_id=ROOT,
        world_definition=definition,
        run_config=config,
        identity_source=identities,
    )
    second = initialize_root(
        event_store=store,
        branch_id=ROOT,
        world_definition=definition,
        run_config=config,
        identity_source=identities,
    )

    assert first is InitializationResult.INITIALIZED
    assert second is InitializationResult.ALREADY_INITIALIZED
    assert len(store.read_transitions(ROOT)) == 1
    assert RuntimeWorkKind.INITIALIZATION.value == "INITIALIZATION"


def test_initialize_root_rejects_malformed_nonempty_history() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = InMemoryEventStore()
    store.create_root_branch(ROOT)
    store.commit_transition(
        TransitionToCommit(
            TransitionRef(ROOT, TransitionId("not-genesis")),
            LogicalTime(3),
            (
                EventToCommit(
                    EventId("not-genesis"),
                    "Unexpected",
                    1,
                    {},
                    Provenance("ENGINE"),
                ),
            ),
        )
    )

    with pytest.raises(RuntimeIntegrityError, match="malformed genesis"):
        initialize_root(
            event_store=store,
            branch_id=ROOT,
            world_definition=definition,
            run_config=config,
            identity_source=UuidRuntimeIdentitySource(),
        )


def test_initialize_root_rejects_additional_initialization_event() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = InMemoryEventStore()
    store.create_root_branch(ROOT)
    store.commit_transition(
        build_genesis_transition(
            definition,
            config,
            TransitionRef(ROOT, TransitionId("genesis")),
            (EventId("genesis"),),
        )
    )
    store.commit_transition(
        TransitionToCommit(
            TransitionRef(ROOT, TransitionId("second-initialization")),
            LogicalTime(3),
            (
                EventToCommit(
                    EventId("second-initialization"),
                    SIMULATION_INITIALIZED,
                    1,
                    {},
                    Provenance("ENGINE"),
                ),
            ),
        )
    )

    with pytest.raises(RuntimeIntegrityError, match="additional SimulationInitialized"):
        initialize_root(
            event_store=store,
            branch_id=ROOT,
            world_definition=definition,
            run_config=config,
            identity_source=UuidRuntimeIdentitySource(),
        )


class _RacingStore(InMemoryEventStore):
    def __init__(self, winner: TransitionToCommit) -> None:
        super().__init__()
        self.winner = winner
        self.raced = False

    def commit_transition(
        self,
        transition: TransitionToCommit,
        *,
        expected_head: HistoryPosition | None = None,
    ) -> CommittedTransition:
        if not self.raced:
            self.raced = True
            super().commit_transition(self.winner, expected_head=expected_head)
        return super().commit_transition(transition, expected_head=expected_head)


def test_initialize_root_recovers_from_concurrent_valid_genesis() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    winner = build_genesis_transition(
        definition,
        config,
        TransitionRef(ROOT, TransitionId("winner")),
        (EventId("winner"),),
    )
    store = _RacingStore(winner)
    store.create_root_branch(ROOT)

    result = initialize_root(
        event_store=store,
        branch_id=ROOT,
        world_definition=definition,
        run_config=config,
        identity_source=UuidRuntimeIdentitySource(),
    )

    assert result is InitializationResult.ALREADY_INITIALIZED
    assert store.head_position(ROOT).transition_ref == winner.transition_ref


def test_initialize_root_rejects_child_branch() -> None:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    store = InMemoryEventStore()
    store.create_root_branch(ROOT)
    store.commit_transition(
        build_genesis_transition(
            definition,
            config,
            TransitionRef(ROOT, TransitionId("genesis")),
            (EventId("genesis"),),
        )
    )
    child = BranchId("child")
    store.fork_branch(child, store.head_position(ROOT))

    with pytest.raises(ValueError, match="parentless"):
        initialize_root(
            event_store=store,
            branch_id=child,
            world_definition=definition,
            run_config=config,
            identity_source=UuidRuntimeIdentitySource(),
        )
