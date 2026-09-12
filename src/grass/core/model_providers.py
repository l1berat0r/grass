# SPDX-License-Identifier: GPL-3.0-only

"""Transport-neutral asynchronous structured model invocation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol

from grass.core._structured_data import StructuredValue, freeze_structured_mapping


def _non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


class ProviderFailureKind(StrEnum):
    AUTHENTICATION = "AUTHENTICATION"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    TRANSPORT = "TRANSPORT"
    PROTOCOL = "PROTOCOL"
    REFUSAL = "REFUSAL"
    INCOMPLETE = "INCOMPLETE"


class ProviderInvocationError(RuntimeError):
    """One external provider invocation failed without changing simulation history."""

    def __init__(self, kind: ProviderFailureKind, message: str) -> None:
        if type(kind) is not ProviderFailureKind:
            raise TypeError("kind must be a ProviderFailureKind")
        _non_empty_string(message, "message")
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ActorModelContext:
    """Versioned actor-relative structured context supplied to a model."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    schema_version: int
    sections: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise TypeError("schema_version must be an integer")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        if not isinstance(self.sections, Mapping):
            raise TypeError("sections must be a mapping")
        object.__setattr__(
            self,
            "sections",
            freeze_structured_mapping(self.sections, description="actor model context"),
        )


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A bounded provider-neutral structured-output invocation."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    model: str
    instructions: str
    context: ActorModelContext
    output_schema: Mapping[str, StructuredValue]
    max_output_tokens: int

    def __post_init__(self) -> None:
        _non_empty_string(self.model, "model")
        _non_empty_string(self.instructions, "instructions")
        if type(self.context) is not ActorModelContext:
            raise TypeError("context must be an ActorModelContext")
        if not isinstance(self.output_schema, Mapping):
            raise TypeError("output_schema must be a mapping")
        if type(self.max_output_tokens) is not int:
            raise TypeError("max_output_tokens must be an integer")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        object.__setattr__(
            self,
            "output_schema",
            freeze_structured_mapping(self.output_schema, description="model output schema"),
        )


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if type(self.input_tokens) is not int or type(self.output_tokens) is not int:
            raise TypeError("token usage must contain integers")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token usage must be non-negative")


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Validated generic structured output plus safe actual-provider metadata."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    output: Mapping[str, StructuredValue]
    provider: str
    model: str
    provider_request_id: str | None = None
    result_status: str | None = None
    usage: ModelUsage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output, Mapping):
            raise TypeError("output must be a mapping")
        _non_empty_string(self.provider, "provider")
        _non_empty_string(self.model, "model")
        if self.provider_request_id is not None:
            _non_empty_string(self.provider_request_id, "provider_request_id")
        if self.result_status is not None:
            _non_empty_string(self.result_status, "result_status")
        if self.usage is not None and type(self.usage) is not ModelUsage:
            raise TypeError("usage must be ModelUsage or None")
        object.__setattr__(
            self,
            "output",
            freeze_structured_mapping(self.output, description="model response output"),
        )


class ModelProvider(Protocol):
    async def invoke(self, request: ModelRequest, /) -> ModelResponse:
        """Invoke one model without creating Events or mutating simulation state."""

        ...
