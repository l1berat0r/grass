# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib
import json
import shutil
from io import StringIO
from pathlib import Path
from typing import cast

import pytest

from grass.cli.main import run_cli
from grass.worlds import WorldTemplateIntegrityError
from tests.test_world_packages import world_document, write_world_package

cli_main = importlib.import_module("grass.cli.main")


def invoke(data_root: Path, *arguments: str) -> tuple[int, dict[str, object], str]:
    stdout = StringIO()
    stderr = StringIO()
    code = run_cli(
        ("--data-dir", str(data_root), "--json", *arguments),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )
    return code, cast("dict[str, object]", json.loads(stdout.getvalue())), stderr.getvalue()


def _run_id(document: dict[str, object]) -> str:
    data = cast(dict[str, object], document["data"])
    run = cast(dict[str, object], data["run"])
    return cast(str, run["run_id"])


def test_template_cli_metadata_init_and_errors_are_application_free(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    destination = tmp_path / "demo"

    list_code, listed, _ = invoke(data_root, "template", "list")
    show_code, shown, _ = invoke(data_root, "template", "show", "occurrence-counter")
    init_code, initialized, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "--output",
        str(destination),
    )
    missing_code, missing, _ = invoke(data_root, "template", "show", "missing")
    exists_code, exists, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "--output",
        str(destination),
    )

    assert (list_code, show_code, init_code) == (0, 0, 0)
    templates = cast(list[dict[str, object]], cast(dict[str, object], listed["data"])["templates"])
    shown_template = cast(dict[str, object], cast(dict[str, object], shown["data"])["template"])
    assert templates == [shown_template]
    assert shown_template["name"] == "occurrence-counter"
    init_data = cast(dict[str, object], initialized["data"])
    assert init_data["destination"] == str(destination)
    assert (
        cast(dict[str, object], init_data["initialized_world_definition_ref"])[
            "world_definition_id"
        ]
        == "demo"
    )
    assert missing_code == 1
    assert cast(dict[str, object], missing["error"])["code"] == "TEMPLATE_NOT_FOUND"
    assert exists_code == 1
    assert cast(dict[str, object], exists["error"])["code"] == ("TEMPLATE_DESTINATION_EXISTS")
    assert not data_root.exists()


def test_template_cli_maps_invalid_destination_without_application(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    destination = tmp_path / "Not-Safe"

    code, document, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "--output",
        str(destination),
    )

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == ("TEMPLATE_DESTINATION_INVALID")
    assert not destination.exists()
    assert not data_root.exists()


def test_template_cli_logical_name_uses_selected_workspace_not_process_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_directory = tmp_path / "process"
    process_directory.mkdir()
    data_root = tmp_path / "workspace"
    monkeypatch.chdir(process_directory)

    code, initialized, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "test",
    )

    destination = data_root / "worlds" / "test"
    assert code == 0
    assert cast(dict[str, object], initialized["data"])["destination"] == str(destination)
    assert destination.is_dir()
    assert not (process_directory / "test").exists()
    assert {path.name for path in data_root.iterdir()} == {"worlds"}

    validate_code, _, _ = invoke(data_root, "world", "validate", "test")

    assert validate_code == 0
    assert {path.name for path in data_root.iterdir()} == {"worlds"}
    create_code, _, _ = invoke(data_root, "run", "create", "test")
    assert create_code == 0
    assert list(process_directory.iterdir()) == []


def test_template_cli_logical_name_uses_default_dot_grass_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    stdout = StringIO()

    code = run_cli(
        ("--json", "template", "init", "occurrence-counter", "test"),
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    destination = tmp_path / ".grass" / "worlds" / "test"
    assert code == 0
    assert cast(dict[str, object], json.loads(stdout.getvalue())["data"])["destination"] == str(
        destination
    )
    assert destination.is_dir()
    assert not (tmp_path / "test").exists()

    for command in (("world", "validate", "test"), ("run", "create", "test")):
        command_stdout = StringIO()
        command_code = run_cli(
            ("--json", *command),
            stdin=StringIO(),
            stdout=command_stdout,
            stderr=StringIO(),
        )
        assert command_code == 0
        assert json.loads(command_stdout.getvalue())["command"] == ".".join(command[:2])


@pytest.mark.parametrize("command", [("world", "validate"), ("run", "create")])
def test_logical_world_never_falls_back_to_process_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: tuple[str, str],
) -> None:
    process_directory = tmp_path / "process"
    process_directory.mkdir()
    write_world_package(process_directory, name="demo")
    data_root = tmp_path / "workspace"
    monkeypatch.chdir(process_directory)

    code, document, _ = invoke(data_root, *command, "demo")

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == "WORLD_INVALID"
    assert not (data_root / "world_snapshots").exists()
    assert not (data_root / "runs").exists()


