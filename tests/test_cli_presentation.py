# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
from io import StringIO
from pathlib import Path

import pytest

from grass.cli.main import _color_enabled, run_cli
from grass.cli.output import JsonValue
from grass.cli.presentation import presenter_commands, write_text

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class TtyBuffer(StringIO):
    def isatty(self) -> bool:
        return True


def _invoke(
    data_root: Path, *arguments: str, stdout: StringIO | None = None
) -> tuple[int, str, str]:
    output = StringIO() if stdout is None else stdout
    errors = StringIO()
    code = run_cli(
        ("--data-dir", str(data_root), *arguments),
        stdin=StringIO(),
        stdout=output,
        stderr=errors,
    )
    return code, output.getvalue(), errors.getvalue()


def test_text_is_default_and_template_list_is_a_table(tmp_path: Path) -> None:
    code, stdout, stderr = _invoke(tmp_path / "data", "template", "list")

    assert code == 0
    assert stderr == ""
    assert "NAME" in stdout
    assert "SCHEMA" in stdout
    assert "DESCRIPTION" in stdout
    assert "occurrence-counter" in stdout
    assert not stdout.lstrip().startswith("{")
    assert "\x1b[" not in stdout


def test_init_has_a_dedicated_text_summary(tmp_path: Path) -> None:
    code, stdout, stderr = _invoke(tmp_path / "data", "init")

    assert code == 0
    assert stderr == ""
    assert "Data root:" in stdout
    assert "Database:" in stdout
    assert "World templates" in stdout
    assert "occurrence-counter" in stdout
    assert "INSTALLED" in stdout


def test_json_format_and_legacy_shortcut_are_identical_and_unstyled(tmp_path: Path) -> None:
    format_code, formatted, format_stderr = _invoke(
        tmp_path / "data", "--format", "json", "template", "list"
    )
    legacy_code, legacy, legacy_stderr = _invoke(tmp_path / "data", "--json", "template", "list")
    combined_code, combined, _ = _invoke(
        tmp_path / "data", "--json", "--format", "json", "template", "list"
    )

    assert (format_code, legacy_code, combined_code) == (0, 0, 0)
    assert formatted == legacy == combined
    assert format_stderr == legacy_stderr == ""
    assert json.loads(formatted)["command"] == "template.list"
    assert "\x1b[" not in formatted


def test_conflicting_json_and_text_options_are_json_usage_error(tmp_path: Path) -> None:
    code, stdout, stderr = _invoke(
        tmp_path / "data", "--json", "--format", "text", "template", "list"
    )

    assert code == 2
    assert stderr == ""
    document = json.loads(stdout)
    assert document["command"] == "cli"
    assert document["error"]["code"] == "USAGE_ERROR"


def test_repeated_format_uses_the_final_value_for_output_and_usage_errors(tmp_path: Path) -> None:
    success_code, success, _ = _invoke(
        tmp_path / "data",
        "--format",
        "json",
        "--format",
        "text",
        "template",
        "list",
    )
    error_code, _, error_stderr = _invoke(
        tmp_path / "data",
        "--format",
        "json",
        "--format",
        "text",
        "missing",
    )

    assert success_code == 0
    assert not success.lstrip().startswith("{")
    assert error_code == 2
    assert "invalid choice" in error_stderr


def test_no_color_is_accepted_in_json_mode(tmp_path: Path) -> None:
    code, stdout, stderr = _invoke(
        tmp_path / "data", "--format", "json", "--no-color", "template", "list"
    )

    assert code == 0
    assert stderr == ""
    assert json.loads(stdout)["schema_version"] == 1
    assert "\x1b[" not in stdout


def test_json_format_help_remains_one_usage_error_document(tmp_path: Path) -> None:
    code, stdout, stderr = _invoke(tmp_path / "data", "--format", "json", "--help")

    assert code == 2
    assert stderr == ""
    document = json.loads(stdout)
    assert document["command"] == "cli"
    assert document["error"] == {
        "code": "USAGE_ERROR",
        "message": "--format json cannot be combined with --help",
    }


def test_color_detection_respects_tty_switch_and_no_color_environment() -> None:
    assert _color_enabled(TtyBuffer(), no_color=False, environment={})
    assert not _color_enabled(StringIO(), no_color=False, environment={})
    assert not _color_enabled(TtyBuffer(), no_color=True, environment={})
    assert not _color_enabled(TtyBuffer(), no_color=False, environment={"NO_COLOR": "1"})
    assert _color_enabled(TtyBuffer(), no_color=False, environment={"NO_COLOR": ""})


