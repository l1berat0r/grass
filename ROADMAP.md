# GRASS Roadmap

This roadmap starts from the `design-0.1` architecture baseline. It is intentionally contract-oriented: implementation should prove one bounded invariant/vertical slice at a time rather than build the whole simulator at once.

## Design track

### design-0.1 architecture baseline

**Status: complete**

The baseline defines the engine authority model, event sourcing/semantic Events, `SimulationState` projections, WorldDefinition/SimulationRunConfig, GEL, action/Plan/Job boundaries, event-driven scheduler, ephemeral ScheduledResolution index, world resolution/validation, DecisionPoints, capability evaluation, replay, and branching.

After this baseline, material architecture changes should normally be introduced through a new ADR and then reflected in the current architecture documentation.

## Implementation track

**Current status:** Slices 0–17.1 and the post-Slice-17.1 Diagnostics Readiness checkpoint are complete on `impl/v0.1-gpt`. Before Slice 18 actor-capable WorldPackage composition, Slice 17.2 stabilizes generic scenario-defined space/location semantics required by MOVE, passive perception, recipient selection, and actor interaction. The evidence-driven Diagnostics Architecture checkpoint still follows Slice 18; backend/frontend and other later capabilities remain unsequenced.

ADR-0026 keeps WorldDefinition at pre-stable schema 1 until the first stable complete
authoring contract is explicitly frozen. Breaking internal representation changes may
replace schema 1 in place; repository-maintained examples move forward with the current
shape, while earlier local pre-release data has no compatibility guarantee. This
maintenance policy does not advance or redefine Slice 18.

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
- provider/configuration inspection where useful.

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
grass template init occurrence-counter demo
grass world validate demo
grass run create demo
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

The pre-stable WorldDefinition policy keeps the current internal document at
`schema_version = 1` until the first stable complete contract is frozen, independently
from SQLite, WorldPackage, GEL, Event, SimulationRunConfig, and CLI version domains. Event
payloads follow their own analogous pre-stable policy: current internal payload shapes stay
at `event_version = 1` until the first stable complete Event-history contract is frozen.
Repository-maintained worlds/templates move forward with incompatible internal shape
changes; earlier local databases, snapshots, and installed packages may need recreation.
Material changes to editable templates still require a semantic
`WorldDefinition.version` bump.

### Slice 17.1 — local CLI workspaces and presentation

**Status: complete**

Improve local usability before the next architecture activity without changing simulation
or persistence semantics:

- create a non-authoritative `runs/<run-id>/` operational workspace before snapshot
  publication and SQLite registration;
- keep SQLite at `grass.db` and immutable package material at
  `world_snapshots/<run-id>/`;
- preserve existing runs when their workspace is absent and keep replay/verification
  independent of workspace contents;
- make command-aware text the default presentation while preserving JSON v1 through
  `--format json` and the compatible `--json` shortcut;
- provide lightweight TTY-aware ANSI color with `--no-color` and `NO_COLOR` support.
- initialize the complete data root explicitly with `grass init`, installing missing
  bundled world templates under `templates/worlds/` while preserving valid local edits;
- allow installed ordinary WorldPackages to enter the unchanged run-creation path through
  `run create --template NAME` without fallback to bundled source material.

## Post-Slice-17.1 architecture checkpoint — Diagnostics Readiness

**Status: complete**

Before actor-capable WorldPackage implementation, preserve enough semantic actor-domain
history for later evidence-driven diagnostics without designing or implementing a
Diagnostics API. This checkpoint clarifies existing accepted contracts and does not add a
new authority, persistence model, CLI surface, or schema.

Slice 18 must follow these readiness principles:

- committed Event history remains canonical; diagnostics must not become a second source
  of truth;
- preserve naturally meaningful identities and semantic links across Perception/
  Observation, DecisionPoint, Decision, Plan/PlanStep, Job, world resolution, and committed
  Events;
- keep provenance, explicit causation/correlation, actor identity, and provider-binding
  references first-class where existing contracts make them material;
- prefer typed domain references and explicit Event causation over opaque metadata when a
  relationship has actor-domain meaning;
- avoid both lossy removal of materially meaningful domain relationships and speculative
  fields added only for a future diagnostics design;
- do not retain private chain-of-thought, credentials, or transient implementation details
  merely for possible future explanation.

The conceptual ownership boundary is:

```text
Query API
    what happened / state and history facts

Diagnostics API
    why it happened / why runtime is in this condition

Debug tooling
    lower-level implementation inspection
```

