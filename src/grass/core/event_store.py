# SPDX-License-Identifier: GPL-3.0-only

"""Atomic in-memory storage for committed Event history."""

from threading import RLock

from grass.core.branches import Branch, HistoryPosition
from grass.core.events import CommittedTransition, Event, TransitionToCommit
from grass.core.identifiers import BranchId, EventId
from grass.core.references import TransitionRef


class StaleHistoryError(ValueError):
    """A guarded commit no longer targets the branch's current visible head."""


class InMemoryEventStore:
    """Store branch-origin Event transitions as immutable snapshots."""

    def __init__(self) -> None:
        self._branches: dict[BranchId, Branch] = {}
        self._transitions_by_branch: dict[BranchId, tuple[CommittedTransition, ...]] = {}
        self._event_ids: frozenset[EventId] = frozenset()
        self._transitions_by_ref: dict[TransitionRef, CommittedTransition] = {}
        self._lock = RLock()

    def create_root_branch(self, branch_id: BranchId) -> Branch:
        """Atomically register one parentless branch."""

        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        with self._lock:
            if branch_id in self._branches:
                raise ValueError("branch_id has already been registered")
            branch = Branch(branch_id)
            branches = self._branches.copy()
            branches[branch_id] = branch
            transitions = self._transitions_by_branch.copy()
            transitions[branch_id] = ()
            self._branches = branches
            self._transitions_by_branch = transitions
            return branch

    def fork_branch(self, branch_id: BranchId, fork_position: HistoryPosition) -> Branch:
        """Atomically register a child at one visible committed transition."""

        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        if type(fork_position) is not HistoryPosition:
            raise TypeError("fork_position must be a HistoryPosition")
        if fork_position.transition_ref is None:
            raise ValueError("a child branch requires a committed-transition fork position")
        if fork_position.branch_id == branch_id:
            raise ValueError("a branch cannot be its own parent")

        with self._lock:
            if branch_id in self._branches:
                raise ValueError("branch_id has already been registered")
            self._require_branch(fork_position.branch_id)
            self._visible_transitions(fork_position)
            branch = Branch(branch_id, fork_position)
            branches = self._branches.copy()
            branches[branch_id] = branch
            transitions = self._transitions_by_branch.copy()
            transitions[branch_id] = ()
            self._branches = branches
            self._transitions_by_branch = transitions
            return branch

    def read_branch(self, branch_id: BranchId) -> Branch:
        """Return immutable topology metadata for one registered branch."""

        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        with self._lock:
            return self._require_branch(branch_id)

    def head_position(self, branch_id: BranchId) -> HistoryPosition:
        """Capture the current complete visible head of one branch."""

        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        with self._lock:
            branch = self._require_branch(branch_id)
            return self._head_position(branch)

    def commit_transition(
        self,
        transition: TransitionToCommit,
        *,
        expected_head: HistoryPosition | None = None,
    ) -> CommittedTransition:
        """Validate and atomically publish one complete transition."""

        if type(transition) is not TransitionToCommit:
            raise TypeError("transition must be a TransitionToCommit")
        if expected_head is not None and type(expected_head) is not HistoryPosition:
            raise TypeError("expected_head must be a HistoryPosition or None")

        with self._lock:
            branch_id = transition.transition_ref.branch_id
            branch = self._require_branch(branch_id)
            if expected_head is not None:
                if expected_head.branch_id != branch_id:
                    raise StaleHistoryError("expected_head branch does not match transition branch")
                if expected_head != self._head_position(branch):
                    raise StaleHistoryError(
                        "expected_head is not the branch's current visible head"
                    )
            if transition.transition_ref in self._transitions_by_ref:
                raise ValueError("transition_ref has already been committed")

            event_ids = tuple(event.event_id for event in transition.events)
            if len(set(event_ids)) != len(event_ids):
                raise ValueError("event_id values must be unique within a transition")
            if any(event_id in self._event_ids for event_id in event_ids):
                raise ValueError("event_id has already been committed")

            previous = self._transitions_by_branch[branch_id]
            if previous and transition.logical_time < previous[-1].logical_time:
                raise ValueError("logical_time must not decrease within a branch")
            if not previous and branch.fork_position is not None:
                fork_ref = branch.fork_position.transition_ref
                if fork_ref is None:  # pragma: no cover - enforced by Branch
                    raise AssertionError("child branch has no fork transition")
                fork_time = self._transitions_by_ref[fork_ref].logical_time
                if transition.logical_time < fork_time:
                    raise ValueError("logical_time must not precede the fork position")

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
            updated_transitions_by_ref = self._transitions_by_ref.copy()
            updated_transitions_by_ref[transition.transition_ref] = committed

            self._transitions_by_branch = updated_branches
            self._event_ids = updated_event_ids
            self._transitions_by_ref = updated_transitions_by_ref
            return committed

    def _head_position(self, branch: Branch) -> HistoryPosition:
        local = self._transitions_by_branch[branch.branch_id]
        transition_ref: TransitionRef | None
        if local:
            transition_ref = local[-1].transition_ref
        elif branch.fork_position is not None:
            transition_ref = branch.fork_position.transition_ref
        else:
            transition_ref = None
        return HistoryPosition(branch.branch_id, transition_ref)

    def read_transitions(self, branch_id: BranchId) -> tuple[CommittedTransition, ...]:
        """Return a complete immutable snapshot of branch-origin transitions."""

        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        with self._lock:
            self._require_branch(branch_id)
            return self._transitions_by_branch[branch_id]

    def read_visible_transitions(
        self, position: HistoryPosition
    ) -> tuple[CommittedTransition, ...]:
        """Return original transitions visible through one complete position."""

        if type(position) is not HistoryPosition:
            raise TypeError("position must be a HistoryPosition")
        with self._lock:
            return self._visible_transitions(position)

    def _require_branch(self, branch_id: BranchId) -> Branch:
        branch = self._branches.get(branch_id)
        if branch is None:
            raise ValueError("branch_id has not been registered")
        return branch

    def _visible_head(self, branch_id: BranchId) -> tuple[CommittedTransition, ...]:
        branch = self._require_branch(branch_id)
        prefix = (
            self._visible_transitions(branch.fork_position)
            if branch.fork_position is not None
            else ()
        )
        return prefix + self._transitions_by_branch[branch_id]

    def _visible_transitions(self, position: HistoryPosition) -> tuple[CommittedTransition, ...]:
        branch = self._require_branch(position.branch_id)
        if position.transition_ref is None:
            if branch.fork_position is not None:
                raise ValueError("an empty position is valid only for a root branch")
            return ()

        visible = self._visible_head(position.branch_id)
        for index, transition in enumerate(visible):
            if transition.transition_ref == position.transition_ref:
                return visible[: index + 1]
        raise ValueError("transition_ref is not visible from branch")
