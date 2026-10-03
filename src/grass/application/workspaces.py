# SPDX-License-Identifier: GPL-3.0-only

"""Non-authoritative per-run filesystem workspace lifecycle."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from grass.persistence import RunId

_SAFE_RUN_SEGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class RunWorkspaceError(RuntimeError):
    """A per-run workspace operation failed."""


class RunWorkspacePathError(RunWorkspaceError):
    """A RunId cannot safely identify one workspace directory."""


class RunWorkspaceConflictError(RunWorkspaceError, FileExistsError):
    """A path already exists for the requested run workspace."""


def _run_segment(run_id: RunId) -> str:
    if type(run_id) is not RunId:
        raise TypeError("run_id must be a RunId")
    if _SAFE_RUN_SEGMENT.fullmatch(run_id.value) is None:
        raise RunWorkspacePathError("workspace RunId must match [a-z0-9]+(?:-[a-z0-9]+)*")
    return run_id.value


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise RunWorkspaceError(f"could not inspect workspace path: {path}") from error
    return True


def _validate_directory(path: Path, description: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise RunWorkspaceError(f"could not inspect {description}") from error
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise RunWorkspaceError(f"{description} must be a non-symlink directory")


class FilesystemRunWorkspaceManager:
    """Create empty operational workspaces without reading them as run material."""

    def __init__(self, root: os.PathLike[str] | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, run_id: RunId, /) -> Path:
        return self._root / _run_segment(run_id)

    def create(self, run_id: RunId, /) -> Path:
        path = self.path_for(run_id)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            pass
        except OSError as error:
            raise RunWorkspaceError("could not create run workspace root") from error
        _validate_directory(self._root, "run workspace root")
        try:
            path.mkdir()
        except FileExistsError as error:
            raise RunWorkspaceConflictError(
                f"run workspace already exists for RunId: {run_id.value}"
            ) from error
        except OSError as error:
            raise RunWorkspaceError("could not create run workspace") from error
        try:
            _validate_directory(path, "run workspace")
        except RunWorkspaceError:
            try:
                path.rmdir()
            except OSError:
                pass
            raise
        return path

    def remove_empty(self, run_id: RunId, /) -> None:
        path = self.path_for(run_id)
        if not _path_exists(path):
            return
        _validate_directory(path, "run workspace")
        try:
            path.rmdir()
        except OSError as error:
            raise RunWorkspaceError("could not remove empty run workspace") from error
