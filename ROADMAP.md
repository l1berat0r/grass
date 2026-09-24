# GRASS Roadmap

This roadmap starts from the `design-0.1` architecture baseline. It is intentionally contract-oriented: implementation should prove one bounded invariant/vertical slice at a time rather than build the whole simulator at once.

## Design track

### design-0.1 architecture baseline

**Status: complete**

The baseline defines the engine authority model, event sourcing/semantic Events, `SimulationState` projections, WorldDefinition/SimulationRunConfig, GEL, action/Plan/Job boundaries, event-driven scheduler, ephemeral ScheduledResolution index, world resolution/validation, DecisionPoints, capability evaluation, replay, and branching.

After this baseline, material architecture changes should normally be introduced through a new ADR and then reflected in the current architecture documentation.

## Implementation track

**Current status:** Slices 0–17 are implemented on `impl/v0.1-gpt`. The next activity is the post-Slice-17 Diagnostics Architecture checkpoint. Slice 18 actor-capable WorldPackage composition requires a new accepted architecture decision; backend/frontend and other later capabilities remain unsequenced.

### Slice 0 — core value objects and package skeleton

- Python package structure independent from FastAPI;
- identifiers, logical time, provenance, branch/transition references;
- typed schemas/value objects;
- deterministic test utilities.

### Slice 1 — EventStore + atomic transitions

- minimal semantic Event envelope/types;
- in-memory EventStore;
- atomic `transition_id` commit boundary;
- append-only/immutability tests;
- stable replay sequence rules.

### Slice 2 — SimulationState projections

- `WorldState`, `ExecutionState`, `CognitionState` projection boundaries;
- deterministic reducers/projections;
- Entity/Relation/Resource/StateVariable state;
- replay equivalence tests;
- no direct state mutation outside transition/reducer code.

### Slice 3 — branch/replay foundation

- branch ancestry and committed-transition fork points;
- shared immutable prefix semantics;
- branch-local continuation;
- branch isolation tests;
- snapshot/checkpoint interface as optimization only.

### Slice 4 — WorldDefinition and genesis

- formal loader/validator for a minimal WorldDefinition;
- SimulationRunConfig separation;
- initial conditions -> genesis Event transition;
- scenario-defined entity/relation/resource/state-variable definitions.

### Slice 5 — Plan / PlanStep / Job

- immutable Plan versions;
- one-primitive PlanSteps with SUCCESS/TERMINAL DAG dependencies;
- optional Blueprint references;
- exactly one Job for every started PlanStep;
- Job lifecycle/progress projection;
- retry as new PlanStep/new Job.

### Slice 6 — event-driven scheduler

- logical clock jumps to next material resolution;
- ephemeral ScheduledResolution index;
- full rebuild fallback;
- incremental-vs-full-rebuild history equivalence test;
- same-time collection and conflict-component grouping;
- elapsed-time progress anchors.

### Slice 7 — deterministic world resolution

- ResolutionRequest/ResolutionProposal boundary;
- closed core WorldEffect algebra;
- full atomic candidate validation;
- deterministic resolver/mechanics;
- normal FAILED/BLOCKED/PARTIAL outcomes vs integrity failures.

### Slice 8 — perception and DecisionPoints

- Observation persistence/projection;
- DecisionTriggerPolicy;
- FULL and BOUNDED DecisionPoints;
- scripted/fake DecisionProvider;
- Decision/Plan persistence sufficient for replay without provider calls.

### Slice 9 — acceptance-scenario vertical slice

Turn `docs/ACCEPTANCE_SCENARIO.md` into executable integration tests covering genesis, plan execution, time jumps, bounded interaction, same-time conflict, scenario event, failure, replay, and branching.

### Slice 10 — GEL

- GEL grammar/parser/AST;
- type/input/output validation;
- bounded interpreter;
- safe standard functions and bounded loops;
- explicit random context;
- resource/operation budgets and failure tests;
- no host/filesystem/network/process capabilities.

### Slice 11 — provider adapters

- DecisionProvider / ModelProvider ports;
- OpenAI adapter;
- Ollama/OpenAI-compatible adapter;
- HumanDecisionProvider boundary;
- explicit server-managed vs client-managed execution location;
- provider/model provenance/fallback rules.

### Slice 12 — local simulation runtime orchestration

**Status: complete**

Introduce the first production runtime coordinator around the implemented core contracts.

