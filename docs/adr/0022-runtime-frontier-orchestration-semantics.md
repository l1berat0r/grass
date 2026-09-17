# ADR-0022: Runtime frontier orchestration semantics

- Status: Accepted
- Date: 2026-09-17

## Context

ADR-0019 established the production runtime boundary and left the exact unit of one
`step` open for implementation. Slice 12 implemented that coordinator, and Slice 13
made its run configuration and canonical history durable. The implemented frontier
rules now need to be explicit so later world composition and application layers do not
redefine runtime behavior.

This ADR refines ADR-0019. It does not change engine authority, EventStore semantics,
replay, branching, scheduler rebuildability, or provider and resolver boundaries.

## Decision

### Step and advance

One `SimulationEngine.step()` commits at most one authoritative transition. If no
transition is committed, it returns one explicit no-commit stop result. Provider,
configuration, unsupported-state, and integrity failures remain typed exceptions; they
are not converted into waiting or other normal stop results.

`advance()` repeatedly calls `step()` until a no-commit stop is returned or its step
budget is exhausted. Multiple consecutive transitions may have the same `LogicalTime`.
Runtime progress is not itself a logical-time advance.

### Current-frontier priority

The current `LogicalTime` is stabilized before the runtime moves to a future scheduler
time. Work at the current frontier has this priority:

1. outstanding automatic perception;
2. pending decisions;
3. ready PlanStep and Job starts;
4. scheduler Job or scenario-occurrence work.

A pending DecisionPoint with a subject Plan blocks new work only for that Plan lineage.
A subjectless pending DecisionPoint blocks new work for that actor. Work for unrelated
actors and already-started Jobs is not globally blocked merely because one actor has a
pending DecisionPoint.

More than one pending DecisionPoint for one actor is unsupported. The runtime rejects
an automatic perception result that would create a second pending point before its
atomic Observation and DecisionPoint transition is committed. It does not choose,
supersede, merge, or silently discard either point.

### Perception reconstruction

Outstanding automatic perception is rebuilt from canonical branch-visible history.
There is no persisted perception cursor. An `ObservationCreated` Event with the source
Event in its causation references records consumption for that source Event and actor.

If history has advanced beyond the source `LogicalTime` while a derived perception was
missed, the runtime raises an integrity error rather than backdating cognition.

### Same-time scheduler work

Independent same-time Job conflict components are evaluated from the same base state
and history position. Their validated results are published atomically in one supported
frontier transition, so component ordering does not become world semantics.

A frontier containing both Job work and a `ScenarioOccurrence` remains explicitly
unsupported in the Slice 12 runtime. This ADR does not define mixed-frontier semantics.

### Decision execution location

The resolved `DecisionProviderBinding.execution_location` in `SimulationRunConfig` is
the source of truth for runtime decision execution:

- `CLIENT_MANAGED` returns `WAITING_FOR_DECISION` and does not invoke an engine-local
  `DecisionInvoker`;
- `SERVER_MANAGED` requires and invokes the configured `DecisionInvoker`;
- a missing server-managed invoker is a `ProviderBindingError`;
- provider, routing, configuration, stale-output, proposal-validation, and integrity
  failures remain typed exceptions and commit nothing.

The runtime has no second external-binding flag or set. Persisting and restoring the
run configuration therefore restores the same execution-location behavior.

### Target time and identity allocation

A target time does not create Tick, Clock, or time-advance Events. Scheduler work
exactly at the target time is included. Once that time is reached, the runtime stabilizes
its current frontier before returning `TARGET_REACHED`.

Provider and resolver proposals are obtained before final transition and Event identity
allocation. Proposal acquisition remains non-authoritative and cannot consume a partial
authoritative transition.

## Consequences

- `step` is a precise debugging and execution primitive with one transition boundary;
- `advance` can stabilize same-time cascades without introducing a global tick;
- persisted provider routing is sufficient to restore client-managed waiting behavior;
- unsupported duplicate actor decisions are rejected before cognition history changes;
- future Application APIs can coordinate external input without redefining engine
  frontier ordering or gaining Event commit authority.

## Alternatives considered

### Keep a separate external-binding set on SimulationEngine

Rejected because it duplicates persisted run configuration and can change behavior after
restart without any change to the run.

### Commit an Observation before rejecting its second DecisionPoint

Rejected because automatic Observation and DecisionPoint creation is one atomic
cognition transition. Partial publication would change the accepted boundary.

### Define mixed Job and scenario-occurrence frontiers now

Rejected because Slice 12 deliberately leaves those interaction semantics unsupported.
They require a separate decision rather than an ordering shortcut.
