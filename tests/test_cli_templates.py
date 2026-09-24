# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import shutil
from io import StringIO
from pathlib import Path
from typing import cast

from grass.cli.main import run_cli


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
        str(destination),
    )
    missing_code, missing, _ = invoke(data_root, "template", "show", "missing")
    exists_code, exists, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
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


def test_occurrence_template_runs_branches_reopens_and_verifies(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    destination = tmp_path / "demo"
    init_code, _, _ = invoke(
        data_root,
        "template",
        "init",
        "occurrence-counter",
        str(destination),
    )
    validate_code, _, _ = invoke(data_root, "world", "validate", str(destination))
    create_code, created, _ = invoke(data_root, "run", "create", str(destination))
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
        root_advance_code,
        child_advance_code,
        state_code,
        events_code,
        child_events_code,
        verify_code,
    ) == (0,) * 10
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