- add a `SimulationEngine`/runtime coordinator that composes replay, scheduler projection, due-work resolution, scenario occurrences, cognition/DecisionPoints, provider acquisition, Plan/Job progression, validation, and commit;
- keep the central authority invariant unchanged: only the engine's normal validated transition/commit path may mutate authoritative simulation history;
- define a precise `step` operation for one bounded unit of engine work;
- define stabilization at one logical-time frontier, including cascades that create new material work without advancing logical time;
- define `advance` as repeated engine work until an explicit stop condition such as idle/quiescent, waiting for external input, termination, failure, step budget, or target logical time;
- keep scheduler indexes and other runtime coordination structures ephemeral/rebuildable;
- use injected providers/mechanics/storage boundaries rather than coupling runtime orchestration to one transport or database;
- preserve replay, branching, deterministic ordering, stale-head protection, provenance, and authority-boundary invariants in runtime-level integration tests.

### Slice 13 — durable local persistence

**Status: complete**

Provide a durable local baseline so separate GRASS processes can reopen and continue runs.

- introduce persistence contracts that keep storage technology outside simulation semantics;
- implement the first durable backend with Python `sqlite3` and a local GRASS database;
- persist run identity/metadata, branch metadata, canonical committed transitions/Events, exact WorldDefinition material needed by a run, and non-secret run configuration;
- preserve atomic transition commit semantics using database transactions;
- retain `InMemoryEventStore` for tests and lightweight execution;
- treat `SimulationState`, scheduler indexes, ActorViews, query caches, and similar derived data as rebuildable rather than canonical persistence by default;
- never persist provider credentials/secrets as run configuration;
- keep wall-clock operational metadata distinct from `LogicalTime`;
- introduce storage/schema versioning sufficient for future migration;
- treat SQLite as the v0.1 implementation baseline, not as a permanent architectural commitment.

### Slice 14 — runnable WorldDefinition composition and WorldPackage

**Status: complete**

Make a normal user-defined world runnable without adding Python code to GRASS.

- compose `WorldDefinition`, built-in mechanics, GEL mechanics, scenario rules, and provider bindings into a runnable runtime configuration;
- provide a trusted composition layer that converts data-defined mechanics into existing candidate-resolution/provider contracts below the same validation/commit boundary;
- ordinary worlds must not require arbitrary Python modules or GRASS source changes;
- trusted installed `IMPLEMENTATION`/plugin mechanics may remain an advanced extension point, but are not required for ordinary v0.1 worlds;
- introduce the `WorldPackage` concept as a delivery/container boundary for a WorldDefinition plus referenced GEL/mechanics/supporting files, distinct from the semantic immutable `WorldDefinition` itself;
- snapshot or otherwise preserve the exact material world inputs used by a run, including referenced GEL source/version/schema where material to future execution or reproducibility;
- validate a complete world package before creating a runnable experiment;
- keep exact package file format and long-term plugin/package distribution mechanisms evolvable.

### Slice 15 — Application API and Query API

**Status: complete**

Expose stable use-case boundaries above the runtime without leaking write authority to clients.

**Command/application surface:**

- create/open/manage local runs;
- execute `step` and `advance`;
- create branches through engine-owned operations;
- verify replay/integrity;
- provide transport-neutral hooks for external/human decision acquisition.

**Query surface:**

- `get_run`, run listing/status and branch inspection;
- `get_state` and canonical history/Event inspection;
- `get_jobs`/`get_job`;
- `get_decisions`/`get_decision`;
- `get_actors`/`get_actor`;
- actor-oriented observations, decisions, Plans, Jobs, and history queries.

Additional rules:

- command paths may request authoritative changes only through trusted runtime/
  `SimulationEngine` operations;
- query paths are read-only and may reconstruct/project data from canonical history;
- `ActorView`-style query DTOs may combine `WorldState`, `ExecutionState`, `CognitionState`, and history without introducing a new authoritative Actor aggregate;
- actor query surfaces must not prematurely freeze the exact long-term actor-memory/retrieval model;
- runtime status such as ready, waiting for decision, quiescent, terminated, or failed should be derived where practical from authoritative state plus explicit runtime/external-input conditions rather than duplicated mutable truth;
- the same Application/Query APIs are intended to be reusable by later CLI, HTTP, UI, and other clients.

### Slice 16 — local CLI

**Status: complete**

Provide the first permanent user/developer interface to the local runtime.

