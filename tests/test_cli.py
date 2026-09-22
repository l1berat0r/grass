# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import cast

from grass.cli.main import run_cli
from grass.core import (
    BranchId,
    DecisionInvoker,
    EventStore,
    ProviderBindingId,
    SimulationRunConfig,
    WorldDefinition,
)
from grass.core.initialization_events import SIMULATION_INITIALIZED
from grass.persistence import RunId, SimulationRunRecord, SqlitePersistence, WorldMaterialKind
from grass.runtime import RuntimeComposer, RuntimeIdentitySource, SimulationEngine
from grass.worlds import (
    FilesystemWorldSnapshotStore,
    WorldCompositionError,
    load_world_package,
    register_world_package_run,
)
from tests.test_world_packages import write_world_package


def invoke(
    data_root: Path,
    *arguments: str,
    composer: RuntimeComposer | None = None,
) -> tuple[int, dict[str, object], str]:
    stdout = StringIO()
    stderr = StringIO()
    code = run_cli(
        ("--data-dir", str(data_root), "--json", *arguments),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
        composer=composer,
    )
    return code, cast("dict[str, object]", json.loads(stdout.getvalue())), stderr.getvalue()


def register_recoverable_run(
    tmp_path: Path,
) -> tuple[Path, SimulationRunRecord, EventStore]:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    data_root = tmp_path / "data"
    data_root.mkdir()
    persistence = SqlitePersistence(data_root / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(data_root / "world_snapshots")
    record = SimulationRunRecord(
        RunId("recoverable"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.PACKAGE_SNAPSHOT,
        datetime.now(UTC),
    )
    register_world_package_run(
        persistence,
        snapshots,
        record,
        package,
        SimulationRunConfig(package.world_definition.ref),
    )
    return data_root, record, persistence.event_store(record.run_id)


def initialization_event_count(store: EventStore, branch_id: BranchId) -> int:
    return sum(
        event.event_type == SIMULATION_INITIALIZED
        for transition in store.read_transitions(branch_id)
        for event in transition.events
    )


class RejectingComposer:
    def validate(
        self,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        /,
    ) -> None:
        del world_definition, run_config
        raise WorldCompositionError("unsupported test composition")

    def compose(
        self,
        *,
        event_store: EventStore,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        identity_source: RuntimeIdentitySource,
        decision_invokers: Mapping[ProviderBindingId, DecisionInvoker] | None = None,
    ) -> SimulationEngine:
        del event_store, world_definition, run_config, identity_source, decision_invokers
        raise AssertionError("validation must fail before composition")


def test_world_validation_runs_package_and_composer_validation(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)

    code, success, _ = invoke(tmp_path / "data", "world", "validate", str(author))
    rejected_code, rejected, _ = invoke(
        tmp_path / "other-data",
        "world",
        "validate",
        str(author),
        composer=RejectingComposer(),
    )

    assert code == 0
    assert cast(dict[str, object], success["data"])["schema_version"] == 3
    assert not (tmp_path / "data").exists()
    assert rejected_code == 1
    assert cast(dict[str, object], rejected["error"])["code"] == "WORLD_INVALID"


def test_cli_run_branch_inspection_and_verification_workflow(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    data_root = tmp_path / "data"

    create_code, created, _ = invoke(data_root, "run", "create", str(author))
    run_data = cast(dict[str, object], created["data"])
    record = cast(dict[str, object], run_data["run"])
    run_id = cast(str, record["run_id"])
    branch_code, branch, _ = invoke(
        data_root,
        "branch",
        "create",
        run_id,
        "--from",
        "root",
        "--branch-id",
        "before",
    )
    advance_code, advanced, _ = invoke(data_root, "run", "advance", run_id)
    events_code, events, _ = invoke(data_root, "inspect", "events", run_id)
    child_code, child_events, _ = invoke(
        data_root,
        "inspect",
        "events",
        run_id,
        "--branch",
        "before",
    )
    origin_code, origin_events, _ = invoke(
        data_root,
        "inspect",
        "events",
        run_id,
        "--branch",
        "before",
        "--scope",
        "origin",
    )
    verify_code, verified, _ = invoke(data_root, "run", "verify", run_id)

    codes = (
        create_code,
        branch_code,
        advance_code,
        events_code,
        child_code,
        origin_code,
        verify_code,
    )
    assert codes == (0, 0, 0, 0, 0, 0, 0)
    assert cast(dict[str, object], branch["data"])["parent_position"] == run_data["position"]
    advance_result = cast(dict[str, object], cast(dict[str, object], advanced["data"])["result"])
    assert advance_result["stop_reason"] == "QUIESCENT"
    root_transitions = cast(list[object], cast(dict[str, object], events["data"])["transitions"])
    child_transitions = cast(
        list[object], cast(dict[str, object], child_events["data"])["transitions"]
    )
    assert len(root_transitions) == 2
    assert len(child_transitions) == 1
    assert cast(dict[str, object], origin_events["data"])["transitions"] == []
    report = cast(dict[str, object], cast(dict[str, object], verified["data"])["verification"])
    assert report["branch_count"] == 2
    assert report["transition_count"] == 2


def test_read_only_command_surface_handles_empty_execution_and_cognition(
    tmp_path: Path,
) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    data_root = tmp_path / "data"
    _, created, _ = invoke(data_root, "run", "create", str(author))
    run_id = cast(
        str,
        cast(
            dict[str, object],
            cast(dict[str, object], created["data"])["run"],
        )["run_id"],
    )
    commands = (
        ("run", "list"),
        ("run", "status", run_id),
        ("branch", "list", run_id),
        ("inspect", "state", run_id),
        ("inspect", "branches", run_id),
        ("inspect", "jobs", run_id),
        ("inspect", "decisions", run_id),
        ("inspect", "actors", run_id),
        ("inspect", "config", run_id),
        ("inspect", "providers", run_id),
    )

    for command in commands:
        code, document, stderr = invoke(data_root, *command)
        assert code == 0
        assert document["command"] == ".".join(command[:2])
        assert stderr == ""

    _, providers, _ = invoke(data_root, "inspect", "providers", run_id)
    provider_data = cast(
        dict[str, object], cast(dict[str, object], providers["data"])["provider_bindings"]
    )
    assert provider_data == {
        "configured": False,
        "routing": None,
        "decision_bindings": [],
        "model_bindings": [],
    }


def test_status_does_not_recover_implicit_or_explicit_empty_root(tmp_path: Path) -> None:
    data_root, record, store = register_recoverable_run(tmp_path)

    commands = (
        ("run", "status", record.run_id.value),
        ("run", "status", record.run_id.value, "--branch", record.root_branch_id.value),
    )
    for command in commands:
        status_code, status, _ = invoke(data_root, *command)

        assert status_code == 1
        assert cast(dict[str, object], status["error"])["code"] == "RUN_RECOVERY_REQUIRED"
        assert store.read_transitions(record.root_branch_id) == ()


def test_explicit_root_step_recovers_and_does_not_duplicate_initialization(
    tmp_path: Path,
) -> None:
    data_root, record, store = register_recoverable_run(tmp_path)
    command = (
        "run",
        "step",
        record.run_id.value,
        "--branch",
        record.root_branch_id.value,
    )

    step_code, stepped, _ = invoke(data_root, *command)

    assert step_code == 0
    step_data = cast(dict[str, object], stepped["data"])
    result = cast(dict[str, object], step_data["result"])
    assert step_data["branch_id"] == record.root_branch_id.value
    assert result["work_kind"] == "SCENARIO_OCCURRENCE"
    assert result["committed_transition"] is not None
    assert initialization_event_count(store, record.root_branch_id) == 1

    second_code, second, _ = invoke(data_root, *command)
    assert second_code == 0
    second_result = cast(dict[str, object], cast(dict[str, object], second["data"])["result"])
    assert second_result["stop_reason"] == "QUIESCENT"
    assert initialization_event_count(store, record.root_branch_id) == 1


def test_explicit_root_advance_recovers_and_returns_normal_stop(tmp_path: Path) -> None:
    data_root, record, store = register_recoverable_run(tmp_path)

    advance_code, advanced, _ = invoke(
        data_root,
        "run",
        "advance",
        record.run_id.value,
        "--branch",
        record.root_branch_id.value,
    )

    assert advance_code == 0
    advance_data = cast(dict[str, object], advanced["data"])
    result = cast(dict[str, object], advance_data["result"])
    assert advance_data["branch_id"] == record.root_branch_id.value
    assert result["committed_steps"] == 1
    assert result["stop_reason"] == "QUIESCENT"
    assert initialization_event_count(store, record.root_branch_id) == 1


def test_missing_execution_branch_does_not_recover_empty_root(tmp_path: Path) -> None:
    data_root, record, store = register_recoverable_run(tmp_path)

    for operation in ("step", "advance"):
        code, document, _ = invoke(
            data_root,
            "run",
            operation,
            record.run_id.value,
            "--branch",
            "missing",
        )

        assert code == 1
        assert cast(dict[str, object], document["error"])["code"] == "BRANCH_NOT_FOUND"
        assert store.read_transitions(record.root_branch_id) == ()


def test_initialized_implicit_and_explicit_root_advance_are_equivalent(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    results: list[tuple[object, object, object, object]] = []

    for selection in ("implicit", "explicit"):
        data_root = tmp_path / selection
        create_code, created, _ = invoke(data_root, "run", "create", str(author))
        assert create_code == 0
        run_id = cast(
            str,
            cast(
                dict[str, object],
                cast(dict[str, object], created["data"])["run"],
            )["run_id"],
        )
        branch_arguments = () if selection == "implicit" else ("--branch", "root")

        advance_code, advanced, _ = invoke(
            data_root,
            "run",
            "advance",
            run_id,
            *branch_arguments,
        )

        assert advance_code == 0
        advance_data = cast(dict[str, object], advanced["data"])
        result = cast(dict[str, object], advance_data["result"])
        assert advance_data["branch_id"] == "root"
        results.append(
            (
                result["logical_time_ns"],
                result["committed_steps"],
                result["stop_reason"],
                result["waiting_decision_point_ids"],
            )
        )

    assert results[0] == results[1]


def test_run_list_is_best_effort_for_recoverable_and_invalid_runs(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    data_root = tmp_path / "data"
    data_root.mkdir()
    persistence = SqlitePersistence(data_root / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(data_root / "world_snapshots")
    config = SimulationRunConfig(package.world_definition.ref)
    recoverable = SimulationRunRecord(
        RunId("recoverable"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.PACKAGE_SNAPSHOT,
        datetime(2026, 9, 20, 1, tzinfo=UTC),
    )
    invalid = SimulationRunRecord(
        RunId("invalid"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.PACKAGE_SNAPSHOT,
        datetime(2026, 9, 20, 2, tzinfo=UTC),
    )
    register_world_package_run(persistence, snapshots, recoverable, package, config)
    persistence.register_run(invalid, package.world_definition, config)
    healthy_code, healthy, _ = invoke(data_root, "run", "create", str(author))
    assert healthy_code == 0

    code, document, _ = invoke(data_root, "run", "list")

    assert code == 0
    entries = cast(list[dict[str, object]], cast(dict[str, object], document["data"])["runs"])
    health_by_id = {
        cast(str, cast(dict[str, object], item["run"])["run_id"]): item["health"]
        for item in entries
    }
    created_id = cast(
        str,
        cast(
            dict[str, object],
            cast(dict[str, object], healthy["data"])["run"],
        )["run_id"],
    )
    assert health_by_id == {
        "recoverable": "RECOVERABLE",
        "invalid": "INVALID",
        created_id: "OK",
    }


def test_json_usage_and_not_found_errors_have_stable_codes(tmp_path: Path) -> None:
    usage_code, usage, _ = invoke(tmp_path / "data", "run", "advance", "run", "--max-steps", "0")
    missing_code, missing, _ = invoke(tmp_path / "data", "run", "status", "missing")

    assert usage_code == 2
    assert cast(dict[str, object], usage["error"])["code"] == "USAGE_ERROR"
    assert missing_code == 1
    assert cast(dict[str, object], missing["error"])["code"] == "RUN_NOT_FOUND"


def test_missing_branch_is_not_mislabeled_as_missing_projected_value(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    data_root = tmp_path / "data"
    _, created, _ = invoke(data_root, "run", "create", str(author))
    run_id = cast(
        str,
        cast(
            dict[str, object],
            cast(dict[str, object], created["data"])["run"],
        )["run_id"],
    )
    commands = (
        ("run", "step", run_id, "--branch", "missing"),
        ("inspect", "job", run_id, "job", "--branch", "missing"),
        ("inspect", "decision", run_id, "decision", "--branch", "missing"),
        ("inspect", "actor", run_id, "actor", "--branch", "missing"),
    )

    for command in commands:
        code, document, _ = invoke(data_root, *command)
        assert code == 1
        assert cast(dict[str, object], document["error"])["code"] == "BRANCH_NOT_FOUND"


def test_invalid_empty_root_topology_is_not_recoverable_or_initialized(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    data_root = tmp_path / "data"
    data_root.mkdir()
    persistence = SqlitePersistence(data_root / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(data_root / "world_snapshots")
    record = SimulationRunRecord(
        RunId("invalid-topology"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.PACKAGE_SNAPSHOT,
        datetime.now(UTC),
    )
    register_world_package_run(
        persistence,
        snapshots,
        record,
        package,
        SimulationRunConfig(package.world_definition.ref),
    )
    store = persistence.event_store(record.run_id)
    store.create_root_branch(BranchId("extra-root"))

    list_code, listed, _ = invoke(data_root, "run", "list")
    step_code, stepped, _ = invoke(data_root, "run", "step", record.run_id.value)

    assert list_code == 0
    entry = cast(list[dict[str, object]], cast(dict[str, object], listed["data"])["runs"])[0]
    assert entry["health"] == "INVALID"
    assert step_code == 1
    assert cast(dict[str, object], stepped["error"])["code"] == "RUN_INVALID"
    assert store.read_transitions(record.root_branch_id) == ()
