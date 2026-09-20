# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event as ThreadEvent

import pytest

from grass.core import (
    BranchId,
    CauseRef,
    CorrelationId,
    HistoryPosition,
    InMemoryEventStore,
    LogicalTime,
    Provenance,
    ProvenanceSourceRef,
    SimulationRunConfig,
    StaleHistoryError,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    WorldDefinition,
    load_world_definition,
)
from grass.persistence import (
    PersistenceError,
    RunId,
    SimulationRunRecord,
    SqliteEventStore,
    SqlitePersistence,
    WorldMaterialKind,
)
from tests.support import event_to_commit, transition_to_commit


def _world() -> WorldDefinition:
    return load_world_definition(
        {
            "world_definition_id": "world",
            "version": "1.0",
            "schema_version": 1,
            "vocabulary": {
                "entity_types": [],
                "relation_types": [],
                "resource_types": [],
                "state_variable_types": [],
            },
            "initial_conditions": {
                "logical_time": 0,
                "entities": [],
                "relations": [],
                "resources": [],
                "state_variables": [],
            },
            "metadata": {},
        }
    )


def _store(tmp_path: Path, run: str = "run") -> tuple[SqlitePersistence, SqliteEventStore]:
    path = tmp_path / "grass.db"
    persistence = SqlitePersistence(path)
    world = _world()
    record = SimulationRunRecord(
        RunId(run),
        BranchId("test:root"),
        world.ref,
        WorldMaterialKind.DEFINITION_ONLY,
        datetime(2026, 9, 14, tzinfo=UTC),
    )
    persistence.register_run(record, world, SimulationRunConfig(world.ref))
    return persistence, persistence.event_store(record.run_id)


def test_complete_event_envelope_matches_in_memory_and_survives_reopen(
    tmp_path: Path,
) -> None:
    persistence, store = _store(tmp_path)
    memory = InMemoryEventStore()
    branch_id = BranchId("test:root")
    memory.create_root_branch(branch_id)
    provenance = Provenance(
        "ENGINE",
        ProvenanceSourceRef("operation", "persist"),
        {"nested": {"huge": 10**50, "values": [True, None, -0.0]}},
    )
    candidate = transition_to_commit(
        "root",
        "first",
        10**30,
        [
            event_to_commit(
                "one",
                event_type="TestFactRecorded",
                event_version=10**20,
                payload={"value": [1, {"text": "stored"}]},
                provenance=provenance,
                causation_refs=(CauseRef("event", "earlier"),),
                correlation_id=CorrelationId("correlation"),
            ),
            event_to_commit("two", payload={"second": True}),
        ],
    )

    expected = memory.commit_transition(candidate)
    actual = store.commit_transition(candidate)

    assert actual == expected
    reopened = SqlitePersistence(persistence.path).event_store(RunId("run"))
    assert reopened.read_transitions(branch_id) == (expected,)
    snapshot = reopened.read_transitions(branch_id)
    reopened.commit_transition(
        transition_to_commit("root", "second", 10**30, [event_to_commit("three")])
    )
    assert snapshot == (expected,)


