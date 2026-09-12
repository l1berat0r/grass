# SPDX-License-Identifier: GPL-3.0-only

"""Native OpenAI Responses API ModelProvider adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast

from grass.core._structured_data import StructuredValue, freeze_structured_mapping
from grass.core.model_providers import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderFailureKind,
    ProviderInvocationError,
)
from grass.providers._http import (
    AsyncJsonHttpTransport,
    HttpxJsonTransport,
    JsonHttpResponse,
    json_value,
)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_STRUCTURED_OUTPUT_CHARACTERS = 1_000_000


def _object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(type(key) is str for key in value):
        raise ProviderInvocationError(ProviderFailureKind.PROTOCOL, f"invalid {name}")
    return value


def _array(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ProviderInvocationError(ProviderFailureKind.PROTOCOL, f"invalid {name}")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or value == "":
        raise ProviderInvocationError(ProviderFailureKind.PROTOCOL, f"invalid {name}")
    return value


def _usage(value: object) -> ModelUsage | None:
    if value is None:
        return None
    usage = _object(value, "OpenAI usage")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    try:
        return ModelUsage(input_tokens, output_tokens)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ProviderInvocationError(
            ProviderFailureKind.PROTOCOL, "invalid OpenAI usage"
        ) from error


def _json_object(text: str) -> Mapping[str, StructuredValue]:
    if len(text) > MAX_STRUCTURED_OUTPUT_CHARACTERS:
        raise ProviderInvocationError(
            ProviderFailureKind.PROTOCOL, "provider structured output exceeds its size limit"
        )

    def reject_constant(value: str) -> object:
        raise ValueError(value)

    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ProviderInvocationError(
            ProviderFailureKind.PROTOCOL, "provider returned malformed structured output"
        ) from error
    output = cast(Mapping[str, StructuredValue], _object(value, "structured output"))
    try:
        return freeze_structured_mapping(output, description="provider structured output")
    except (TypeError, ValueError) as error:
        raise ProviderInvocationError(
            ProviderFailureKind.PROTOCOL, "provider returned malformed structured output"
        ) from error


def _output_text(body: Mapping[str, object]) -> str:
    for item in _array(body.get("output"), "OpenAI output"):
        output_item = _object(item, "OpenAI output item")
        if output_item.get("type") != "message":
            continue
        for content in _array(output_item.get("content"), "OpenAI message content"):
            content_item = _object(content, "OpenAI content item")
            if content_item.get("type") == "refusal":
                raise ProviderInvocationError(
                    ProviderFailureKind.REFUSAL, "provider refused structured output"
                )
            if content_item.get("type") == "output_text":
                text = content_item.get("text")
                if type(text) is str and text != "":
                    return text
    raise ProviderInvocationError(
        ProviderFailureKind.PROTOCOL, "provider response contains no structured output"
    )


def _http_failure(response: JsonHttpResponse) -> None:
    if response.status_code in (401, 403):
        kind = ProviderFailureKind.AUTHENTICATION
    elif response.status_code == 429:
        kind = ProviderFailureKind.RATE_LIMIT
    else:
        kind = ProviderFailureKind.TRANSPORT
    raise ProviderInvocationError(kind, f"provider HTTP request failed with {response.status_code}")


class OpenAIModelProvider(ModelProvider):
    """Translate generic structured invocation to the native Responses API."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: AsyncJsonHttpTransport | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if type(api_key) is not str or api_key == "":
            raise ValueError("api_key must be a non-empty string")
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key
        self._transport = HttpxJsonTransport() if transport is None else transport
        self._timeout_seconds = float(timeout_seconds)

    async def invoke(self, request: ModelRequest, /) -> ModelResponse:
        if type(request) is not ModelRequest:
            raise TypeError("request must be a ModelRequest")
        payload = {
            "model": request.model,
            "instructions": request.instructions,
            "input": json.dumps(json_value(request.context.sections), separators=(",", ":")),
            "max_output_tokens": request.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "grass_structured_output",
                    "strict": False,
                    "schema": json_value(request.output_schema),
                }
            },
        }
        try:
            response = await self._transport.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout_seconds=self._timeout_seconds,
            )
        except TimeoutError as error:
            raise ProviderInvocationError(
                ProviderFailureKind.TIMEOUT, "provider request timed out"
            ) from error
        except OSError as error:
            raise ProviderInvocationError(
                ProviderFailureKind.TRANSPORT, "provider transport failed"
            ) from error
        if response.status_code < 200 or response.status_code >= 300:
            _http_failure(response)
        body = _object(response.body, "OpenAI response")
        status = _optional_string(body.get("status"), "OpenAI status")
        if status != "completed":
            raise ProviderInvocationError(
                ProviderFailureKind.INCOMPLETE, "provider response is incomplete"
            )
        model = _optional_string(body.get("model"), "OpenAI model")
        if model is None:
            raise ProviderInvocationError(
                ProviderFailureKind.PROTOCOL, "OpenAI response is missing model identity"
            )
        return ModelResponse(
            output=_json_object(_output_text(body)),
            provider="openai",
            model=model,
            provider_request_id=_optional_string(body.get("id"), "OpenAI response id"),
            result_status=status,
            usage=_usage(body.get("usage")),
        )
