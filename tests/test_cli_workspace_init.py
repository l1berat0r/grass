# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import cast

import pytest

from grass.cli.main import run_cli
from grass.cli.workspace import LocalWorkspacePaths
from grass.persistence import SqlitePersistence
from tests.test_world_packages import write_world_package


def invoke(data_root: Path, *arguments: str) -> tuple[int, dict[str, object], str]:
    stdout = StringIO()
    stderr = StringIO()
    code = run_cli(
        ("--data-dir", str(data_root), "--format", "json", *arguments),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )
    return code, cast("dict[str, object]", json.loads(stdout.getvalue())), stderr.getvalue()


def test_init_creates_complete_layout_and_is_idempotent(tmp_path: Path) -> None:
    data_root = tmp_path / "data"

    first_code, first, first_stderr = invoke(data_root, "init")
    second_code, second, second_stderr = invoke(data_root, "init")

    assert (first_code, second_code) == (0, 0)
    assert first_stderr == second_stderr == ""
    assert (data_root / "grass.db").is_file()
    assert (data_root / "worlds").is_dir()
    assert (data_root / "world_snapshots").is_dir()
    assert (data_root / "runs").is_dir()
    assert (data_root / "templates" / "worlds" / "occurrence-counter").is_dir()
    first_templates = cast(
        list[dict[str, object]], cast(dict[str, object], first["data"])["world_templates"]
    )
    second_templates = cast(
        list[dict[str, object]], cast(dict[str, object], second["data"])["world_templates"]
    )
    assert first_templates == [
        {
            "name": "occurrence-counter",
            "path": str(data_root / "templates" / "worlds" / "occurrence-counter"),
            "status": "INSTALLED",
        }
    ]
    assert second_templates[0]["status"] == "PRESERVED"


def test_local_workspace_paths_derive_every_managed_location_from_one_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    paths = LocalWorkspacePaths(root)

    assert paths.root == root
    assert paths.database == root / "grass.db"
    assert paths.worlds == root / "worlds"
    assert paths.world_snapshots == root / "world_snapshots"
    assert paths.runs == root / "runs"
    assert paths.templates == root / "templates"
    assert paths.world_templates == root / "templates" / "worlds"


