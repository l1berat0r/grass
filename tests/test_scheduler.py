# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import FrozenInstanceError
from itertools import permutations
from typing import cast

import pytest

from grass.core import (
    BinaryProgress,
    BranchId,
    JobId,
    LogicalDuration,
    LogicalTime,
    ProgressAnchor,
    ScheduledResolution,
    ScheduledResolutionIndex,
    ScheduleProjector,
    SchedulerError,
    SimulationState,
    group_conflict_components,
)
from grass.core._structured_data import StructuredValue


def candidate(
    source: str,
    time: int,
    *,
    kind: str = "JOB_CHECKPOINT",
    metadata: Mapping[str, StructuredValue] | None = None,
) -> ScheduledResolution[JobId]:
    return ScheduledResolution(
        LogicalTime(time),
        kind,
        JobId(source),
        {} if metadata is None else metadata,
    )


def component_sources(
    components: Sequence[Sequence[ScheduledResolution[JobId]]],
) -> set[frozenset[JobId]]:
    return {
        frozenset(resolution.source_ref for resolution in component) for component in components
    }


def test_scheduled_resolution_is_immutable_and_freezes_metadata() -> None:
    values: list[StructuredValue] = [1]
    metadata: dict[str, StructuredValue] = {"values": values}
    resolution = candidate("job", 10, metadata=metadata)

    values.append(2)

    assert resolution.metadata == {"values": (1,)}
    with pytest.raises(TypeError):
        cast(dict[str, StructuredValue], resolution.metadata)["new"] = True
    with pytest.raises(FrozenInstanceError):
        resolution.kind = "OTHER"  # type: ignore[misc]


def test_scheduled_resolution_validates_operational_fields() -> None:
    with pytest.raises(ValueError, match="kind must not be empty"):
        ScheduledResolution(LogicalTime(1), "", JobId("job"))
    with pytest.raises(TypeError, match="kind must be a string"):
        ScheduledResolution(LogicalTime(1), cast(str, 1), JobId("job"))
    with pytest.raises(TypeError, match="source_ref must be hashable"):
        ScheduledResolution(LogicalTime(1), "KIND", cast(Hashable, []))


def test_progress_anchor_is_an_immutable_committed_baseline() -> None:
    anchor = ProgressAnchor(JobId("job"), BinaryProgress(False), LogicalTime(4))

    assert anchor.baseline_progress == BinaryProgress(False)
    assert anchor.anchor_time == LogicalTime(4)
    with pytest.raises(FrozenInstanceError):
        anchor.anchor_time = LogicalTime(5)  # type: ignore[misc]


class ScriptedProjector:
    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> Sequence[ScheduledResolution[JobId]]:
        assert state.position.branch_id == BranchId("branch")
        assert progress_anchors == {}
        return [
            ScheduledResolution(
                current_time + LogicalDuration(5),
                "JOB_EXPECTED_COMPLETION",
                JobId("job"),
            )
        ]


def run_projector(projector: ScheduleProjector[JobId]) -> Sequence[ScheduledResolution[JobId]]:
    return projector.project(
        SimulationState.empty(BranchId("branch")),
        LogicalTime(10),
        {},
    )


def test_schedule_projector_is_replaceable_and_receives_explicit_time() -> None:
    assert run_projector(ScriptedProjector()) == [
        candidate("job", 15, kind="JOB_EXPECTED_COMPLETION")
    ]


def test_index_rebuilds_and_keeps_multiple_candidates_per_source() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    entries = [candidate("one", 10), candidate("one", 20), candidate("two", 10)]

    index.rebuild(LogicalTime(5), entries)

    assert index.snapshot(LogicalTime(5)) == tuple(entries)
    assert index.earliest_candidates(LogicalTime(5)) == (entries[0], entries[2])


def test_source_replacement_is_complete_and_empty_replacement_removes_source() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    original = [candidate("one", 10), candidate("one", 20), candidate("two", 12)]
    index.rebuild(LogicalTime(5), original)

    replacement = candidate("one", 15, kind="JOB_EXPECTED_COMPLETION")
    index.replace_source(LogicalTime(5), JobId("one"), [replacement])

    assert index.snapshot(LogicalTime(5)) == (replacement, original[2])
    index.replace_source(LogicalTime(5), JobId("one"), [])
    assert index.snapshot(LogicalTime(5)) == (original[2],)


