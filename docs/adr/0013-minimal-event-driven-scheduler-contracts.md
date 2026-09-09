# ADR-0013: Minimal event-driven scheduler contracts

- Status: Accepted
- Date: 2026-09-08

## Context

Slice 6 introduces the first executable scheduler boundary. ADR-0003 already
requires an ephemeral, rebuildable ScheduledResolution index, direct jumps to
material times, complete same-time collection, conflict grouping, and
incremental-versus-rebuild equivalence. The implementation still needs exact
duration arithmetic, explicit current-time input, progress-anchor derivation,
and narrow projection/index contracts without implementing world resolution.

## Decision 1: Exact logical duration

`LogicalDuration` is an immutable non-negative integer number of nanoseconds,
using the same exact coordinate unit as `LogicalTime`.

Slice 6 supports only:

```text
LogicalTime + LogicalDuration -> LogicalTime
later/equal LogicalTime - earlier LogicalTime -> LogicalDuration
```

Negative elapsed durations are invalid. Core introduces no wall-clock access,
implicit current time, mutable clock, calendar/timezone behavior, timer,
sleeping, or simulation tick.

## Decision 2: Explicit scheduler time

The scheduler receives `current_time` explicitly as a `LogicalTime`. It does not
infer scheduler time from `SimulationState.position`, because
`ProjectionPosition` is branch-origin-local and may not describe inherited
history. A branch-history-aware helper requires current time to equal the time
of the current branch-visible committed history position.

The scheduler owns no authoritative mutable clock. Selecting a future target is
not itself an authoritative time change.

## Decision 3: Ephemeral progress anchors

`ProgressAnchor` is derived scheduler input containing:

```text
job_id
baseline_progress
anchor_time
```

No activation, resume, or anchor field is added to `Job`, `ExecutionState`, or
`SimulationState`.

For each currently ACTIVE Job, branch-visible committed history determines the
current active segment. The anchor time is the later relevant boundary between
the activation/resume that began that segment and a subsequent committed
`JobProgressUpdated` in the same segment. After pause/resume, the resume
activation is the new anchor while the latest committed progress remains the
baseline.

The baseline is always the current committed Job progress. Anchor derivation
never infers uncommitted authoritative progress.

## Decision 4: Temporal projection boundary

`ScheduleProjector` is a pure deterministic protocol. It receives explicit
authoritative state, current LogicalTime, and derived progress anchors, and
returns ephemeral `ScheduledResolution` values.

The scheduler does not infer rates, durations, expected completion, BINARY
timing, Blueprint mechanics, or scenario semantics from opaque PlanStep data.
Slice 6 uses scripted deterministic projectors only in tests.

## Decision 5: ScheduledResolution

`ScheduledResolution` is generic over a typed hashable source reference. Slice
6 introduces no universal scheduler source-reference hierarchy. Job-focused
tests use `JobId` directly.

Its minimal fields are:

```text
logical_time
kind
source_ref
metadata
```

`logical_time` is absolute. `kind` is a non-empty operational token, never a
state-transition opcode. Metadata is immutable, derived, and disposable.

A candidate earlier than the explicit scheduler current time is invalid and
fails explicitly. A candidate exactly at current time is valid.

## Decision 6: Ephemeral index

`ScheduledResolutionIndex` is entirely ephemeral. It supports complete rebuild
and source-level replacement/removal. One source may produce several current
ScheduledResolution values; replacement supplies that source's complete set.

The index stores no authoritative clock, persisted entry, queue-entry identity,
or generation token. Earliest-time reads are non-destructive. Complete rebuild
from the same authoritative inputs remains available at all times.

## Decision 7: Due batching and conflicts

One scheduler invocation first gathers every current candidate at the earliest
logical time. It then evaluates an injected pure deterministic symmetric
pairwise conflict predicate and computes undirected connected components,
including transitive connectivity.

The scheduler does not inspect opaque bindings to invent conflicts, allocate
resources, select winners, or establish causal order. Ordering among equal-time
candidates or conflict components has no world semantics.

## Decision 8: SchedulerStep and same-time continuation

One immutable `SchedulerStep` contains:

```text
current_time
target_time
elapsed
due_candidates
conflict_components
```

Target time may equal current time, so zero-duration steps are valid. One
invocation handles one snapshot-derived due batch. If a later committed
resolution creates more work due at that same LogicalTime, a subsequent
invocation may return another zero-duration batch. Slice 6 has no internal
same-time fixed-point loop.

## Decision 9: Rebuild equivalence

Incremental maintenance and complete reconstruction from identical
authoritative inputs must produce semantically equivalent candidates. With
deterministic inputs they must permit identical authoritative history.

A deterministic test-only materializer may translate due Job batches into
already-supported Job Events solely to prove this property. Slice 6 introduces
no production ResolutionRequest, ResolutionProposal, WorldEffect, resolver, or
Event materializer.

## Decision 10: No Plan readiness in Slice 6

Slice 6 does not select a current Plan, evaluate dependency readiness, perform
capability checks, or create Jobs. Readiness across revised Plans and Jobs pinned
to earlier PlanStepRefs remains a separate execution/orchestration decision.

## Consequences

- The scheduler can jump directly between exact material times without owning
  time or reality.
- Active Job timing can be reconstructed after replay/fork without expanding
  authoritative Job state.
- Queue/index implementation remains replaceable and disposable.
- Conflict grouping is deterministic while scenario conflict meaning remains
  outside the scheduler.
- Slice 6 can prove rebuild equivalence without pulling Slice 7 resolution into
  production code.

## Deferred details

- production temporal/world resolution and Event materialization;
- ResolutionRequest, ResolutionProposal, WorldEffects, and candidate validation;
- rates, units, expected-completion formulas, rounding, and BINARY timing;
- scenario mechanics, ScenarioEventRules, Commitments, Blueprints, GEL, and
  random streams;
- automatic Plan selection/readiness, capability checks, and Job creation;
- resource-allocation outcomes and conflict winners;
- same-time fixed-point engine orchestration;
- persisted queues, queue identities, generation tokens, durable/distributed
  scheduling, and performance tuning;
- DecisionPoints, Observations, providers, and the complete engine loop.
