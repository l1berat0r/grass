# SPDX-License-Identifier: GPL-3.0-only

"""Syntactic references to branch-local simulation identities."""

from dataclasses import dataclass

from grass.core.identifiers import BranchId, TransitionId


@dataclass(frozen=True, slots=True)
class TransitionRef:
    """A branch-qualified transition identity without existence semantics."""

    branch_id: BranchId
    transition_id: TransitionId

    def __post_init__(self) -> None:
        if type(self.branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        if type(self.transition_id) is not TransitionId:
            raise TypeError("transition_id must be a TransitionId")