The CLI is a client of the Application/Query APIs, not a parallel execution path and not a write-capable EventStore client.

Initial command families should cover:

- `grass world validate ...`;
- `grass run create/list/status/step/advance/verify ...`;
- `grass branch list/create ...`;
- `grass inspect state/events/branches/jobs/job/decisions/decision ...`;
- `grass inspect actors RUN` and `grass inspect actor RUN ACTOR`;
- actor-focused observation/decision/Plan/Job/history inspection;
- provider/configuration diagnostics where useful.

CLI requirements:

- human-readable terminal output plus stable machine-readable JSON output;
- a lightweight standard-library CLI (`argparse`) unless a concrete requirement justifies another dependency;
- a CLI implementation of the transport-neutral human decision source, so human actor decisions use the same Slice-11 invocation and trusted preparation path as other providers;
- no direct projection mutation, scheduler mutation, raw Event insertion, or bypass of world/decision validation;
- integration tests showing that CLI-driven runs are replayable, branch-safe, provenance-preserving, and reopen correctly across separate processes.

### Slice 17 — reusable WorldPackage template infrastructure and occurrence examples

**Status: complete**

Make current world authoring approachable without creating a second scenario mechanism.

- provide `grass template list`, `grass template show`, and `grass template init`;
- use a fixed trusted registry and packaged resource inventory;
- initialize copyable/editable ordinary WorldPackages with no hidden mechanics or privileged runtime path;
- validate bundled and initialized packages through the normal loader and occurrence-only production composer;
- ship the honest occurrence-only `occurrence-counter` starter;
- exercise normal creation, execution, inspection, branching, reopen, replay verification, and distribution packaging.

ADR-0021 defines the eventual local template capabilities and examples. This roadmap
sequences their delivery: Slice 17 supplies template infrastructure and examples supported
by current occurrence-only composition; Slice 18 and later supply actor-oriented examples
after their architecture is accepted.

## Post-Slice-17 occurrence milestone

After Slice 17, a new user can perform this workflow using the actual current CLI:

```text
grass template list
grass template show occurrence-counter
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

The process may terminate and restart between commands. The run continues from its durable
package snapshot and canonical history without depending on the editable template copy.

## Post-Slice-17 architecture checkpoint — Diagnostics Architecture

Stop before actor-capable WorldPackage implementation. The next architecture activity is
Diagnostics Architecture, preserving this boundary:

```text
Query API
    what happened / state and history facts

Diagnostics API
    why it happened / why runtime is in this condition

Debug tooling
    lower-level implementation inspection
```

Slice 17 does not implement Diagnostics. The checkpoint should also inspect actual data
shape, query patterns, run size, authoring ergonomics, and performance before actor-capable
composition is designed.

### Slice 18 — actor-capable WorldPackage composition and actor templates

**Status: planned; requires a new accepted architecture decision**

Define the missing ordinary-package architecture before implementing actor templates. The
decision must cover actor declaration/bootstrap, actor query visibility, initial cognition
and DecisionPoints where needed, perception, DecisionPoint triggering, provider/run-config
ownership and authoring, Plan/Job participation, actor world effects, and the resource
interaction/conflict semantics needed by conflict examples.

The intended actor-oriented set includes minimal actor interaction, a small multi-actor
team/social scenario, and a shared-resource conflict scenario. Shared-resource conflict may
move to a later slice if its semantics should follow the initial actor-capable composition
rather than be frozen with it.

Do not emulate these examples with Entity-property conventions, metadata conventions,
opaque PlanStep parameters, narrated StateVariable changes, test-only composition, or hidden
template mechanics.

## Remaining actor-capable local 0.1 milestone

Slice 18 and later should unlock ordinary authored worlds with query-visible actors,
DecisionPoints, provider-backed decisions, Plans/Jobs, communication/perception, and
world-affecting actor behavior. Exact package and CLI contracts remain for the required
architecture decision rather than being invented by the Slice-17 template layer.

Frontend remains deliberately deferred rather than assumed to follow the local milestone.

## Explicitly later / not required for local 0.1

- collective/institutional actor cognition beyond the currently supported actor model;
- society-scale distributed execution;
- dynamic population resolution;
- sophisticated calibrated economics/psychology/law/biology;
- advanced geography/physics;
- rich graphical/animated UI;
- causal-inference claims/tooling beyond observational metrics.
