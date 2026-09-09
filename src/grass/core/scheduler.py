# SPDX-License-Identifier: GPL-3.0-only

"""Ephemeral event-driven scheduling over authoritative state and history."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Generic, Protocol, TypeVar

from grass.core._structured_data import StructuredValue, freeze_structured_mapping
from grass.core.events import CommittedTransition
from grass.core.execution import BinaryProgress, JobProgress, JobStatus, LinearProgress
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_PROGRESS_UPDATED,
    ExecutionEventPayloadError,
    JobActivatedPayload,
    JobProgressUpdatedPayload,
    decode_execution_event,
)
from grass.core.identifiers import JobId
from grass.core.logical_time import LogicalDuration, LogicalTime
from grass.core.state import SimulationState

SourceRefT = TypeVar("SourceRefT", bound=Hashable)


class SchedulerError(ValueError):
    """Ephemeral scheduler inputs violate the Slice 6 contracts."""


class SchedulerHistoryError(SchedulerError):
    """Branch-visible history cannot produce coherent scheduler inputs."""


@dataclass(frozen=True, slots=True)
class ProgressAnchor:
    """Committed progress baseline and time for one currently active Job."""

    job_id: JobId
    baseline_progress: JobProgress
    anchor_time: LogicalTime

    def __post_init__(self) -> None:
        if type(self.job_id) is not JobId:
            raise TypeError("job_id must be a JobId")
        if type(self.baseline_progress) not in (LinearProgress, BinaryProgress):
            raise TypeError("baseline_progress must be LinearProgress or BinaryProgress")
        if type(self.anchor_time) is not LogicalTime:
            raise TypeError("anchor_time must be a LogicalTime")


@dataclass(frozen=True, slots=True)
class ScheduledResolution(Generic[SourceRefT]):
    """One disposable prediction of a future material reconsideration point."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    logical_time: LogicalTime
    kind: str
    source_ref: SourceRefT
    metadata: Mapping[str, StructuredValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.logical_time) is not LogicalTime:
            raise TypeError("logical_time must be a LogicalTime")
        if type(self.kind) is not str:
            raise TypeError("kind must be a string")
        if self.kind == "":
            raise ValueError("kind must not be empty")
        try:
            hash(self.source_ref)
        except TypeError as error:
            raise TypeError("source_ref must be hashable") from error
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(
            self,
            "metadata",
            freeze_structured_mapping(self.metadata, description="ScheduledResolution metadata"),
        )


class ScheduleProjector(Protocol[SourceRefT]):
    """Pure deterministic projection of current ephemeral scheduler candidates."""

    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> Sequence[ScheduledResolution[SourceRefT]]:
        """Derive all current candidates from explicit authoritative inputs."""

        ...


def _contains_equal(values: Sequence[ScheduledResolution[SourceRefT]], index: int) -> bool:
    return any(values[index] == values[other] for other in range(index))


def _validate_candidates(
    current_time: LogicalTime,
    candidates: Sequence[ScheduledResolution[SourceRefT]],
) -> tuple[ScheduledResolution[SourceRefT], ...]:
    if type(current_time) is not LogicalTime:
        raise TypeError("current_time must be a LogicalTime")
    frozen = tuple(candidates)
    for index, candidate in enumerate(frozen):
        if type(candidate) is not ScheduledResolution:
            raise TypeError("candidates must contain ScheduledResolution values")
        if candidate.logical_time < current_time:
            raise SchedulerError("ScheduledResolution cannot precede current_time")
        if _contains_equal(frozen, index):
            raise SchedulerError("ScheduledResolution candidates must not contain duplicates")
    return frozen


