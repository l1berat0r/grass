# SPDX-License-Identifier: GPL-3.0-only

"""Opaque identifier value objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Identifier:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str:
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
class EntityId(_Identifier):
    """Opaque identity of a persistent scenario Entity."""


@dataclass(frozen=True, slots=True)
class RelationId(_Identifier):
    """Opaque identity of a persistent Relation."""


@dataclass(frozen=True, slots=True)
class WorldDefinitionId(_Identifier):
    """Opaque identity of a versioned WorldDefinition."""


@dataclass(frozen=True, slots=True)
class TransitionId(_Identifier):
    """Opaque identity of an atomic authoritative transition."""


@dataclass(frozen=True, slots=True)
class CorrelationId(_Identifier):
    """Opaque identity used to correlate a larger process."""
