# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import BranchId, CorrelationId, EventId, TransitionId
from tests.support import stable_id


def test_identifier_preserves_opaque_value() -> None:
    identifier = EventId("opaque value/with:no-assumed-format")

    assert identifier.value == "opaque value/with:no-assumed-format"
    assert str(identifier) == identifier.value


def test_identifier_types_are_nominally_distinct() -> None:
    assert cast(object, EventId("same")) != BranchId("same")
    assert cast(object, BranchId("same")) != TransitionId("same")
    assert cast(object, TransitionId("same")) != CorrelationId("same")


@pytest.mark.parametrize(
    "identifier_type",
    [EventId, BranchId, TransitionId, CorrelationId],
)
def test_identifier_rejects_empty_value(
    identifier_type: type[EventId] | type[BranchId] | type[TransitionId] | type[CorrelationId],
) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        identifier_type("")


def test_identifier_rejects_non_string_value() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        EventId(cast(str, 7))


def test_identifier_is_immutable_hashable_and_unordered() -> None:
    identifier = BranchId("branch")

    assert {identifier: "value"}[BranchId("branch")] == "value"
    with pytest.raises(FrozenInstanceError):
        identifier.value = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        _ = identifier < BranchId("other")  # type: ignore[operator]


def test_test_identifier_helper_is_stable_and_typed() -> None:
    assert stable_id(EventId, "event") == EventId("test:event")
    assert stable_id(BranchId, "branch") == BranchId("test:branch")
