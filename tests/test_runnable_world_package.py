# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from grass.core import (
    BranchId,
    EventId,
    LogicalTime,
    SimulationRunConfig,
    StateVariableKey,
    TransitionId,
    TransitionRef,
    WorldScope,
    build_genesis_transition,
    replay_branch,
)
from grass.persistence import RunId, SimulationRunRecord, SqlitePersistence
from grass.runtime import RuntimeStopReason, UuidRuntimeIdentitySource
from grass.worlds import (
    FilesystemWorldSnapshotStore,
    compose_occurrence_engine,
    load_world_package,
    register_world_package_run,
)
from tests.test_world_packages import write_world_package


def test_packaged_run_reopens_without_author_files_and_preserves_branching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    author_root, _, _, _ = write_world_package(worlds)
    package = load_world_package(author_root)
    run_id = RunId("run-one")
    root_id = BranchId("root")
    record = SimulationRunRecord(
        run_id,
        root_id,
        package.world_definition.ref,
        datetime(2026, 9, 19, tzinfo=UTC),
    )
    config = SimulationRunConfig(package.world_definition.ref)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    register_world_package_run(persistence, snapshots, record, package, config)
    store = persistence.event_store(run_id)
    store.commit_transition(
        build_genesis_transition(
            package.world_definition,
            config,
            TransitionRef(root_id, TransitionId("genesis")),
            (EventId("genesis:initialized"), EventId("genesis:counter")),
        )
    )
    before_occurrence = store.head_position(root_id)
    store.fork_branch(BranchId("before"), before_occurrence)

    shutil.rmtree(author_root)
    reopened = SqlitePersistence(tmp_path / "grass.db")
    restored_definition = reopened.read_world_definition(run_id)
    snapshot = snapshots.load(run_id, restored_definition)
    restored_config = reopened.read_run_config(run_id)
    reopened_store = reopened.event_store(run_id)
    engine = compose_occurrence_engine(
        event_store=reopened_store,
        world_definition=snapshot.world_definition,
        run_config=restored_config,
        identity_source=UuidRuntimeIdentitySource(),
    )

    root_result = asyncio.run(engine.step(root_id))
    assert root_result.logical_time == LogicalTime(10)
    root_state = replay_branch(reopened_store, reopened_store.head_position(root_id))
    assert root_state.world.state_variables[StateVariableKey(WorldScope(), "counter")] == 2

    before_result = asyncio.run(engine.step(BranchId("before")))
    assert before_result.logical_time == LogicalTime(10)
    before_state = replay_branch(reopened_store, reopened_store.head_position(BranchId("before")))
    assert before_state.world.state_variables[StateVariableKey(WorldScope(), "counter")] == 2

    reopened_store.fork_branch(BranchId("after"), reopened_store.head_position(root_id))

    def fail_if_executed(*_: object, **__: object) -> object:
        raise AssertionError("ordinary replay and inherited occurrence must not execute GEL")

    monkeypatch.setattr("grass.worlds.mechanics.execute_gel", fail_if_executed)
    assert replay_branch(reopened_store, reopened_store.head_position(root_id)) == root_state
    after_result = asyncio.run(engine.step(BranchId("after")))
    assert after_result.stop_reason is RuntimeStopReason.QUIESCENT
