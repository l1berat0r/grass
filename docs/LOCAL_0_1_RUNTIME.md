# Local GRASS 0.1 Runtime

## Purpose

The local 0.1 work proves usable simulator capabilities without requiring the user to add Python code to GRASS itself.

The work is intentionally local-first. Slices 12 through 17 prove runtime orchestration, persistence, occurrence-only world composition, branching, replay, inspection, and template authoring workflows before committing to a backend/frontend architecture or a final actor-memory model. Actor-capable ordinary worlds remain a separate milestone.

Slices 0–17 are complete. The next activity is the Diagnostics Architecture checkpoint described in `ROADMAP.md`; actor-capable WorldPackage composition follows only after its Slice-18 architecture is accepted.

## Architectural boundary

The intended direction is:

```text
CLI / future HTTP / future UI
        |
        v
Application API / Query API
        |
        v
Simulation runtime / engine coordinator
        |
        +----------------+----------------+----------------+
        |                |                |                |
        v                v                v                v
     core           persistence        providers      world composition
```

The runtime/application layers do not replace core contracts. They coordinate them.

The central invariant remains:

> Only the simulation engine commits reality.

A client may request a command such as create-run, step, advance, or create-branch. It must not gain direct authority to mutate projections, scheduler state, or canonical history.

## Runtime orchestration

The production `SimulationEngine` combines the core contracts for replay, scheduling, world resolution, cognition, provider invocation, validation, and atomic commit into one executable runtime.

Conceptually:

```text
SimulationEngine
    reconstruct current branch state/history
    determine actionable work at the current frontier
    progress eligible Plan/PlanStep/Job work
    derive observations/DecisionPoints where required
    acquire provider/human decisions
    validate and materialize accepted Decisions/Plans
    rebuild/maintain ephemeral scheduler candidates
    resolve due Jobs and scenario occurrences
    validate candidate effects/transitions
    commit through EventStore
    repeat according to the requested execution mode
```

External provider latency has no simulation-time meaning.

### `step`

`step` commits at most one authoritative transition and returns control to the caller. If it does not commit, it returns one explicit no-commit stop result. It is a precise execution/debugging primitive with deterministic frontier selection rules.

### Stabilizing one logical-time frontier

One committed Event may create additional immediately actionable work at the same `LogicalTime`, for example:

```text
Job resolution
    -> Observation
    -> DecisionPoint
    -> Decision
    -> Plan
    -> eligible PlanStep
    -> Job
```

`advance` stabilizes this frontier by repeatedly calling `step`. Multiple consecutive transitions may therefore share one `LogicalTime`; one runtime step is not necessarily a time jump.

Current-frontier priority is automatic perception, pending decisions, ready PlanStep/Job starts, then scheduler/scenario work. A subject Plan DecisionPoint blocks only its Plan lineage, while a subjectless DecisionPoint blocks new work for that actor. More than one pending DecisionPoint for one actor is unsupported and automatic perception is rejected before commit if it would create that state. ADR-0022 records the complete implemented frontier semantics.

### `advance`

`advance` repeatedly performs engine work until an explicit stop condition is satisfied.

The implemented no-commit stop reasons are:

- quiescent / no more material work;
- waiting for an external/human decision;
- target logical time;
- step/operation budget.

Provider, configuration, unsupported-state, and integrity failures remain typed exceptions rather than normal stop results. The scheduler remains event-driven, and `advance` does not introduce a hidden global tick.

The resolved provider binding in `SimulationRunConfig` controls decision execution. `SERVER_MANAGED` bindings require and invoke a configured `DecisionInvoker`. `CLIENT_MANAGED` bindings do not invoke an engine-local invoker and produce `WAITING_FOR_DECISION`. Because this execution location is persisted with run configuration, reopen preserves the same behavior without a second runtime flag.

## Run identity and lifecycle

A concrete simulation experiment needs application-level identity separate from modeled world state.

Conceptually:

