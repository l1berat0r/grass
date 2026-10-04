# SPDX-License-Identifier: GPL-3.0-only

"""Initialization of the CLI's local application data root."""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path

from grass.persistence import SqlitePersistence
from grass.worlds import (
    FilesystemWorldTemplateStore,
    WorldPackage,
    WorldTemplateInstallation,
    load_world_package,
)

_LOCAL_WORLD_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class LocalWorkspaceInitializationError(RuntimeError):
    """The local CLI data root cannot be initialized safely."""


def validate_local_world_name(value: str, /) -> str:
    """Return one safe local world name or reject it before path construction."""

    if type(value) is not str:
        raise TypeError("local world name must be a string")
    if _LOCAL_WORLD_NAME.fullmatch(value) is None:
        raise ValueError("local world name must match [a-z0-9]+(?:-[a-z0-9]+)*")
    return value


@dataclass(frozen=True, slots=True)
class LocalWorkspacePaths:
    """All filesystem paths owned implicitly by one local CLI workspace."""

    root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise TypeError("root must be a Path")

    @property
    def database(self) -> Path:
        return self.root / "grass.db"

    @property
    def worlds(self) -> Path:
        return self.root / "worlds"

    def world(self, name: str, /) -> Path:
        return self.worlds / validate_local_world_name(name)

    @property
    def world_snapshots(self) -> Path:
        return self.root / "world_snapshots"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def templates(self) -> Path:
        return self.root / "templates"

    @property
    def world_templates(self) -> Path:
        return self.templates / "worlds"


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


def ensure_local_storage_paths(paths: LocalWorkspacePaths, /) -> None:
    """Create the data root and reject unsafe existing storage paths."""

    if type(paths) is not LocalWorkspacePaths:
        raise TypeError("paths must be LocalWorkspacePaths")
    _ensure_directory(paths.root, "data root")
    _validate_database_path(paths.database)


def ensure_local_world_root(paths: LocalWorkspacePaths, /) -> None:
    """Create the root for implicit editable worlds without initializing other storage."""

    if type(paths) is not LocalWorkspacePaths:
        raise TypeError("paths must be LocalWorkspacePaths")
    _ensure_directory(paths.root, "data root")
    _ensure_directory(paths.worlds, "world root")


def installed_world_template_store(paths: LocalWorkspacePaths, /) -> FilesystemWorldTemplateStore:
    """Return the local store after validating each existing managed directory."""

    ensure_local_storage_paths(paths)
    for path, description in (
        (paths.templates, "template root"),
        (paths.world_templates, "world-template root"),
    ):
        try:
            path.lstat()
        except FileNotFoundError:
            break
        except OSError as error:
            raise LocalWorkspaceInitializationError(f"could not inspect {description}") from error
        _ensure_directory(path, description)
    return FilesystemWorldTemplateStore(paths.world_templates)


def load_cli_world_source(
    paths: LocalWorkspacePaths,
    /,
    *,
    workspace_name: str | None = None,
    external_path: Path | None = None,
    template_name: str | None = None,
) -> WorldPackage:
    """Load exactly one CLI-selected managed world, external path, or installed template."""

    if type(paths) is not LocalWorkspacePaths:
        raise TypeError("paths must be LocalWorkspacePaths")
    if sum(item is not None for item in (workspace_name, external_path, template_name)) != 1:
        raise ValueError("exactly one world source must be selected")
    if workspace_name is not None:
        return load_world_package(paths.world(workspace_name))
    if external_path is not None:
        if not isinstance(external_path, Path):
            raise TypeError("external_path must be a Path")
        return load_world_package(external_path)
    assert template_name is not None
    return installed_world_template_store(paths).load_installed(template_name)


def initialize_local_workspace(paths: LocalWorkspacePaths, /) -> LocalWorkspaceInitialization:
    """Initialize local storage and install missing bundled world-template copies."""

    ensure_local_storage_paths(paths)
    SqlitePersistence(paths.database)

    _ensure_directory(paths.worlds, "world root")
    _ensure_directory(paths.world_snapshots, "world snapshot root")
    _ensure_directory(paths.runs, "run workspace root")
    _ensure_directory(paths.templates, "template root")
    _ensure_directory(paths.world_templates, "world-template root")
    installations = FilesystemWorldTemplateStore(paths.world_templates).install_registered()
    return LocalWorkspaceInitialization(
        paths.root,
        paths.database,
        paths.world_snapshots,
        paths.runs,
        paths.templates,
        paths.world_templates,
        installations,
    )
