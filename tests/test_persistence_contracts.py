# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from grass.core import (
    BranchId,
    DecisionProviderBinding,
    DecisionProviderRouting,
    EntityId,
    ModelProviderBinding,
    ModelProviderBindingId,
    ProviderBindingConfiguration,
    ProviderBindingId,
    ProviderExecutionLocation,
    SimulationRunConfig,
    WorldDefinition,
    load_world_definition,
)
from grass.persistence import (
    PersistenceError,
    PersistenceIntegrityError,
    RunConfigSnapshotRepository,
    RunId,
    RunNotFoundError,
    RunRepository,
    SimulationRunRecord,
    SqlitePersistence,
    UnsupportedStorageVersionError,
    WorldDefinitionSnapshotRepository,
)


def _world(*, schema_version: int = 2, metadata_value: str = "original") -> WorldDefinition:
    document: dict[str, object] = {
        "world_definition_id": "world",
        "version": "1.0",
        "schema_version": schema_version,
        "vocabulary": {
            "entity_types": ["Location", "Person"],
            "relation_types": ["knows"],
            "resource_types": ["capacity"],
            "state_variable_types": ["details"],
        },
        "initial_conditions": {
            "logical_time": 10**30,
            "entities": [
                {
                    "entity_id": "alice",
                    "entity_type": "Person",
                    "properties": {"name": "Alice", "nested": [True, None, 10**40]},
                },
                {"entity_id": "office", "entity_type": "Location", "properties": {}},
            ],
            "relations": [
                {
                    "relation_id": "alice-knows-office",
                    "relation_type": "knows",
                    "participants": [
                        {"role": "place", "entity_id": "office"},
                        {"role": "person", "entity_id": "alice"},
                    ],
                    "properties": {"confidence": 0.5},
                }
            ],
            "resources": [{"entity_id": "office", "resource_type": "capacity", "quantity": 10**35}],
            "state_variables": [
                {
                    "scope": {"kind": "ENTITY", "entity_id": "alice"},
                    "state_variable_type": "details",
                    "value": {"mood": "focused", "scores": [1, 2, 3]},
                }
            ],
        },
        "metadata": {"value": metadata_value, "negative_zero": -0.0},
    }
    if schema_version == 2:
        document["scenario_event_rules"] = [
            {
                "rule_id": "later",
                "trigger": {"kind": "AT_TIME", "logical_time": 10**30 + 5},
            }
        ]
    return load_world_definition(document)


def _config(world: WorldDefinition) -> SimulationRunConfig:
    model_id = ModelProviderBindingId("model")
    default_id = ProviderBindingId("default")
    group_id = ProviderBindingId("group")
    actor_id = ProviderBindingId("actor")
    models = {model_id: ModelProviderBinding(model_id, "openai", "gpt-test")}
    decisions = {
        default_id: DecisionProviderBinding(
            default_id,
            "model-adapter",
            ProviderExecutionLocation.SERVER_MANAGED,
            model_id,
        ),
        group_id: DecisionProviderBinding(
            group_id,
            "human-adapter",
            ProviderExecutionLocation.CLIENT_MANAGED,
        ),
        actor_id: DecisionProviderBinding(
            actor_id,
            "scripted-adapter",
            ProviderExecutionLocation.SERVER_MANAGED,
        ),
    }
    routing = DecisionProviderRouting(
        default_id,
        {"operators": group_id},
        {EntityId("bob"): "operators"},
        {EntityId("alice"): actor_id},
    )
    return SimulationRunConfig(
        world.ref,
        ProviderBindingConfiguration(routing, decisions, models),
    )


def _record(world: WorldDefinition, run_id: str = "run") -> SimulationRunRecord:
    offset = timezone(timedelta(hours=5, minutes=30))
    return SimulationRunRecord(
        RunId(run_id),
        BranchId("root"),
        world.ref,
        datetime(2026, 9, 14, 12, 30, 45, 123456, tzinfo=offset),
    )


