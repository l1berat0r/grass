# SPDX-License-Identifier: GPL-3.0-only

"""Opaque identifier value objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Identifier:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("identifier value must be a string")
        if self.value == "":
            raise ValueError("identifier value must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class EventId(_Identifier):
    """Opaque identity of an Event."""


@dataclass(frozen=True, slots=True)
class BranchId(_Identifier):
    """Opaque identity of a simulation branch."""


@dataclass(frozen=True, slots=True)
class TransitionId(_Identifier):
    """Opaque identity of an atomic authoritative transition."""


@dataclass(frozen=True, slots=True)
class CorrelationId(_Identifier):
    """Opaque identity used to correlate a larger process."""
