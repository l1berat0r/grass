# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError
from operator import add, sub
from typing import cast

import pytest

from grass.core import LogicalDuration, LogicalTime
from tests.support import FIXED_LOGICAL_TIME


def test_logical_time_is_non_negative_nanoseconds_from_origin() -> None:
    assert LogicalTime(0).nanoseconds_from_origin == 0
    assert LogicalTime(28_800_000_000_000).nanoseconds_from_origin == 28_800_000_000_000


def test_logical_time_has_value_equality_and_total_ordering() -> None:
    earlier = LogicalTime(10)
    same = LogicalTime(10)
    later = LogicalTime(11)

    assert earlier == same
    assert earlier <= same
    assert earlier < later
    assert later > earlier
    assert later >= same
    assert sorted([later, earlier, same]) == [earlier, same, later]


def test_logical_time_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        LogicalTime(-1)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_logical_time_rejects_non_integer_values(value: object) -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        LogicalTime(cast(int, value))


def test_logical_time_is_immutable_hashable_and_rejects_unapproved_arithmetic() -> None:
    logical_time = LogicalTime(5)

    assert {logical_time: "value"}[LogicalTime(5)] == "value"
    with pytest.raises(FrozenInstanceError):
        logical_time.nanoseconds_from_origin = 6  # type: ignore[misc]
    with pytest.raises(TypeError):
        add(logical_time, LogicalTime(1))
    with pytest.raises(TypeError):
        sub(logical_time, LogicalDuration(1))


def test_logical_duration_is_exact_non_negative_nanoseconds() -> None:
    zero = LogicalDuration(0)
    duration = LogicalDuration(28_800_000_000_000)

    assert zero.nanoseconds == 0
    assert duration.nanoseconds == 28_800_000_000_000
    assert LogicalTime(5) + duration == LogicalTime(28_800_000_000_005)
    assert LogicalTime(9) - LogicalTime(5) == LogicalDuration(4)
    assert LogicalTime(5) - LogicalTime(5) == zero
    assert {duration: "value"}[LogicalDuration(28_800_000_000_000)] == "value"
    with pytest.raises(FrozenInstanceError):
        duration.nanoseconds = 1  # type: ignore[misc]


def test_logical_duration_rejects_backward_and_invalid_values() -> None:
    with pytest.raises(ValueError, match="elapsed logical duration"):
        _ = LogicalTime(4) - LogicalTime(5)
    with pytest.raises(ValueError, match="must not be negative"):
        LogicalDuration(-1)
    for value in (True, 1.0, "1"):
        with pytest.raises(TypeError, match="must be an integer"):
            LogicalDuration(cast(int, value))


def test_fixed_logical_time_fixture_is_stable() -> None:
    assert FIXED_LOGICAL_TIME == LogicalTime(12_345_678_901)
