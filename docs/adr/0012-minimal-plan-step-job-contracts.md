# ADR-0012: Minimal Plan, PlanStep, and Job contracts

- Status: Accepted
- Date: 2026-09-07

## Context

Slice 5 materializes persistent actor intention and execution state. The design
baseline requires immutable Plan versions, one-primitive PlanSteps with DAG
dependencies, exactly one Job for every started logical step, structured
progress, and deterministic replay. Exact identities, Event payloads, lifecycle
edges, and atomic projection rules were intentionally deferred.

## Decision 1: Execution identities and references

`PlanId`, `PlanStepId`, `JobId`, and `BlueprintId` are opaque nominal
identifiers. References are:

```text
PlanRef(PlanId, positive integer version)
PlanStepRef(exact PlanRef, PlanStepId)
BlueprintRef(BlueprintId, positive integer version)
```

`PlanStepId` is the globally unique logical identity of a step. It may appear in
several versions of one `PlanId`, with different immutable snapshot content, but
never under another `PlanId`. A Job pins one exact `PlanStepRef`. Across all
versions containing a logical step, at most one Job may exist in branch-visible
state.

Blueprint references preserve identity only. Existence and primitive
compatibility validation remain deferred until an authoritative Blueprint
catalog/runtime history exists. `PlanStep.primitive` is authoritative.

## Decision 2: Plan and PlanStep

The version-1 primitive vocabulary is exactly `CREATE`, `MODIFY`, `RELATE`,
`TRANSFER`, `MOVE`, `COMMUNICATE`, `OBSERVE`, `WAIT`, and `REST`. PlanStep origin
is exactly `ACTOR_INTENT` or `PLANNER_DERIVED`.

A Plan version has a non-empty objective and at least one PlanStep. Each step has
one primitive, optional BlueprintRef, required immutable structured `bindings`
and `parameters`, an unordered immutable dependency set, origin, and optional
non-empty description. Authored step order is presentation order only.

Every persisted dependency explicitly identifies a target `PlanStepId` and a
condition of `SUCCESS` or `TERMINAL`. Targets belong to the same complete Plan
version. Duplicate, missing, self, and cyclic dependencies are invalid;
dependencies may target later-listed steps. Scheduler readiness is not part of
this contract.

The Plan's actor must be an Entity present in the final candidate WorldState of
the complete transition. Core does not require that Entity to be active or have
an ActorFacet in Slice 5.

## Decision 3: Plan versioning and replacement

`PlanCreated` creates version 1 with no replacement reference. `PlanRevised`
creates exactly the next integer version of the same PlanId as a complete
snapshot. Its `replaces_plan_ref` equals the predecessor version's value.

`PlanReplaced` creates a new PlanId at version 1. Its required
`replaces_plan_ref` identifies the current latest version of an unreplaced
PlanId in pre-transition branch-visible state. Replacement is final for the
replaced PlanId on that branch: it cannot be revised or replaced again. A
replacement Plan may itself later be revised or replaced.

At most one Plan operation may affect a PlanId in one transition.
`PlanReplaced` affects both old and new PlanIds. Revision and replacement
predecessors must preexist the transition. Jobs may reference a Plan version
created by the same complete transition.

Plan versions preserve Event-envelope provenance and logical time as projected
`provenance` and `recorded_at`; those values are not duplicated in payloads.
Revision/replacement never changes an existing Job.

## Decision 4: Plan Event payloads

Version-1 `PlanCreated`, `PlanRevised`, and `PlanReplaced` each contain exactly
one `plan` field with a complete snapshot:

```text
plan
    plan_id
    version
    actor_id
    objective
    steps
    replaces_plan_ref     # nullable
```

Steps contain `step_id`, `primitive`, nullable `blueprint_ref`, `bindings`,
`parameters`, explicit `dependencies`, `origin`, and nullable `description`.
Replacement identity appears only in the Plan snapshot.

## Decision 5: Job lifecycle

