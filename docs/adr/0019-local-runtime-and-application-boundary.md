# ADR-0019: Local runtime and application/query boundary

- Status: Accepted
- Date: 2026-09-13

## Context

Slices 0–11 provide the core contracts required for event-sourced history, replay, branching, scheduling, deterministic world resolution, cognition, DecisionPoints, GEL, and provider invocation. The executable acceptance scenario currently composes those contracts through test-specific orchestration.

A locally usable GRASS 0.1 needs a production runtime coordinator and stable client-facing use-case boundaries before a web backend or frontend is designed.

The architecture must preserve the central invariant that only the simulation engine commits authoritative reality. CLI, future HTTP handlers, and future UI code must not gain direct mutation authority over projections, scheduler indexes, or EventStore history.

## Decision

Introduce three distinct layers above/beside the existing core:

```text
clients (CLI / future HTTP / future UI)
        |
        v
Application API / Query API
        |
        v
Simulation runtime / engine coordinator
        |
        v
existing core + persistence + providers + world composition
```

### Simulation runtime

The runtime coordinates existing core contracts. It reconstructs the current branch state/history, determines actionable work, progresses execution, derives or resolves DecisionPoints, invokes configured providers where required, projects scheduler candidates, resolves due work/scenario occurrences, validates candidate transitions, and commits only through the existing authoritative transition/EventStore boundary.

The runtime does not become an alternate source of truth. Ephemeral orchestration structures remain rebuildable.

### Step and advance

`step` is a bounded engine execution primitive with explicit deterministic selection/ordering semantics.

`advance` repeats engine work until an explicit stop condition such as quiescence, external-input wait, termination, failure, step/operation budget, or target logical time.

The runtime may perform multiple authoritative reactions at one LogicalTime. Runtime progress is therefore not equivalent to advancing simulation time and must not introduce a hidden global tick.

### Application API

The Application API exposes commands/use cases such as create/open run, step, advance, create branch, and verify replay/integrity.

Clients may request changes only through this API/runtime path. The Application API must not expose arbitrary Event insertion, mutable SimulationState, or raw write-capable EventStore access.

### Query API

The Query API is read-only and may reconstruct/project read models from canonical history.

It includes run/state/history/branch queries, Job and Decision queries, and actor-oriented queries such as `get_actors`, `get_actor`, actor observations, decisions, Plans, Jobs, and history.

Actor-oriented query DTOs may combine WorldState, ExecutionState, CognitionState, provenance, and history. They are read models and do not introduce a new authoritative Actor aggregate or freeze the long-term actor-memory model.

### Client reuse

The CLI is the first client of these APIs. Future HTTP/backend/UI clients should reuse the same Application/Query boundaries instead of reimplementing simulation orchestration in transport handlers.

## Consequences

- the currently test-local orchestration becomes a production architectural layer;
- engine authority is structurally enforceable rather than merely documented;
- CLI development becomes an end-to-end test of core completeness;
- later FastAPI/React work can remain transport/presentation work instead of defining engine semantics;
- actor inspection can become useful before the final actor-memory model is chosen;
- runtime status can be derived from authoritative state plus explicit external-input/runtime conditions where practical.

## Deferred details

- exact runtime internal class/module layout;
- exact definition of one `step` if implementation proves one transition is too narrow;
- exact runtime status enum and persistence of operational failures;
- final actor memory/retrieval/compaction semantics;
- HTTP/WebSocket/session/frontend design;
- distributed runtime execution.

## Alternatives considered

### Put orchestration in the CLI or HTTP handlers

Rejected because it duplicates semantics across transports and gives presentation layers too much knowledge of core internals.

### Expose EventStore and SimulationState directly as the public application interface

Rejected because clients could bypass authority, validation, replay, and stale-head rules.

### Build the frontend first and discover orchestration through API endpoints

Rejected because it would freeze transport/UI assumptions before the local runtime and data shape have been exercised.
