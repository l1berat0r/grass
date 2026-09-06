# SPDX-License-Identifier: GPL-3.0-only

"""Run-local logical time."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class LogicalTime:
    """Nanoseconds from a run-local logical origin."""

    nanoseconds_from_origin: int

    def __post_init__(self) -> None:
        if type(self.nanoseconds_from_origin) is not int:
            raise TypeError("logical time must be an integer")
        if self.nanoseconds_from_origin < 0:
            raise ValueError("logical time must not be negative")
