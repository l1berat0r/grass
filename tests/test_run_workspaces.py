# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import pytest

from grass.application import (
    FilesystemRunWorkspaceManager,
    RunWorkspaceConflictError,
    RunWorkspaceError,
    RunWorkspacePathError,
)
from grass.persistence import RunId


def test_workspace_uses_safe_deterministic_run_path_and_removes_only_when_empty(
    tmp_path: Path,
) -> None:
    manager = FilesystemRunWorkspaceManager(tmp_path / "runs")
    run_id = RunId("12345678-1234-1234-1234-123456789abc")

    path = manager.create(run_id)

    assert path == tmp_path / "runs" / run_id.value
    assert path.is_dir()
    marker = path / "marker"
    marker.write_text("operational", encoding="utf-8")
    with pytest.raises(RunWorkspaceError, match="empty"):
        manager.remove_empty(run_id)
    assert marker.read_text(encoding="utf-8") == "operational"
    marker.unlink()
    manager.remove_empty(run_id)
    assert not path.exists()


@pytest.mark.parametrize(
    "value",
    ("../unsafe", "/absolute", "upper-Case", "two--segments", "contains_underscore"),
)
def test_workspace_rejects_unsafe_run_ids(tmp_path: Path, value: str) -> None:
    manager = FilesystemRunWorkspaceManager(tmp_path / "runs")

    with pytest.raises(RunWorkspacePathError):
        manager.create(RunId(value))

    assert not manager.root.exists()


@pytest.mark.parametrize("kind", ("directory", "file", "symlink"))
def test_workspace_refuses_and_preserves_existing_run_path(tmp_path: Path, kind: str) -> None:
    manager = FilesystemRunWorkspaceManager(tmp_path / "runs")
    manager.root.mkdir()
    path = manager.path_for(RunId("existing-run"))
    if kind == "directory":
        path.mkdir()
    elif kind == "file":
        path.write_text("existing", encoding="utf-8")
    else:
        target = tmp_path / "target"
        target.mkdir()
        path.symlink_to(target, target_is_directory=True)

    with pytest.raises(RunWorkspaceConflictError):
        manager.create(RunId("existing-run"))

    assert path.exists() or path.is_symlink()


@pytest.mark.parametrize("kind", ("file", "symlink"))
def test_workspace_rejects_non_directory_root(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "runs"
    if kind == "file":
        root.write_text("not a directory", encoding="utf-8")
    else:
        target = tmp_path / "target"
        target.mkdir()
        root.symlink_to(target, target_is_directory=True)

    with pytest.raises(RunWorkspaceError, match="non-symlink directory"):
        FilesystemRunWorkspaceManager(root).create(RunId("safe-run"))

    assert root.exists()
