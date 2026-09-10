# SPDX-License-Identifier: GPL-3.0-only

"""Strict versioned payload decoding for cognition Events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias, TypeGuard, TypeVar, cast

from grass.core._structured_data import StructuredValue
from grass.core.cognition import (
    BoundedReaction,
    BoundedReactionDecision,
    ContinuePlanDecision,
    Decision,
    DecisionOutcome,
    DecisionOutcomeKind,
    DecisionPoint,
    DecisionPointReason,
    DecisionPointScope,
    Observation,
    ReplacePlanDecision,
    RevisePlanDecision,
)
from grass.core.events import Event
from grass.core.execution import PlanRef
from grass.core.identifiers import DecisionPointId, EntityId, ObservationId, PlanId

OBSERVATION_CREATED = "ObservationCreated"
DECISION_POINT_CREATED = "DecisionPointCreated"
DECISION_RECORDED = "DecisionRecorded"

COGNITION_EVENT_TYPES = frozenset({OBSERVATION_CREATED, DECISION_POINT_CREATED, DECISION_RECORDED})


class CognitionEventPayloadError(ValueError):
    """A known cognition Event has an invalid version or payload."""


@dataclass(frozen=True, slots=True)
class ObservationCreatedPayload:
    observation: Observation


@dataclass(frozen=True, slots=True)
class DecisionPointCreatedPayload:
    decision_point: DecisionPoint


@dataclass(frozen=True, slots=True)
class DecisionRecordedPayload:
    decision: Decision


CognitionEventPayload: TypeAlias = (
    ObservationCreatedPayload | DecisionPointCreatedPayload | DecisionRecordedPayload
)
EnumT = TypeVar("EnumT", DecisionPointReason, DecisionPointScope, DecisionOutcomeKind)


def is_cognition_event_payload(value: object) -> TypeGuard[CognitionEventPayload]:
    return isinstance(
        value,
        (ObservationCreatedPayload, DecisionPointCreatedPayload, DecisionRecordedPayload),
    )


def _mapping(value: object, field_name: str) -> Mapping[str, StructuredValue]:
    if not isinstance(value, Mapping):
        raise CognitionEventPayloadError(f"{field_name} must be a mapping")
    if not all(type(key) is str for key in value):
        raise CognitionEventPayloadError(f"{field_name} keys must be strings")
    return cast("Mapping[str, StructuredValue]", value)


def _fields(
    value: Mapping[str, StructuredValue], expected: frozenset[str], field_name: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CognitionEventPayloadError(
            f"{field_name} fields do not match schema; missing={missing}, extra={extra}"
        )


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or value == "":
        raise CognitionEventPayloadError(f"{field_name} must be a non-empty string")
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise CognitionEventPayloadError(f"{field_name} must be a positive integer")
    return value


def _enum_value(enum_type: type[EnumT], value: object, field_name: str) -> EnumT:
    token = _token(value, field_name)
    try:
        return enum_type(token)
    except ValueError as error:
        raise CognitionEventPayloadError(f"unsupported {field_name}: {token}") from error


def _plan_ref(value: object, field_name: str) -> PlanRef:
    ref = _mapping(value, field_name)
    _fields(ref, frozenset({"plan_id", "version"}), field_name)
    return PlanRef(
        PlanId(_token(ref["plan_id"], "plan_id")),
        _positive_integer(ref["version"], "Plan version"),
    )


def _observation_ids(value: object) -> frozenset[ObservationId]:
    if type(value) is not tuple:
        raise CognitionEventPayloadError("observation_ids must be a sequence")
    ids = tuple(ObservationId(_token(item, "observation_id")) for item in value)
    if len(set(ids)) != len(ids):
        raise CognitionEventPayloadError("observation_ids must not contain duplicates")
    return frozenset(ids)


def _observation_created(event: Event) -> ObservationCreatedPayload:
    _fields(event.payload, frozenset({"observation_id", "actor_id", "content"}), "payload")
    return ObservationCreatedPayload(
        Observation(
            observation_id=ObservationId(_token(event.payload["observation_id"], "observation_id")),
            actor_id=EntityId(_token(event.payload["actor_id"], "actor_id")),
            content=_mapping(event.payload["content"], "content"),
            provenance=event.provenance,
            observed_at=event.logical_time,
        )
    )


def _decision_point_created(event: Event) -> DecisionPointCreatedPayload:
    _fields(
        event.payload,
        frozenset(
            {
                "decision_point_id",
                "actor_id",
                "reason",
                "scope",
                "observation_ids",
                "subject_plan_ref",
            }
        ),
        "payload",
    )
    raw_subject = event.payload["subject_plan_ref"]
    return DecisionPointCreatedPayload(
        DecisionPoint(
            decision_point_id=DecisionPointId(
                _token(event.payload["decision_point_id"], "decision_point_id")
            ),
            actor_id=EntityId(_token(event.payload["actor_id"], "actor_id")),
            reason=_enum_value(DecisionPointReason, event.payload["reason"], "reason"),
            scope=_enum_value(DecisionPointScope, event.payload["scope"], "scope"),
            observation_ids=_observation_ids(event.payload["observation_ids"]),
            subject_plan_ref=(
                None if raw_subject is None else _plan_ref(raw_subject, "subject_plan_ref")
            ),
        )
    )


def _outcome(value: object) -> DecisionOutcome:
    outcome = _mapping(value, "outcome")
    kind = _enum_value(DecisionOutcomeKind, outcome.get("kind"), "outcome kind")
    if kind is DecisionOutcomeKind.CONTINUE_PLAN:
        _fields(outcome, frozenset({"kind"}), "outcome")
        return ContinuePlanDecision()
    if kind is DecisionOutcomeKind.REVISE_PLAN:
        _fields(outcome, frozenset({"kind", "resulting_plan_ref"}), "outcome")
        return RevisePlanDecision(_plan_ref(outcome["resulting_plan_ref"], "resulting_plan_ref"))
    if kind is DecisionOutcomeKind.REPLACE_PLAN:
        _fields(outcome, frozenset({"kind", "resulting_plan_ref"}), "outcome")
        return ReplacePlanDecision(_plan_ref(outcome["resulting_plan_ref"], "resulting_plan_ref"))

    _fields(outcome, frozenset({"kind", "bounded_reaction"}), "outcome")
    reaction = _mapping(outcome["bounded_reaction"], "bounded_reaction")
    _fields(reaction, frozenset({"intent_description", "content"}), "bounded_reaction")
    return BoundedReactionDecision(
        BoundedReaction(
            intent_description=_token(reaction["intent_description"], "intent_description"),
            content=reaction["content"],
        )
    )


def _decision_recorded(event: Event) -> DecisionRecordedPayload:
    _fields(event.payload, frozenset({"decision_point_id", "outcome"}), "payload")
    return DecisionRecordedPayload(
        Decision(
            decision_point_id=DecisionPointId(
                _token(event.payload["decision_point_id"], "decision_point_id")
            ),
            outcome=_outcome(event.payload["outcome"]),
            provenance=event.provenance,
            recorded_at=event.logical_time,
        )
    )


def decode_cognition_event(event: Event) -> CognitionEventPayload:
    """Decode one known version-1 cognition Event into a typed payload."""

    if type(event) is not Event:
        raise TypeError("event must be an Event")
    try:
        if event.event_type not in COGNITION_EVENT_TYPES:
            raise CognitionEventPayloadError(f"unknown cognition Event type: {event.event_type}")
        if event.event_version != 1:
            raise CognitionEventPayloadError(
                f"unsupported {event.event_type} version: {event.event_version}"
            )
        if event.event_type == OBSERVATION_CREATED:
            return _observation_created(event)
        if event.event_type == DECISION_POINT_CREATED:
            return _decision_point_created(event)
        return _decision_recorded(event)
    except CognitionEventPayloadError:
        raise
    except (TypeError, ValueError) as error:
        raise CognitionEventPayloadError(str(error)) from error