When actor communication is represented by semantic simulation history, its transcript or
content, sender/recipient, logical time/order, and conversation history are Query facts.
Why an actor communicated, which perception or DecisionPoint triggered it, and its
provider/decision lineage are future Diagnostics concerns. This checkpoint does not freeze
a `Message`, `Conversation`, transcript, or other communication schema.

### Slice 17.2 — scenario-defined space semantics

**Status: architecture substantially defined; final consistency review before implementation**

Stabilize a small generic spatial model before actor-capable package composition. GRASS
uses first-class scenario-defined Spaces without compiling domain concepts such as room,
building, city, vehicle, grid cell, or zone into core.

Accepted architecture direction includes:

- dedicated `SpaceId`, first-class `Space` in `WorldState`, and mandatory `Entity.location_id`;
- one direct canonical `location_id`; enclosing context is derived cycle-safely;
- WorldDefinition `spatial_policy.allow_cycles`, with acyclic containment as the ordinary explicit policy;
- closed spatial/lifecycle authority catalogue includes location-bearing `CreateEntityEffect`, `ReactivateEntityEffect`, `CreateSpaceEffect`, `SetLocationEffect`, `DeactivateSpaceEffect`, and `ReactivateSpaceEffect`, mapped to `EntityCreated/Updated/Deactivated/Reactivated`, `SpaceCreated/Deactivated/Reactivated`, and one typed `LocationChanged`; runtime Space/Entity identity is allocated by GRASS, and transient mechanic-local `CreationRef` handles are fully resolved before the closed WorldEffect boundary;
- generic MOVE intent resolved by world-owned MovementRule/MovementContract mechanics; `MovementRule` is the shared base contract, `movement.rules` contains selector-bearing `ConditionalMovementRule` values, and `default_rule` is a selector-free `DefaultMovementRule | null` consulted only after zero conditional matches; `MovementSelector` is a bounded declarative typed matcher returning MATCH/NO_MATCH, not a BUILTIN/GEL/IMPLEMENTATION mechanic, with a closed initial `ALL`/`ANY`/`NOT`/`EQ`/`IN`/`EXISTS` algebra over `ACTOR_ID`, `ACTOR_ENTITY_TYPE`, `CURRENT_LOCATION`, optional `BLUEPRINT_ID/VERSION`, named `STEP_PARAMETER`/`STEP_BINDING`, and trusted derived `NAMED_VALUE` refs; GRASS now treats `ValueBinding` as one global typed deterministic read-only value-resolution contract, reused by movement selection/mechanic inputs and later reaction/perception `input_bindings`, while each usage keeps its own bounded `BindingContext` and source/query vocabulary; bindings use only a literal, bounded JSONPath-like `ValuePath`, or a flat authorized query whose arguments are paths/literals, with no unrestricted JSONPath or recursive query-expression language; one global `ValueSchema` independently of GelSchema provides BOOLEAN/INTEGER/FLOAT/STRING/NULL, nominal `IDENTIFIER(kind)`, homogeneous LIST, and exact-field OBJECT semantics, so serialized strings are not implicitly canonical IDs; MOVE-specific request arguments stay in generic `PlanStep.parameters`; `MovementContract.input_schema` is an exact ValueSchema OBJECT whose fields have explicit requiredness distinct from `ValueBinding.optional`, and each MovementRule declares exactly one type-compatible binding for every contract field; one global `MechanicBinding` selects BUILTIN/GEL/explicitly trusted installed IMPLEMENTATION computation only, without owning input bindings, world-read authority, semantic result mapping, effects, Events, or commit authority; every selected movement mechanic returns the standard core `MovementResult(outcome, resolved_destination)` where destination is an existing canonical `SpaceId | None`, with trusted preparation producing the existing Job resolution outcome plus optional `SetLocationEffect` and no scenario-specific result-mapping DSL; standard MOVE does not use `CreatedSpaceRef` because it carries no same-result Space creation graph; current strict WorldDefinition keeps the mandatory explicit `movement` section, with `[] / [] / null` as a valid deliberate no-MOVE configuration and no implicit fallback;
- creation carries initial location directly and genesis validates the final atomic candidate; runtime Space creation occurs through normal Job/world or scenario mechanics, not an imperative mutation API;
- scenario-authorized Space deactivation cascades atomically through contained active Spaces and Entities while preserving historical location links;
- WorldDefinition LifecyclePolicy may independently permit explicit non-cascading Entity/Space reactivation; reactivation preserves `location_id` unless the same atomic candidate explicitly relocates the subject;
- atomic Entity/Space conflict detection is per semantic field (lifecycle/location/properties), permitting explicitly composable order-independent writes while rejecting duplicate writes to the same field; creation remains a full-state write;
- Space-deactivation closure is derived after composing explicit creation/relocation into candidate topology; closures from multiple accepted roots are unioned and deduplicated to at most one derived lifecycle deactivation write per subject before normal field-level conflict validation, so same-transition relocation can move a subject out of all closures without relying on Event order;
- inactive Entity/Space state is preserved/queryable but not ordinarily mutable: non-lifecycle writes require base-state activity or explicit valid same-candidate reactivation; a base-active subject may still be mutated and deactivated atomically;
- bounded spatial query capabilities over one immutable invocation view, with statically declared readable Space properties;
- Query API semantics for direct location, enclosing Spaces, `is_within`, cycle handling, and inactive topology;
- current pre-stable WorldDefinition remains `schema_version = 1`: mandatory explicit `spatial_policy`, mandatory explicit `lifecycle_policy`, mandatory explicit `movement`, initial `spaces`, and mandatory Entity `location_id` become part of the one current schema-1 shape; policy/movement sections have no implicit loader defaults; WorldPackage format remains 1;
- acceptance examples migrate `Office` from an informal `Location` Entity convention to a first-class Space and assign explicit initial locations to Entities;
- runtime identity allocation is deterministic for the same authoritative preparation context; rejected/stale candidates reserve no authoritative IDs and replay never reallocates committed identities;
- mechanic-facing same-result references use typed `ExistingEntityRef|CreatedEntityRef` and `ExistingSpaceRef|CreatedSpaceRef` unions across spatial, Relation, Resource, and Entity-scoped StateVariable consequences; trusted preparation resolves the complete graph before any closed WorldEffect is constructed;
- projection applies each CommittedTransition as one semantic batch: composite Entity/Space fields are derived from base state plus the complete write-set, Event order has no mutation precedence, and replay validates universal structural invariants without requiring WorldDefinition policy;
- all current Event payloads remain provisional `event_version = 1` before the first stable Event-history contract; incompatible internal payload changes replace v1 in place, while post-stabilization versioning remains independent per Event type.

