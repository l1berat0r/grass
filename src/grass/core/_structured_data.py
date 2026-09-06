# SPDX-License-Identifier: GPL-3.0-only

"""Minimal freezing for structured core values."""

from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType
from typing import TypeAlias

StructuredScalar: TypeAlias = str | int | float | bool | None
StructuredValue: TypeAlias = (
    StructuredScalar
    | Mapping[str, "StructuredValue"]
    | list["StructuredValue"]
    | tuple["StructuredValue", ...]
)


def freeze_structured_mapping(
    value: Mapping[str, StructuredValue], *, description: str
) -> Mapping[str, StructuredValue]:
    """Copy and recursively freeze one structured mapping."""

    frozen = _freeze_structured_value(value, description=description)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guaranteed by the input type
        raise TypeError(f"{description} must be a mapping")
    return frozen


def freeze_structured_value(value: StructuredValue, *, description: str) -> StructuredValue:
    """Copy and recursively freeze one structured value."""

    return _freeze_structured_value(value, description=description)


def _freeze_structured_value(value: StructuredValue, *, description: str) -> StructuredValue:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError(f"{description} floats must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, StructuredValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"{description} mapping keys must be strings")
            frozen[key] = _freeze_structured_value(item, description=description)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_structured_value(item, description=description) for item in value)
    raise TypeError(f"unsupported {description} value: {type(value).__name__}")
