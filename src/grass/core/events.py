# SPDX-License-Identifier: GPL-3.0-only

"""Immutable pre-commit and committed Event contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, TypeAlias

from grass.core._structured_data import StructuredValue, freeze_structured_mapping
from grass.core.identifiers import BranchId, CorrelationId, EventId, TransitionId
from grass.core.logical_time import LogicalTime
from grass.core.provenance import Provenance
from grass.core.references import TransitionRef

EventPayload: TypeAlias = Mapping[str, StructuredValue]


def _require_non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


def _validate_event_version(value: object) -> None:
    if type(value) is not int:
        raise TypeError("event_version must be an integer")
    if value < 1:
        raise ValueError("event_version must be positive")


def _freeze_causes(causes: Sequence[CauseRef]) -> tuple[CauseRef, ...]:
    frozen = tuple(causes)
    if not all(type(cause) is CauseRef for cause in frozen):
        raise TypeError("causation_refs must contain only CauseRef values")
    return frozen


@dataclass(frozen=True, slots=True)
class CauseRef:
    """An explicit syntactic causal reference without inferred semantics."""

    kind: str
    value: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.kind, "cause kind")
        _require_non_empty_string(self.value, "cause value")


@dataclass(frozen=True, slots=True)
class EventToCommit:
    """One engine-authorized Event record before authoritative commit."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    event_id: EventId
    event_type: str
    event_version: int
    payload: EventPayload
    provenance: Provenance
    causation_refs: Sequence[CauseRef] = ()
    correlation_id: CorrelationId | None = None

    def __post_init__(self) -> None:
        if type(self.event_id) is not EventId:
            raise TypeError("event_id must be an EventId")
        _require_non_empty_string(self.event_type, "event_type")
        _validate_event_version(self.event_version)
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if type(self.provenance) is not Provenance:
            raise TypeError("provenance must be Provenance")
        if self.correlation_id is not None and type(self.correlation_id) is not CorrelationId:
            raise TypeError("correlation_id must be a CorrelationId or None")
        object.__setattr__(
            self,
            "payload",
            freeze_structured_mapping(self.payload, description="event payload"),
        )
        object.__setattr__(self, "causation_refs", _freeze_causes(self.causation_refs))


@dataclass(frozen=True, slots=True)
class TransitionToCommit:
    """A non-empty atomic transition before authoritative commit."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    transition_ref: TransitionRef
    logical_time: LogicalTime
    events: Sequence[EventToCommit]

    def __post_init__(self) -> None:
        if type(self.transition_ref) is not TransitionRef:
            raise TypeError("transition_ref must be a TransitionRef")
        if type(self.logical_time) is not LogicalTime:
            raise TypeError("logical_time must be LogicalTime")
        frozen_events = tuple(self.events)
        if not frozen_events:
            raise ValueError("a transition must contain at least one Event")
        if not all(type(event) is EventToCommit for event in frozen_events):
            raise TypeError("events must contain only EventToCommit values")
        object.__setattr__(self, "events", frozen_events)


@dataclass(frozen=True, slots=True)
class Event:
    """An immutable accepted historical fact."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    event_id: EventId
    branch_id: BranchId
    sequence: int
    logical_time: LogicalTime
    transition_id: TransitionId
    event_type: str
    event_version: int
    payload: EventPayload
    provenance: Provenance
    causation_refs: Sequence[CauseRef] = ()
    correlation_id: CorrelationId | None = None

    def __post_init__(self) -> None:
        if type(self.event_id) is not EventId:
            raise TypeError("event_id must be an EventId")
        if type(self.branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        if type(self.sequence) is not int:
            raise TypeError("sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        if type(self.logical_time) is not LogicalTime:
            raise TypeError("logical_time must be LogicalTime")
        if type(self.transition_id) is not TransitionId:
            raise TypeError("transition_id must be a TransitionId")
        _require_non_empty_string(self.event_type, "event_type")
        _validate_event_version(self.event_version)
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if type(self.provenance) is not Provenance:
            raise TypeError("provenance must be Provenance")
        if self.correlation_id is not None and type(self.correlation_id) is not CorrelationId:
            raise TypeError("correlation_id must be a CorrelationId or None")
        object.__setattr__(
            self,
            "payload",
            freeze_structured_mapping(self.payload, description="event payload"),
        )
        object.__setattr__(self, "causation_refs", _freeze_causes(self.causation_refs))


@dataclass(frozen=True, slots=True)
class CommittedTransition:
    """One complete atomic transition derived from its committed Events."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    events: Sequence[Event]

    def __post_init__(self) -> None:
        frozen_events = tuple(self.events)
        if not frozen_events:
            raise ValueError("a committed transition must contain at least one Event")
        if not all(type(event) is Event for event in frozen_events):
            raise TypeError("events must contain only Event values")

        first = frozen_events[0]
        for offset, event in enumerate(frozen_events):
            if event.branch_id != first.branch_id:
                raise ValueError("committed Events must share one branch_id")
            if event.transition_id != first.transition_id:
                raise ValueError("committed Events must share one transition_id")
            if event.logical_time != first.logical_time:
                raise ValueError("committed Events must share one logical_time")
            if event.sequence != first.sequence + offset:
                raise ValueError("committed Event sequences must be contiguous")

        object.__setattr__(self, "events", frozen_events)

    @property
    def branch_id(self) -> BranchId:
        return self.events[0].branch_id

    @property
    def transition_id(self) -> TransitionId:
        return self.events[0].transition_id

    @property
    def transition_ref(self) -> TransitionRef:
        return TransitionRef(self.branch_id, self.transition_id)

    @property
    def logical_time(self) -> LogicalTime:
        return self.events[0].logical_time