def test_atomic_failure_consumes_no_transition_event_or_sequence(tmp_path: Path) -> None:
    persistence, store = _store(tmp_path)
    candidate = transition_to_commit(
        "root",
        "atomic",
        10,
        [event_to_commit("one"), event_to_commit("two")],
    )
    with sqlite3.connect(persistence.path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_second_event BEFORE INSERT ON events "
            "WHEN NEW.event_offset = 1 BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )

    with pytest.raises(PersistenceError, match="atomically"):
        store.commit_transition(candidate)

    assert store.read_transitions(BranchId("test:root")) == ()
    with sqlite3.connect(persistence.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transitions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        connection.execute("DROP TRIGGER fail_second_event")
    committed = store.commit_transition(candidate)
    assert [event.sequence for event in committed.events] == [1, 2]


def test_reader_observes_no_partial_transition_during_event_inserts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    persistence, store = _store(tmp_path)
    candidate = transition_to_commit(
        "root",
        "atomic",
        10,
        [event_to_commit("one"), event_to_commit("two")],
    )
    first_event_inserted = ThreadEvent()
    permit_second_event = ThreadEvent()
    original_connect = store._connect

    def pause_commit() -> None:
        first_event_inserted.set()
        assert permit_second_event.wait(timeout=5)

    def instrumented_connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.create_function("pause_commit", 0, pause_commit)
        return connection

    monkeypatch.setattr(store, "_connect", instrumented_connect)
    with sqlite3.connect(persistence.path) as connection:
        connection.execute(
            "CREATE TRIGGER pause_second_event BEFORE INSERT ON events "
            "WHEN NEW.event_offset = 1 BEGIN SELECT pause_commit(); END"
        )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(store.commit_transition, candidate)
        assert first_event_inserted.wait(timeout=5)
        assert store.read_transitions(BranchId("test:root")) == ()
        permit_second_event.set()
        committed = future.result(timeout=5)

    assert store.read_transitions(BranchId("test:root")) == (committed,)


def test_guarded_writers_on_independent_connections_have_one_winner(tmp_path: Path) -> None:
    persistence, first_store = _store(tmp_path)
    second_store = SqlitePersistence(persistence.path).event_store(RunId("run"))
    branch_id = BranchId("test:root")
    expected = HistoryPosition(branch_id)
    candidates = {
        label: transition_to_commit("root", label, 10, [event_to_commit(f"{label}-event")])
        for label in ("one", "two")
    }

    def commit(label: str) -> tuple[str, bool]:
        selected = first_store if label == "one" else second_store
        try:
            selected.commit_transition(candidates[label], expected_head=expected)
        except StaleHistoryError:
            return label, False
        return label, True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(commit, candidates))

    assert sum(won for _, won in results) == 1
    losing = next(label for label, won in results if not won)
    committed = first_store.commit_transition(
        candidates[losing], expected_head=first_store.head_position(branch_id)
    )
    assert committed.events[0].sequence == 2


def test_branch_prefixes_remain_isolated_after_restart(tmp_path: Path) -> None:
    persistence, store = _store(tmp_path)
    root_id = BranchId("test:root")
    first = store.commit_transition(
        transition_to_commit("root", "first", 10, [event_to_commit("root-one")])
    )
    child_id = BranchId("test:child")
    store.fork_branch(child_id, HistoryPosition(root_id, first.transition_ref))
    second = store.commit_transition(
        transition_to_commit("root", "second", 20, [event_to_commit("root-two")])
    )
    child = store.commit_transition(
        TransitionToCommit(
            TransitionRef(child_id, TransitionId("child-transition")),
            LogicalTime(10),
            (event_to_commit("child-event"),),
        ),
        expected_head=HistoryPosition(child_id, first.transition_ref),
    )
    nested_id = BranchId("test:nested")
    store.fork_branch(nested_id, HistoryPosition(child_id, first.transition_ref))

    reopened = SqlitePersistence(persistence.path).event_store(RunId("run"))

    assert reopened.read_visible_transitions(reopened.head_position(root_id)) == (first, second)
    assert reopened.read_visible_transitions(reopened.head_position(child_id)) == (first, child)
    assert reopened.read_visible_transitions(reopened.head_position(nested_id)) == (first,)
    assert child.events[0].sequence == 1


def test_branch_catalog_is_lexicographic_and_survives_reopen(tmp_path: Path) -> None:
    persistence, store = _store(tmp_path)
    store.create_root_branch(BranchId("zeta"))
    store.create_root_branch(BranchId("alpha"))

    reopened = SqlitePersistence(persistence.path).event_store(RunId("run"))

    assert [branch.branch_id.value for branch in reopened.list_branches()] == [
        "alpha",
        "test:root",
        "zeta",
    ]


def test_run_scopes_branches_but_event_ids_remain_database_global(tmp_path: Path) -> None:
    persistence, first = _store(tmp_path, "one")
    world = _world()
    second_record = SimulationRunRecord(
        RunId("two"),
        BranchId("test:root"),
        world.ref,
        WorldMaterialKind.DEFINITION_ONLY,
        datetime(2026, 9, 14, tzinfo=UTC),
    )
    persistence.register_run(second_record, world, SimulationRunConfig(world.ref))
    second = persistence.event_store(second_record.run_id)
    first.commit_transition(
        transition_to_commit("root", "same", 0, [event_to_commit("global-event")])
    )

    with pytest.raises(ValueError, match="event_id has already been committed"):
        second.commit_transition(
            transition_to_commit("root", "same", 0, [event_to_commit("global-event")])
        )

    accepted = second.commit_transition(
        transition_to_commit("root", "same", 0, [event_to_commit("other-event")])
    )
    assert accepted.events[0].sequence == 1
