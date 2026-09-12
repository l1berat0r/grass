# SPDX-License-Identifier: GPL-3.0-only

"""Small injected async JSON HTTP boundary for provider adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from grass.core.model_providers import (
    ProviderFailureKind,
    ProviderInvocationError,
)


@dataclass(frozen=True, slots=True)
class JsonHttpResponse:
    status_code: int
    body: object


class AsyncJsonHttpTransport(Protocol):
    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout_seconds: float,
    ) -> JsonHttpResponse: ...


class HttpxJsonTransport:
    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout_seconds: float,
    ) -> JsonHttpResponse:
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError as error:  # pragma: no cover - environment dependent
            raise ProviderInvocationError(
                ProviderFailureKind.TRANSPORT,
                "install grass-simulator[providers] for HTTP adapters",
            ) from error
        try:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                response = await client.post(
                    url,
                    headers=dict(headers),
                    json=dict(json),
                    timeout=timeout_seconds,
                )
            body: Any = response.json() if 200 <= response.status_code < 300 else None
        except httpx.TimeoutException as error:
            raise TimeoutError("provider HTTP request timed out") from error
        except httpx.HTTPError as error:
            raise OSError("provider HTTP request failed") from error
        except ValueError as error:
            raise ProviderInvocationError(
                ProviderFailureKind.PROTOCOL, "provider returned an invalid JSON response"
            ) from error
        return JsonHttpResponse(response.status_code, body)


def json_value(value: object) -> object:
    """Copy frozen GRASS structured data into standard JSON containers."""

    if isinstance(value, Mapping):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_value(item) for item in value]
    return value
