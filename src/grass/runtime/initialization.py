# SPDX-License-Identifier: GPL-3.0-only

"""Idempotent root initialization through one exact genesis transition."""

from __future__ import annotations

from enum import StrEnum

from grass.core.branches import HistoryPosition
from grass.core.event_store import EventStore, StaleHistoryError
from grass.core.genesis import (
    GenesisError,
    build_genesis_transition,
    genesis_event_count,
    validate_committed_genesis,
)
from grass.core.identifiers import BranchId, EventId
from grass.core.initialization_events import SIMULATION_INITIALIZED
from grass.core.references import TransitionRef
from grass.core.world_definitions import SimulationRunConfig, WorldDefinition
from grass.runtime.contracts import RuntimeIdentitySource, RuntimeIntegrityError, RuntimeWorkKind


class InitializationResult(StrEnum):
    """Outcome of ensuring that a parentless branch has exact genesis history."""

    INITIALIZED = "INITIALIZED"
    ALREADY_INITIALIZED = "ALREADY_INITIALIZED"


def _validate_existing_root(
    event_store: EventStore,
    branch_id: BranchId,
    world_definition: WorldDefinition,
    run_config: SimulationRunConfig,
) -> InitializationResult:
    position = event_store.head_position(branch_id)
    history = tuple(event_store.read_visible_transitions(position))
    if not history:
        raise RuntimeIntegrityError("root branch remained empty after a stale genesis commit")
    try:
        validate_committed_genesis(world_definition, run_config, history[0])
    except GenesisError as error:
        raise RuntimeIntegrityError("root branch has malformed genesis history") from error
    if any(
        event.event_type == SIMULATION_INITIALIZED
        for transition in history[1:]
        for event in transition.events
    ):
        raise RuntimeIntegrityError(
            "root branch contains an additional SimulationInitialized Event"
        )
    return InitializationResult.ALREADY_INITIALIZED


def initialize_root(
    *,
    event_store: EventStore,
    branch_id: BranchId,
    world_definition: WorldDefinition,
    run_config: SimulationRunConfig,
    identity_source: RuntimeIdentitySource,
) -> InitializationResult:
    """Commit exact genesis to an empty root, or validate an existing initialization."""

    if type(branch_id) is not BranchId:
        raise TypeError("branch_id must be a BranchId")
    if type(world_definition) is not WorldDefinition:
        raise TypeError("world_definition must be a WorldDefinition")
    if type(run_config) is not SimulationRunConfig:
        raise TypeError("run_config must be a SimulationRunConfig")
    branch = event_store.read_branch(branch_id)
    if branch.fork_position is not None:
        raise ValueError("initialize_root requires a parentless root branch")

    empty_head = HistoryPosition(branch_id)
    head = event_store.head_position(branch_id)
    if head != empty_head:
        return _validate_existing_root(event_store, branch_id, world_definition, run_config)

    kind = RuntimeWorkKind.INITIALIZATION
    transition_ref = TransitionRef(branch_id, identity_source.transition_id(branch_id, kind))
    count = genesis_event_count(world_definition)
    event_ids = tuple(identity_source.event_ids(count))
    if not all(type(event_id) is EventId for event_id in event_ids):
        raise RuntimeIntegrityError("RuntimeIdentitySource returned invalid genesis EventIds")
    if len(event_ids) != count:
        raise RuntimeIntegrityError(
            "RuntimeIdentitySource returned the wrong genesis EventId count"
        )
    transition = build_genesis_transition(
        world_definition,
        run_config,
        transition_ref,
        event_ids,
    )
    try:
        event_store.commit_transition(transition, expected_head=empty_head)
    except StaleHistoryError:
        return _validate_existing_root(event_store, branch_id, world_definition, run_config)
    return InitializationResult.INITIALIZED
