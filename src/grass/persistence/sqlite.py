# SPDX-License-Identifier: GPL-3.0-only

"""SQLite-backed durable local run and canonical Event history storage."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from grass.core.branches import Branch, HistoryPosition
from grass.core.event_store import StaleHistoryError
from grass.core.events import CommittedTransition, Event, TransitionToCommit
from grass.core.identifiers import (
    BranchId,
    CorrelationId,
    EventId,
    TransitionId,
    WorldDefinitionId,
)
from grass.core.logical_time import LogicalTime
from grass.core.references import TransitionRef
from grass.core.world_definitions import (
    SimulationRunConfig,
    WorldDefinition,
    WorldDefinitionRef,
)
from grass.persistence._serialization import (
    RUN_CONFIG_DOCUMENT_VERSION,
    decode_causes,
    decode_datetime,
    decode_provenance,
    decode_run_config,
    decode_structured_mapping,
    decode_world_definition,
    encode_causes,
    encode_datetime,
    encode_provenance,
    encode_run_config,
    encode_structured_mapping,
    encode_world_definition,
)
from grass.persistence.contracts import (
    PersistenceError,
    PersistenceIntegrityError,
    RunId,
    RunNotFoundError,
    SimulationRunRecord,
    UnsupportedStorageVersionError,
)

SQLITE_STORAGE_SCHEMA_VERSION = 1

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE world_definitions (
        world_definition_id TEXT NOT NULL,
        version TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        document_json TEXT NOT NULL,
        PRIMARY KEY (world_definition_id, version)
    )
    """,
    """
    CREATE TABLE simulation_runs (
        run_id TEXT PRIMARY KEY,
        root_branch_id TEXT NOT NULL,
        world_definition_id TEXT NOT NULL,
        world_definition_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (world_definition_id, world_definition_version)
            REFERENCES world_definitions (world_definition_id, version)
    )
    """,
    """
    CREATE TABLE run_configs (
        run_id TEXT PRIMARY KEY,
        schema_version INTEGER NOT NULL,
        document_json TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES simulation_runs (run_id)
    )
    """,
    """
    CREATE TABLE branches (
        run_id TEXT NOT NULL,
        branch_id TEXT NOT NULL,
        parent_branch_id TEXT,
        fork_transition_branch_id TEXT,
        fork_transition_id TEXT,
        PRIMARY KEY (run_id, branch_id),
        FOREIGN KEY (run_id) REFERENCES simulation_runs (run_id),
        FOREIGN KEY (run_id, parent_branch_id)
            REFERENCES branches (run_id, branch_id),
        CHECK (
            (parent_branch_id IS NULL
                AND fork_transition_branch_id IS NULL
                AND fork_transition_id IS NULL)
            OR
            (parent_branch_id IS NOT NULL
                AND fork_transition_branch_id IS NOT NULL
                AND fork_transition_id IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE transitions (
        run_id TEXT NOT NULL,
        branch_id TEXT NOT NULL,
        transition_id TEXT NOT NULL,
        local_ordinal TEXT NOT NULL,
        logical_time TEXT NOT NULL,
        PRIMARY KEY (run_id, branch_id, transition_id),
        UNIQUE (run_id, branch_id, local_ordinal),
        FOREIGN KEY (run_id, branch_id) REFERENCES branches (run_id, branch_id)
    )
    """,
    """
    CREATE TABLE events (
        run_id TEXT NOT NULL,
        branch_id TEXT NOT NULL,
        transition_id TEXT NOT NULL,
        event_offset INTEGER NOT NULL,
        event_id TEXT NOT NULL UNIQUE,
        sequence TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_version TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        causation_refs_json TEXT NOT NULL,
        correlation_id TEXT,
        PRIMARY KEY (run_id, branch_id, transition_id, event_offset),
        UNIQUE (run_id, branch_id, sequence),
        FOREIGN KEY (run_id, branch_id, transition_id)
            REFERENCES transitions (run_id, branch_id, transition_id)
    )
    """,
)


