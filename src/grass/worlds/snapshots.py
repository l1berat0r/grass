# SPDX-License-Identifier: GPL-3.0-only

"""Immutable per-run filesystem snapshots for validated WorldPackages."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import ClassVar

from grass.core.world_definitions import SimulationRunConfig, WorldDefinition
from grass.persistence.contracts import (
    RunId,
    RunRepository,
    SimulationRunRecord,
)
from grass.worlds.package import (
    WorldPackage,
    WorldPackageError,
    WorldPackageManifest,
    _load_world_package_directory,
    _safe_slug,
)


class WorldSnapshotError(RuntimeError):
    """A per-run WorldPackage snapshot operation failed."""


class WorldSnapshotPathError(WorldSnapshotError):
    """A RunId cannot safely identify one snapshot directory."""


class WorldSnapshotConflictError(WorldSnapshotError, FileExistsError):
    """The final immutable snapshot directory already exists."""


class WorldSnapshotNotFoundError(WorldSnapshotError, FileNotFoundError):
    """The requested run snapshot does not exist."""


class WorldSnapshotIntegrityError(WorldSnapshotError):
    """Snapshot material is incomplete, unexpected, unsafe, or inconsistent."""


@dataclass(frozen=True, slots=True)
class WorldPackageSnapshot:
    """One validated immutable package snapshot associated with a run."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    run_id: RunId
    manifest: WorldPackageManifest
    world_definition: WorldDefinition
    material_files: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if type(self.run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        package = WorldPackage(self.manifest, self.world_definition, self.material_files)
        object.__setattr__(
            self,
            "material_files",
            MappingProxyType(dict(package.material_files)),
        )

    @property
    def package(self) -> WorldPackage:
        """Return the validated package value represented by this snapshot."""

        return WorldPackage(self.manifest, self.world_definition, self.material_files)


def _run_segment(run_id: RunId) -> str:
    if type(run_id) is not RunId:
        raise TypeError("run_id must be a RunId")
    try:
        return _safe_slug(run_id.value, "snapshot RunId")
    except WorldPackageError as error:
        raise WorldSnapshotPathError(str(error)) from error


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise WorldSnapshotError(f"could not inspect snapshot path: {path}") from error
    return True


def _validate_directory(path: Path, description: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise WorldSnapshotNotFoundError(f"{description} does not exist") from error
    except OSError as error:
        raise WorldSnapshotError(f"could not inspect {description}") from error
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise WorldSnapshotIntegrityError(f"{description} must be a non-symlink directory")


def _inventory_snapshot(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    files: set[str] = set()
    directories: set[str] = set()

    def visit(directory: Path, relative_directory: PurePosixPath | None) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise WorldSnapshotIntegrityError("could not enumerate snapshot material") from error
        for entry in entries:
            relative = (
                PurePosixPath(entry.name)
                if relative_directory is None
                else relative_directory / entry.name
            )
            relative_text = relative.as_posix()
            if "\\" in relative_text or any(part in ("", ".", "..") for part in relative.parts):
                raise WorldSnapshotIntegrityError("snapshot contains a non-canonical material path")
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as error:
                raise WorldSnapshotIntegrityError(
                    f"could not inspect snapshot material: {relative_text}"
                ) from error
            if stat.S_ISLNK(mode):
                raise WorldSnapshotIntegrityError(
                    f"snapshot material must not be symlinked: {relative_text}"
                )
            if stat.S_ISDIR(mode):
                directories.add(relative_text)
                visit(Path(entry.path), relative)
            elif stat.S_ISREG(mode):
                files.add(relative_text)
            else:
                raise WorldSnapshotIntegrityError(
                    f"snapshot material must be a regular file or directory: {relative_text}"
                )

    visit(root, None)
    return frozenset(files), frozenset(directories)


def _required_directories(files: Mapping[str, bytes]) -> frozenset[str]:
    directories: set[str] = set()
    for relative_path in files:
        parts = PurePosixPath(relative_path).parts
        for count in range(1, len(parts)):
            directories.add(PurePosixPath(*parts[:count]).as_posix())
    return frozenset(directories)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_snapshot_directory(
    run_id: RunId, directory: Path, expected_world_definition: WorldDefinition
) -> WorldPackageSnapshot:
    _validate_directory(directory, "WorldPackage snapshot")
    actual_files, actual_directories = _inventory_snapshot(directory)
    try:
        package = _load_world_package_directory(directory, require_directory_slug=False)
    except WorldPackageError as error:
        raise WorldSnapshotIntegrityError("WorldPackage snapshot is invalid") from error
    expected_files = frozenset(package.material_files)
    expected_directories = _required_directories(package.material_files)
    if actual_files != expected_files or actual_directories != expected_directories:
        raise WorldSnapshotIntegrityError(
            "WorldPackage snapshot contains missing or extra material"
        )
    if package.world_definition != expected_world_definition:
        raise WorldSnapshotIntegrityError(
            "WorldPackage snapshot WorldDefinition does not match the expected definition"
        )
    return WorldPackageSnapshot(
        run_id,
        package.manifest,
        package.world_definition,
        package.material_files,
    )


class FilesystemWorldSnapshotStore:
    """Publish and load one immutable material WorldPackage copy per safe RunId."""

    def __init__(self, root: os.PathLike[str] | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def _ensure_root(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise WorldSnapshotError("could not create world snapshot root") from error
        _validate_directory(self._root, "world snapshot root")

    def publish(self, run_id: RunId, package: WorldPackage, /) -> WorldPackageSnapshot:
        """Atomically publish exact captured package bytes under one new RunId."""

        segment = _run_segment(run_id)
        if type(package) is not WorldPackage:
            raise TypeError("package must be a WorldPackage")
        self._ensure_root()
        final = self._root / segment
        if _path_exists(final):
            raise WorldSnapshotConflictError(
                f"WorldPackage snapshot already exists for RunId: {segment}"
            )
        try:
            temporary = Path(tempfile.mkdtemp(prefix=f".{segment}-", dir=self._root))
        except OSError as error:
            raise WorldSnapshotError("could not create temporary snapshot") from error

        renamed = False
        published = False
        try:
            for relative_path, content in package.material_files.items():
                destination = temporary.joinpath(*PurePosixPath(relative_path).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            for relative_directory in sorted(
                _required_directories(package.material_files),
                key=lambda value: len(PurePosixPath(value).parts),
                reverse=True,
            ):
                _fsync_directory(temporary.joinpath(*PurePosixPath(relative_directory).parts))
            _fsync_directory(temporary)
            snapshot = _load_snapshot_directory(run_id, temporary, package.world_definition)
            if _path_exists(final):
                raise WorldSnapshotConflictError(
                    f"WorldPackage snapshot already exists for RunId: {segment}"
                )
            os.rename(temporary, final)
            renamed = True
            _fsync_directory(self._root)
            published = True
            return snapshot
        except WorldSnapshotError:
            raise
        except FileExistsError as error:
            raise WorldSnapshotConflictError(
                f"WorldPackage snapshot already exists for RunId: {segment}"
            ) from error
        except OSError as error:
            raise WorldSnapshotError("could not publish WorldPackage snapshot") from error
        finally:
            if not published:
                shutil.rmtree(temporary, ignore_errors=True)
                if renamed:
                    shutil.rmtree(final, ignore_errors=True)

    def load(
        self,
        run_id: RunId,
        expected_world_definition: WorldDefinition,
        /,
    ) -> WorldPackageSnapshot:
        """Load a complete snapshot and verify its exact semantic definition."""

        segment = _run_segment(run_id)
        if type(expected_world_definition) is not WorldDefinition:
            raise TypeError("expected_world_definition must be a WorldDefinition")
        return _load_snapshot_directory(
            run_id,
            self._root / segment,
            expected_world_definition,
        )

    def remove(self, run_id: RunId, /) -> None:
        """Remove one snapshot, doing nothing when it is already absent."""

        segment = _run_segment(run_id)
        path = self._root / segment
        if not _path_exists(path):
            return
        _validate_directory(path, "WorldPackage snapshot")
        try:
            shutil.rmtree(path)
        except OSError as error:
            raise WorldSnapshotError("could not remove WorldPackage snapshot") from error


def register_world_package_run(
    run_repository: RunRepository,
    snapshot_store: FilesystemWorldSnapshotStore,
    record: SimulationRunRecord,
    package: WorldPackage,
    run_config: SimulationRunConfig,
    /,
) -> WorldPackageSnapshot:
    """Publish package material before atomically registering its durable run."""

    if type(record) is not SimulationRunRecord:
        raise TypeError("record must be a SimulationRunRecord")
    if type(package) is not WorldPackage:
        raise TypeError("package must be a WorldPackage")
    if type(run_config) is not SimulationRunConfig:
        raise TypeError("run_config must be a SimulationRunConfig")
    if record.world_definition_ref != package.world_definition.ref:
        raise ValueError("run record must reference the package WorldDefinition")
    if run_config.world_definition_ref != package.world_definition.ref:
        raise ValueError("run config must reference the package WorldDefinition")

    snapshot = snapshot_store.publish(record.run_id, package)
    try:
        run_repository.register_run(
            record,
            package.world_definition,
            run_config,
        )
    except Exception:
        try:
            snapshot_store.remove(record.run_id)
        except Exception:
            pass
        raise
    return snapshot
