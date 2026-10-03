# SPDX-License-Identifier: GPL-3.0-only

"""Filesystem installation of bundled templates as ordinary WorldPackages."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from grass.core import SimulationRunConfig
from grass.worlds.composition import OccurrenceRuntimeComposer, WorldCompositionError
from grass.worlds.package import WorldPackage, WorldPackageError, load_world_package
from grass.worlds.templates import (
    WorldTemplateDestinationExistsError,
    WorldTemplateInfo,
    WorldTemplateNotFoundError,
    initialize_world_template,
    list_world_templates,
    world_template_names,
)


class WorldTemplateInstallationError(RuntimeError):
    """A local world-template installation operation failed."""


class WorldTemplateInstallationConflictError(WorldTemplateInstallationError):
    """An existing local template path is unsafe or invalid."""


class WorldTemplateNotInstalledError(WorldTemplateInstallationError, FileNotFoundError):
    """A bundled template has no installed local copy."""


class WorldTemplateInstallationStatus(StrEnum):
    INSTALLED = "INSTALLED"
    PRESERVED = "PRESERVED"


@dataclass(frozen=True, slots=True)
class WorldTemplateInstallation:
    """Operational result for one bundled template's local copy."""

    template: WorldTemplateInfo
    path: Path
    status: WorldTemplateInstallationStatus

    def __post_init__(self) -> None:
        if type(self.template) is not WorldTemplateInfo:
            raise TypeError("template must be a WorldTemplateInfo")
        if not isinstance(self.path, Path):
            raise TypeError("path must be a Path")
        if type(self.status) is not WorldTemplateInstallationStatus:
            raise TypeError("status must be a WorldTemplateInstallationStatus")


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise WorldTemplateInstallationError(
            f"could not inspect world-template installation path: {path}"
        ) from error
    return True


def _validate_directory(path: Path, description: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise WorldTemplateInstallationError(f"could not inspect {description}") from error
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise WorldTemplateInstallationConflictError(
            f"{description} must be a non-symlink directory"
        )


class FilesystemWorldTemplateStore:
    """Install and load local copies of the trusted bundled world-template registry."""

    def __init__(self, root: os.PathLike[str] | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def _ensure_root(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            pass
        except OSError as error:
            raise WorldTemplateInstallationError(
                "could not create world-template installation root"
            ) from error
        _validate_directory(self._root, "world-template installation root")

    def path_for(self, name: str, /) -> Path:
        if type(name) is not str:
            raise TypeError("name must be a string")
        if name not in world_template_names():
            raise WorldTemplateNotFoundError(f"world template does not exist: {name}")
        return self._root / name

    def load_installed(self, name: str, /) -> WorldPackage:
        path = self.path_for(name)
        if not _path_exists(self._root):
            raise WorldTemplateNotInstalledError(f"world template is not installed: {name}")
        _validate_directory(self._root, "world-template installation root")
        if not _path_exists(path):
            raise WorldTemplateNotInstalledError(f"world template is not installed: {name}")
        try:
            _validate_directory(path, f"installed world template {name}")
            package = load_world_package(path)
            OccurrenceRuntimeComposer().validate(
                package.world_definition,
                SimulationRunConfig(package.world_definition.ref),
            )
        except WorldTemplateInstallationConflictError:
            raise
        except (OSError, WorldPackageError, WorldCompositionError) as error:
            raise WorldTemplateInstallationConflictError(
                f"installed world template is invalid: {name}"
            ) from error
        return package

    def install_registered(self) -> tuple[WorldTemplateInstallation, ...]:
        self._ensure_root()
        installations: list[WorldTemplateInstallation] = []
        for template in list_world_templates():
            path = self._root / template.name
            if _path_exists(path):
                self.load_installed(template.name)
                status = WorldTemplateInstallationStatus.PRESERVED
            else:
                try:
                    initialize_world_template(template.name, path)
                except WorldTemplateDestinationExistsError:
                    self.load_installed(template.name)
                    status = WorldTemplateInstallationStatus.PRESERVED
                else:
                    status = WorldTemplateInstallationStatus.INSTALLED
            installations.append(WorldTemplateInstallation(template, path, status))
        return tuple(installations)
