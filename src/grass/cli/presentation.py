# SPDX-License-Identifier: GPL-3.0-only

"""Command-aware, human-oriented text presentation for the local CLI."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TextIO, cast

from grass.cli.output import JsonValue

Presenter = Callable[[TextIO, Mapping[str, JsonValue], "TextStyle"], None]


@dataclass(frozen=True, slots=True)
class TextStyle:
    color: bool = False

    def heading(self, value: str) -> str:
        return self._apply("1", value)

    def token(self, value: str) -> str:
        candidate = value.rstrip()
        code = {
            "READY": "32",
            "OK": "32",
            "COMPLETED": "32",
            "QUIESCENT": "36",
            "TARGET_REACHED": "36",
            "WAITING_FOR_DECISION": "33",
            "RECOVERABLE": "33",
            "PAUSED": "33",
            "INVALID": "31",
            "FAILED": "31",
            "CANCELLED": "31",
        }.get(candidate)
        return value if code is None else self._apply(code, value)

    def _apply(self, code: str, value: str) -> str:
        if not self.color:
            return value
        return f"\x1b[{code}m{value}\x1b[0m"


def _mapping(value: JsonValue) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError("presenter expected a mapping")
    return value


def _sequence(value: JsonValue) -> Sequence[JsonValue]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise TypeError("presenter expected a sequence")
    return value


def _safe_text(value: str) -> str:
    parts: list[str] = []
    for character in value:
        codepoint = ord(character)
        if character == "\n":
            parts.append("\\n")
        elif character == "\r":
            parts.append("\\r")
        elif character == "\t":
            parts.append("\\t")
        elif unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}:
            width = 4 if codepoint <= 0xFFFF else 8
            parts.append(f"\\u{codepoint:0{width}x}")
        else:
            parts.append(character)
    return "".join(parts)


def _scalar(value: JsonValue) -> str:
    if value is None:
        return "-"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float):
        return str(value)
    if type(value) is str:
        return _safe_text(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _world_ref(value: JsonValue) -> str:
    reference = _mapping(value)
    return f"{_scalar(reference['world_definition_id'])} @ {_scalar(reference['version'])}"


def _time(value: JsonValue) -> str:
    return f"{_scalar(value)} ns"


def _timestamp(value: JsonValue) -> str:
    return f"{_scalar(value).replace('T', ' ')} UTC"


def _position_fields(value: JsonValue) -> tuple[tuple[str, str], ...]:
    position = _mapping(value)
    transition = position.get("transition_ref")
    transition_text = "-"
    if transition is not None:
        transition_data = _mapping(transition)
        transition_text = (
            f"{_scalar(transition_data['origin_branch_id'])}/"
            f"{_scalar(transition_data['transition_id'])}"
        )
    fields: list[tuple[str, str]] = []
    if "run_id" in position:
        fields.append(("Run", _scalar(position["run_id"])))
    fields.extend(
        (
            ("Branch", _scalar(position["viewed_branch_id"])),
            ("Time", _time(position["logical_time_ns"])),
            ("Transition", transition_text),
        )
    )
    return tuple(fields)


def _write_fields(
    stream: TextIO,
    fields: Sequence[tuple[str, str]],
    style: TextStyle,
) -> None:
    width = max((len(label) for label, _ in fields), default=0)
    for label, value in fields:
        stream.write(f"{style.heading((label + ':').ljust(width + 1))} {style.token(value)}\n")


def _write_table(
    stream: TextIO,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    style: TextStyle,
) -> None:
    if not rows:
        stream.write("(none)\n")
        return
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    stream.write(
        "  ".join(
            style.heading(header.ljust(widths[index])) for index, header in enumerate(headers)
        )
        + "\n"
    )
    stream.write("  ".join("-" * width for width in widths) + "\n")
    for row in rows:
        stream.write(
            "  ".join(
                style.token(value.ljust(widths[index])) for index, value in enumerate(row)
            ).rstrip()
            + "\n"
        )


def _write_nested(stream: TextIO, value: JsonValue, *, indent: int = 0) -> None:
    prefix = " " * indent
    if isinstance(value, Mapping):
        if not value:
            stream.write(f"{prefix}(none)\n")
            return
        for key in sorted(value):
            item = value[key]
            safe_key = _safe_text(str(key))
            if isinstance(item, Mapping) or (
                isinstance(item, Sequence) and not isinstance(item, str)
            ):
                stream.write(f"{prefix}{safe_key}:\n")
                _write_nested(stream, cast("JsonValue", item), indent=indent + 2)
            else:
                stream.write(f"{prefix}{safe_key}: {_scalar(item)}\n")
        return
    if isinstance(value, Sequence) and not isinstance(value, str):
        if not value:
            stream.write(f"{prefix}(none)\n")
            return
        for item in value:
            if isinstance(item, Mapping) or (
                isinstance(item, Sequence) and not isinstance(item, str)
            ):
                stream.write(f"{prefix}-\n")
                _write_nested(stream, cast("JsonValue", item), indent=indent + 2)
            else:
                stream.write(f"{prefix}- {_scalar(item)}\n")
        return
    stream.write(f"{prefix}{_scalar(value)}\n")


def _present_template_list(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    rows = []
    for item in _sequence(data["templates"]):
        template = _mapping(item)
        rows.append(
            (
                _scalar(template["name"]),
                _scalar(template["schema_version"]),
                _world_ref(template["world_definition_ref"]),
                _scalar(template["description"]),
            )
        )
    _write_table(stream, ("NAME", "SCHEMA", "WORLD", "DESCRIPTION"), rows, style)


def _present_template_show(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    template = _mapping(data["template"])
    _write_fields(
        stream,
        (
            ("Name", _scalar(template["name"])),
            ("Description", _scalar(template["description"])),
            ("Package", _scalar(template["package_version"])),
            ("World", _world_ref(template["world_definition_ref"])),
            ("Schema", _scalar(template["schema_version"])),
        ),
        style,
    )
    stream.write(f"\n{style.heading('Files')}\n")
    _write_nested(stream, template["files"], indent=2)


def _present_init(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    _write_fields(
        stream,
        (
            ("Data root", _scalar(data["data_root"])),
            ("Database", _scalar(data["database"])),
        ),
        style,
    )
    stream.write(f"\n{style.heading('World templates')}\n")
    rows = []
    for item in _sequence(data["world_templates"]):
        installation = _mapping(item)
        rows.append(
            (
                _scalar(installation["name"]),
                _scalar(installation["status"]),
                _scalar(installation["path"]),
            )
        )
    _write_table(stream, ("NAME", "STATUS", "PATH"), rows, style)


def _present_run_list(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    rows = []
    errors: list[tuple[str, str]] = []
    for item in _sequence(data["runs"]):
        entry = _mapping(item)
        run = _mapping(entry["run"])
        error = entry.get("error")
        error_code = "-"
        if error is not None:
            error_data = _mapping(error)
            error_code = _scalar(error_data["code"])
            errors.append(
                (
                    _scalar(run["run_id"]),
                    f"{error_code}: {_scalar(error_data['message'])}",
                )
            )
        rows.append(
            (
                _scalar(run["run_id"]),
                _scalar(entry["health"]),
                _world_ref(run["world_definition_ref"]),
                _timestamp(run["created_at"]),
                error_code,
            )
        )
    _write_table(stream, ("RUN ID", "HEALTH", "WORLD", "CREATED", "ERROR"), rows, style)
    if errors:
        stream.write(f"\n{style.heading('Errors')}\n")
        _write_fields(stream, errors, style)


def _present_run_create(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    run = _mapping(data["run"])
    fields = [
        ("Run", _scalar(run["run_id"])),
        ("World", _world_ref(run["world_definition_ref"])),
        ("Branch", _scalar(run["root_branch_id"])),
        ("Status", _scalar(data["status"])),
        ("Created", _timestamp(run["created_at"])),
    ]
    position = _mapping(data["position"])
    fields.append(("Time", _time(position["logical_time_ns"])))
    _write_fields(stream, fields, style)


def _present_run_status(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    _write_fields(
        stream,
        (
            ("Run", _scalar(data["run_id"])),
            ("Branch", _scalar(data["branch_id"])),
            ("Status", _scalar(data["status"])),
        ),
        style,
    )


def _present_verification(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    report = _mapping(data["verification"])
    _write_fields(
        stream,
        (
            ("Run", _scalar(report["run_id"])),
            ("Material", _scalar(report["world_material_kind"])),
            ("Branches", _scalar(report["branch_count"])),
            ("Transitions", _scalar(report["transition_count"])),
            ("Events", _scalar(report["event_count"])),
            ("Snapshot files", _scalar(report["snapshot_file_count"])),
        ),
        style,
    )


def _present_branches(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    stream.write(f"{style.heading('Run:')} {_scalar(data['run_id'])}\n\n")
    rows = []
    for item in _sequence(data["branches"]):
        view = _mapping(item)
        branch = _mapping(view["branch"])
        position = _mapping(view["position"])
        rows.append(
            (
                _scalar(branch["branch_id"]),
                _scalar(branch["parent_branch_id"]),
                _time(position["logical_time_ns"]),
                _scalar(view["visible_transition_count"]),
                _scalar(view["origin_transition_count"]),
            )
        )
    _write_table(stream, ("BRANCH", "PARENT", "TIME", "VISIBLE", "ORIGIN"), rows, style)


def _present_jobs(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    _write_fields(stream, _position_fields(data["position"]), style)
    stream.write("\n")
    rows = []
    for item in _sequence(data["jobs"]):
        view = _mapping(item)
        job = _mapping(view["job"])
        step_ref = _mapping(job["plan_step_ref"])
        plan_ref = _mapping(step_ref["plan_ref"])
        progress = _mapping(job["progress"])
        progress_text = _scalar(progress["kind"])
        if progress["kind"] == "LINEAR":
            progress_text = f"{_scalar(progress['completed'])}/{_scalar(progress['total'])}"
        elif progress["kind"] == "BINARY":
            progress_text = "complete" if progress["complete"] is True else "pending"
        rows.append(
            (
                _scalar(job["job_id"]),
                _scalar(job["status"]),
                f"{_scalar(plan_ref['plan_id'])}@{_scalar(plan_ref['version'])}",
                _scalar(step_ref["step_id"]),
                progress_text,
            )
        )
    _write_table(stream, ("JOB", "STATUS", "PLAN", "STEP", "PROGRESS"), rows, style)


def _present_decisions(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    _write_fields(stream, _position_fields(data["position"]), style)
    stream.write("\n")
    rows = []
    for item in _sequence(data["decisions"]):
        view = _mapping(item)
        point = _mapping(view["decision_point"])
        decision = view["decision"]
        outcome = "-"
        if decision is not None:
            outcome = _scalar(_mapping(_mapping(decision)["outcome"])["kind"])
        rows.append(
            (
                _scalar(point["decision_point_id"]),
                _scalar(point["actor_id"]),
                _scalar(point["reason"]),
                _scalar(view["status"]),
                outcome,
            )
        )
    _write_table(stream, ("DECISION", "ACTOR", "REASON", "STATUS", "OUTCOME"), rows, style)


def _present_actors(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    _write_fields(stream, _position_fields(data["position"]), style)
    stream.write("\n")
    rows = []
    for item in _sequence(data["actors"]):
        actor = _mapping(item)
        entity = _mapping(actor["entity"])
        rows.append(
            (
                _scalar(entity["entity_id"]),
                _scalar(entity["entity_type"]),
                _scalar(entity["active"]),
                str(len(_sequence(actor["plans"]))),
                str(len(_sequence(actor["jobs"]))),
            )
        )
    _write_table(stream, ("ACTOR", "TYPE", "ACTIVE", "PLANS", "JOBS"), rows, style)


def _write_event_timeline(
    stream: TextIO, transitions: JsonValue, style: TextStyle, *, indent: int = 0
) -> None:
    items = _sequence(transitions)
    if not items:
        stream.write(" " * indent + "(none)\n")
        return
    prefix = " " * indent
    for index, item in enumerate(items):
        transition = _mapping(item)
        reference = _mapping(transition["transition_ref"])
        stream.write(
            f"{prefix}{style.heading('Time')} {_time(transition['logical_time_ns'])} | "
            f"{style.heading('Transition')} {_scalar(reference['transition_id'])} | "
            f"{style.heading('Origin')} {_scalar(reference['origin_branch_id'])}\n"
        )
        for event_value in _sequence(transition["events"]):
            event = _mapping(event_value)
            stream.write(
                f"{prefix}  {style.heading(_scalar(event['event_type']))} "
                f"[sequence {_scalar(event['sequence'])}, "
                f"version {_scalar(event['event_version'])}]\n"
            )
            stream.write(f"{prefix}    id: {_scalar(event['event_id'])}\n")
            stream.write(f"{prefix}    payload:\n")
            _write_nested(stream, event["payload"], indent=indent + 6)
            provenance = _mapping(event["provenance"])
            stream.write(f"{prefix}    source: {_scalar(provenance['source_kind'])}\n")
            if event["causation_refs"]:
                stream.write(f"{prefix}    causes:\n")
                _write_nested(stream, event["causation_refs"], indent=indent + 6)
            if event["correlation_id"] is not None:
                stream.write(f"{prefix}    correlation: {_scalar(event['correlation_id'])}\n")
        if index != len(items) - 1:
            stream.write("\n")


def _present_events(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    _write_fields(stream, _position_fields(data["position"]), style)
    stream.write(f"{style.heading('Scope:')} {_scalar(data['scope'])}\n\n")
    _write_event_timeline(stream, data["transitions"], style)


def _present_actor_history(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    _write_fields(
        stream,
        (*_position_fields(data["position"]), ("Actor", _scalar(data["actor_id"]))),
        style,
    )
    stream.write("\n")
    history = _sequence(data["history"])
    if not history:
        stream.write("(none)\n")
        return
    for index, item in enumerate(history):
        entry = _mapping(item)
        _write_event_timeline(stream, (entry["transition"],), style)
        stream.write(f"  {style.heading('Attributions')}\n")
        _write_nested(stream, entry["attributions"], indent=4)
        if index != len(history) - 1:
            stream.write("\n")


def _present_state(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    _write_fields(stream, _position_fields(data["position"]), style)
    state = _mapping(data["state"])
    for section in ("world", "execution", "cognition"):
        stream.write(f"\n{style.heading(section.title())}\n")
        _write_nested(stream, state[section], indent=2)


def _present_execution(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    result = _mapping(data["result"])
    fields = [
        ("Run", _scalar(data["run_id"])),
        ("Branch", _scalar(data["branch_id"])),
        ("Time", _time(result["logical_time_ns"])),
    ]
    for key, label in (
        ("work_kind", "Work"),
        ("committed_steps", "Committed steps"),
        ("stop_reason", "Stop"),
    ):
        if key in result:
            fields.append((label, _scalar(result[key])))
    _write_fields(stream, fields, style)
    waiting = result["waiting_decision_point_ids"]
    if waiting:
        stream.write(f"\n{style.heading('Waiting decisions')}\n")
        _write_nested(stream, waiting, indent=2)
    transition = result.get("committed_transition")
    if transition is not None:
        stream.write(f"\n{style.heading('Committed transition')}\n")
        _write_event_timeline(stream, (transition,), style, indent=2)


def _present_nested_result(stream: TextIO, data: Mapping[str, JsonValue], style: TextStyle) -> None:
    for index, key in enumerate(data):
        if index:
            stream.write("\n")
        value = data[key]
        if isinstance(value, Mapping) or (
            isinstance(value, Sequence) and not isinstance(value, str)
        ):
            stream.write(f"{style.heading(key.replace('_', ' ').title())}\n")
            _write_nested(stream, value, indent=2)
        else:
            _write_fields(stream, ((key.replace("_", " ").title(), _scalar(value)),), style)


_PRESENTERS: Mapping[str, Presenter] = {
    "init": _present_init,
    "template.list": _present_template_list,
    "template.show": _present_template_show,
    "template.init": _present_nested_result,
    "world.validate": _present_nested_result,
    "run.create": _present_run_create,
    "run.list": _present_run_list,
    "run.status": _present_run_status,
    "run.step": _present_execution,
    "run.advance": _present_execution,
    "run.verify": _present_verification,
    "branch.list": _present_branches,
    "branch.create": _present_nested_result,
    "inspect.state": _present_state,
    "inspect.events": _present_events,
    "inspect.branches": _present_branches,
    "inspect.jobs": _present_jobs,
    "inspect.job": _present_nested_result,
    "inspect.decisions": _present_decisions,
    "inspect.decision": _present_nested_result,
    "inspect.actors": _present_actors,
    "inspect.actor": _present_nested_result,
    "inspect.actor-observations": _present_nested_result,
    "inspect.actor-decisions": _present_nested_result,
    "inspect.actor-plans": _present_nested_result,
    "inspect.actor-jobs": _present_jobs,
    "inspect.actor-history": _present_actor_history,
    "inspect.config": _present_nested_result,
    "inspect.providers": _present_nested_result,
}


def presenter_commands() -> frozenset[str]:
    return frozenset(_PRESENTERS)


def write_text(
    stream: TextIO,
    command: str,
    data: Mapping[str, JsonValue],
    /,
    *,
    color: bool = False,
) -> None:
    try:
        presenter = _PRESENTERS[command]
    except KeyError as error:
        raise ValueError(f"no text presenter registered for command: {command}") from error
    presenter(stream, data, TextStyle(color))
