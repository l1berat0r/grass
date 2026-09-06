# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import BranchId, TransitionId, TransitionRef


def test_transition_reference_is_branch_qualified() -> None:
    reference = TransitionRef(BranchId("branch"), TransitionId("transition"))

    assert reference.branch_id == BranchId("branch")
    assert reference.transition_id == TransitionId("transition")
    assert hash(reference) == hash(TransitionRef(BranchId("branch"), TransitionId("transition")))


def test_transition_reference_rejects_swapped_identifier_types() -> None:
    with pytest.raises(TypeError, match="branch_id must be a BranchId"):
        TransitionRef(cast(BranchId, TransitionId("transition")), TransitionId("transition"))
    with pytest.raises(TypeError, match="transition_id must be a TransitionId"):
        TransitionRef(BranchId("branch"), cast(TransitionId, BranchId("branch")))


def test_transition_reference_is_immutable() -> None:
    reference = TransitionRef(BranchId("branch"), TransitionId("transition"))

    with pytest.raises(FrozenInstanceError):
        reference.branch_id = BranchId("other")  # type: ignore[misc]
