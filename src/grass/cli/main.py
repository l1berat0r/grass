# SPDX-License-Identifier: GPL-3.0-only

"""Standard-library command line client for the local simulation application."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, TextIO, cast

from grass.application import (
    LocalSimulationApplication,
    QueryError,
    QueryNotFoundError,
    RunInitializationRequiredError,
    VerificationIntegrityError,
)
from grass.cli import output
from grass.cli.output import JsonValue
from grass.core import (
    BranchId,
    DecisionOutputError,
    DecisionPointId,
    EntityId,
    JobId,
    LogicalTime,
    ProviderBindingError,
    SimulationRunConfig,
)
from grass.persistence import (
    PersistenceError,
    PersistenceIntegrityError,
    RunId,
    RunNotFoundError,
    SqlitePersistence,
)
from grass.runtime import (
    RuntimeComposer,
    RuntimeIntegrityError,
    UnsupportedRuntimeFrontierError,
    UnsupportedRuntimeStateError,
)
from grass.worlds import (
    FilesystemWorldSnapshotStore,
    OccurrenceRuntimeComposer,
    WorldCompositionError,
    WorldPackageError,
    WorldSnapshotError,
    WorldSnapshotIntegrityError,
    WorldSnapshotNotFoundError,
    WorldTemplateDestinationError,
    WorldTemplateDestinationExistsError,
    WorldTemplateError,
    WorldTemplateIntegrityError,
    WorldTemplateNotFoundError,
    get_world_template,
    initialize_world_template,
    list_world_templates,
    load_world_package,
)


class CliUsageError(ValueError):
    pass


class CliFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CliUsageError(message)


def _non_empty(value: str) -> str:
    if value == "":
        raise argparse.ArgumentTypeError("value must not be empty")
    return value


def _non_negative(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _positive(value: str) -> int:
    parsed = _non_negative(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _branch_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--branch", type=_non_empty)


def _build_parser() -> _Parser:
    parser = _Parser(prog="grass", description="GRASS local simulation CLI")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--json", action="store_true", dest="json_output")
    families = parser.add_subparsers(dest="family", required=True)

    template = families.add_parser("template")
    template_commands = template.add_subparsers(dest="template_command", required=True)
    template_list = template_commands.add_parser("list")
    template_list.set_defaults(command="template.list")
    template_show = template_commands.add_parser("show")
    template_show.add_argument("name", type=_non_empty)
    template_show.set_defaults(command="template.show")
    template_init = template_commands.add_parser("init")
    template_init.add_argument("name", type=_non_empty)
    template_init.add_argument("destination", type=Path)
    template_init.set_defaults(command="template.init")

    world = families.add_parser("world")
    world_commands = world.add_subparsers(dest="world_command", required=True)
    validate = world_commands.add_parser("validate")
    validate.add_argument("world", type=Path)
    validate.set_defaults(command="world.validate")

    run = families.add_parser("run")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    create = run_commands.add_parser("create")
    create.add_argument("world", type=Path)
    create.set_defaults(command="run.create")
    list_runs = run_commands.add_parser("list")
    list_runs.set_defaults(command="run.list")
    status = run_commands.add_parser("status")
    status.add_argument("run", type=_non_empty)
    _branch_option(status)
    status.set_defaults(command="run.status")
    step = run_commands.add_parser("step")
    step.add_argument("run", type=_non_empty)
    _branch_option(step)
    step.add_argument("--target-time-ns", type=_non_negative)
    step.set_defaults(command="run.step")
    advance = run_commands.add_parser("advance")
    advance.add_argument("run", type=_non_empty)
    _branch_option(advance)
    advance.add_argument("--target-time-ns", type=_non_negative)
    advance.add_argument("--max-steps", type=_positive, default=1000)
    advance.set_defaults(command="run.advance")
    verify = run_commands.add_parser("verify")
    verify.add_argument("run", type=_non_empty)
    verify.set_defaults(command="run.verify")

    branch_family = families.add_parser("branch")
    branch_commands = branch_family.add_subparsers(dest="branch_command", required=True)
    branch_list = branch_commands.add_parser("list")
    branch_list.add_argument("run", type=_non_empty)
    branch_list.set_defaults(command="branch.list")
    branch_create = branch_commands.add_parser("create")
    branch_create.add_argument("run", type=_non_empty)
    branch_create.add_argument("--from", dest="parent", required=True, type=_non_empty)
    branch_create.add_argument("--branch-id", required=True, type=_non_empty)
    branch_create.set_defaults(command="branch.create")

    inspect = families.add_parser("inspect")
    inspect_commands = inspect.add_subparsers(dest="inspect_command", required=True)
    for name in ("state", "branches", "jobs", "decisions", "actors"):
        command = inspect_commands.add_parser(name)
        command.add_argument("run", type=_non_empty)
        if name != "branches":
            _branch_option(command)
        command.set_defaults(command=f"inspect.{name}")
    events = inspect_commands.add_parser("events")
    events.add_argument("run", type=_non_empty)
    _branch_option(events)
    events.add_argument("--scope", choices=("visible", "origin"), default="visible")
    events.set_defaults(command="inspect.events")
    job = inspect_commands.add_parser("job")
    job.add_argument("run", type=_non_empty)
    job.add_argument("job", type=_non_empty)
    _branch_option(job)
    job.set_defaults(command="inspect.job")
    decision = inspect_commands.add_parser("decision")
    decision.add_argument("run", type=_non_empty)
    decision.add_argument("decision", type=_non_empty)
    _branch_option(decision)
    decision.set_defaults(command="inspect.decision")
    actor = inspect_commands.add_parser("actor")
    actor.add_argument("run", type=_non_empty)
    actor.add_argument("actor", type=_non_empty)
    _branch_option(actor)
    actor.set_defaults(command="inspect.actor")
    for name in (
        "actor-observations",
        "actor-decisions",
        "actor-plans",
        "actor-jobs",
        "actor-history",
    ):
        command = inspect_commands.add_parser(name)
        command.add_argument("run", type=_non_empty)
        command.add_argument("actor", type=_non_empty)
        _branch_option(command)
        command.set_defaults(command=f"inspect.{name}")
    for name in ("config", "providers"):
        command = inspect_commands.add_parser(name)
        command.add_argument("run", type=_non_empty)
        command.set_defaults(command=f"inspect.{name}")
    return parser


def _run_id(arguments: argparse.Namespace) -> RunId:
    return RunId(cast("str", arguments.run))


def _branch_id(arguments: argparse.Namespace) -> BranchId | None:
    value = getattr(arguments, "branch", None)
    return None if value is None else BranchId(cast("str", value))


def _target_time(arguments: argparse.Namespace) -> LogicalTime | None:
    value = getattr(arguments, "target_time_ns", None)
    return None if value is None else LogicalTime(cast("int", value))


def _application(data_root: Path, composer: RuntimeComposer) -> LocalSimulationApplication:
    data_root.mkdir(parents=True, exist_ok=True)
    return LocalSimulationApplication(
        SqlitePersistence(data_root / "grass.db"),
        FilesystemWorldSnapshotStore(data_root / "world_snapshots"),
        composer=composer,
    )


def _actual_branch(
    application: LocalSimulationApplication,
    run_id: RunId,
    selected: BranchId | None,
) -> BranchId:
    if selected is not None:
        return selected
    return application.queries.get_run(run_id).record.root_branch_id


def _validate_execution_branch(
    application: LocalSimulationApplication,
    run_id: RunId,
    selected: BranchId | None,
) -> None:
    if selected is None:
        return
    root_branch_id = application.queries.get_run(run_id).record.root_branch_id
    if selected != root_branch_id:
        application.queries.get_branch(run_id, selected)


def _catalog(application: LocalSimulationApplication) -> dict[str, JsonValue]:
    entries: list[JsonValue] = []
    records = sorted(
        application.queries.list_run_records(),
        key=lambda item: (item.created_at, item.run_id.value),
    )
    for record in records:
        entry: dict[str, JsonValue] = {
            "run": output.run_record(record),
            "schema_version": None,
            "health": "INVALID",
            "verification": None,
            "error": None,
        }
        try:
            run = application.queries.get_run(record.run_id)
            entry["schema_version"] = run.definition.schema_version
            try:
                application.queries.get_branch(record.run_id, record.root_branch_id)
            except RunInitializationRequiredError:
                entry["health"] = "RECOVERABLE"
            else:
                report = application.verify_run(record.run_id)
                entry["health"] = "OK"
                entry["verification"] = output.verification_report(report)
        except RunInitializationRequiredError:
            entry["health"] = "RECOVERABLE"
        except Exception as error:  # Each durable registration must remain visible.
            failure = _map_failure("run.list", error)
            entry["error"] = {"code": failure.code, "message": failure.message}
        entries.append(entry)
    return {"runs": entries}


async def _dispatch(
    arguments: argparse.Namespace,
    application: LocalSimulationApplication | None,
    composer: RuntimeComposer,
) -> dict[str, JsonValue]:
    command = cast("str", arguments.command)
    if command == "template.list":
        return {
            "templates": [
                output.world_template_info(template) for template in list_world_templates()
            ]
        }
    if command == "template.show":
        return {"template": output.world_template_info(get_world_template(arguments.name))}
    if command == "template.init":
        template = get_world_template(arguments.name)
        package = initialize_world_template(arguments.name, arguments.destination)
        return {
            "template": output.world_template_info(template),
            "destination": str(arguments.destination),
            "initialized_world_definition_ref": output.world_definition_ref(
                package.world_definition.ref
            ),
            "schema_version": package.world_definition.schema_version,
        }
    if command == "world.validate":
        package = load_world_package(arguments.world)
        config = SimulationRunConfig(package.world_definition.ref)
        composer.validate(package.world_definition, config)
        return {
            "package_version": package.manifest.package_version,
            "world_definition_ref": output.world_definition_ref(package.world_definition.ref),
            "schema_version": package.world_definition.schema_version,
            "material_files": sorted(package.material_files),
        }
    assert application is not None
    queries = application.queries
    if command == "run.create":
        package = load_world_package(arguments.world)
        opened = application.create_run(
            package,
            SimulationRunConfig(package.world_definition.ref),
        )
        run = queries.get_run(opened.run_id)
        root = queries.get_branch(opened.run_id, opened.root_branch_id)
        return {
            "run": output.run_record(run.record),
            "position": output.query_position(root.position),
            "status": queries.get_status(opened.run_id).value,
        }
    if command == "run.list":
        return _catalog(application)
    if command == "run.status":
        run_id = _run_id(arguments)
        selected = _branch_id(arguments)
        return {
            "run_id": run_id.value,
            "branch_id": _actual_branch(application, run_id, selected).value,
            "status": queries.get_status(run_id, selected).value,
        }
    if command == "run.step":
        run_id = _run_id(arguments)
        selected = _branch_id(arguments)
        _validate_execution_branch(application, run_id, selected)
        opened = application.open_run(run_id)
        step_outcome = await opened.step(selected, target_time=_target_time(arguments))
        return {
            "run_id": run_id.value,
            "branch_id": (opened.root_branch_id if selected is None else selected).value,
            "result": output.step_result(step_outcome),
        }
    if command == "run.advance":
        run_id = _run_id(arguments)
        selected = _branch_id(arguments)
        _validate_execution_branch(application, run_id, selected)
        opened = application.open_run(run_id)
        advance_outcome = await opened.advance(
            selected,
            target_time=_target_time(arguments),
            max_steps=arguments.max_steps,
        )
        return {
            "run_id": run_id.value,
            "branch_id": (opened.root_branch_id if selected is None else selected).value,
            "result": output.advance_result(advance_outcome),
        }
    if command == "run.verify":
        report = application.verify_run(_run_id(arguments))
        return {"verification": output.verification_report(report)}
    if command == "branch.list" or command == "inspect.branches":
        run_id = _run_id(arguments)
        return {
            "run_id": run_id.value,
            "branches": [output.branch_view(item) for item in queries.list_branches(run_id)],
        }
    if command == "branch.create":
        run_id = _run_id(arguments)
        parent = queries.get_branch(run_id, BranchId(arguments.parent))
        parent_position = parent.position.history_position
        opened = application.open_run(run_id)
        created = opened.create_branch(BranchId(arguments.branch_id), parent_position)
        return {
            "run_id": run_id.value,
            "parent_position": output.query_position(parent.position),
            "branch": output.branch(created),
        }

    run_id = _run_id(arguments)
    selected = _branch_id(arguments)
    if command == "inspect.state":
        return output.state_view(queries.get_state(run_id, selected))
    if command == "inspect.events":
        from grass.application import HistoryScope

        scope = HistoryScope.VISIBLE if arguments.scope == "visible" else HistoryScope.BRANCH_ORIGIN
        return output.history_view(queries.get_history(run_id, selected, scope=scope))
    if command in ("inspect.config", "inspect.providers"):
        run = queries.get_run(run_id)
        if command == "inspect.config":
            return {"run_id": run_id.value, "config": output.run_config(run.config)}
        return {
            "run_id": run_id.value,
            "provider_bindings": output.provider_bindings(run.config.provider_bindings),
        }

    try:
        state_capture = queries.get_state(run_id, selected)
    except QueryNotFoundError as error:
        if isinstance(error.__cause__, RunNotFoundError):
            raise
        raise CliFailure("BRANCH_NOT_FOUND", str(error)) from error
    position = state_capture.position.history_position
    position_data = output.query_position(state_capture.position)
    if command == "inspect.jobs":
        jobs = queries.get_jobs(run_id, selected, position=position)
        return {"position": position_data, "jobs": [output.job_view(item) for item in jobs]}
    if command == "inspect.job":
        selected_job = queries.get_job(run_id, selected, JobId(arguments.job), position=position)
        return output.job_view(selected_job)
    if command == "inspect.decisions":
        decisions = queries.get_decisions(run_id, selected, position=position)
        return {
            "position": position_data,
            "decisions": [output.decision_view(item) for item in decisions],
        }
    if command == "inspect.decision":
        selected_decision = queries.get_decision(
            run_id,
            selected,
            DecisionPointId(arguments.decision),
            position=position,
        )
        return output.decision_view(selected_decision)
    if command == "inspect.actors":
        actors = queries.get_actors(run_id, selected, position=position)
        return {
            "position": position_data,
            "actors": [output.actor_view(item) for item in actors],
        }

    actor_id = EntityId(arguments.actor)
    actor = queries.get_actor(run_id, selected, actor_id, position=position)
    if command == "inspect.actor":
        return output.actor_view(actor)
    if command == "inspect.actor-observations":
        return {
            "position": position_data,
            "actor_id": actor_id.value,
            "observations": [output.observation(item) for item in actor.observations],
        }
    if command == "inspect.actor-decisions":
        return {
            "position": position_data,
            "actor_id": actor_id.value,
            "decisions": [output.decision_view(item) for item in actor.decisions],
        }
    if command == "inspect.actor-plans":
        return {
            "position": position_data,
            "actor_id": actor_id.value,
            "plans": [output.plan(item) for item in actor.plans],
        }
    if command == "inspect.actor-jobs":
        return {
            "position": position_data,
            "actor_id": actor_id.value,
            "jobs": [output.job_view(item) for item in actor.jobs],
        }
    if command == "inspect.actor-history":
        entries = queries.get_actor_history(
            run_id,
            selected,
            actor_id,
            position=position,
        )
        return {
            "position": position_data,
            "actor_id": actor_id.value,
            "history": [output.actor_history_entry(item) for item in entries],
        }
    raise AssertionError(f"unhandled command: {command}")


def _map_failure(command: str, error: BaseException) -> CliFailure:
    message = str(error) or "The command failed."
    if isinstance(error, CliFailure):
        return error
    if isinstance(error, CliUsageError):
        return CliFailure("USAGE_ERROR", message)
    if isinstance(error, WorldTemplateNotFoundError):
        return CliFailure("TEMPLATE_NOT_FOUND", message)
    if isinstance(error, WorldTemplateDestinationExistsError):
        return CliFailure("TEMPLATE_DESTINATION_EXISTS", message)
    if isinstance(error, WorldTemplateDestinationError):
        return CliFailure("TEMPLATE_DESTINATION_INVALID", message)
    if isinstance(error, (WorldTemplateIntegrityError, WorldTemplateError)):
        return CliFailure("TEMPLATE_INVALID", message)
    if isinstance(error, RunInitializationRequiredError):
        return CliFailure("RUN_RECOVERY_REQUIRED", message)
    if isinstance(error, WorldSnapshotNotFoundError):
        return CliFailure("WORLD_SNAPSHOT_MISSING", message)
    if isinstance(error, WorldSnapshotIntegrityError):
        return CliFailure("WORLD_SNAPSHOT_INVALID", message)
    if isinstance(error, (WorldPackageError, WorldCompositionError)):
        return CliFailure("WORLD_INVALID", message)
    if isinstance(error, (RunNotFoundError,)) or isinstance(error.__cause__, RunNotFoundError):
        return CliFailure("RUN_NOT_FOUND", message)
    if isinstance(error, QueryNotFoundError):
        if command == "inspect.job":
            return CliFailure("JOB_NOT_FOUND", message)
        if command == "inspect.decision":
            return CliFailure("DECISION_NOT_FOUND", message)
        if command.startswith("inspect.actor"):
            return CliFailure("ACTOR_NOT_FOUND", message)
        return CliFailure("BRANCH_NOT_FOUND", message)
    if isinstance(
        error,
        (VerificationIntegrityError, PersistenceIntegrityError, RuntimeIntegrityError, QueryError),
    ):
        return CliFailure("RUN_INVALID", message)
    if isinstance(error, WorldSnapshotError):
        return CliFailure("WORLD_SNAPSHOT_INVALID", message)
    if isinstance(error, PersistenceError):
        return CliFailure("STORAGE_ERROR", message)
    if isinstance(
        error,
        (
            DecisionOutputError,
            ProviderBindingError,
            UnsupportedRuntimeFrontierError,
            UnsupportedRuntimeStateError,
        ),
    ):
        return CliFailure("RUN_EXECUTION_FAILED", message)
    if command == "branch.create" and isinstance(error, ValueError):
        return CliFailure("BRANCH_INVALID", message)
    if command == "world.validate" and isinstance(error, (TypeError, ValueError)):
        return CliFailure("WORLD_INVALID", message)
    if isinstance(error, OSError):
        return CliFailure("STORAGE_ERROR", message)
    if isinstance(error, (TypeError, ValueError, RuntimeError)):
        return CliFailure("RUN_EXECUTION_FAILED", message)
    return CliFailure("INTERNAL_ERROR", "An unexpected internal error occurred.")


def run_cli(
    argv: Sequence[str],
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    composer: RuntimeComposer | None = None,
) -> int:
    raw = tuple(argv)
    json_requested = "--json" in raw
    parser = _build_parser()
    if json_requested and ("--help" in raw or "-h" in raw):
        output.write_json(
            stdout,
            output.error_document("cli", "USAGE_ERROR", "--json cannot be combined with --help"),
        )
        return 2
    try:
        arguments = parser.parse_args(raw)
    except CliUsageError as error:
        if json_requested:
            output.write_json(
                stdout,
                output.error_document("cli", "USAGE_ERROR", str(error)),
            )
        else:
            parser.print_usage(stderr)
            stderr.write(f"grass: error: {error}\n")
        return 2

    command = cast("str", arguments.command)
    selected_composer = OccurrenceRuntimeComposer() if composer is None else composer
    data_root = Path.cwd() / ".grass" if arguments.data_dir is None else arguments.data_dir
    try:
        applicationless = frozenset(
            {"template.list", "template.show", "template.init", "world.validate"}
        )
        application = (
            None if command in applicationless else _application(data_root, selected_composer)
        )
        data = asyncio.run(_dispatch(arguments, application, selected_composer))
    except KeyboardInterrupt:
        failure = CliFailure("INTERRUPTED", "Command interrupted.")
        if arguments.json_output:
            output.write_json(stdout, output.error_document(command, failure.code, failure.message))
        else:
            stderr.write(f"{failure.code}: {failure.message}\n")
        return 130
    except Exception as error:
        failure = _map_failure(command, error)
        if arguments.json_output:
            output.write_json(stdout, output.error_document(command, failure.code, failure.message))
        else:
            stderr.write(f"{failure.code}: {failure.message}\n")
        return 1

    if arguments.json_output:
        output.write_json(stdout, output.success_document(command, data))
    else:
        output.write_human(stdout, data)
    del stdin  # Reserved for CliHumanDecisionSource composition in actor-capable runtimes.
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(
        sys.argv[1:] if argv is None else argv,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
