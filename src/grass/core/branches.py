# SPDX-License-Identifier: GPL-3.0-only

"""Immutable branch-topology and ancestry-position contracts."""

from __future__ import annotations

from dataclasses import dataclass

from grass.core.identifiers import BranchId
from grass.core.references import TransitionRef


@dataclass(frozen=True, slots=True)
class HistoryPosition:
    """One complete position in the history visible from a branch."""

    branch_id: BranchId
    transition_ref: TransitionRef | None = None

    def __post_init__(self) -> None:
        if type(self.branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        if self.transition_ref is not None and type(self.transition_ref) is not TransitionRef:
            raise TypeError("transition_ref must be a TransitionRef or None")


@dataclass(frozen=True, slots=True)
class Branch:
    """A root branch or an independent continuation from one parent position."""

    branch_id: BranchId
    fork_position: HistoryPosition | None = None

    def __post_init__(self) -> None:
        if type(self.branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        if self.fork_position is None:
            return
        if type(self.fork_position) is not HistoryPosition:
            raise TypeError("fork_position must be a HistoryPosition or None")
        if self.fork_position.transition_ref is None:
            raise ValueError("a child branch requires a committed-transition fork position")
        if self.fork_position.branch_id == self.branch_id:
            raise ValueError("a branch cannot be its own parent")

    @property
    def parent_branch_id(self) -> BranchId | None:
        if self.fork_position is None:
            return None
        return self.fork_position.branch_id
