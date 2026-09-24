# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import cast


def test_built_distributions_include_and_run_template_resources(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    subprocess.run(
        (
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(distribution_directory),
            str(project_root),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(distribution_directory.glob("*.whl"))
    source_distribution = next(distribution_directory.glob("*.tar.gz"))
    resource_suffixes = (
        "grass/worlds/_template_data/occurrence-counter/README.md",
        "grass/worlds/_template_data/occurrence-counter/mechanics/increment.gel",
        "grass/worlds/_template_data/occurrence-counter/package.json",
        "grass/worlds/_template_data/occurrence-counter/world.json",
    )

    with zipfile.ZipFile(wheel) as archive:
        wheel_names = frozenset(archive.namelist())
    with tarfile.open(source_distribution, "r:gz") as archive:
        source_names = frozenset(archive.getnames())
    assert all(suffix in wheel_names for suffix in resource_suffixes)
    assert all(any(name.endswith(suffix) for name in source_names) for suffix in resource_suffixes)

    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    virtual_environment = tmp_path / "venv"
    subprocess.run(
        (sys.executable, "-m", "venv", str(virtual_environment)),
        check=True,
        capture_output=True,
        text=True,
    )
    executable_directory = virtual_environment / ("Scripts" if os.name == "nt" else "bin")
    python = executable_directory / ("python.exe" if os.name == "nt" else "python")
    grass = executable_directory / ("grass.exe" if os.name == "nt" else "grass")
    subprocess.run(
        (str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
    )
    listed = subprocess.run(
        (str(grass), "--json", "template", "list"),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
    )
    initialized = subprocess.run(
        (
            str(grass),
            "--json",
            "template",
            "init",
            "occurrence-counter",
            "demo",
        ),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
    )
    validated = subprocess.run(
        (str(python), "-m", "grass.cli", "--json", "world", "validate", "demo"),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
    )
    subprocess.run(
        (str(python), "-I", "-c", "import grass.worlds, grass.cli"),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
    )

    assert cast(dict[str, object], json.loads(listed.stdout))["command"] == "template.list"
    assert cast(dict[str, object], json.loads(initialized.stdout))["command"] == "template.init"
    assert cast(dict[str, object], json.loads(validated.stdout))["command"] == "world.validate"
