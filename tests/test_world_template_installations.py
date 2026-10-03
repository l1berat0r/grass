# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from pathlib import Path

import pytest

import grass.worlds.templates as templates_module
from grass.worlds import (
    FilesystemWorldTemplateStore,
    WorldTemplateInstallationConflictError,
    WorldTemplateInstallationStatus,
    WorldTemplateNotInstalledError,
)


def test_installs_registered_templates_as_ordinary_world_packages(tmp_path: Path) -> None:
    store = FilesystemWorldTemplateStore(tmp_path / "templates" / "worlds")

    installations = store.install_registered()
    package = store.load_installed("occurrence-counter")

    assert tuple(item.template.name for item in installations) == ("occurrence-counter",)
    assert installations[0].status is WorldTemplateInstallationStatus.INSTALLED
    assert installations[0].path == store.root / "occurrence-counter"
    assert package.world_definition.world_definition_id.value == "occurrence-counter"
    assert (installations[0].path / "README.md").is_file()


def test_repeated_installation_preserves_valid_user_changes(tmp_path: Path) -> None:
    store = FilesystemWorldTemplateStore(tmp_path / "templates" / "worlds")
    path = store.install_registered()[0].path
    world_path = path / "world.json"
    document = json.loads(world_path.read_text(encoding="utf-8"))
    document["initial_conditions"]["state_variables"][0]["value"] = 5
    modified = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    world_path.write_text(modified, encoding="utf-8")

    repeated = store.install_registered()

    assert repeated[0].status is WorldTemplateInstallationStatus.PRESERVED
    assert world_path.read_text(encoding="utf-8") == modified
    assert (
        store.load_installed("occurrence-counter")
        .world_definition.initial_conditions.state_variables[0]
        .value
        == 5
    )


@pytest.mark.parametrize("kind", ("file", "directory", "symlink"))
def test_existing_invalid_installation_conflicts_without_replacement(
    tmp_path: Path, kind: str
) -> None:
    root = tmp_path / "templates" / "worlds"
    root.mkdir(parents=True)
    destination = root / "occurrence-counter"
    if kind == "file":
        destination.write_text("user data", encoding="utf-8")
    elif kind == "directory":
        destination.mkdir()
        (destination / "user.txt").write_text("user data", encoding="utf-8")
    else:
        target = tmp_path / "user-template"
        target.mkdir()
        destination.symlink_to(target, target_is_directory=True)

    with pytest.raises(WorldTemplateInstallationConflictError):
        FilesystemWorldTemplateStore(root).install_registered()

    assert destination.exists() or destination.is_symlink()
    if kind == "file":
        assert destination.read_text(encoding="utf-8") == "user data"
    elif kind == "directory":
        assert (destination / "user.txt").read_text(encoding="utf-8") == "user data"


def test_missing_installed_template_does_not_fall_back_to_bundled_source(
    tmp_path: Path,
) -> None:
    store = FilesystemWorldTemplateStore(tmp_path / "templates" / "worlds")

    with pytest.raises(WorldTemplateNotInstalledError, match="not installed"):
        store.load_installed("occurrence-counter")

    assert not store.root.exists()


def test_loading_installed_copy_does_not_read_bundled_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FilesystemWorldTemplateStore(tmp_path / "templates" / "worlds")
    store.install_registered()

    def fail_bundled_read(spec: object) -> dict[str, bytes]:
        del spec
        raise AssertionError("installed-template loading must not read bundled material")

    monkeypatch.setattr(templates_module, "_resource_files", fail_bundled_read)

    package = store.load_installed("occurrence-counter")

    assert package.world_definition.world_definition_id.value == "occurrence-counter"


def test_installation_root_must_be_a_non_symlink_directory(tmp_path: Path) -> None:
    target = tmp_path / "target" / "worlds"
    real_store = FilesystemWorldTemplateStore(target)
    real_store.install_registered()
    root = tmp_path / "worlds"
    root.symlink_to(target, target_is_directory=True)

    with pytest.raises(WorldTemplateInstallationConflictError, match="non-symlink"):
        FilesystemWorldTemplateStore(root).install_registered()
    with pytest.raises(WorldTemplateInstallationConflictError, match="non-symlink"):
        FilesystemWorldTemplateStore(root).load_installed("occurrence-counter")

    assert real_store.load_installed("occurrence-counter").world_definition.ref.version == "1.0.0"
