# SPDX-License-Identifier: GPL-3.0-only

"""Run-local logical time."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class LogicalDuration:
    """An exact non-negative elapsed duration in nanoseconds."""

    nanoseconds: int

    def __post_init__(self) -> None:
        if type(self.nanoseconds) is not int:
            raise TypeError("logical duration must be an integer")
        if self.nanoseconds < 0:
            raise ValueError("logical duration must not be negative")


@dataclass(frozen=True, order=True, slots=True)
class LogicalTime:
    """Nanoseconds from a run-local logical origin."""

    nanoseconds_from_origin: int

    def __post_init__(self) -> None:
        if type(self.nanoseconds_from_origin) is not int:
            raise TypeError("logical time must be an integer")
        if self.nanoseconds_from_origin < 0:
            raise ValueError("logical time must not be negative")

    def __add__(self, duration: LogicalDuration, /) -> LogicalTime:
        if type(duration) is not LogicalDuration:
            raise TypeError("LogicalTime can only add LogicalDuration")
        return LogicalTime(self.nanoseconds_from_origin + duration.nanoseconds)

    def __sub__(self, earlier: LogicalTime, /) -> LogicalDuration:
        if type(earlier) is not LogicalTime:
            raise TypeError("LogicalTime can only subtract LogicalTime")
        elapsed = self.nanoseconds_from_origin - earlier.nanoseconds_from_origin
        if elapsed < 0:
            raise ValueError("elapsed logical duration must not be negative")
        return LogicalDuration(elapsed)