def _rollback(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        connection.rollback()


def _parse_nonnegative_decimal(value: object, description: str) -> int:
    if type(value) is not str or value == "" or not value.isascii() or not value.isdigit():
        raise PersistenceIntegrityError(f"stored {description} is not a canonical decimal")
    if len(value) > 1 and value[0] == "0":
        raise PersistenceIntegrityError(f"stored {description} is not a canonical decimal")
    return int(value)


class SqlitePersistence:
    """One versioned local SQLite database containing one or more simulation runs."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        raw_path = os.fspath(path)
        if type(raw_path) is not str:
            raise TypeError("SQLite path must resolve to a string")
        if raw_path == "":
            raise ValueError("SQLite path must not be empty")
        if raw_path == ":memory:":
            raise ValueError("durable persistence requires a filesystem SQLite path")
        self._path = str(Path(raw_path))
        self._initialize()

    @property
    def path(self) -> str:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        try:
            connection = self._connect()
        except sqlite3.Error as error:
            raise PersistenceError("could not open SQLite persistence") from error
        try:
            connection.execute("BEGIN IMMEDIATE")
            raw_version = connection.execute("PRAGMA user_version").fetchone()
            if raw_version is None:
                raise PersistenceIntegrityError("SQLite did not report a storage schema version")
            version = cast(int, raw_version[0])
            if version == 0:
                existing_tables = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing_tables:
                    raise UnsupportedStorageVersionError(
                        "refusing to initialize an unversioned non-empty SQLite database"
                    )
                for statement in _SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {SQLITE_STORAGE_SCHEMA_VERSION}")
            elif version != SQLITE_STORAGE_SCHEMA_VERSION:
                raise UnsupportedStorageVersionError(
                    f"unsupported SQLite storage schema version: {version}"
                )
            connection.commit()
        except sqlite3.Error as error:
            _rollback(connection)
            raise PersistenceError("could not initialize SQLite persistence") from error
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def register_run(
        self,
        record: SimulationRunRecord,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        /,
    ) -> None:
        if type(record) is not SimulationRunRecord:
            raise TypeError("record must be a SimulationRunRecord")
        if type(world_definition) is not WorldDefinition:
            raise TypeError("world_definition must be a WorldDefinition")
        if type(run_config) is not SimulationRunConfig:
            raise TypeError("run_config must be a SimulationRunConfig")
        if record.world_definition_ref != world_definition.ref:
            raise ValueError("run record must reference the supplied WorldDefinition")
        if run_config.world_definition_ref != world_definition.ref:
            raise ValueError("run config must reference the supplied WorldDefinition")

        definition_json = encode_world_definition(world_definition)
        config_json = encode_run_config(run_config)
        created_at = encode_datetime(record.created_at)
        try:
            connection = self._connect()
        except sqlite3.Error as error:
            raise PersistenceError("could not open SQLite persistence") from error
        try:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM simulation_runs WHERE run_id = ?",
                    (record.run_id.value,),
                ).fetchone()
                is not None
            ):
                raise ValueError("run_id has already been registered")

            existing_definition = connection.execute(
                "SELECT schema_version, document_json FROM world_definitions "
                "WHERE world_definition_id = ? AND version = ?",
                (world_definition.world_definition_id.value, world_definition.version),
            ).fetchone()
            if existing_definition is None:
                connection.execute(
                    "INSERT INTO world_definitions "
                    "(world_definition_id, version, schema_version, document_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        world_definition.world_definition_id.value,
                        world_definition.version,
                        world_definition.schema_version,
                        definition_json,
                    ),
                )
            elif (
                existing_definition["schema_version"] != world_definition.schema_version
                or existing_definition["document_json"] != definition_json
            ):
                raise PersistenceIntegrityError(
                    "WorldDefinitionRef is already associated with different material"
                )

            connection.execute(
                "INSERT INTO simulation_runs "
                "(run_id, root_branch_id, world_definition_id, "
                "world_definition_version, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    record.run_id.value,
                    record.root_branch_id.value,
                    record.world_definition_ref.world_definition_id.value,
                    record.world_definition_ref.version,
                    created_at,
                ),
            )
            connection.execute(
                "INSERT INTO run_configs (run_id, schema_version, document_json) VALUES (?, ?, ?)",
                (record.run_id.value, RUN_CONFIG_DOCUMENT_VERSION, config_json),
            )
            connection.execute(
                "INSERT INTO branches "
                "(run_id, branch_id, parent_branch_id, "
                "fork_transition_branch_id, fork_transition_id) "
                "VALUES (?, ?, NULL, NULL, NULL)",
                (record.run_id.value, record.root_branch_id.value),
            )
            connection.commit()
        except sqlite3.Error as error:
            _rollback(connection)
            raise PersistenceError("could not register simulation run") from error
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def read_run(self, run_id: RunId, /) -> SimulationRunRecord:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT root_branch_id, world_definition_id, "
                    "world_definition_version, created_at "
                    "FROM simulation_runs WHERE run_id = ?",
                    (run_id.value,),
                ).fetchone()
        except sqlite3.Error as error:
            raise PersistenceError("could not read simulation run") from error
        if row is None:
            raise RunNotFoundError(f"simulation run is not registered: {run_id.value}")
        try:
            return SimulationRunRecord(
                run_id,
                BranchId(cast(str, row["root_branch_id"])),
                WorldDefinitionRef(
                    WorldDefinitionId(cast(str, row["world_definition_id"])),
                    cast(str, row["world_definition_version"]),
                ),
                decode_datetime(cast(str, row["created_at"])),
            )
        except (TypeError, ValueError) as error:
            raise PersistenceIntegrityError("stored simulation run is invalid") from error

    def read_world_definition(self, run_id: RunId, /) -> WorldDefinition:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT definitions.world_definition_id, definitions.version, "
                    "definitions.schema_version, definitions.document_json "
                    "FROM simulation_runs AS runs "
                    "JOIN world_definitions AS definitions "
                    "ON definitions.world_definition_id = runs.world_definition_id "
                    "AND definitions.version = runs.world_definition_version "
                    "WHERE runs.run_id = ?",
                    (run_id.value,),
                ).fetchone()
        except sqlite3.Error as error:
            raise PersistenceError("could not read WorldDefinition snapshot") from error
        if row is None:
            if self._run_exists(run_id):
                raise PersistenceIntegrityError("simulation run has no WorldDefinition snapshot")
            raise RunNotFoundError(f"simulation run is not registered: {run_id.value}")
        definition = decode_world_definition(cast(str, row["document_json"]))
        try:
            stored_ref = WorldDefinitionRef(
                WorldDefinitionId(cast(str, row["world_definition_id"])),
                cast(str, row["version"]),
            )
        except (TypeError, ValueError) as error:
            raise PersistenceIntegrityError(
                "stored WorldDefinition repository key is invalid"
            ) from error
        if definition.ref != stored_ref:
            raise PersistenceIntegrityError(
                "stored WorldDefinition identity does not match its repository key"
            )
        if row["schema_version"] != definition.schema_version:
            raise PersistenceIntegrityError(
                "stored WorldDefinition schema metadata does not match its document"
            )
        return definition

    def read_run_config(self, run_id: RunId, /) -> SimulationRunConfig:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT configs.schema_version, configs.document_json, "
                    "runs.world_definition_id, runs.world_definition_version "
                    "FROM run_configs AS configs "
                    "JOIN simulation_runs AS runs ON runs.run_id = configs.run_id "
                    "WHERE configs.run_id = ?",
                    (run_id.value,),
                ).fetchone()
        except sqlite3.Error as error:
            raise PersistenceError("could not read SimulationRunConfig snapshot") from error
        if row is None:
            if self._run_exists(run_id):
                raise PersistenceIntegrityError("simulation run has no configuration snapshot")
            raise RunNotFoundError(f"simulation run is not registered: {run_id.value}")
        if row["schema_version"] != RUN_CONFIG_DOCUMENT_VERSION:
            raise UnsupportedStorageVersionError(
                f"unsupported run config document version: {row['schema_version']}"
            )
        config = decode_run_config(cast(str, row["document_json"]))
        try:
            stored_ref = WorldDefinitionRef(
                WorldDefinitionId(cast(str, row["world_definition_id"])),
                cast(str, row["world_definition_version"]),
            )
        except (TypeError, ValueError) as error:
            raise PersistenceIntegrityError("stored run WorldDefinition key is invalid") from error
        if config.world_definition_ref != stored_ref:
            raise PersistenceIntegrityError(
                "stored run config WorldDefinition identity does not match its run"
            )
        return config

    def _run_exists(self, run_id: RunId) -> bool:
        try:
            with closing(self._connect()) as connection:
                return (
                    connection.execute(
                        "SELECT 1 FROM simulation_runs WHERE run_id = ?", (run_id.value,)
                    ).fetchone()
                    is not None
                )
        except sqlite3.Error as error:
            raise PersistenceError("could not read simulation run") from error

    def event_store(self, run_id: RunId, /) -> SqliteEventStore:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        if not self._run_exists(run_id):
            raise RunNotFoundError(f"simulation run is not registered: {run_id.value}")
        return SqliteEventStore(self._path, run_id)


class SqliteEventStore:
    """Run-scoped SQLite implementation of the canonical EventStore contract."""

    def __init__(self, path: str, run_id: RunId) -> None:
        if type(path) is not str or path == "":
            raise TypeError("path must be a non-empty string")
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        self._path = path
        self._run_id = run_id

    @property
    def run_id(self) -> RunId:
        return self._run_id

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection
        except sqlite3.Error as error:
            raise PersistenceError("could not open SQLite EventStore") from error

    def _require_run(self, connection: sqlite3.Connection) -> None:
        if (
            connection.execute(
                "SELECT 1 FROM simulation_runs WHERE run_id = ?", (self._run_id.value,)
            ).fetchone()
            is None
        ):
            raise RunNotFoundError(f"simulation run is not registered: {self._run_id.value}")

    def _read_branch(self, connection: sqlite3.Connection, branch_id: BranchId) -> Branch:
        row = connection.execute(
            "SELECT parent_branch_id, fork_transition_branch_id, fork_transition_id "
            "FROM branches WHERE run_id = ? AND branch_id = ?",
            (self._run_id.value, branch_id.value),
        ).fetchone()
        if row is None:
            raise ValueError("branch_id has not been registered")
        parent_id = row["parent_branch_id"]
        origin_id = row["fork_transition_branch_id"]
        transition_id = row["fork_transition_id"]
        try:
            if parent_id is None and origin_id is None and transition_id is None:
                return Branch(branch_id)
            fork_values = (parent_id, origin_id, transition_id)
            if not all(type(item) is str and item != "" for item in fork_values):
                raise PersistenceIntegrityError("stored branch fork metadata is incomplete")
            return Branch(
                branch_id,
                HistoryPosition(
                    BranchId(cast(str, parent_id)),
                    TransitionRef(
                        BranchId(cast(str, origin_id)),
                        TransitionId(cast(str, transition_id)),
                    ),
                ),
            )
        except (TypeError, ValueError) as error:
            raise PersistenceIntegrityError("stored branch metadata is invalid") from error

    def create_root_branch(self, branch_id: BranchId) -> Branch:
        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        branch = Branch(branch_id)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_run(connection)
            if (
                connection.execute(
                    "SELECT 1 FROM branches WHERE run_id = ? AND branch_id = ?",
                    (self._run_id.value, branch_id.value),
                ).fetchone()
                is not None
            ):
                raise ValueError("branch_id has already been registered")
            connection.execute(
                "INSERT INTO branches "
                "(run_id, branch_id, parent_branch_id, "
                "fork_transition_branch_id, fork_transition_id) "
                "VALUES (?, ?, NULL, NULL, NULL)",
                (self._run_id.value, branch_id.value),
            )
            connection.commit()
            return branch
        except sqlite3.Error as error:
            _rollback(connection)
            raise PersistenceError("could not create root branch") from error
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def fork_branch(self, branch_id: BranchId, fork_position: HistoryPosition) -> Branch:
        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        if type(fork_position) is not HistoryPosition:
            raise TypeError("fork_position must be a HistoryPosition")
        branch = Branch(branch_id, fork_position)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_run(connection)
            if (
                connection.execute(
                    "SELECT 1 FROM branches WHERE run_id = ? AND branch_id = ?",
                    (self._run_id.value, branch_id.value),
                ).fetchone()
                is not None
            ):
                raise ValueError("branch_id has already been registered")
            self._visible_transitions(connection, fork_position)
            ref = cast(TransitionRef, fork_position.transition_ref)
            connection.execute(
                "INSERT INTO branches "
                "(run_id, branch_id, parent_branch_id, "
                "fork_transition_branch_id, fork_transition_id) VALUES (?, ?, ?, ?, ?)",
                (
                    self._run_id.value,
                    branch_id.value,
                    fork_position.branch_id.value,
                    ref.branch_id.value,
                    ref.transition_id.value,
                ),
            )
            connection.commit()
            return branch
        except sqlite3.Error as error:
            _rollback(connection)
            raise PersistenceError("could not fork branch") from error
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def read_branch(self, branch_id: BranchId) -> Branch:
        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        try:
            with closing(self._connect()) as connection:
                self._require_run(connection)
                return self._read_branch(connection, branch_id)
        except sqlite3.Error as error:
            raise PersistenceError("could not read branch") from error

    def _read_origin_transitions(
        self, connection: sqlite3.Connection, branch_id: BranchId
    ) -> tuple[CommittedTransition, ...]:
        rows = connection.execute(
            "SELECT transition_id, local_ordinal, logical_time FROM transitions "
            "WHERE run_id = ? AND branch_id = ?",
            (self._run_id.value, branch_id.value),
        ).fetchall()
        ordered_rows = sorted(
            rows,
            key=lambda row: _parse_nonnegative_decimal(row["local_ordinal"], "transition ordinal"),
        )
        transitions: list[CommittedTransition] = []
        expected_ordinal = 1
        expected_sequence = 1
        previous_time: LogicalTime | None = None
        for row in ordered_rows:
            ordinal = _parse_nonnegative_decimal(row["local_ordinal"], "transition ordinal")
            if ordinal != expected_ordinal:
                raise PersistenceIntegrityError("stored transition ordinals are not contiguous")
            try:
                transition_id = TransitionId(cast(str, row["transition_id"]))
                logical_time = LogicalTime(
                    _parse_nonnegative_decimal(row["logical_time"], "logical time")
                )
            except (TypeError, ValueError) as error:
                raise PersistenceIntegrityError("stored transition metadata is invalid") from error
            if previous_time is not None and logical_time < previous_time:
                raise PersistenceIntegrityError("stored branch logical time decreases")
            event_rows = connection.execute(
                "SELECT event_offset, event_id, sequence, event_type, event_version, "
                "payload_json, provenance_json, causation_refs_json, correlation_id "
                "FROM events WHERE run_id = ? AND branch_id = ? AND transition_id = ? "
                "ORDER BY event_offset",
                (self._run_id.value, branch_id.value, transition_id.value),
            ).fetchall()
            if not event_rows:
                raise PersistenceIntegrityError("stored transition has no Events")
            events: list[Event] = []
            for expected_offset, event_row in enumerate(event_rows):
                if event_row["event_offset"] != expected_offset:
                    raise PersistenceIntegrityError("stored Event offsets are not contiguous")
                sequence = _parse_nonnegative_decimal(event_row["sequence"], "Event sequence")
                if sequence != expected_sequence:
                    raise PersistenceIntegrityError("stored Event sequences are not contiguous")
                try:
                    correlation_value = event_row["correlation_id"]
                    correlation_id = (
                        None
                        if correlation_value is None
                        else CorrelationId(cast(str, correlation_value))
                    )
                    events.append(
                        Event(
                            EventId(cast(str, event_row["event_id"])),
                            branch_id,
                            sequence,
                            logical_time,
                            transition_id,
                            cast(str, event_row["event_type"]),
                            _parse_nonnegative_decimal(event_row["event_version"], "Event version"),
                            decode_structured_mapping(
                                cast(str, event_row["payload_json"]), "Event payload"
                            ),
                            decode_provenance(cast(str, event_row["provenance_json"])),
                            decode_causes(cast(str, event_row["causation_refs_json"])),
                            correlation_id,
                        )
                    )
                except (TypeError, ValueError) as error:
                    raise PersistenceIntegrityError("stored Event is invalid") from error
                expected_sequence += 1
            try:
                transitions.append(CommittedTransition(tuple(events)))
            except (TypeError, ValueError) as error:
                raise PersistenceIntegrityError("stored transition is invalid") from error
            expected_ordinal += 1
            previous_time = logical_time
        return tuple(transitions)

    def _visible_head(
        self,
        connection: sqlite3.Connection,
        branch_id: BranchId,
        visited: frozenset[BranchId] = frozenset(),
    ) -> tuple[CommittedTransition, ...]:
        if branch_id in visited:
            raise PersistenceIntegrityError("stored branch ancestry contains a cycle")
        branch = self._read_branch(connection, branch_id)
        prefix: tuple[CommittedTransition, ...] = ()
        if branch.fork_position is not None:
            parent_visible = self._visible_head(
                connection,
                branch.fork_position.branch_id,
                visited.union({branch_id}),
            )
            ref = cast(TransitionRef, branch.fork_position.transition_ref)
            for index, transition in enumerate(parent_visible):
                if transition.transition_ref == ref:
                    prefix = parent_visible[: index + 1]
                    break
            else:
                raise PersistenceIntegrityError(
                    "stored branch fork transition is not visible through its parent"
                )
        return prefix + self._read_origin_transitions(connection, branch_id)

    def _visible_transitions(
        self, connection: sqlite3.Connection, position: HistoryPosition
    ) -> tuple[CommittedTransition, ...]:
        self._read_branch(connection, position.branch_id)
        if position.transition_ref is None:
            branch = self._read_branch(connection, position.branch_id)
            if branch.fork_position is not None:
                raise ValueError("an empty position is valid only for a root branch")
            return ()
        visible = self._visible_head(connection, position.branch_id)
        for index, transition in enumerate(visible):
            if transition.transition_ref == position.transition_ref:
                return visible[: index + 1]
        raise ValueError("transition_ref is not visible from branch")

    def _head_position(
        self, connection: sqlite3.Connection, branch_id: BranchId
    ) -> HistoryPosition:
        branch = self._read_branch(connection, branch_id)
        local = self._read_origin_transitions(connection, branch_id)
        if local:
            return HistoryPosition(branch_id, local[-1].transition_ref)
        if branch.fork_position is not None:
            return HistoryPosition(branch_id, branch.fork_position.transition_ref)
        return HistoryPosition(branch_id)

    def head_position(self, branch_id: BranchId) -> HistoryPosition:
        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        try:
            with closing(self._connect()) as connection:
                self._require_run(connection)
                return self._head_position(connection, branch_id)
        except sqlite3.Error as error:
            raise PersistenceError("could not read branch head") from error

    def commit_transition(
        self,
        transition: TransitionToCommit,
        *,
        expected_head: HistoryPosition | None = None,
    ) -> CommittedTransition:
        if type(transition) is not TransitionToCommit:
            raise TypeError("transition must be a TransitionToCommit")
        if expected_head is not None and type(expected_head) is not HistoryPosition:
            raise TypeError("expected_head must be a HistoryPosition or None")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_run(connection)
            branch_id = transition.transition_ref.branch_id
            branch = self._read_branch(connection, branch_id)
            current_head = self._head_position(connection, branch_id)
            if expected_head is not None:
                if expected_head.branch_id != branch_id:
                    raise StaleHistoryError("expected_head branch does not match transition branch")
                if expected_head != current_head:
                    raise StaleHistoryError(
                        "expected_head is not the branch's current visible head"
                    )
            if (
                connection.execute(
                    "SELECT 1 FROM transitions "
                    "WHERE run_id = ? AND branch_id = ? AND transition_id = ?",
                    (
                        self._run_id.value,
                        branch_id.value,
                        transition.transition_ref.transition_id.value,
                    ),
                ).fetchone()
                is not None
            ):
                raise ValueError("transition_ref has already been committed")

            event_ids = tuple(event.event_id for event in transition.events)
            if len(set(event_ids)) != len(event_ids):
                raise ValueError("event_id values must be unique within a transition")
            for event_id in event_ids:
                if (
                    connection.execute(
                        "SELECT 1 FROM events WHERE event_id = ?", (event_id.value,)
                    ).fetchone()
                    is not None
                ):
                    raise ValueError("event_id has already been committed")

            previous = self._read_origin_transitions(connection, branch_id)
            if previous and transition.logical_time < previous[-1].logical_time:
                raise ValueError("logical_time must not decrease within a branch")
            if not previous and branch.fork_position is not None:
                fork_history = self._visible_transitions(connection, branch.fork_position)
                fork_time = fork_history[-1].logical_time
                if transition.logical_time < fork_time:
                    raise ValueError("logical_time must not precede the fork position")

            next_sequence = previous[-1].events[-1].sequence + 1 if previous else 1
            committed = CommittedTransition(
                tuple(
                    Event(
                        record.event_id,
                        branch_id,
                        next_sequence + offset,
                        transition.logical_time,
                        transition.transition_ref.transition_id,
                        record.event_type,
                        record.event_version,
                        record.payload,
                        record.provenance,
                        record.causation_refs,
                        record.correlation_id,
                    )
                    for offset, record in enumerate(transition.events)
                )
            )
            local_ordinal = len(previous) + 1
            connection.execute(
                "INSERT INTO transitions "
                "(run_id, branch_id, transition_id, local_ordinal, logical_time) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    self._run_id.value,
                    branch_id.value,
                    transition.transition_ref.transition_id.value,
                    str(local_ordinal),
                    str(transition.logical_time.nanoseconds_from_origin),
                ),
            )
            for offset, event in enumerate(committed.events):
                connection.execute(
                    "INSERT INTO events "
                    "(run_id, branch_id, transition_id, event_offset, event_id, sequence, "
                    "event_type, event_version, payload_json, provenance_json, "
                    "causation_refs_json, correlation_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._run_id.value,
                        branch_id.value,
                        transition.transition_ref.transition_id.value,
                        offset,
                        event.event_id.value,
                        str(event.sequence),
                        event.event_type,
                        str(event.event_version),
                        encode_structured_mapping(event.payload),
                        encode_provenance(event.provenance),
                        encode_causes(event.causation_refs),
                        None if event.correlation_id is None else event.correlation_id.value,
                    ),
                )
            connection.commit()
            return committed
        except sqlite3.Error as error:
            _rollback(connection)
            raise PersistenceError("could not commit transition atomically") from error
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def read_transitions(self, branch_id: BranchId) -> tuple[CommittedTransition, ...]:
        if type(branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        try:
            with closing(self._connect()) as connection:
                self._require_run(connection)
                self._read_branch(connection, branch_id)
                return self._read_origin_transitions(connection, branch_id)
        except sqlite3.Error as error:
            raise PersistenceError("could not read branch transitions") from error

    def read_visible_transitions(
        self, position: HistoryPosition
    ) -> tuple[CommittedTransition, ...]:
        if type(position) is not HistoryPosition:
            raise TypeError("position must be a HistoryPosition")
        try:
            with closing(self._connect()) as connection:
                self._require_run(connection)
                return self._visible_transitions(connection, position)
        except sqlite3.Error as error:
            raise PersistenceError("could not read visible transitions") from error