Before implementation, perform one final consistency review against existing Event,
projection, WorldEffect, WorldDefinition/genesis, package, and Query contracts. Do not add
a physics engine, mandatory geometry, coordinates, distance metric, adjacency, universal
visibility, or property inheritance unless a separate concrete scenario contract requires it.

### Slice 18 — actor-capable WorldPackage composition and actor templates

**Status: planned; requires a new accepted architecture decision**

Define the missing ordinary-package architecture before implementing actor templates. The
decision must cover actor declaration/bootstrap, actor query visibility, initial cognition
and DecisionPoints where needed, perception, DecisionPoint triggering, provider/run-config
ownership and authoring, Plan/Job participation, actor world effects, and the resource
interaction/conflict semantics needed by conflict examples.

The decision must also preserve the readiness principles above wherever the actor-domain
model naturally provides semantic identities or relationships. It must make actor
communication queryable as simulation history when communication is modeled, but must not
invent diagnostics-only state or implement a Diagnostics API, CLI, persistence model, or
provider trace format.

The intended actor-oriented set includes minimal actor interaction, a small multi-actor
team/social scenario, and a shared-resource conflict scenario. Shared-resource conflict may
move to a later slice if its semantics should follow the initial actor-capable composition
rather than be frozen with it.

Do not emulate these examples with Entity-property conventions, metadata conventions,
opaque PlanStep parameters, narrated StateVariable changes, test-only composition, or hidden
template mechanics.

## Post-Slice-18 architecture checkpoint — Diagnostics Architecture

**Status: planned after Slice 18**

Use evidence from actor-capable runs rather than anticipated requirements to design the full
Diagnostics Architecture. The checkpoint must decide:

- exact ownership among Query facts, Diagnostics explanations, and low-level Debug data;
- which semantic links and explanatory evidence are available, incomplete, or require new
  accepted contracts;
- provider-invocation detail, retention, redaction, credentials/security boundaries, and
  reproducibility metadata;
- replay and branch treatment without regenerating historical cognition, resolution, or
  provider calls;
- which diagnostics are computed ephemerally, stored as rebuildable projections/indexes,
  or sufficiently material to require an explicit durable contract;
- data-size, access-pattern, pagination, indexing, and performance implications;
- effects on ordinary WorldPackage authoring and validation ergonomics.

Only after this checkpoint should Diagnostics implementation be sequenced. It must continue
to derive from canonical history and accepted runtime configuration rather than introduce a
parallel account of simulation reality.

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
