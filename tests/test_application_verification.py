# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from grass.application import (
    LocalSimulationApplication,
    VerificationIntegrityError,
)
from grass.core import (
    BranchId,
    EventId,
    EventToCommit,
    LogicalTime,
    Provenance,
    SimulationRunConfig,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
)
from grass.core.initialization_events import SIMULATION_INITIALIZED
from grass.persistence import (
    RunId,
    SimulationRunRecord,
    SqlitePersistence,
    WorldMaterialKind,
)
from grass.worlds import (
    FilesystemWorldSnapshotStore,
    WorldSnapshotIntegrityError,
    WorldSnapshotNotFoundError,
    load_world_package,
)
from tests.test_world_packages import write_world_package


def _created(tmp_path: Path):  # type: ignore[no-untyped-def]
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    application = LocalSimulationApplication(persistence, snapshots)
    opened = application.create_run(package, SimulationRunConfig(package.world_definition.ref))
    return application, opened, persistence, snapshots


def test_verify_valid_run_counts_unique_origin_history_and_does_not_execute(
    tmp_path: Path,
) -> None:
    application, opened, persistence, snapshots = _created(tmp_path)
    root_position = application.queries.get_branch(opened.run_id).position.history_position
    opened.create_branch(BranchId("child"), root_position)

    def fail_factory():  # type: ignore[no-untyped-def]
        raise AssertionError("verification must not allocate runtime identities")

    verifier_only = LocalSimulationApplication(
        persistence,
        snapshots,
        identity_source_factory=fail_factory,
    )
    report = verifier_only.verify_run(opened.run_id)

    assert report.world_material_kind is WorldMaterialKind.PACKAGE_SNAPSHOT
    assert report.branch_count == 2
    assert report.transition_count == 1
    assert report.event_count == 2
    assert report.snapshot_file_count == 3


def test_verify_rejects_corrupt_and_missing_package_snapshot(tmp_path: Path) -> None:
    application, opened, _, snapshots = _created(tmp_path)
    snapshot = snapshots.root / opened.run_id.value
    (snapshot / "mechanics" / "increment.gel").unlink()
    with pytest.raises(WorldSnapshotIntegrityError):
        application.verify_run(opened.run_id)

    snapshots.remove(opened.run_id)
    with pytest.raises(WorldSnapshotNotFoundError):
        application.verify_run(opened.run_id)


def test_verify_rejects_later_initialization_event(tmp_path: Path) -> None:
    application, opened, persistence, _ = _created(tmp_path)
    store = persistence.event_store(opened.run_id)
    store.commit_transition(
        TransitionToCommit(
            TransitionRef(BranchId("root"), TransitionId("second-init")),
            LogicalTime(0),
            (
                EventToCommit(
                    EventId("second-init"),
                    SIMULATION_INITIALIZED,
                    1,
                    {},
                    Provenance("ENGINE"),
                ),
            ),
        )
    )

    with pytest.raises(VerificationIntegrityError) as raised:
        application.verify_run(opened.run_id)
    assert raised.value.__cause__ is not None


def test_verify_definition_only_run_does_not_inspect_snapshot_paths(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    config = SimulationRunConfig(package.world_definition.ref)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    record = SimulationRunRecord(
        RunId("definition-only"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.DEFINITION_ONLY,
        datetime.now(UTC),
    )
    persistence.register_run(record, package.world_definition, config)
    application = LocalSimulationApplication(persistence, snapshots)
    application.open_run(record.run_id)
    snapshots.root.mkdir(exist_ok=True)
    (snapshots.root / record.run_id.value).write_text("not a snapshot", encoding="utf-8")

    report = application.verify_run(record.run_id)

    assert report.world_material_kind is WorldMaterialKind.DEFINITION_ONLY
    assert report.snapshot_file_count is None