```text
SimulationRun
    run_id
    world_definition_ref
    run_config
    root_branch_id
    operational metadata
```

Run identity/metadata is not a new source of modeled world truth. Wall-clock metadata such as creation time is operational data and must not be confused with `LogicalTime`.

A run must retain or be able to recover the exact material world definition/package inputs used for execution so that continuation/replay does not depend on mutable files on disk.

`SimulationRunRecord.world_material_kind` explicitly distinguishes definition-only runs
from package-backed runs. Reopen follows that persisted discriminator and never infers
semantics from snapshot-path presence. Normal Application creation allocates a canonical
UUID RunId. Registration followed by an empty root is a recoverable internal state;
opening the run idempotently commits exact genesis or validates genesis already present.

## Persistence baseline

Local 0.1 uses SQLite through storage abstractions, not by embedding SQLite semantics into the core domain model.

Slice 13 implements these durable responsibilities:

```text
RunRepository
EventStore
WorldDefinition and SimulationRunConfig snapshot storage
```

`SqlitePersistence` uses one versioned SQLite database at a caller-supplied filesystem path. Choosing an application default such as `.grass/grass.db` remains application behavior.

Canonical/durable data includes at least:

- run identity and operational metadata;
- branch metadata;
- committed transitions and Events;
- exact WorldDefinition material associated with a run;
- non-secret SimulationRunConfig/provider-routing configuration.

Slice 14 stores each package-backed run's exact declared authored material under
`world_snapshots/<run_id>/`. Snapshot publication precedes SQLite registration, while
SQLite retains the canonical semantic WorldDefinition, including resolved GEL source,
schema, and language version. Reopen validates that the filesystem snapshot reconstructs
the same definition and never falls back to mutable author files.

Derived/rebuildable data should not become canonical merely for convenience. This includes, by default:

- `SimulationState` snapshots/projections;
- `ScheduledResolutionIndex`;
- actor/query views;
- query caches and indexes that can be rebuilt.

Checkpoints or derived indexes may be introduced later as optimizations without changing canonical history semantics.

SQLite is a local 0.1 implementation choice. Future evidence from real runs may justify Postgres, other local stores, derived read stores, or distributed persistence without changing engine authority/replay semantics.

## Application API

The Application API represents commands/use cases. It is the write-side surface for CLI and future clients.

The implemented operations are:

```text
create_run(...)
open_run(...)
step(...)
advance(...)
create_branch(...)
verify_run(...)
```

Application commands may result in authoritative changes only through the runtime/engine and existing validated transition + EventStore commit path.

`OpenedRun` is an opaque handle. It does not expose mutable `SimulationState`, a
write-capable EventStore, `SimulationEngine`, or lower-level shortcuts that let a client
construct arbitrary authoritative Events. Branch creation requires an exact committed
`HistoryPosition`, not a symbolic fork-at-head request.

Runtime construction is replaceable through the trusted `RuntimeComposer` boundary.
The default `OccurrenceRuntimeComposer` composes the Slice-14 occurrence-only subset;
other installed composers can supply cognition, Job, and provider components without
changing the Application API.

## Query API

The Query API is read-only and optimized for useful inspection rather than mirroring internal class boundaries.

Every branch-dependent query captures one exact head or accepts one exact historical
position, then returns that position with its immutable view. Visible history includes
ancestry; branch-origin history includes only transitions committed on the viewed branch.
Branch views report topology, exact position, and visible/origin transition counts.

Run/world queries:

```text
list_runs()
get_run(...)
get_status(...)
get_state(...)
get_history(...)
list_branches(...)
```

Execution/cognition queries:

```text
get_jobs(...)
get_job(...)
get_decisions(...)
get_decision(...)
```

Actor-oriented queries:

```text
get_actors(...)
get_actor(...)
get_actor_observations(...)
get_actor_decisions(...)
get_actor_plans(...)
get_actor_jobs(...)
get_actor_history(...)
```

