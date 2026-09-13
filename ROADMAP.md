# GRASS Roadmap

This roadmap starts from the `design-0.1` architecture baseline. It is intentionally contract-oriented: implementation should prove one bounded invariant/vertical slice at a time rather than build the whole simulator at once.

## Design track

### design-0.1 architecture baseline

**Status: complete**

The baseline defines the engine authority model, event sourcing/semantic Events, `SimulationState` projections, WorldDefinition/SimulationRunConfig, GEL, action/Plan/Job boundaries, event-driven scheduler, ephemeral ScheduledResolution index, world resolution/validation, DecisionPoints, capability evaluation, replay, and branching.

After this baseline, material architecture changes should normally be introduced through a new ADR and then reflected in the current architecture documentation.

## Implementation track

**Current status:** Slices 0–11 are implemented on `impl/v0.1-gpt`. The next milestone is a locally runnable GRASS 0.1 that can execute user-defined worlds without requiring changes to GRASS Python code. Slices 12–17 build that milestone. Backend/frontend, actor-memory evolution, observer/analyst capabilities, and persistence beyond the local baseline are intentionally not pre-sequenced before the post-Slice-17 architecture checkpoint.

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

- command paths may request authoritative changes only through `SimulationEngine`;
- query paths are read-only and may reconstruct/project data from canonical history;
- `ActorView`-style query DTOs may combine `WorldState`, `ExecutionState`, `CognitionState`, and history without introducing a new authoritative Actor aggregate;
- actor query surfaces must not prematurely freeze the exact long-term actor-memory/retrieval model;
- runtime status such as ready, waiting for decision, quiescent, terminated, or failed should be derived where practical from authoritative state plus explicit runtime/external-input conditions rather than duplicated mutable truth;
- the same Application/Query APIs are intended to be reusable by later CLI, HTTP, UI, and other clients.

### Slice 16 — local CLI

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

### Slice 17 — reusable world templates and executable examples

Make world authoring approachable without creating a second scenario mechanism.

- templates are ordinary valid WorldPackages processed by exactly the same validation/composition/runtime path as user-created worlds;
- provide `grass template list`, `grass template show`, and `grass template init`-style workflows;
- initial examples should cover at least a minimal actor interaction, a shared-resource conflict, and a small multi-actor team/social scenario;
- templates should be copyable/editable starting points rather than hidden special cases;
- template worlds double as executable examples and high-level acceptance/regression scenarios for the local 0.1 runtime.

## Local GRASS 0.1 acceptance milestone

After Slice 17, a new user should be able to perform a workflow equivalent to:

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

The process may terminate and restart between commands; the run remains available through local persistence. At least simple worlds can mix supported model-backed, scripted/deterministic, and human decision providers without changing GRASS source code.

## Post-Slice-17 architecture checkpoint

Do not pre-commit the next implementation order before exercising several real local runs.

The checkpoint should inspect actual data shape, query patterns, run size, provider context/cost behavior, authoring ergonomics, and performance before deciding the next slice. Candidate areas include:

- exact actor memory/retrieval/compaction model;
- persistence evolution beyond SQLite and derived indexes/read models;
- observer/analyst and branch-comparison capabilities;
- HTTP/backend/session APIs;
- frontend/UI;
- client-managed providers and richer human possession workflows;
- larger-scale/distributed execution;
- improved world-authoring tooling.

Frontend is therefore deliberately deferred rather than assumed to be the immediate successor to the local 0.1 milestone.

## Explicitly later / not required for local 0.1

- collective/institutional actor cognition beyond the currently supported actor model;
- society-scale distributed execution;
- dynamic population resolution;
- sophisticated calibrated economics/psychology/law/biology;
- advanced geography/physics;
- rich graphical/animated UI;
- causal-inference claims/tooling beyond observational metrics.
