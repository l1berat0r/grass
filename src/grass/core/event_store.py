# SPDX-License-Identifier: GPL-3.0-only

"""Atomic in-memory storage for committed Event history."""

from threading import RLock

from grass.core.events import CommittedTransition, Event, TransitionToCommit
from grass.core.identifiers import BranchId, EventId
from grass.core.references import TransitionRef


class InMemoryEventStore:
    """Store branch-origin Event transitions as immutable snapshots."""

    def __init__(self) -> None:
        self._transitions_by_branch: dict[BranchId, tuple[CommittedTransition, ...]] = {}
        self._event_ids: frozenset[EventId] = frozenset()
        self._transition_refs: frozenset[TransitionRef] = frozenset()
        self._lock = RLock()

    def commit_transition(self, transition: TransitionToCommit) -> CommittedTransition:
        """Validate and atomically publish one complete transition."""

        if type(transition) is not TransitionToCommit:
            raise TypeError("transition must be a TransitionToCommit")

        with self._lock:
            if transition.transition_ref in self._transition_refs:
                raise ValueError("transition_ref has already been committed")

            event_ids = tuple(event.event_id for event in transition.events)
            if len(set(event_ids)) != len(event_ids):
                raise ValueError("event_id values must be unique within a transition")
            if any(event_id in self._event_ids for event_id in event_ids):
                raise ValueError("event_id has already been committed")

            branch_id = transition.transition_ref.branch_id
            previous = self._transitions_by_branch.get(branch_id, ())
            if previous and transition.logical_time < previous[-1].logical_time:
                raise ValueError("logical_time must not decrease within a branch")

            next_sequence = previous[-1].events[-1].sequence + 1 if previous else 1
            committed_events = tuple(
                Event(
                    event_id=record.event_id,
                    branch_id=branch_id,
                    sequence=next_sequence + offset,
                    logical_time=transition.logical_time,
                    transition_id=transition.transition_ref.transition_id,
                    event_type=record.event_type,
                    event_version=record.event_version,
                    payload=record.payload,
                    provenance=record.provenance,
                    causation_refs=record.causation_refs,
                    correlation_id=record.correlation_id,
                )
                for offset, record in enumerate(transition.events)
            )
            committed = CommittedTransition(committed_events)

            updated_branches = self._transitions_by_branch.copy()
            updated_branches[branch_id] = previous + (committed,)
            updated_event_ids = self._event_ids.union(event_ids)
            updated_transition_refs = self._transition_refs.union((transition.transition_ref,))

            self._transitions_by_branch = updated_branches
            self._event_ids = updated_event_ids
            self._transition_refs = updated_transition_refs
            return committed

    def read_transitions(self, branch_id: BranchId) -> tuple[CommittedTransition, ...]:
        """Return a complete immutable snapshot of branch-origin transitions."""

        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        with self._lock:
            return self._transitions_by_branch.get(branch_id, ())