`JobCreated` is the unique fact that a PlanStep has started an execution attempt.
It creates a PENDING Job, pins an exact PlanStepRef, and supplies explicit
initial progress. PENDING means the attempt exists but no active work interval
has begun.

Legal lifecycle edges are:

```text
PENDING -> ACTIVE | COMPLETED | FAILED | CANCELLED
ACTIVE  -> PAUSED | COMPLETED | FAILED | CANCELLED
PAUSED  -> ACTIVE | FAILED | CANCELLED
```

`JobActivated` performs PENDING/PAUSED to ACTIVE. `JobPaused` requires ACTIVE.
COMPLETED, FAILED, and CANCELLED are terminal. Same-status changes and every
post-terminal lifecycle/progress change are invalid.

Per Job, one transition may contain at most one JobCreated, one lifecycle Event,
and one JobProgressUpdated. Projection validates their combined result without
using Event sequence as precedence. Creation plus activation, progress plus
completion, and creation plus terminal progress plus completion may therefore
be atomic.

Projected Job records `JobCreated` envelope provenance/time as
`creation_provenance` and `created_at`. Later lifecycle/progress provenance
remains in Event history.

## Decision 6: Progress

Every Job has one explicit immutable progress model kind from creation.

```text
LINEAR
    completed    # exact int or finite float, bool invalid
    total        # exact int or finite float > 0, bool invalid
    0 <= completed <= total

BINARY
    complete     # bool
```

Initial LINEAR completed is zero and initial BINARY complete is false. Progress
is monotonic. Model kind and LINEAR total are immutable.
`JobProgressUpdated` contains complete `progress_after`, never a delta.

A standalone progress update requires ACTIVE. Progress may also accompany
PENDING/PAUSED activation, instantaneous PENDING completion, or an ACTIVE Job's
pause, completion, failure, or cancellation. Standalone PENDING/PAUSED progress
is invalid. `JobCompleted` requires final terminal progress.

## Decision 7: Job Event payloads

Version-1 payloads are strict:

```text
JobCreated
    job_id
    plan_step_ref
    progress

JobProgressUpdated
    job_id
    progress_after

JobActivated / JobPaused / JobCompleted / JobFailed / JobCancelled
    job_id
```

JobCreated does not duplicate actor, primitive, Blueprint, bindings, or
parameters fixed by the pinned PlanStep snapshot.

## Decision 8: ExecutionState and projection

```text
ExecutionState
    plans: Mapping[PlanRef, Plan]
    jobs: Mapping[JobId, Job]
```

No latest-version index, current-Plan pointer, readiness cache, PlanStep status,
PlanExecution aggregate, or stored job-by-step index is authoritative state.

Projection consumes complete committed transitions, groups orthogonal Job
changes, validates final cross-references and all lifecycle/versioning
invariants, and publishes one immutable SimulationState only after the complete
candidate succeeds. EventStore remains generic structural history storage.

Retry uses a new PlanStepId and JobId. Core does not infer semantic equivalence,
store retry ancestry, or add retry workflow nodes.

## Consequences

- Plans and Jobs replay and branch without regenerating cognition or execution.
- Plan revision can change unstarted logical-step details without changing Jobs
  already pinned to earlier exact snapshots.
- Atomic Job state does not depend on incidental Event ordering.
- Blueprint identity can be preserved without prematurely extending
  WorldDefinition or runtime Blueprint history.

## Deferred details

- Blueprint catalogs, actor-created Blueprint history, existence checks, and
  primitive compatibility validation;
- ActionProposal, planner, DecisionPoint, provider, and ActorFacet integration;
- scheduler readiness, ScheduledResolution, clock advancement, progress accrual,
  units, rates, elapsed-time anchors, and expected completion;
- lifecycle reasons/results beyond Event provenance;
- engine command/precommit services and world resolution;
- current-Plan indexes, retry counters/ancestry, and workflow DSL;
- durable persistence, serialization, migration, API, and frontend concerns.
