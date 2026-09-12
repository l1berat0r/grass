# SPDX-License-Identifier: GPL-3.0-only

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from grass.core import (
    ActorModelContext,
    ModelRequest,
    ProviderFailureKind,
    ProviderInvocationError,
)
from grass.providers._http import JsonHttpResponse
from grass.providers.openai import OPENAI_RESPONSES_URL, OpenAIModelProvider
from grass.providers.openai_compatible import OpenAICompatibleModelProvider


@dataclass
class FakeTransport:
    response: JsonHttpResponse | None = None
    error: Exception | None = None
    calls: list[tuple[str, Mapping[str, str], Mapping[str, object], float]] = field(
        default_factory=list
    )

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout_seconds: float,
    ) -> JsonHttpResponse:
        self.calls.append((url, headers, json, timeout_seconds))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def request() -> ModelRequest:
    return ModelRequest(
        "requested-model",
        "Return JSON",
        ActorModelContext(1, {"decision": {"reason": "PLAN_REQUIRED"}}),
        {"type": "object", "properties": {"kind": {"type": "string"}}},
        100,
    )


def test_native_openai_responses_translation_and_safe_metadata() -> None:
    secret = "secret-openai-key"
    transport = FakeTransport(
        JsonHttpResponse(
            200,
            {
                "id": "response-1",
                "model": "actual-model",
                "status": "completed",
                "usage": {"input_tokens": 4, "output_tokens": 2},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"kind":"CONTINUE_PLAN"}'}],
                    }
                ],
            },
        )
    )
    provider = OpenAIModelProvider(secret, transport=transport)

    response = asyncio.run(provider.invoke(request()))

    assert response.output == {"kind": "CONTINUE_PLAN"}
    assert response.provider == "openai"
    assert response.model == "actual-model"
    assert response.usage is not None and response.usage.output_tokens == 2
    url, headers, payload, _timeout = transport.calls[0]
    assert url == OPENAI_RESPONSES_URL
    assert headers["Authorization"] == f"Bearer {secret}"
    assert payload["model"] == "requested-model"
    assert "responses" not in repr(response).lower()
    assert secret not in repr(provider)
    assert secret not in repr(response)


def test_compatible_translation_supports_trusted_ollama_endpoint() -> None:
    transport = FakeTransport(
        JsonHttpResponse(
            200,
            {
                "id": "chat-1",
                "model": "qwen-actual",
                "choices": [
                    {
                        "message": {"content": '{"kind":"CONTINUE_PLAN"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )
    )
    provider = OpenAICompatibleModelProvider(
        "ollama", "http://localhost:11434/v1", transport=transport
    )

    response = asyncio.run(provider.invoke(request()))

    assert response.provider == "ollama"
    assert response.output == {"kind": "CONTINUE_PLAN"}
    assert transport.calls[0][0] == "http://localhost:11434/v1/chat/completions"
    assert "response_format" in transport.calls[0][2]


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/model",
        "http://user:password@localhost:11434/v1",
        "http://localhost:11434/v1?target=other",
        "http://localhost:11434/v1#fragment",
    ],
)
def test_compatible_adapter_rejects_untrusted_url_shapes(url: str) -> None:
    with pytest.raises(ValueError, match="trusted_base_url"):
        OpenAICompatibleModelProvider("local", url, transport=FakeTransport())


@pytest.mark.parametrize(
    "response,error_kind",
    [
        (JsonHttpResponse(401, {}), ProviderFailureKind.AUTHENTICATION),
        (JsonHttpResponse(429, {}), ProviderFailureKind.RATE_LIMIT),
        (
            JsonHttpResponse(200, {"model": "x", "status": "completed", "output": []}),
            ProviderFailureKind.PROTOCOL,
        ),
    ],
)
def test_provider_failures_are_explicit_and_sanitized(
    response: JsonHttpResponse, error_kind: ProviderFailureKind
) -> None:
    provider = OpenAIModelProvider("secret", transport=FakeTransport(response))

    with pytest.raises(ProviderInvocationError) as caught:
        asyncio.run(provider.invoke(request()))

    assert caught.value.kind is error_kind
    assert "secret" not in str(caught.value)


def test_timeout_is_not_conflated_with_transport_or_protocol_failure() -> None:
    provider = OpenAIModelProvider(
        "secret", transport=FakeTransport(error=TimeoutError("unsafe details"))
    )

    with pytest.raises(ProviderInvocationError) as caught:
        asyncio.run(provider.invoke(request()))

    assert caught.value.kind is ProviderFailureKind.TIMEOUT
    assert "unsafe details" not in str(caught.value)


def test_transport_failure_is_distinct_and_sanitized() -> None:
    provider = OpenAIModelProvider(
        "secret", transport=FakeTransport(error=OSError("unsafe transport details"))
    )

    with pytest.raises(ProviderInvocationError) as caught:
        asyncio.run(provider.invoke(request()))

    assert caught.value.kind is ProviderFailureKind.TRANSPORT
    assert "unsafe transport details" not in str(caught.value)


def test_incomplete_native_and_compatible_responses_are_rejected() -> None:
    native = OpenAIModelProvider(
        "secret",
        transport=FakeTransport(
            JsonHttpResponse(
                200,
                {
                    "id": "response",
                    "model": "model",
                    "status": "incomplete",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": '{"kind":"CONTINUE_PLAN"}'}
                            ],
                        }
                    ],
                },
            )
        ),
    )
    compatible = OpenAICompatibleModelProvider(
        "ollama",
        "http://localhost:11434/v1",
        transport=FakeTransport(
            JsonHttpResponse(
                200,
                {
                    "model": "model",
                    "choices": [
                        {
                            "message": {"content": '{"kind":"CONTINUE_PLAN"}'},
                            "finish_reason": "length",
                        }
                    ],
                },
            )
        ),
    )

    for provider in (native, compatible):
        with pytest.raises(ProviderInvocationError) as caught:
            asyncio.run(provider.invoke(request()))
        assert caught.value.kind is ProviderFailureKind.INCOMPLETE


@pytest.mark.parametrize(
    "text",
    [
        '{"kind":"CONTINUE_PLAN","kind":"REPLACE_PLAN"}',
        '{"kind":NaN}',
        '{"value":1e10000}',
        "not-json",
    ],
)
def test_malformed_structured_output_is_rejected(text: str) -> None:
    provider = OpenAIModelProvider(
        "secret",
        transport=FakeTransport(
            JsonHttpResponse(
                200,
                {
                    "model": "model",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    ],
                },
            )
        ),
    )

    with pytest.raises(ProviderInvocationError) as caught:
        asyncio.run(provider.invoke(request()))

    assert caught.value.kind is ProviderFailureKind.PROTOCOL


@pytest.mark.parametrize(
    "choice",
    [
        {"message": {"content": None, "refusal": "unsafe"}, "finish_reason": "stop"},
        {"message": {"content": None}, "finish_reason": "content_filter"},
    ],
)
def test_compatible_provider_refusal_is_distinct_from_incomplete_output(
    choice: dict[str, object],
) -> None:
    provider = OpenAICompatibleModelProvider(
        "compatible",
        "https://provider.example/v1",
        transport=FakeTransport(
            JsonHttpResponse(
                200,
                {"model": "model", "choices": [choice]},
            )
        ),
    )

    with pytest.raises(ProviderInvocationError) as caught:
        asyncio.run(provider.invoke(request()))

    assert caught.value.kind is ProviderFailureKind.REFUSAL
