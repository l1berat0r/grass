# SPDX-License-Identifier: GPL-3.0-only

"""Ancestry-aware reconstruction with optional derived checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol

from grass.core.branches import HistoryPosition
from grass.core.event_store import InMemoryEventStore
from grass.core.events import CommittedTransition
from grass.core.identifiers import BranchId
from grass.core.projections import project_transition
from grass.core.state import ProjectionPosition, SimulationState


@dataclass(frozen=True, slots=True)
class StateCheckpoint:
    """A trusted derived state at one ancestry-aware history position."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position: HistoryPosition
    state: SimulationState

    def __post_init__(self) -> None:
        if type(self.position) is not HistoryPosition:
            raise TypeError("position must be a HistoryPosition")
        if type(self.state) is not SimulationState:
            raise TypeError("state must be a SimulationState")
        if self.state.position.branch_id != self.position.branch_id:
            raise ValueError("checkpoint state and history position branches must match")


class CheckpointLoader(Protocol):
    """Load one applicable trusted checkpoint for a requested target."""

    def load_checkpoint(self, target: HistoryPosition, /) -> StateCheckpoint | None:
        """Return an applicable checkpoint or no optimization."""

        ...


def _position_after_local_history(
    branch_id: BranchId, history: tuple[CommittedTransition, ...]
) -> ProjectionPosition:
    local = tuple(transition for transition in history if transition.branch_id == branch_id)
    if not local:
        return ProjectionPosition(branch_id)
    transition = local[-1]
    return ProjectionPosition(
        branch_id=transition.branch_id,
        last_transition_ref=transition.transition_ref,
        last_sequence=transition.events[-1].sequence,
        logical_time=transition.logical_time,
    )


def _carry_state_to_branch(state: SimulationState, branch_id: BranchId) -> SimulationState:
    return SimulationState(
        position=ProjectionPosition(branch_id),
        world=state.world,
        execution=state.execution,
        cognition=state.cognition,
    )


def _carry_state_to_position(
    state: SimulationState, position: ProjectionPosition
) -> SimulationState:
    return SimulationState(
        position=position,
        world=state.world,
        execution=state.execution,
        cognition=state.cognition,
    )


def _checkpoint_start(
    store: InMemoryEventStore,
    checkpoint: StateCheckpoint,
    target_history: tuple[CommittedTransition, ...],
) -> tuple[SimulationState, int]:
    checkpoint_history = store.read_visible_transitions(checkpoint.position)
    prefix_length = len(checkpoint_history)
    if target_history[:prefix_length] != checkpoint_history:
        raise ValueError("checkpoint history is not a prefix of target history")

    expected_position = _position_after_local_history(
        checkpoint.position.branch_id, checkpoint_history
    )
    if checkpoint.state.position != expected_position:
        raise ValueError("checkpoint ProjectionPosition does not match canonical history")

    remaining = target_history[prefix_length:]
    if (
        remaining
        and remaining[0].branch_id != checkpoint.state.position.branch_id
        and remaining[0].events[0].sequence != 1
    ):
        raise ValueError("checkpoint does not align with an origin-branch boundary")
    return checkpoint.state, prefix_length


def replay_branch(
    store: InMemoryEventStore,
    target: HistoryPosition,
    checkpoint_loader: CheckpointLoader | None = None,
) -> SimulationState:
    """Reconstruct complete state at one ancestry-aware history position."""

    if type(store) is not InMemoryEventStore:
        raise TypeError("store must be an InMemoryEventStore")
    if type(target) is not HistoryPosition:
        raise TypeError("target must be a HistoryPosition")

    target_history = store.read_visible_transitions(target)
    checkpoint = (
        checkpoint_loader.load_checkpoint(target) if checkpoint_loader is not None else None
    )
    if checkpoint is not None and type(checkpoint) is not StateCheckpoint:
        raise TypeError("checkpoint loader must return a StateCheckpoint or None")

    if checkpoint is None:
        first_branch = target_history[0].branch_id if target_history else target.branch_id
        state = SimulationState.empty(first_branch)
        start = 0
    else:
        state, start = _checkpoint_start(store, checkpoint, target_history)

    for transition in target_history[start:]:
        if state.position.branch_id != transition.branch_id:
            state = _carry_state_to_branch(state, transition.branch_id)
        state = project_transition(state, transition)

    target_projection_position = _position_after_local_history(target.branch_id, target_history)
    if state.position.branch_id != target.branch_id:
        state = _carry_state_to_position(state, target_projection_position)
    elif state.position != target_projection_position:
        raise AssertionError("replay did not reach the requested projection position")
    return state