def test_rebuild_and_replacement_reject_past_candidates_atomically() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    current = candidate("job", 10)
    index.rebuild(LogicalTime(5), [current])

    with pytest.raises(SchedulerError, match="cannot precede"):
        index.rebuild(LogicalTime(5), [candidate("other", 4)])
    assert index.snapshot(LogicalTime(5)) == (current,)

    with pytest.raises(SchedulerError, match="cannot precede"):
        index.replace_source(LogicalTime(5), JobId("job"), [candidate("job", 4)])
    assert index.snapshot(LogicalTime(5)) == (current,)


def test_index_rejects_stale_reads_duplicate_candidates_and_source_mismatch() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    entry = candidate("job", 5)
    with pytest.raises(SchedulerError, match="duplicates"):
        index.rebuild(LogicalTime(0), [entry, entry])

    index.rebuild(LogicalTime(0), [entry])
    with pytest.raises(SchedulerError, match="cannot precede"):
        index.snapshot(LogicalTime(6))
    with pytest.raises(SchedulerError, match="must match source_ref"):
        index.replace_source(LogicalTime(0), JobId("other"), [entry])


def test_source_replacement_rejects_a_stale_retained_source_atomically() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    entries = [candidate("stale", 5), candidate("replaced", 7)]
    index.rebuild(LogicalTime(0), entries)

    with pytest.raises(SchedulerError, match="cannot precede"):
        index.replace_source(
            LogicalTime(6),
            JobId("replaced"),
            [candidate("replaced", 8)],
        )

    assert index.snapshot(LogicalTime(0)) == tuple(entries)


def test_candidate_at_current_time_produces_zero_duration_non_destructive_step() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    entry = candidate("job", 5)
    index.rebuild(LogicalTime(5), [entry])

    first = index.next_step(LogicalTime(5), lambda _left, _right: False)
    second = index.next_step(LogicalTime(5), lambda _left, _right: False)

    assert first == second
    assert first is not None
    assert first.current_time == LogicalTime(5)
    assert first.target_time == LogicalTime(5)
    assert first.elapsed == LogicalDuration(0)
    assert first.due_candidates == (entry,)
    assert first.conflict_components == ((entry,),)


def test_scheduler_jumps_directly_to_next_material_time() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    completion = candidate("job", 28_800_000_000_000, kind="JOB_EXPECTED_COMPLETION")
    later = candidate("later", 30_000_000_000_000)
    index.rebuild(LogicalTime(0), [later, completion])

    step = index.next_step(LogicalTime(0), lambda _left, _right: False)

    assert step is not None
    assert step.target_time == LogicalTime(28_800_000_000_000)
    assert step.elapsed == LogicalDuration(28_800_000_000_000)
    assert step.due_candidates == (completion,)
    assert index.snapshot(LogicalTime(0)) == (later, completion)


def test_concurrent_due_candidates_share_one_elapsed_interval() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    entries = [candidate("one", 12), candidate("two", 12)]
    index.rebuild(LogicalTime(5), entries)

    step = index.next_step(LogicalTime(5), lambda _left, _right: False)

    assert step is not None
    assert step.elapsed == LogicalDuration(7)
    assert step.due_candidates == tuple(entries)
    assert step.conflict_components == ((entries[0],), (entries[1],))


def test_conflicts_form_undirected_transitive_components() -> None:
    entries = tuple(candidate(source, 10) for source in ("a", "b", "c", "d"))
    edges = {
        frozenset({JobId("a"), JobId("b")}),
        frozenset({JobId("b"), JobId("c")}),
    }

    def conflicts(left: ScheduledResolution[JobId], right: ScheduledResolution[JobId]) -> bool:
        return frozenset({left.source_ref, right.source_ref}) in edges

    expected = {
        frozenset({JobId("a"), JobId("b"), JobId("c")}),
        frozenset({JobId("d")}),
    }
    for ordering in permutations(entries):
        assert component_sources(group_conflict_components(ordering, conflicts)) == expected


def test_conflict_predicate_must_be_symmetric_and_boolean() -> None:
    entries = [candidate("a", 10), candidate("b", 10)]

    with pytest.raises(SchedulerError, match="symmetric"):
        group_conflict_components(
            entries,
            lambda left, _right: left.source_ref == JobId("a"),
        )
    with pytest.raises(TypeError, match="return a boolean"):
        group_conflict_components(entries, lambda _left, _right: cast(bool, 1))
    with pytest.raises(SchedulerError, match="share one logical_time"):
        group_conflict_components(
            [candidate("a", 10), candidate("b", 11)],
            lambda _left, _right: False,
        )


def test_empty_index_has_no_scheduler_step() -> None:
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()

    assert index.next_step(LogicalTime(10), lambda _left, _right: False) is None
