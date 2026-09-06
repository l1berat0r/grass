# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic values shared by Slice 0 tests."""

from typing import TypeVar

from grass.core import BranchId, CorrelationId, EventId, LogicalTime, TransitionId

IdentifierT = TypeVar(
    "IdentifierT",
    EventId,
    BranchId,
    TransitionId,
    CorrelationId,
)


def stable_id(identifier_type: type[IdentifierT], label: str) -> IdentifierT:
    """Construct a stable typed identifier without production ID generation."""

    return identifier_type(f"test:{label}")


FIXED_LOGICAL_TIME = LogicalTime(12_345_678_901)