def test_workspace_world_and_explicit_path_do_not_compete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "workspace"
    process_directory = tmp_path / "process"
    process_directory.mkdir()
    external_document = world_document("demo")
    external_document["version"] = "9.0.0"
    write_world_package(process_directory, name="demo", document=external_document)
    monkeypatch.chdir(process_directory)
    invoke(data_root, "template", "init", "occurrence-counter", "demo")

    logical_validate_code, logical_validate, _ = invoke(data_root, "world", "validate", "demo")
    external_validate_code, external_validate, _ = invoke(
        data_root, "world", "validate", "--path", "./demo"
    )
    logical_create_code, logical_create, _ = invoke(data_root, "run", "create", "demo")
    external_create_code, external_create, _ = invoke(
        data_root, "run", "create", "--path", "./demo"
    )

    assert (
        logical_validate_code,
        external_validate_code,
        logical_create_code,
        external_create_code,
    ) == (0, 0, 0, 0)
    logical_validate_ref = cast(
        dict[str, object], cast(dict[str, object], logical_validate["data"])["world_definition_ref"]
    )
    external_validate_ref = cast(
        dict[str, object],
        cast(dict[str, object], external_validate["data"])["world_definition_ref"],
    )
    logical_run = cast(dict[str, object], cast(dict[str, object], logical_create["data"])["run"])
    external_run = cast(dict[str, object], cast(dict[str, object], external_create["data"])["run"])
    assert logical_validate_ref["version"] == "1.0.0"
    assert external_validate_ref["version"] == "9.0.0"
    assert cast(dict[str, object], logical_run["world_definition_ref"])["version"] == "1.0.0"
    assert cast(dict[str, object], external_run["world_definition_ref"])["version"] == "9.0.0"


def test_template_cli_defaults_world_name_to_template_name(tmp_path: Path) -> None:
    data_root = tmp_path / "workspace"

    code, initialized, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
    )

    destination = data_root / "worlds" / "occurrence-counter"
    assert code == 0
    assert cast(dict[str, object], initialized["data"])["destination"] == str(destination)
    assert destination.is_dir()


def test_template_cli_accepts_matching_logical_name_and_explicit_output(tmp_path: Path) -> None:
    data_root = tmp_path / "workspace"
    destination = tmp_path / "external" / "test"
    destination.parent.mkdir()

    code, initialized, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "test",
        "--output",
        str(destination),
    )

    assert code == 0
    assert cast(dict[str, object], initialized["data"])["destination"] == str(destination)
    assert destination.is_dir()
    assert not data_root.exists()


def test_template_cli_rejects_invalid_name_and_name_output_mismatch(tmp_path: Path) -> None:
    data_root = tmp_path / "workspace"
    output = tmp_path / "other"

    invalid_code, invalid, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "../test",
    )
    mismatch_code, mismatch, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "test",
        "--output",
        str(output),
    )

    assert invalid_code == mismatch_code == 2
    assert cast(dict[str, object], invalid["error"])["code"] == "USAGE_ERROR"
    assert cast(dict[str, object], mismatch["error"])["code"] == "USAGE_ERROR"
    assert not data_root.exists()
    assert not output.exists()


def test_template_cli_maps_template_integrity_error_without_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"

    def invalid_templates() -> None:
        raise WorldTemplateIntegrityError("injected invalid template")

    monkeypatch.setattr(cli_main, "list_world_templates", invalid_templates)

    code, document, _ = invoke(data_root, "template", "list")

    assert code == 1
    assert cast(dict[str, object], document["error"])["code"] == "TEMPLATE_INVALID"
    assert not data_root.exists()


def test_occurrence_template_runs_branches_reopens_and_verifies(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    destination = data_root / "worlds" / "demo"
    init_code, initialized, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        "demo",
    )
    initialized_ref = cast(
        dict[str, object],
        cast(dict[str, object], initialized["data"])["initialized_world_definition_ref"],
    )
    world_name = cast(str, initialized_ref["world_definition_id"])
    validate_code, _, _ = invoke(data_root, "world", "validate", world_name)
    create_code, created, _ = invoke(data_root, "run", "create", world_name)
    run_id = _run_id(created)
    branch_code, _, _ = invoke(
        data_root,
        "branch",
        "create",
        run_id,
        "--from",
        "root",
        "--branch-id",
        "alternative",
    )
    shutil.rmtree(destination)

    status_code, _, _ = invoke(data_root, "run", "status", run_id)
    root_advance_code, root_advanced, _ = invoke(data_root, "run", "advance", run_id)
    child_advance_code, child_advanced, _ = invoke(
        data_root,
        "run",
        "advance",
        run_id,
        "--branch",
        "alternative",
    )
    state_code, state, _ = invoke(data_root, "inspect", "state", run_id)
    events_code, events, _ = invoke(data_root, "inspect", "events", run_id)
    child_events_code, child_events, _ = invoke(
        data_root,
        "inspect",
        "events",
        run_id,
        "--branch",
        "alternative",
        "--scope",
        "origin",
    )
    verify_code, verified, _ = invoke(data_root, "run", "verify", run_id)

    assert (
        init_code,
        validate_code,
        create_code,
        branch_code,
        status_code,
        root_advance_code,
        child_advance_code,
        state_code,
        events_code,
        child_events_code,
        verify_code,
    ) == (0,) * 11
    root_result = cast(dict[str, object], cast(dict[str, object], root_advanced["data"])["result"])
    child_result = cast(
        dict[str, object], cast(dict[str, object], child_advanced["data"])["result"]
    )
    assert root_result["stop_reason"] == "QUIESCENT"
    assert child_result["stop_reason"] == "QUIESCENT"
    state_data = cast(dict[str, object], state["data"])
    projected = cast(dict[str, object], state_data["state"])
    world = cast(dict[str, object], projected["world"])
    assert cast(list[dict[str, object]], world["state_variables"])[0]["value"] == 1
    assert len(cast(list[object], cast(dict[str, object], events["data"])["transitions"])) == 2
    assert (
        len(cast(list[object], cast(dict[str, object], child_events["data"])["transitions"])) == 1
    )
    report = cast(dict[str, object], cast(dict[str, object], verified["data"])["verification"])
    assert report["branch_count"] == 2
    assert report["transition_count"] == 3
