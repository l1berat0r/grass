# Local GRASS 0.1 Runtime

## Purpose

The local 0.1 milestone is the first version of GRASS that should be usable as a complete simulator without requiring the user to add Python code to GRASS itself.

The milestone is intentionally local-first. Its purpose is to prove runtime orchestration, persistence, world composition, actor/provider execution, branching, replay, inspection, and authoring workflows before committing to a backend/frontend architecture or a final actor-memory model.

The milestone spans Slices 12–17 in `ROADMAP.md`.

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

The current core exposes the contracts required for replay, scheduling, world resolution, cognition, provider invocation, validation, and atomic commit. A production runtime coordinator must combine them into one executable system.

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

`step` performs one bounded authoritative engine unit and returns control to the caller. It is primarily a precise execution/debugging primitive and must have deterministic selection/order rules for simultaneous work.

The exact unit may be a committed transition or another narrowly defined engine unit where one command cannot safely be represented by one transition, but its semantics must remain explicit and testable.

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

The engine therefore needs a notion of stabilizing the current frontier rather than equating every engine reaction with a logical-time jump.

### `advance`

`advance` repeatedly performs engine work until an explicit stop condition is satisfied.

Useful stop conditions include:

- quiescent / no more material work;
- waiting for an external/human decision;
- simulation termination rule;
- failure/integrity failure;
- target logical time;
- step/operation budget.

The scheduler remains event-driven. `advance` must not introduce a hidden global tick.

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

## Persistence baseline

Local 0.1 uses SQLite through storage abstractions, not by embedding SQLite semantics into the core domain model.

Expected durable responsibilities include:

```text
RunRepository
EventStore
WorldDefinition / WorldPackage snapshot storage
```

The first implementation may share one local database, for example:

```text
.grass/grass.db
```

Canonical/durable data includes at least:

- run identity and operational metadata;
- branch metadata;
- committed transitions and Events;
- exact WorldDefinition material associated with a run;
- material referenced GEL source/schema/version needed for future continuation/reproducibility;
- non-secret SimulationRunConfig/provider-routing configuration.

Derived/rebuildable data should not become canonical merely for convenience. This includes, by default:

- `SimulationState` snapshots/projections;
- `ScheduledResolutionIndex`;
- actor/query views;
- query caches and indexes that can be rebuilt.

Checkpoints or derived indexes may be introduced later as optimizations without changing canonical history semantics.

SQLite is a local 0.1 implementation choice. Future evidence from real runs may justify Postgres, other local stores, derived read stores, or distributed persistence without changing engine authority/replay semantics.

## Application API

The Application API represents commands/use cases. It is the write-side surface for CLI and future clients.

Candidate operations include:

```text
create_run(...)
open_run(...)
step(...)
advance(...)
create_branch(...)
verify_run(...)
```

Application commands may result in authoritative changes only through the runtime/engine and existing validated transition + EventStore commit path.

The Application API should not expose mutable `SimulationState`, a write-capable raw EventStore, or lower-level shortcuts that let a client construct arbitrary authoritative Events.

## Query API

The Query API is read-only and optimized for useful inspection rather than mirroring internal class boundaries.

Run/world queries:

```text
list_runs()
get_run(...)
get_run_status(...)
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

## Runtime status

Useful application-facing states may include concepts such as:

```text
READY
RUNNING
WAITING_FOR_DECISION
QUIESCENT
TERMINATED
FAILED
```

Where practical these should be derived from authoritative history/state plus explicit ephemeral/external-input conditions, rather than stored as an independent mutable source of truth.

## CLI

The CLI is the first permanent client of the Application and Query APIs and remains useful after future HTTP/UI layers exist.

Representative command families:

```text
grass world validate WORLD

grass run create WORLD --name RUN
grass run list
grass run status RUN
grass run step RUN
grass run advance RUN --until-idle
grass run verify RUN

grass branch list RUN
grass branch create RUN --from BRANCH --name NEW_BRANCH

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

The exact package format is not frozen yet. The important architectural distinction is:

```text
WorldPackage = authored/distributed files required to construct a runnable world
WorldDefinition = immutable semantic world definition consumed by GRASS
```

Material referenced content must be captured/snapshotted sufficiently for continuation and reproducibility of a run.

## Templates

Templates are ordinary valid WorldPackages. They must not use a privileged hidden execution path.

Expected CLI workflows:

```text
grass template list
grass template show minimal
grass template init small-team ./my-world
```

Initial template set should include at least:

- `minimal`: minimal actor interaction and provider wiring;
- `resource-conflict`: multiple actors competing over a scarce shared resource;
- `small-team`: multiple actors, communication, Plans/Jobs, state changes, and useful actor inspection.

Templates serve three purposes simultaneously:

1. authoring starting points;
2. runnable documentation/examples;
3. high-level acceptance/regression worlds for the complete local runtime.

## Local 0.1 acceptance workflow

A representative successful workflow is:

```text
grass template init small-team ./demo
grass world validate ./demo

grass run create ./demo --name demo-run
grass run advance demo-run --until-idle

grass inspect actors demo-run
grass inspect actor demo-run alice
grass inspect actor-decisions demo-run alice
grass inspect events demo-run

grass branch create demo-run --from root --name alternative
grass run advance demo-run --branch alternative --until-idle

grass run verify demo-run
```

The user may close the process and continue later. The run remains available through local persistence.

At least simple scenarios should be able to use supported model-backed providers, deterministic/scripted policies, and human decisions in the same overall engine architecture.

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