def test_run_value_objects_are_strict_and_wall_time_is_normalized() -> None:
    world = _world()
    record = _record(world)

    assert record.created_at.tzinfo is UTC
    assert record.created_at == datetime(2026, 9, 14, 7, 0, 45, 123456, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        SimulationRunRecord(
            RunId("run"),
            BranchId("root"),
            world.ref,
            datetime(2026, 9, 14),
        )
    with pytest.raises(ValueError, match="must not be empty"):
        RunId("")


@pytest.mark.parametrize("schema_version", [1, 2])
def test_run_definition_and_non_secret_config_survive_reopen(
    tmp_path: Path, schema_version: int
) -> None:
    path = tmp_path / f"schema-{schema_version}.db"
    world = _world(schema_version=schema_version)
    config = _config(world)
    record = _record(world)
    persistence = SqlitePersistence(path)

    run_repository: RunRepository = persistence
    definition_repository: WorldDefinitionSnapshotRepository = persistence
    config_repository: RunConfigSnapshotRepository = persistence
    run_repository.register_run(record, world, config)

    reopened = SqlitePersistence(path)
    assert reopened.read_run(record.run_id) == record
    assert definition_repository.read_world_definition(record.run_id) == world
    assert config_repository.read_run_config(record.run_id) == config
    assert reopened.read_world_definition(record.run_id) == world
    assert reopened.read_run_config(record.run_id) == config
    root_branch = reopened.event_store(record.run_id).read_branch(record.root_branch_id)
    assert root_branch.fork_position is None

    with sqlite3.connect(path) as connection:
        config_json = connection.execute(
            "SELECT document_json FROM run_configs WHERE run_id = ?", (record.run_id.value,)
        ).fetchone()[0]
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    config_document = json.loads(config_json)
    assert set(config_document) == {
        "schema_version",
        "world_definition_ref",
        "provider_bindings",
    }
    assert set(config_document["provider_bindings"]) == {
        "routing",
        "decision_bindings",
        "model_bindings",
    }
    assert all(
        set(binding) == {"binding_id", "invoker_ref", "execution_location", "model_binding_id"}
        for binding in config_document["provider_bindings"]["decision_bindings"]
    )
    assert all(
        set(binding) == {"binding_id", "provider_ref", "model"}
        for binding in config_document["provider_bindings"]["model_bindings"]
    )
    assert table_names == {
        "world_definitions",
        "simulation_runs",
        "run_configs",
        "branches",
        "transitions",
        "events",
    }


def test_definition_identity_is_immutable_and_failed_registration_is_atomic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.db"
    original = _world()
    persistence = SqlitePersistence(path)
    persistence.register_run(_record(original, "one"), original, _config(original))
    changed = _world(metadata_value="changed")

    with pytest.raises(PersistenceIntegrityError, match="different material"):
        persistence.register_run(_record(changed, "two"), changed, _config(changed))

    with pytest.raises(RunNotFoundError):
        persistence.read_run(RunId("two"))

    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_root BEFORE INSERT ON branches "
            "WHEN NEW.run_id = 'three' BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    third = load_world_definition(
        {
            **_world_document_for_distinct_ref(),
            "world_definition_id": "other-world",
        }
    )
    with pytest.raises(PersistenceError, match="register simulation run"):
        persistence.register_run(_record(third, "three"), third, SimulationRunConfig(third.ref))
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM world_definitions WHERE world_definition_id = 'other-world'"
            ).fetchone()
            is None
        )
        assert (
            connection.execute("SELECT 1 FROM simulation_runs WHERE run_id = 'three'").fetchone()
            is None
        )


def _world_document_for_distinct_ref() -> dict[str, object]:
    return {
        "world_definition_id": "placeholder",
        "version": "1.0",
        "schema_version": 1,
        "vocabulary": {
            "entity_types": [],
            "relation_types": [],
            "resource_types": [],
            "state_variable_types": [],
        },
        "initial_conditions": {
            "logical_time": 0,
            "entities": [],
            "relations": [],
            "resources": [],
            "state_variables": [],
        },
        "metadata": {},
    }


def test_storage_and_run_config_versions_fail_explicitly(tmp_path: Path) -> None:
    future_path = tmp_path / "future.db"
    with sqlite3.connect(future_path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(UnsupportedStorageVersionError, match="schema version: 99"):
        SqlitePersistence(future_path)

    path = tmp_path / "config.db"
    world = _world()
    persistence = SqlitePersistence(path)
    persistence.register_run(_record(world), world, _config(world))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE run_configs SET schema_version = 99")
    with pytest.raises(UnsupportedStorageVersionError, match="document version: 99"):
        persistence.read_run_config(RunId("run"))


def test_snapshot_identity_and_future_definition_version_corruption_fail(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.db"
    world = _world()
    persistence = SqlitePersistence(path)
    persistence.register_run(_record(world), world, _config(world))
    with sqlite3.connect(path) as connection:
        raw_definition = connection.execute(
            "SELECT document_json FROM world_definitions"
        ).fetchone()[0]
        definition_document = json.loads(raw_definition)
        definition_document["world_definition_id"] = "wrong"
        connection.execute(
            "UPDATE world_definitions SET document_json = ?",
            (json.dumps(definition_document),),
        )
    with pytest.raises(PersistenceIntegrityError, match="repository key"):
        persistence.read_world_definition(RunId("run"))

    with sqlite3.connect(path) as connection:
        definition_document["world_definition_id"] = "world"
        definition_document["schema_version"] = 99
        connection.execute(
            "UPDATE world_definitions SET schema_version = 99, document_json = ?",
            (json.dumps(definition_document),),
        )
    with pytest.raises(
        UnsupportedStorageVersionError,
        match="WorldDefinition document version: 99",
    ):
        persistence.read_world_definition(RunId("run"))

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE world_definitions SET world_definition_id = '', "
            "schema_version = 1, document_json = ?",
            (raw_definition,),
        )
        connection.execute(
            "UPDATE simulation_runs SET world_definition_id = '' WHERE run_id = 'run'"
        )
    with pytest.raises(PersistenceIntegrityError, match="repository key is invalid"):
        persistence.read_world_definition(RunId("run"))

    config_path = tmp_path / "corrupt-config.db"
    config_persistence = SqlitePersistence(config_path)
    config_persistence.register_run(_record(world), world, _config(world))
    with sqlite3.connect(config_path) as connection:
        raw_config = connection.execute("SELECT document_json FROM run_configs").fetchone()[0]
        config_document = json.loads(raw_config)
        config_document["world_definition_ref"]["world_definition_id"] = "wrong"
        connection.execute(
            "UPDATE run_configs SET document_json = ?", (json.dumps(config_document),)
        )
    with pytest.raises(PersistenceIntegrityError, match="does not match its run"):
        config_persistence.read_run_config(RunId("run"))

    with sqlite3.connect(config_path) as connection:
        connection.execute(
            "UPDATE simulation_runs SET world_definition_id = '' WHERE run_id = 'run'"
        )
    with pytest.raises(PersistenceIntegrityError, match="run WorldDefinition key is invalid"):
        config_persistence.read_run_config(RunId("run"))
