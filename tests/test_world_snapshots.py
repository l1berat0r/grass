# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from grass.core import BranchId, SimulationRunConfig
from grass.persistence import RunId, SimulationRunRecord, WorldMaterialKind
from grass.persistence.contracts import RunRepository
from grass.worlds import snapshots as snapshots_module
from grass.worlds.package import WorldPackage, load_world_package
from grass.worlds.snapshots import (
    FilesystemWorldSnapshotStore,
    WorldSnapshotConflictError,
    WorldSnapshotError,
    WorldSnapshotIntegrityError,
    WorldSnapshotPathError,
    register_world_package_run,
)
from tests.test_world_packages import write_world_package


class RecordingRunRepository:
    def __init__(self, failure: Exception | None = None) -> None:
        self.calls: list[tuple[SimulationRunRecord, object, SimulationRunConfig]] = []
        self.failure = failure

    def register_run(
        self,
        record: SimulationRunRecord,
        world_definition: object,
        run_config: SimulationRunConfig,
        /,
    ) -> None:
        self.calls.append((record, world_definition, run_config))
        if self.failure is not None:
            raise self.failure

    def read_run(self, run_id: RunId, /) -> SimulationRunRecord:
        raise NotImplementedError(run_id)

    def list_runs(self) -> tuple[SimulationRunRecord, ...]:
        return tuple(call[0] for call in self.calls)


def record_for_package(run_id: RunId, world_ref: object) -> SimulationRunRecord:
    from grass.core.world_definitions import WorldDefinitionRef

    assert type(world_ref) is WorldDefinitionRef
    return SimulationRunRecord(
        run_id,
        BranchId("root"),
        world_ref,
        WorldMaterialKind.PACKAGE_SNAPSHOT,
        datetime(2026, 9, 19, tzinfo=UTC),
    )


def test_publish_reopens_without_author_directory_and_refuses_existing(
    tmp_path: Path,
) -> None:
    author_root, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author_root)
    run_id = RunId("run-one")
    store = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")

    published = store.publish(run_id, package)
    shutil.rmtree(author_root)
    loaded = store.load(run_id, package.world_definition)

    assert published.material_files == package.material_files
    assert loaded.world_definition == package.world_definition
    assert loaded.material_files == package.material_files
    with pytest.raises(WorldSnapshotConflictError):
        store.publish(run_id, package)


@pytest.mark.parametrize("extra_kind", ["file", "directory", "symlink"])
def test_load_rejects_extra_and_symlinked_snapshot_material(
    tmp_path: Path, extra_kind: str
) -> None:
    author_root, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author_root)
    run_id = RunId("run-one")
    snapshots = tmp_path / "world_snapshots"
    store = FilesystemWorldSnapshotStore(snapshots)
    store.publish(run_id, package)
    snapshot_root = snapshots / run_id.value
    if extra_kind == "file":
        (snapshot_root / "extra.txt").write_text("extra", encoding="utf-8")
    elif extra_kind == "directory":
        (snapshot_root / "extra").mkdir()
    else:
        (snapshot_root / "extra").symlink_to(snapshot_root / "world.json")

    with pytest.raises(WorldSnapshotIntegrityError):
        store.load(run_id, package.world_definition)


def test_load_rejects_missing_material_and_wrong_expected_definition(tmp_path: Path) -> None:
    first_root, _, _, _ = write_world_package(tmp_path)
    first = load_world_package(first_root)
    second_parent = tmp_path / "other"
    second_parent.mkdir()
    second_root, _, _, _ = write_world_package(second_parent, name="other-world")
    second = load_world_package(second_root)
    run_id = RunId("run-one")
    snapshots = tmp_path / "world_snapshots"
    store = FilesystemWorldSnapshotStore(snapshots)
    store.publish(run_id, first)

    with pytest.raises(WorldSnapshotIntegrityError, match="expected definition"):
        store.load(run_id, second.world_definition)

    (snapshots / run_id.value / "mechanics" / "increment.gel").unlink()
    with pytest.raises(WorldSnapshotIntegrityError):
        store.load(run_id, first.world_definition)


def test_run_id_path_is_restricted_to_safe_slug(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(root)
    store = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")

    with pytest.raises(WorldSnapshotPathError):
        store.publish(RunId("../unsafe"), package)


def test_registration_publishes_first_and_cleans_snapshot_on_failure(
    tmp_path: Path,
) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(root)
    run_id = RunId("run-one")
    record = record_for_package(run_id, package.world_definition.ref)
    config = SimulationRunConfig(package.world_definition.ref)
    store = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    failure = RuntimeError("registration failed")
    repository: RunRepository = RecordingRunRepository(failure)

    with pytest.raises(RuntimeError, match="registration failed") as raised:
        register_world_package_run(repository, store, record, package, config)

    assert raised.value is failure
    assert not (store.root / run_id.value).exists()


def test_registration_retains_snapshot_after_success(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(root)
    run_id = RunId("run-one")
    record = record_for_package(run_id, package.world_definition.ref)
    config = SimulationRunConfig(package.world_definition.ref)
    store = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    concrete_repository = RecordingRunRepository()
    repository: RunRepository = concrete_repository

    register_world_package_run(repository, store, record, package, config)

    assert len(concrete_repository.calls) == 1
    assert store.load(run_id, package.world_definition).material_files == package.material_files


def test_failed_snapshot_validation_publishes_no_partial_directory(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(root)
    invalid = WorldPackage(
        package.manifest,
        package.world_definition,
        {**package.material_files, "undeclared.txt": b"not material"},
    )
    run_id = RunId("run-one")
    store = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")

    with pytest.raises(WorldSnapshotIntegrityError):
        store.publish(run_id, invalid)

    assert not (store.root / run_id.value).exists()


def test_failed_parent_fsync_removes_renamed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(root)
    run_id = RunId("run-one")
    store = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    original_fsync_directory = snapshots_module._fsync_directory

    def fail_root_fsync(path: Path) -> None:
        if path == store.root:
            raise OSError("fsync failed")
        original_fsync_directory(path)

    monkeypatch.setattr(snapshots_module, "_fsync_directory", fail_root_fsync)

    with pytest.raises(WorldSnapshotError, match="could not publish"):
        store.publish(run_id, package)

    assert not (store.root / run_id.value).exists()