Query APIs may assemble read DTOs from `WorldState`, `ExecutionState`, `CognitionState`, provenance, and history.

For example, an `ActorView` may include:

```text
ActorView
    identity / Entity properties
    relevant relationships/resources
    provider/routing information
    current/pending observations and DecisionPoints
    Decisions
    active/relevant Plans and Jobs
    cognition/memory summary that is already authoritative/available
```

This query view is not a new authoritative Actor aggregate and must not freeze the future actor-memory/retrieval model prematurely.

The provisional actor set is exactly the union of actor identifiers in Plans,
Observations, and DecisionPoints. Actor history is mechanically attributed through
cognition, Plans, Jobs, and Job resolution. A matching Event selects its complete atomic
transition; Event sequence is not treated as causality.

## Runtime status

The implemented derived status set is:

```text
READY
WAITING_FOR_DECISION
QUIESCENT
```

These values are derived from authoritative history/state plus explicit runtime and
external-input conditions, not stored as independent mutable truth. Inspection does not
invoke providers, resolvers, GEL, randomness, identity allocation, commits, or logical-time
advancement. Independent future scheduler work is `READY` before a client-managed wait.

Verification is likewise read-only. It validates exact run material, branch topology,
genesis, branch histories, identity uniqueness, and replay at every branch head. Static
package/GEL validation is allowed, but mechanics and provider/resolver code are not run.

## CLI

The CLI is the first permanent client of the Application and Query APIs and remains useful after future HTTP/UI layers exist.

The implemented command families are:

```text
grass template list
grass template show NAME
grass template init NAME DESTINATION

grass world validate WORLD

grass run create WORLD
grass run list
grass run status RUN [--branch BRANCH]
grass run step RUN [--branch BRANCH] [--target-time-ns N]
grass run advance RUN [--branch BRANCH] [--target-time-ns N] [--max-steps N]
grass run verify RUN

grass branch list RUN
grass branch create RUN --from PARENT --branch-id CHILD

grass inspect state RUN
grass inspect events RUN
grass inspect branches RUN
grass inspect jobs RUN
grass inspect job RUN JOB
grass inspect decisions RUN
grass inspect decision RUN DECISION

grass inspect actors RUN
grass inspect actor RUN ACTOR
grass inspect actor-observations RUN ACTOR
grass inspect actor-decisions RUN ACTOR
grass inspect actor-plans RUN ACTOR
grass inspect actor-jobs RUN ACTOR
grass inspect actor-history RUN ACTOR
```

CLI requirements:

- human-readable output for interactive use;
- stable JSON output for scripts/diagnostics;
- no direct Event insertion or projection mutation;
- no direct write-capable EventStore access;
- a CLI-backed `HumanDecisionSource` for human-controlled actors, still routed through Slice-11 `DecisionInvoker`/validation/provenance semantics;
- process restart between commands must not lose local runs.

The default data root is exactly `.grass` under the current working directory,
with `grass.db` and `world_snapshots/` beneath it. `--data-dir` replaces that
root. RunIds are Application-generated UUIDs; Slice 16 has no friendly aliases.
JSON schema v1 uses one success or failure envelope on stdout, explicit
deterministic serializers, integer-nanosecond logical times, complete atomic
transition groups, and full Event provenance. See `docs/CLI.md` for the exact
command, output, error, and lifecycle contracts.

`run status` is read-only. A registered empty root is reported as requiring
recovery, while `run step` and `run advance` may perform normal idempotent
genesis recovery through `open_run`. Branch creation captures one exact parent
position before requesting the child through `OpenedRun`.

The production CLI uses the occurrence-only composer and default provider-free
`SimulationRunConfig`. `CliHumanDecisionSource` is implemented and tested with
an injected actor-capable composer, but ordinary authored packages cannot yet
configure interactive actor execution.

## Runnable user-defined worlds

A central local 0.1 acceptance criterion is:

> A user can create or edit a simple WorldDefinition and run it without adding Python code to GRASS.

A runnable world composes:

```text
WorldDefinition
    + built-in mechanics
    + GEL mechanics
    + scenario rules
    + provider bindings
    -> trusted runtime composition
    -> existing provider/resolution/validation contracts
```

Ordinary world definitions should not contain arbitrary Python import/class references. This keeps normal scenario authoring data-driven and preserves trust boundaries.

Trusted installed `IMPLEMENTATION` mechanics/plugins may remain an advanced future/extension capability, but they are not required to make ordinary local 0.1 worlds useful.

## WorldDefinition versus WorldPackage

`WorldDefinition` is the immutable semantic definition of a world/version.

A practical authored world may need multiple files. `WorldPackage` is therefore a delivery/container concept, not a replacement domain aggregate.

Example:

```text
my-world/
    world.json
    mechanics/
        stress.gel
        negotiation.gel
    prompts/
        actor.txt
    README.md
```

Package format 1 uses a strict `package.json` that references `world.json`. Authored GEL
uses contained relative `source_file` references. Loading resolves those files into the
canonical `GelProgram` retained by WorldDefinition schema version 3. The important
architectural distinction remains:

```text
WorldPackage = authored/distributed files required to construct a runnable world
WorldDefinition = immutable semantic world definition consumed by GRASS
```

Material referenced content must be captured/snapshotted sufficiently for continuation and reproducibility of a run.

Slice 14's first runnable mechanic is an AT_TIME rule-bound
`SET_STATE_VARIABLE`. It supports a BUILTIN constant setter and a GEL program receiving
only `current_value` and returning only `new_value`; trusted code constructs the existing
`SetStateVariableEffect`. This occurrence-only slice adds no actor bootstrap, perception,
Job mechanics, random streams, plugins, or generic effect language.

## Templates

Templates are ordinary valid WorldPackages. They must not use a privileged hidden execution path.

Expected CLI workflows:

```text
grass template list
grass template show occurrence-counter
grass template init occurrence-counter ./my-world
```

Slice 17 uses a fixed trusted registry and file inventory and ships
`occurrence-counter`, an occurrence-only GEL StateVariable example. Initialization copies
an editable package, rewrites its WorldDefinition identity to the destination basename,
and validates it through the normal package loader and production composer. It does not
construct `.grass`, SQLite, EventStore, or Application infrastructure.

Templates serve three purposes simultaneously:

1. authoring starting points;
2. runnable documentation/examples;
3. high-level acceptance/regression worlds for their supported production runtime path.

ADR-0021's actor interaction, team/social, and shared-resource conflict examples remain
the eventual local template set. They move to Slice 18 or later because ordinary authored
worlds cannot yet declare/bootstrap actors, configure perception/provider execution, or
participate in Plans/Jobs and resource conflict semantics.

## Local 0.1 acceptance workflow

A representative successful workflow is:

```text
grass template init occurrence-counter ./demo
grass world validate ./demo

grass run create ./demo
# Retain the generated UUID as RUN.
grass branch create RUN --from root --branch-id alternative
grass run advance RUN
grass run advance RUN --branch alternative

grass inspect state RUN
grass inspect events RUN

grass run verify RUN
```

The user may close the process and continue later. The run remains available through local persistence.

Actor-capable ordinary package and provider authoring remains Slice 18 architecture work.

## Deliberately deferred until after practical local runs

The local milestone is intended to generate evidence before freezing the next architecture sequence.

After several real runs, review:

- actual Event/run/database size and access patterns;
- which actor-oriented queries are useful;
- provider token/context/cost behavior;
- whether actor memory requires episodic/semantic/retrieval/compaction concepts and which parts are authoritative;
- whether SQLite remains adequate and which derived indexes/read models are justified;
- world-authoring ergonomics and validation failures;
- which inspection/observer capabilities are most useful;
- whether HTTP/backend/frontend is the highest-value next step.

The frontend is therefore not part of the local 0.1 acceptance definition and is intentionally not assumed to be the immediate next slice.
