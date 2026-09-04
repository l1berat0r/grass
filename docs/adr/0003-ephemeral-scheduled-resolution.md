# ADR-0003: Ephemeral scheduled-resolution index

- Status: Accepted
- Date: 2026-09-04

## Context

GRASS advances logical time to the next material resolution point instead of running a fixed simulation tick. The scheduler therefore needs an efficient way to identify future times at which a job, commitment, scenario process, temporal threshold, or another process may need to be reconsidered.

That scheduler-facing data must not become a second historical state model. The authoritative sources of truth remain the event-sourced world state and the current authoritative actor/plan/job/scenario state derived from it. Future completion times and thresholds are predictions derived from those sources and may become obsolete whenever the world changes.

A previous candidate design considered a priority queue with generation/version tokens and lazy invalidation. While technically workable, stale entries can accumulate, consume memory, increase discarded-pop work, and make debugging harder in long simulations. More importantly, generation tokens are properties of one queue-maintenance strategy rather than simulation semantics.

## Decision

`ScheduledResolution` is an **ephemeral, derived scheduler optimization**.

It is not authoritative state, is not an `Event`, is not historical fact, and MUST NOT be persisted or archived as part of the simulation state/history. The complete scheduler index may be discarded at any time and reconstructed from the current authoritative state, plans, jobs, commitments, and scenario/temporal mechanics.

Conceptually:

`ScheduledResolution = derive(authoritative state, plans, jobs, commitments, temporal/scenario mechanics)`

A minimal v0.1 representation is intentionally small:

```text
ScheduledResolution
    logical_time
    kind
    source_ref
    metadata?
```

`logical_time` is an absolute simulation time at which the source should next be reconsidered.

`kind` is a broad scheduler hint, not a state-transition opcode. Initial examples may include:

- `JOB_CHECKPOINT`;
- `JOB_EXPECTED_COMPLETION`;
- `SCENARIO_EVENT`;
- `COMMITMENT_DUE`;
- `DEADLINE`;
- `TEMPORAL_THRESHOLD`.

This vocabulary is operational and may evolve. A `kind` never directly completes a job, mutates world state, or commits events. When the time is reached, normal temporal/world-resolution mechanics determine what actually happens.

`source_ref` identifies the job, commitment, temporal/scenario process, or other source from which the projection was derived. Scheduler-local queue-entry identity is not simulation identity.

Opaque/versioned `metadata` may be used only when a projection mechanism genuinely needs execution-model-specific scheduler data. It remains derived and disposable.

## Queue/index semantics

The scheduler may use a priority queue or another index optimized for the earliest `logical_time`, but the concrete data structure is not part of the simulation contract.

Permitted implementation strategies include, for example:

- an indexed priority queue with explicit replacement/removal;
- a heap with lazy invalidation plus bounded/periodic compaction;
- partial re-projection of affected sources;
- full rebuilding of the scheduler index from current authoritative state.

Generation/version tokens MAY be used internally by a particular implementation, but they are not part of the core `ScheduledResolution` contract and MUST NOT become required persisted simulation data merely to support lazy invalidation.

Because the index is fully reconstructable, an implementation may always fall back to:

```text
clear scheduler index
rederive all current ScheduledResolution entries
continue
```

without changing simulation semantics.

## Same-time batching

The scheduler is ordered primarily by `logical_time`, but internal queue order among entries with the same logical time has no world semantics.

When the earliest logical time is reached, the scheduler MUST first gather all current/non-stale scheduled-resolution entries for that time before deciding how to resolve them.

Conceptually:

```text
10:00 A
10:00 B
10:00 C
    ↓
collect same-time set
    ↓
dependency/conflict analysis
    ↓
one or more coherent ResolutionRequests
```

Independent items may be split into separate `ResolutionRequest`s for efficiency. Interacting items, including competition for the same resource, participant, exclusive control, or mutually incompatible state transitions, must be grouped coherently so arbitrary heap order does not create causality.

Stable technical ordering may still be used internally for deterministic iteration/debugging, but such ordering MUST NOT be interpreted as one same-time event having occurred before another unless an actual committed event establishes that causal order.

## Reprojection and invalidation

A scheduled resolution is a prediction, not a promise.

For example, an uninterrupted sleep job may project expected completion at 07:00. If an alarm at 02:00 changes the job/world state, the old projection may be removed, ignored, compacted away, or replaced; the scheduler then derives the next relevant resolution from the new authoritative state.

The architecture therefore defines **semantic invalidation** but does not prescribe one physical invalidation algorithm.

## Recurring and continuous processes

GRASS does not introduce a global periodic tick merely to support recurring or continuous dynamics.

A recurring process may resolve one material boundary and then derive its next `ScheduledResolution`. Rate/continuous processes should project material threshold times rather than emit tiny periodic updates when an anchor + elapsed-time model can calculate intermediate values on demand.

## Rebuild equivalence invariant

The following is a required semantic property of the scheduler boundary:

> Rebuilding the scheduler index from the same authoritative state must produce a semantically equivalent set of future material resolution candidates.

The reconstructed entries do not need identical scheduler-local IDs, heap layout, or iteration order.

For deterministic simulations with identical inputs, an implementation that maintains the index incrementally and one that rebuilds the entire index after each committed batch should produce the same authoritative history. This should become a scheduler regression/property test because failure indicates that hidden scheduler state has accidentally acquired simulation authority.

## Consequences

### Positive

- Scheduler data cannot silently become a second source of truth.
- Crash/restart or debugging tools do not need to persist queue internals.
- Queue implementation can evolve independently of scenario/event schemas.
- Stale-entry accumulation can be solved by replacement, compaction, or rebuild without architectural migration.
- Same-time fairness is explicit and independent of heap ordering.
- Rebuild-equivalence testing provides a strong detector for hidden scheduler semantics.

### Costs

- Reconstructing the entire index may be expensive for very large simulations, so efficient incremental projection/indexing will still matter for performance.
- Projection mechanics must be deterministic/complete enough in deterministic mode to rediscover all relevant future material boundaries from authoritative state.
- Implementations using lazy invalidation need operational controls such as compaction/rebuild thresholds to avoid unbounded stale-entry growth.

## Deferred details

This ADR intentionally does not fix:

- the concrete priority-queue/index implementation;
- compaction/rebuild thresholds;
- internal generation-token representation, if any;
- scheduler-local queue-entry IDs;
- exact `source_ref` schema;
- exact `metadata` payload;
- the final `kind` vocabulary;
- conflict-component detection algorithm;
- performance optimizations for very large actor/job populations.
