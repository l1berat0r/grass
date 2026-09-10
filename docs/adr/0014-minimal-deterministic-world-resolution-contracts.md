# ADR-0014: Minimal deterministic world-resolution contracts

- Status: Accepted
- Date: 2026-09-09

## Context

Slice 7 introduces the first executable world-resolution boundary. The design
baseline already requires replaceable resolvers, a closed WorldEffect algebra,
complete candidate validation before commit, semantic Events, and a distinction
between normal infeasibility and invalid resolver output. ADR-0013 deliberately
left the exact request, proposal, outcome, effect, and precommit contracts open.

This slice must prove deterministic Job resolution without adding scenario
mechanic catalogs, generative repair, cognition, or a complete engine loop.

## Decision 1: One request per Job conflict component

One `ResolutionRequest` represents one coherent scheduler conflict component.
Slice 7 subjects are Jobs only. Each subject groups one or more due
`ScheduledResolution[JobId]` values for one unique Job. Every candidate belongs
to that Job and has the request target time.

The request contains the exact ancestry-aware base `HistoryPosition`, target
`LogicalTime`, scheduler-supplied elapsed `LogicalDuration`, the Job subjects,
and the immutable authoritative `SimulationState` at the base position.

ScenarioEventRule, Commitment, and other resolution-source kinds remain
deferred. Slice 7 does not build a multi-component coordinator. Future
independent same-time component requests must all be derived from the same
pre-step state; sequential commit order must not become world semantics.

## Decision 2: Per-subject outcomes are persisted

Each request subject receives exactly one outcome:

```text
SUCCESS
PARTIAL
BLOCKED
FAILED
INTERRUPTED
```

`ResolutionProposal` contains exactly one outcome for every request Job and no
outcome for any other Job. There is no required request-level outcome.

Each subject outcome materializes one version-1 non-mutating semantic Event:

```text
ResolutionOutcomeRecorded
    job_id
    outcome
```

Projection recognizes and validates this Event without directly changing
WorldState or ExecutionState. The referenced Job must exist, and one transition
may record at most one outcome for a Job. A valid no-effect proposal therefore
still creates non-empty canonical history.

An outcome does not imply a Job lifecycle transition. Only explicit
WorldEffects may change authoritative Job status or progress.

## Decision 3: Closed transient WorldEffect algebra

The Slice 7 WorldEffect union contains exactly:

```text
CreateEntityEffect
UpdateEntityEffect
DeactivateEntityEffect
CreateRelationEffect
UpdateRelationEffect
DeactivateRelationEffect
ChangeResourceEffect
SetStateVariableEffect
UpdateJobEffect
```

Effects are immutable candidate values, are not persisted, and have no Slice 7
serialization or effect-version field. Persisted Events retain their independent
payload versions.

All effects use resulting-state semantics. In particular,
`ChangeResourceEffect` contains `quantity_after`, never a delta.

`UpdateJobEffect` contains a Job ID and optional `status_after` and
`progress_after` values. At least one resulting field is required. PENDING is
not a valid status target. One effect may materialize progress and one lifecycle
Event atomically. A proposal may contain at most one UpdateJobEffect per Job.

CREATE_INFORMATION and Information identity/state/Event semantics remain
deferred.

## Decision 4: Narrow deterministic provider boundary

The replaceable boundary is:

```text
WorldResolutionProvider.resolve(ResolutionRequest) -> ResolutionProposal
```

Slice 7 uses injected pure deterministic implementations. It does not change
WorldDefinition schema version 1 or SimulationRunConfig and does not introduce
resolver bindings or mechanic catalogs.

The resolver receives immutable candidate input. It returns outcomes and
WorldEffects only. It never returns Events, replacement SimulationState, Event
identities, authoritative provenance, causation, or correlation and never
commits history.

## Decision 5: Validation and deterministic integrity failure

Resolution validates the complete proposal before it becomes commit-eligible.
Validation includes proposal completeness, the closed effect set, duplicate
target writes, references, currently expressible WorldDefinition vocabulary,
existing Event payload contracts, and Job lifecycle/progress rules.

Normal infeasibility is an outcome and is not an exception. Malformed or invalid
deterministic resolver output is surfaced as
`DeterministicResolutionIntegrityError`; it is never converted to FAILED or
BLOCKED. A pure validation boundary may expose `ResolutionValidationError`.

No invalid candidate returns a partial transition or reaches canonical history.

## Decision 6: Effect materialization

Effects materialize to existing version-1 semantic Events:

```text
CreateEntityEffect       -> EntityCreated
UpdateEntityEffect       -> EntityUpdated
DeactivateEntityEffect   -> EntityDeactivated
CreateRelationEffect     -> RelationCreated
UpdateRelationEffect     -> RelationUpdated
DeactivateRelationEffect -> RelationDeactivated
ChangeResourceEffect     -> ResourceChanged
SetStateVariableEffect   -> StateVariableChanged
```

`UpdateJobEffect` may produce `JobProgressUpdated`, one of `JobActivated`,
`JobPaused`, `JobCompleted`, `JobFailed`, or `JobCancelled`, or both progress and
lifecycle Events. Progress is encoded before lifecycle when both are present;
the existing projection validates their combined result without assigning
semantic precedence to Event sequence.

Outcome Events are encoded in request-subject order, followed by effects in
proposal order. This is deterministic replay/storage encoding only and does not
express causality, priority, or conflict resolution.

## Decision 7: Engine-controlled Event envelope

The trusted caller supplies the `TransitionRef` and the exact required sequence
of `EventId` values. Slice 7 adds no ResolutionId or production ID generator.

Materialization creates `WORLD_RESOLVER` provenance. A trusted caller may supply
a resolver source reference and immutable metadata. Explicit trusted CauseRefs
and CorrelationId values may be applied to the materialized Events. No causal
reference is inferred from scheduler order, conflict membership, Event sequence,
or Job identity.

## Decision 8: Prepared resolution and stale-head protection

Preparation never commits. It returns an immutable `PreparedResolution`
containing:

```text
expected_head
transition
```

The expected head is the request base HistoryPosition against which the
candidate was validated.

Preparation also receives the branch-visible committed history ending at that
base position. It uses this read-only canonical input to validate the
scheduler-supplied elapsed duration against the base transition's logical time,
including when a child has no branch-local ProjectionPosition time. The history
is not supplied to the resolver.

`InMemoryEventStore` supports optional optimistic expected-head commit. Under
the same store lock used for commit, the expected branch must match the
transition branch and the expected position must equal the current
ancestry-visible branch head. A mismatch raises a dedicated stale-history error
and consumes no Event sequence, EventId, or TransitionRef. Existing unchecked
structural commits remain available for genesis and lower-level tests.

## Consequences

- Deterministic resolvers remain replaceable and non-authoritative.
- Every resolved Job has explicit replayable outcome history, including no-op
  BLOCKED/FAILED/INTERRUPTED results.
- Effects remain transient and cannot become an open scenario mutation escape
  hatch.
- Existing reducers provide the final atomic lifecycle/reference check before a
  transition becomes commit-eligible.
- Optimistic head checking prevents a transition validated against stale state
  from being published.
- Same-time multi-component publication still requires a future coordinator.

## Deferred details

- generative resolution and repair loops;
- Information;
- WorldDefinition mechanics, schemas, bounds, Blueprint execution, and
  ScenarioEventRules;
- SimulationRunConfig resolver mode/bindings;
- capability evaluation and UNKNOWN policy;
- ActionProposal, planning, readiness, and automatic Job creation;
- multi-component same-time commit coordination and the complete engine loop;
- GEL, random streams, durable persistence, APIs, and production ID generation.