def _predicate_result(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("conflict predicate must return a boolean")
    return value


def group_conflict_components(
    candidates: Sequence[ScheduledResolution[SourceRefT]],
    conflicts: Callable[[ScheduledResolution[SourceRefT], ScheduledResolution[SourceRefT]], bool],
    /,
) -> tuple[tuple[ScheduledResolution[SourceRefT], ...], ...]:
    """Group one same-time candidate set by symmetric transitive conflicts."""

    frozen = tuple(candidates)
    for index, candidate in enumerate(frozen):
        if type(candidate) is not ScheduledResolution:
            raise TypeError("candidates must contain ScheduledResolution values")
        if _contains_equal(frozen, index):
            raise SchedulerError("ScheduledResolution candidates must not contain duplicates")
    if frozen and any(candidate.logical_time != frozen[0].logical_time for candidate in frozen):
        raise SchedulerError("conflict candidates must share one logical_time")
    if not callable(conflicts):
        raise TypeError("conflicts must be callable")

    adjacency: list[set[int]] = [set() for _ in frozen]
    for left_index, left in enumerate(frozen):
        for right_index in range(left_index + 1, len(frozen)):
            right = frozen[right_index]
            forward = _predicate_result(conflicts(left, right))
            reverse = _predicate_result(conflicts(right, left))
            if forward != reverse:
                raise SchedulerError("conflict predicate must be symmetric")
            if forward:
                adjacency[left_index].add(right_index)
                adjacency[right_index].add(left_index)

    components: list[tuple[ScheduledResolution[SourceRefT], ...]] = []
    remaining = set(range(len(frozen)))
    while remaining:
        start = min(remaining)
        pending = [start]
        component: list[int] = []
        remaining.remove(start)
        while pending:
            index = pending.pop()
            component.append(index)
            for neighbor in sorted(adjacency[index]):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        components.append(tuple(frozen[index] for index in sorted(component)))
    return tuple(components)


@dataclass(frozen=True, slots=True)
class SchedulerStep(Generic[SourceRefT]):
    """One non-authoritative snapshot-derived due batch."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    current_time: LogicalTime
    target_time: LogicalTime
    elapsed: LogicalDuration
    due_candidates: Sequence[ScheduledResolution[SourceRefT]]
    conflict_components: Sequence[Sequence[ScheduledResolution[SourceRefT]]]

    def __post_init__(self) -> None:
        if type(self.current_time) is not LogicalTime:
            raise TypeError("current_time must be a LogicalTime")
        if type(self.target_time) is not LogicalTime:
            raise TypeError("target_time must be a LogicalTime")
        if type(self.elapsed) is not LogicalDuration:
            raise TypeError("elapsed must be a LogicalDuration")
        expected_elapsed = self.target_time - self.current_time
        if self.elapsed != expected_elapsed:
            raise ValueError("elapsed must equal target_time minus current_time")

        due = tuple(self.due_candidates)
        if not due:
            raise ValueError("due_candidates must not be empty")
        if any(type(candidate) is not ScheduledResolution for candidate in due):
            raise TypeError("due_candidates must contain ScheduledResolution values")
        if any(candidate.logical_time != self.target_time for candidate in due):
            raise ValueError("due candidates must share target_time")
        if any(_contains_equal(due, index) for index in range(len(due))):
            raise ValueError("due_candidates must not contain duplicates")

        components = tuple(tuple(component) for component in self.conflict_components)
        if not components or any(not component for component in components):
            raise ValueError("conflict_components must partition due_candidates")
        if any(
            type(candidate) is not ScheduledResolution
            for component in components
            for candidate in component
        ):
            raise TypeError("conflict_components must contain ScheduledResolution values")
        remaining = list(due)
        for component in components:
            for candidate in component:
                for index, expected in enumerate(remaining):
                    if candidate == expected:
                        remaining.pop(index)
                        break
                else:
                    raise ValueError("conflict_components must partition due_candidates")
        if remaining:
            raise ValueError("conflict_components must partition due_candidates")

        object.__setattr__(self, "due_candidates", due)
        object.__setattr__(self, "conflict_components", components)


class ScheduledResolutionIndex(Generic[SourceRefT]):
    """Disposable source-indexed collection of current scheduler predictions."""

    def __init__(self) -> None:
        self._by_source: dict[SourceRefT, tuple[ScheduledResolution[SourceRefT], ...]] = {}

    def rebuild(
        self,
        current_time: LogicalTime,
        candidates: Sequence[ScheduledResolution[SourceRefT]],
        /,
    ) -> None:
        """Replace the complete index with one fully derived candidate set."""

        frozen = _validate_candidates(current_time, candidates)
        rebuilt: dict[SourceRefT, list[ScheduledResolution[SourceRefT]]] = {}
        for candidate in frozen:
            rebuilt.setdefault(candidate.source_ref, []).append(candidate)
        self._by_source = {
            source_ref: tuple(source_candidates)
            for source_ref, source_candidates in rebuilt.items()
        }

    def replace_source(
        self,
        current_time: LogicalTime,
        source_ref: SourceRefT,
        candidates: Sequence[ScheduledResolution[SourceRefT]],
        /,
    ) -> None:
        """Replace one source's complete projected set; an empty set removes it."""

        try:
            hash(source_ref)
        except TypeError as error:
            raise TypeError("source_ref must be hashable") from error
        frozen = _validate_candidates(current_time, candidates)
        if any(candidate.source_ref != source_ref for candidate in frozen):
            raise SchedulerError("replacement candidates must match source_ref")

        updated = self._by_source.copy()
        if frozen:
            updated[source_ref] = frozen
        else:
            updated.pop(source_ref, None)
        _validate_candidates(
            current_time,
            tuple(
                candidate
                for source_candidates in updated.values()
                for candidate in source_candidates
            ),
        )
        self._by_source = updated

    def snapshot(self, current_time: LogicalTime, /) -> tuple[ScheduledResolution[SourceRefT], ...]:
        """Return all current entries without consuming them."""

        candidates = tuple(
            candidate
            for source_candidates in self._by_source.values()
            for candidate in source_candidates
        )
        return _validate_candidates(current_time, candidates)

    def earliest_candidates(
        self, current_time: LogicalTime, /
    ) -> tuple[ScheduledResolution[SourceRefT], ...]:
        """Return the complete earliest same-time set without consuming it."""

        candidates = self.snapshot(current_time)
        if not candidates:
            return ()
        earliest = min(candidate.logical_time for candidate in candidates)
        return tuple(candidate for candidate in candidates if candidate.logical_time == earliest)

    def next_step(
        self,
        current_time: LogicalTime,
        conflicts: Callable[
            [ScheduledResolution[SourceRefT], ScheduledResolution[SourceRefT]], bool
        ],
        /,
    ) -> SchedulerStep[SourceRefT] | None:
        """Build one non-destructive scheduler step for the earliest due set."""

        due = self.earliest_candidates(current_time)
        if not due:
            return None
        target_time = due[0].logical_time
        return SchedulerStep(
            current_time=current_time,
            target_time=target_time,
            elapsed=target_time - current_time,
            due_candidates=due,
            conflict_components=group_conflict_components(due, conflicts),
        )


def derive_progress_anchors(
    state: SimulationState,
    current_time: LogicalTime,
    visible_history: Sequence[CommittedTransition],
    /,
) -> Mapping[JobId, ProgressAnchor]:
    """Derive active-Job anchors from complete branch-visible committed history."""

    if type(state) is not SimulationState:
        raise TypeError("state must be a SimulationState")
    if type(current_time) is not LogicalTime:
        raise TypeError("current_time must be a LogicalTime")
    history = tuple(visible_history)
    if not history:
        raise SchedulerHistoryError("branch-visible history must not be empty")
    if not all(type(transition) is CommittedTransition for transition in history):
        raise TypeError("visible_history must contain CommittedTransition values")
    if history[-1].logical_time != current_time:
        raise SchedulerHistoryError(
            "current_time must equal the branch-visible history position time"
        )
    if any(
        later.logical_time < earlier.logical_time
        for earlier, later in zip(history, history[1:], strict=False)
    ):
        raise SchedulerHistoryError("branch-visible history time must be nondecreasing")

    latest_activation: dict[JobId, tuple[int, LogicalTime]] = {}
    latest_progress: dict[JobId, tuple[int, LogicalTime]] = {}
    for transition_index, transition in enumerate(history):
        for event in transition.events:
            if event.event_type not in (JOB_ACTIVATED, JOB_PROGRESS_UPDATED):
                continue
            try:
                payload = decode_execution_event(event)
            except ExecutionEventPayloadError as error:
                raise SchedulerHistoryError(str(error)) from error
            if type(payload) is JobActivatedPayload:
                latest_activation[payload.job_id] = (transition_index, transition.logical_time)
            elif type(payload) is JobProgressUpdatedPayload:
                latest_progress[payload.job_id] = (transition_index, transition.logical_time)
            else:  # pragma: no cover - event-type routing above is closed
                raise AssertionError("unexpected execution payload")

    anchors: dict[JobId, ProgressAnchor] = {}
    for job_id, job in state.execution.jobs.items():
        if job.status is not JobStatus.ACTIVE:
            continue
        activation = latest_activation.get(job_id)
        if activation is None:
            raise SchedulerHistoryError("ACTIVE Job has no visible activation boundary")
        anchor_index, anchor_time = activation
        progress = latest_progress.get(job_id)
        if progress is not None and progress[0] >= anchor_index:
            anchor_time = progress[1]
        if anchor_time > current_time:  # pragma: no cover - guarded by history ordering
            raise SchedulerHistoryError("progress anchor cannot follow current_time")
        anchors[job_id] = ProgressAnchor(job_id, job.progress, anchor_time)
    return MappingProxyType(anchors)