def test_cli_auto_color_no_color_flag_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    _, colored, _ = _invoke(tmp_path / "data", "template", "list", stdout=TtyBuffer())
    _, disabled, _ = _invoke(
        tmp_path / "data", "--no-color", "template", "list", stdout=TtyBuffer()
    )
    monkeypatch.setenv("NO_COLOR", "1")
    _, environmental, _ = _invoke(tmp_path / "data", "template", "list", stdout=TtyBuffer())
    _, json_output, _ = _invoke(
        tmp_path / "data", "--format", "json", "template", "list", stdout=TtyBuffer()
    )

    assert "\x1b[" in colored
    assert "\x1b[" not in disabled
    assert "\x1b[" not in environmental
    assert "\x1b[" not in json_output


def test_color_is_supplemental_to_status_text() -> None:
    data: dict[str, JsonValue] = {
        "run_id": "run",
        "branch_id": "root",
        "status": "QUIESCENT",
    }
    plain = StringIO()
    colored = StringIO()

    write_text(plain, "run.status", data, color=False)
    write_text(colored, "run.status", data, color=True)

    assert "QUIESCENT" in plain.getvalue()
    assert "QUIESCENT" in colored.getvalue()
    assert "\x1b[" not in plain.getvalue()
    assert "\x1b[" in colored.getvalue()
    assert ANSI.sub("", colored.getvalue()) == plain.getvalue()


def test_run_catalog_is_a_table_and_status_is_a_detail_view() -> None:
    catalog: dict[str, JsonValue] = {
        "runs": [
            {
                "run": {
                    "run_id": "run-one",
                    "root_branch_id": "root",
                    "world_definition_ref": {
                        "world_definition_id": "demo",
                        "version": "1.0.0",
                    },
                    "world_material_kind": "PACKAGE_SNAPSHOT",
                    "created_at": "2026-10-02T21:10:00",
                },
                "schema_version": 3,
                "health": "OK",
                "verification": None,
                "error": None,
            }
        ]
    }
    status: dict[str, JsonValue] = {
        "run_id": "run-one",
        "branch_id": "root",
        "status": "QUIESCENT",
    }
    catalog_output = StringIO()
    status_output = StringIO()

    write_text(catalog_output, "run.list", catalog)
    write_text(status_output, "run.status", status)

    assert "RUN ID" in catalog_output.getvalue()
    assert "HEALTH" in catalog_output.getvalue()
    assert "demo @ 1.0.0" in catalog_output.getvalue()
    assert "Run:    run-one" in status_output.getvalue()
    assert "Branch: root" in status_output.getvalue()
    assert "Status: QUIESCENT" in status_output.getvalue()


def test_event_history_is_a_structured_timeline_and_escapes_terminal_controls() -> None:
    data: dict[str, JsonValue] = {
        "position": {
            "run_id": "run",
            "viewed_branch_id": "root",
            "transition_ref": {"origin_branch_id": "root", "transition_id": "transition"},
            "logical_time_ns": 10,
        },
        "scope": "VISIBLE",
        "transitions": [
            {
                "transition_ref": {
                    "origin_branch_id": "root",
                    "transition_id": "transition",
                },
                "logical_time_ns": 10,
                "events": [
                    {
                        "event_id": "event",
                        "sequence": 1,
                        "event_type": "StateVariableChanged",
                        "event_version": 1,
                        "payload": {
                            "scope": {"kind": "WORLD"},
                            "state_variable_type": "counter\x1b[31m\u202e\u2028",
                            "value_after": 1,
                        },
                        "provenance": {
                            "source_kind": "ENGINE",
                            "source_ref": None,
                            "metadata": {},
                        },
                        "causation_refs": [],
                        "correlation_id": None,
                    }
                ],
            }
        ],
    }
    first = StringIO()
    second = StringIO()

    write_text(first, "inspect.events", data)
    write_text(second, "inspect.events", data)

    assert first.getvalue() == second.getvalue()
    assert "Time 10 ns | Transition transition | Origin root" in first.getvalue()
    assert "StateVariableChanged" in first.getvalue()
    assert "value_after: 1" in first.getvalue()
    assert "counter\\u001b[31m\\u202e\\u2028" in first.getvalue()
    assert "\x1b[" not in first.getvalue()


def test_every_cli_command_has_an_explicit_text_presenter() -> None:
    assert presenter_commands() == frozenset(
        {
            "init",
            "template.list",
            "template.show",
            "template.init",
            "world.validate",
            "run.create",
            "run.list",
            "run.status",
            "run.step",
            "run.advance",
            "run.verify",
            "branch.list",
            "branch.create",
            "inspect.state",
            "inspect.events",
            "inspect.branches",
            "inspect.jobs",
            "inspect.job",
            "inspect.decisions",
            "inspect.decision",
            "inspect.actors",
            "inspect.actor",
            "inspect.actor-observations",
            "inspect.actor-decisions",
            "inspect.actor-plans",
            "inspect.actor-jobs",
            "inspect.actor-history",
            "inspect.config",
            "inspect.providers",
        }
    )
