# GRASS Roadmap

This roadmap starts from the `design-0.1` architecture baseline. It is intentionally contract-oriented: implementation should prove one bounded invariant/vertical slice at a time rather than build the whole simulator at once.

## Design track

### design-0.1 architecture baseline

**Status: complete**

The baseline defines the engine authority model, event sourcing/semantic Events, `SimulationState` projections, WorldDefinition/SimulationRunConfig, GEL, action/Plan/Job boundaries, event-driven scheduler, ephemeral ScheduledResolution index, world resolution/validation, DecisionPoints, capability evaluation, replay, and branching.

After this baseline, material architecture changes should normally be introduced through a new ADR and then reflected in `docs/DESIGN.md`.

## Implementation track

**Current status:** Slices 0–11 are implemented on the implementation branch. The next planned slice is Slice 11.5, which exposes the implemented kernel and provider flow through a small application boundary and CLI before adding the web application.

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

### Slice 11.5 — application API and minimal CLI

Expose the implemented simulation kernel through a small application/use-case boundary before building the web application. The CLI is the first client of that boundary and a permanent development/diagnostic surface rather than a parallel execution path.

- define a small public application API for simulation use cases and orchestration;
- keep engine authority unchanged: the application layer and CLI may request operations, but only normal transition/commit machinery may mutate authoritative simulation history;
- keep the CLI thin and prevent it from reaching around the application boundary to mutate projections, scheduler state, or EventStore internals directly;
- support the minimum useful workflow for validating/loading a world, creating or initializing a run, inspecting run/state/history, advancing to the next material resolution, and inspecting/creating branches;
- expose provider-backed decision execution through the same application path where applicable;
- provide human-readable terminal output plus stable machine-readable JSON output for scripting and diagnostics;
- start with a lightweight standard-library CLI (`argparse`) unless a concrete requirement justifies an additional framework dependency;
- make the application API reusable by Slice 12 FastAPI rather than duplicating orchestration in HTTP handlers;
- add integration tests proving that CLI/application operations preserve replay, branching, determinism, provenance, and engine-authority invariants.

### Slice 12 — backend and frontend

- FastAPI application around the independent core and the Slice 11.5 application API;
- REST for ordinary configuration/query operations;
- WebSocket for interactive/session/client-managed provider round trips;
- React UI for scenario/run control, timelines, actor inspection, branches, and provider configuration.

### Slice 13 — observer and analyst foundations

- event/actor/plan/job/decision inspection;
- branch comparison metadata;
- deterministic MetricProvider boundary;
- provenance-linked analysis surfaces;
- optional LLM analyst as read-only interpretation layer.

## Explicitly later

- collective/institutional actor cognition;
- society-scale distributed execution;
- dynamic population resolution;
- sophisticated calibrated economics/psychology/law/biology;
- advanced geography/physics;
- rich graphical/animated UI;
- causal-inference claims/tooling beyond observational metrics.
