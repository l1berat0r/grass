# SPDX-License-Identifier: GPL-3.0-only

"""Strict versioned payload decoding for resolution outcome Events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from grass.core._structured_data import StructuredValue
from grass.core.events import Event
from grass.core.identifiers import JobId

RESOLUTION_OUTCOME_RECORDED = "ResolutionOutcomeRecorded"
RESOLUTION_EVENT_TYPES = frozenset({RESOLUTION_OUTCOME_RECORDED})


class ResolutionOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ResolutionEventPayloadError(ValueError):
    """A known resolution Event has an invalid version or payload."""


@dataclass(frozen=True, slots=True)
class ResolutionOutcomeRecordedPayload:
    job_id: JobId
    outcome: ResolutionOutcome


def _require_fields(payload: Mapping[str, StructuredValue]) -> None:
    expected = frozenset({"job_id", "outcome"})
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ResolutionEventPayloadError(
            f"payload fields do not match schema; missing={missing}, extra={extra}"
        )


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or value == "":
        raise ResolutionEventPayloadError(f"{field_name} must be a non-empty string")
    return value


def decode_resolution_event(event: Event) -> ResolutionOutcomeRecordedPayload:
    """Decode one known version-1 resolution Event into a typed payload."""

    if type(event) is not Event:
        raise TypeError("event must be an Event")
    if event.event_type not in RESOLUTION_EVENT_TYPES:
        raise ResolutionEventPayloadError(f"unknown resolution Event type: {event.event_type}")
    if event.event_version != 1:
        raise ResolutionEventPayloadError(
            f"unsupported {event.event_type} version: {event.event_version}"
        )
    _require_fields(event.payload)
    outcome = _token(event.payload["outcome"], "outcome")
    try:
        resolution_outcome = ResolutionOutcome(outcome)
    except ValueError as error:
        raise ResolutionEventPayloadError(f"unsupported resolution outcome: {outcome}") from error
    return ResolutionOutcomeRecordedPayload(
        JobId(_token(event.payload["job_id"], "job_id")),
        resolution_outcome,
    )
