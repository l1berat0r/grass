# SPDX-License-Identifier: GPL-3.0-only

"""Provenance value objects."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import ClassVar, TypeAlias

MetadataScalar: TypeAlias = str | int | float | bool | None
MetadataValue: TypeAlias = (
    MetadataScalar
    | Mapping[str, "MetadataValue"]
    | list["MetadataValue"]
    | tuple["MetadataValue", ...]
)


def _require_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


def _freeze_metadata_value(value: MetadataValue) -> MetadataValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("metadata floats must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, MetadataValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("metadata mapping keys must be strings")
            frozen[key] = _freeze_metadata_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_metadata_value(item) for item in value)
    raise TypeError(f"unsupported metadata value: {type(value).__name__}")


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
        if self.source_ref is not None and not isinstance(self.source_ref, ProvenanceSourceRef):
            raise TypeError("source_ref must be a ProvenanceSourceRef or None")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        frozen_metadata = _freeze_metadata_value(self.metadata)
        if not isinstance(frozen_metadata, Mapping):  # pragma: no cover - guarded above
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", frozen_metadata)
