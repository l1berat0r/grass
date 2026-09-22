# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

from tests.test_world_packages import write_world_package


def run_process(root: Path, *arguments: str) -> dict[str, object]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "grass.cli",
            "--data-dir",
            str(root),
            "--json",
            *arguments,
        ),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.stderr == ""
    return cast("dict[str, object]", json.loads(completed.stdout))


def test_separate_cli_processes_reopen_snapshot_advance_branch_and_verify(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    data_root = tmp_path / "data"
    created = run_process(data_root, "run", "create", str(author))
    run_id = cast(
        str,
        cast(
            dict[str, object],
            cast(dict[str, object], created["data"])["run"],
        )["run_id"],
    )
    shutil.rmtree(author)

    status = run_process(data_root, "run", "status", run_id)
    branch = run_process(
        data_root,
        "branch",
        "create",
        run_id,
        "--from",
        "root",
        "--branch-id",
        "alternative",
    )
    advanced = run_process(data_root, "run", "advance", run_id)
    child = run_process(
        data_root,
        "inspect",
        "events",
        run_id,
        "--branch",
        "alternative",
    )
    verified = run_process(data_root, "run", "verify", run_id)

    assert cast(dict[str, object], status["data"])["status"] == "READY"
    assert cast(dict[str, object], branch["data"])["branch"] is not None
    assert (
        cast(dict[str, object], cast(dict[str, object], advanced["data"])["result"])["stop_reason"]
        == "QUIESCENT"
    )
    assert len(cast(list[object], cast(dict[str, object], child["data"])["transitions"])) == 1
    assert (
        cast(dict[str, object], cast(dict[str, object], verified["data"])["verification"])[
            "branch_count"
        ]
        == 2
    )