def test_default_init_uses_dot_grass_under_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    stdout = StringIO()

    code = run_cli(
        ("--format", "json", "init"),
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert code == 0
    assert cast(dict[str, object], json.loads(stdout.getvalue())["data"])["data_root"] == str(
        tmp_path / ".grass"
    )
    assert (tmp_path / ".grass" / "templates" / "worlds" / "occurrence-counter").is_dir()
    assert (tmp_path / ".grass" / "worlds").is_dir()


def test_init_preserves_modified_local_template_and_existing_runs(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    data_root = tmp_path / "data"
    _, created, _ = invoke(data_root, "run", "create", str(author))
    run_id = cast(
        str,
        cast(dict[str, object], cast(dict[str, object], created["data"])["run"])["run_id"],
    )
    invoke(data_root, "init")
    world_path = data_root / "templates" / "worlds" / "occurrence-counter" / "world.json"
    document = json.loads(world_path.read_text(encoding="utf-8"))
    document["initial_conditions"]["state_variables"][0]["value"] = 7
    modified = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    world_path.write_text(modified, encoding="utf-8")

    repeat_code, repeated, _ = invoke(data_root, "init")
    list_code, listed, _ = invoke(data_root, "run", "list")

    assert repeat_code == list_code == 0
    assert world_path.read_text(encoding="utf-8") == modified
    repeated_templates = cast(
        list[dict[str, object]],
        cast(dict[str, object], repeated["data"])["world_templates"],
    )
    assert repeated_templates[0]["status"] == "PRESERVED"
    run_ids = {
        cast(str, cast(dict[str, object], item["run"])["run_id"])
        for item in cast(list[dict[str, object]], cast(dict[str, object], listed["data"])["runs"])
    }
    assert run_id in run_ids


def test_init_refuses_invalid_existing_template_without_overwrite(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    destination = data_root / "templates" / "worlds" / "occurrence-counter"
    destination.parent.mkdir(parents=True)
    destination.write_text("user data", encoding="utf-8")

    code, document, _ = invoke(data_root, "init")

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == ("TEMPLATE_INSTALLATION_CONFLICT")
    assert destination.read_text(encoding="utf-8") == "user data"


def test_init_rejects_database_symlink_without_touching_target(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    external = tmp_path / "external.db"
    (data_root / "grass.db").symlink_to(external)

    code, document, _ = invoke(data_root, "init")

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == "STORAGE_ERROR"
    assert not external.exists()


def test_run_create_template_rejects_database_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    external = tmp_path / "external.db"
    (data_root / "grass.db").symlink_to(external)

    code, document, _ = invoke(data_root, "run", "create", "--template", "occurrence-counter")

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == "STORAGE_ERROR"
    assert not external.exists()


def test_run_create_template_rejects_symlinked_data_root_without_writing_target(
    tmp_path: Path,
) -> None:
    external_root = tmp_path / "external"
    external_root.mkdir()
    data_root = tmp_path / "data"
    data_root.symlink_to(external_root, target_is_directory=True)

    code, document, _ = invoke(data_root, "run", "create", "--template", "occurrence-counter")

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == "STORAGE_ERROR"
    assert list(external_root.iterdir()) == []


def test_template_init_rejects_symlinked_world_root_without_writing_target(
    tmp_path: Path,
) -> None:
    external_root = tmp_path / "external"
    external_root.mkdir()
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "worlds").symlink_to(external_root, target_is_directory=True)

    code, document, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "test",
    )

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == "STORAGE_ERROR"
    assert list(external_root.iterdir()) == []


def test_run_create_template_uses_installed_copy_and_never_bundled_fallback(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    missing_code, missing, _ = invoke(
        data_root, "run", "create", "--template", "occurrence-counter"
    )
    assert missing_code == 1
    assert cast(dict[str, object], missing["error"])["code"] == "TEMPLATE_NOT_INSTALLED"

    invoke(data_root, "init")
    world_path = data_root / "templates" / "worlds" / "occurrence-counter" / "world.json"
    document = json.loads(world_path.read_text(encoding="utf-8"))
    document["initial_conditions"]["state_variables"][0]["value"] = 9
    world_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    create_code, created, _ = invoke(data_root, "run", "create", "--template", "occurrence-counter")
    run_id = cast(
        str,
        cast(dict[str, object], cast(dict[str, object], created["data"])["run"])["run_id"],
    )
    state_code, state, _ = invoke(data_root, "inspect", "state", run_id)
    projected = cast(dict[str, object], cast(dict[str, object], state["data"])["state"])
    world = cast(dict[str, object], projected["world"])

    assert create_code == state_code == 0
    assert cast(list[dict[str, object]], world["state_variables"])[0]["value"] == 9


def test_run_create_template_rejects_symlinked_template_parent(tmp_path: Path) -> None:
    external_root = tmp_path / "external"
    invoke(external_root, "init")
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "templates").symlink_to(external_root / "templates", target_is_directory=True)

    code, document, _ = invoke(data_root, "run", "create", "--template", "occurrence-counter")

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == "STORAGE_ERROR"
    assert SqlitePersistence(data_root / "grass.db").list_runs() == ()


def test_run_create_requires_exactly_one_world_source(tmp_path: Path) -> None:
    neither_code, neither, _ = invoke(tmp_path / "data", "run", "create")
    both_code, both, _ = invoke(
        tmp_path / "data",
        "run",
        "create",
        "world",
        "--template",
        "occurrence-counter",
    )

    assert neither_code == both_code == 2
    assert cast(dict[str, object], neither["error"])["code"] == "USAGE_ERROR"
    assert cast(dict[str, object], both["error"])["code"] == "USAGE_ERROR"


def test_init_does_not_change_sqlite_schema_version(tmp_path: Path) -> None:
    data_root = tmp_path / "data"

    code, _, _ = invoke(data_root, "init")

    assert code == 0
    assert SqlitePersistence(data_root / "grass.db").list_runs() == ()
