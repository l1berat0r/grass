# SPDX-License-Identifier: GPL-3.0-only

"""Initialization of the CLI's local application data root."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from grass.persistence import SqlitePersistence
from grass.worlds import FilesystemWorldTemplateStore, WorldTemplateInstallation


class LocalWorkspaceInitializationError(RuntimeError):
    """The local CLI data root cannot be initialized safely."""


@dataclass(frozen=True, slots=True)
class LocalWorkspaceInitialization:
    data_root: Path
    database: Path
    world_snapshot_root: Path
    run_workspace_root: Path
    template_root: Path
    world_template_root: Path
    world_templates: tuple[WorldTemplateInstallation, ...]


def _ensure_directory(path: Path, description: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass
    except OSError as error:
        raise LocalWorkspaceInitializationError(f"could not create {description}") from error
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise LocalWorkspaceInitializationError(f"could not inspect {description}") from error
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise LocalWorkspaceInitializationError(f"{description} must be a non-symlink directory")


def _validate_database_path(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise LocalWorkspaceInitializationError("could not inspect SQLite database path") from error
    if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
        raise LocalWorkspaceInitializationError(
            "SQLite database path must be a non-symlink regular file"
        )


def ensure_local_storage_paths(data_root: Path, /) -> None:
    """Create the data root and reject unsafe existing storage paths."""

    if not isinstance(data_root, Path):
        raise TypeError("data_root must be a Path")
    _ensure_directory(data_root, "data root")
    _validate_database_path(data_root / "grass.db")


def installed_world_template_store(data_root: Path, /) -> FilesystemWorldTemplateStore:
    """Return the local store after validating each existing managed directory."""

    ensure_local_storage_paths(data_root)
    template_root = data_root / "templates"
    world_template_root = template_root / "worlds"
    for path, description in (
        (template_root, "template root"),
        (world_template_root, "world-template root"),
    ):
        try:
            path.lstat()
        except FileNotFoundError:
            break
        except OSError as error:
            raise LocalWorkspaceInitializationError(f"could not inspect {description}") from error
        _ensure_directory(path, description)
    return FilesystemWorldTemplateStore(world_template_root)


def initialize_local_workspace(data_root: Path, /) -> LocalWorkspaceInitialization:
    """Initialize local storage and install missing bundled world-template copies."""

    ensure_local_storage_paths(data_root)
    database = data_root / "grass.db"
    SqlitePersistence(database)

    world_snapshot_root = data_root / "world_snapshots"
    run_workspace_root = data_root / "runs"
    template_root = data_root / "templates"
    world_template_root = template_root / "worlds"
    _ensure_directory(world_snapshot_root, "world snapshot root")
    _ensure_directory(run_workspace_root, "run workspace root")
    _ensure_directory(template_root, "template root")
    _ensure_directory(world_template_root, "world-template root")
    installations = FilesystemWorldTemplateStore(world_template_root).install_registered()
    return LocalWorkspaceInitialization(
        data_root,
        database,
        world_snapshot_root,
        run_workspace_root,
        template_root,
        world_template_root,
        installations,
    )
