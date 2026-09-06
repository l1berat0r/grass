# SPDX-License-Identifier: GPL-3.0-only

"""Provenance value objects."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, TypeAlias

from grass.core._structured_data import (
    StructuredScalar,
    StructuredValue,
    freeze_structured_mapping,
)

MetadataScalar: TypeAlias = StructuredScalar
MetadataValue: TypeAlias = StructuredValue


def _require_non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


def _empty_metadata() -> Mapping[str, MetadataValue]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ProvenanceSourceRef:
    """Opaque reference to the source represented by provenance."""

    kind: str
    value: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.kind, "source reference kind")
        _require_non_empty_string(self.value, "source reference value")


@dataclass(frozen=True, slots=True)
class Provenance:
    """Structured origin information without causation semantics."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    source_kind: str
    source_ref: ProvenanceSourceRef | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        _require_non_empty_string(self.source_kind, "source kind")
        if self.source_ref is not None and type(self.source_ref) is not ProvenanceSourceRef:
            raise TypeError("source_ref must be a ProvenanceSourceRef or None")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        frozen_metadata = freeze_structured_mapping(self.metadata, description="metadata")
        object.__setattr__(self, "metadata", frozen_metadata)
