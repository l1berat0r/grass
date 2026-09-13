# ADR-0020: SQLite local persistence baseline

- Status: Accepted
- Date: 2026-09-13

## Context

A usable local GRASS 0.1 must survive process termination between commands such as run creation, advancement, inspection, branching, and verification. The current in-memory EventStore is appropriate for tests and transient execution but cannot provide this workflow.

The long-term persistence technology should not be chosen prematurely before several real runs reveal Event volume, query patterns, actor-memory needs, and derived-read-model requirements.

## Decision

Introduce explicit persistence abstractions and use SQLite as the first durable local implementation for GRASS 0.1.

SQLite is an implementation baseline, not a permanent architectural commitment.

### Durable responsibilities

The local persistence layer must durably store at least:

- simulation run identity and operational metadata;
- branch metadata;
- canonical committed transitions and Events;
- exact WorldDefinition material associated with a run;
- referenced material GEL/world-package content required for continuation and reproducibility;
- non-secret SimulationRunConfig/provider-routing configuration.

Persistence contracts should distinguish responsibilities such as EventStore, RunRepository, and WorldDefinition/WorldPackage snapshot storage even when the first implementation shares one SQLite database.

### Canonical versus derived data

Canonical history remains committed Event history.

The following remain rebuildable/derived by default and must not become independent sources of truth merely for convenience:

- SimulationState projections;
- ScheduledResolution indexes;
- ActorView/query DTOs;
- query caches;
- other indexes/read models that can be rebuilt from canonical persisted data.

Checkpoints, materialized projections, or derived indexes may be added later as optimizations without changing canonical semantics.

### Atomicity

SQLite transition persistence must preserve the existing atomic transition commit contract using database transactions. Partial transition visibility is not allowed.

### Local database

A local installation may use one database such as `.grass/grass.db`. Exact path/configuration is deployment/application behavior rather than simulation semantics.

### Secrets

Provider credentials, bearer tokens, API keys, cookies, and similar secrets are not run configuration and must not be persisted in the canonical local run database by this design.

### Time

Operational wall-clock metadata may be persisted for administration, but remains explicitly distinct from simulation LogicalTime.

### Evolution

Persistence/schema versioning and migrations must be possible. Future storage implementations such as PostgreSQL, other local stores, derived read stores, or distributed persistence must be able to implement the same semantic contracts without changing engine authority, replay, or branching semantics.

## Consequences

- CLI commands can run in separate processes and reopen the same simulation;
- local v0.1 can be exercised with real multi-run datasets;
- SQLite keeps deployment simple and is available through Python's standard library;
- storage remains replaceable once real evidence justifies another backend;
- event-sourcing/replay semantics remain independent from database technology.

## Deferred details

- exact SQL schema/indexes;
- exact migration framework;
- checkpoint/materialized projection strategy;
- retention/archival/compaction policies;
- multi-process writer policy beyond preserving commit correctness;
- PostgreSQL/distributed persistence;
- final actor-memory persistence once the memory model is designed.

## Alternatives considered

### Keep local 0.1 in-memory only

Rejected because ordinary CLI workflows would lose runs whenever the process exits.

### Commit to PostgreSQL immediately

Rejected because it adds operational complexity before actual run/query characteristics justify it.

### Persist SimulationState as canonical state

Rejected because it would weaken the accepted Event-history authority/replay model and create competing truth.
