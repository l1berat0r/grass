# SPDX-License-Identifier: GPL-3.0-only

"""Limited trusted OpenAI-compatible structured-output ModelProvider adapter."""

from __future__ import annotations

import json
from collections.abc import Sequence
from urllib.parse import urlsplit

from grass.core.model_providers import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderFailureKind,
    ProviderInvocationError,
)
from grass.providers._http import AsyncJsonHttpTransport, HttpxJsonTransport, json_value
from grass.providers.openai import _http_failure, _json_object, _object, _optional_string


class OpenAICompatibleModelProvider(ModelProvider):
    """Call one explicitly trusted compatible chat-completions endpoint."""

    def __init__(
        self,
        provider_name: str,
        trusted_base_url: str,
        *,
        api_key: str | None = None,
        transport: AsyncJsonHttpTransport | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if type(provider_name) is not str or provider_name == "":
            raise ValueError("provider_name must be a non-empty string")
        if type(trusted_base_url) is not str or trusted_base_url == "":
            raise ValueError("trusted_base_url must be a non-empty string")
        parsed = urlsplit(trusted_base_url)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query != ""
            or parsed.fragment != ""
        ):
            raise ValueError("trusted_base_url must be an absolute HTTP URL without credentials")
        if api_key is not None and (type(api_key) is not str or api_key == ""):
            raise ValueError("api_key must be a non-empty string or None")
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._provider_name = provider_name
        self._url = f"{trusted_base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._transport = HttpxJsonTransport() if transport is None else transport
        self._timeout_seconds = float(timeout_seconds)

    async def invoke(self, request: ModelRequest, /) -> ModelResponse:
        if type(request) is not ModelRequest:
            raise TypeError("request must be a ModelRequest")
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.instructions},
                {
                    "role": "user",
                    "content": json.dumps(
                        json_value(request.context.sections), separators=(",", ":")
                    ),
                },
            ],
            "max_tokens": request.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "grass_structured_output",
                    "strict": False,
                    "schema": json_value(request.output_schema),
                },
            },
        }
        try:
            response = await self._transport.post(
                self._url,
                headers=headers,
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
        body = _object(response.body, "compatible response")
        choices = body.get("choices")
        if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes, bytearray)):
            raise ProviderInvocationError(
                ProviderFailureKind.PROTOCOL, "compatible response has invalid choices"
            )
        if len(choices) != 1:
            raise ProviderInvocationError(
                ProviderFailureKind.PROTOCOL, "compatible response must contain one choice"
            )
        choice = _object(choices[0], "compatible choice")
        finish_reason = _optional_string(choice.get("finish_reason"), "finish_reason")
        if finish_reason == "content_filter":
            raise ProviderInvocationError(
                ProviderFailureKind.REFUSAL, "compatible provider refused structured output"
            )
        if finish_reason != "stop":
            raise ProviderInvocationError(
                ProviderFailureKind.INCOMPLETE, "compatible provider response is incomplete"
            )
        message = _object(choice.get("message"), "compatible message")
        if message.get("refusal") is not None:
            _optional_string(message["refusal"], "compatible refusal")
            raise ProviderInvocationError(
                ProviderFailureKind.REFUSAL, "compatible provider refused structured output"
            )
        content = message.get("content")
        if type(content) is not str or content == "":
            raise ProviderInvocationError(
                ProviderFailureKind.PROTOCOL, "compatible response has no structured output"
            )
        model = _optional_string(body.get("model"), "compatible model")
        if model is None:
            raise ProviderInvocationError(
                ProviderFailureKind.PROTOCOL, "compatible response is missing model identity"
            )
        usage_value = body.get("usage")
        usage: ModelUsage | None = None
        if usage_value is not None:
            usage_object = _object(usage_value, "compatible usage")
            try:
                usage = ModelUsage(
                    usage_object.get("prompt_tokens"),  # type: ignore[arg-type]
                    usage_object.get("completion_tokens"),  # type: ignore[arg-type]
                )
            except (TypeError, ValueError) as error:
                raise ProviderInvocationError(
                    ProviderFailureKind.PROTOCOL, "compatible response has invalid usage"
                ) from error
        return ModelResponse(
            output=_json_object(content),
            provider=self._provider_name,
            model=model,
            provider_request_id=_optional_string(body.get("id"), "compatible response id"),
            result_status=finish_reason,
            usage=usage,
        )
