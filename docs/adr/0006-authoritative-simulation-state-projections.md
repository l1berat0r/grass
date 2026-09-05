# ADR-0006: Authoritative SimulationState projections

- Status: Accepted
- Date: 2026-09-05

## Context

The architecture already defines an event-sourced authoritative history, a domain-neutral `WorldState`, persistent Plans and Jobs, actor-relative Observations, and `DecisionPoint`-driven cognition. The end-to-end acceptance walkthrough exposed an important boundary that had not yet been named explicitly.

`WorldState` is too narrow to describe everything that must be reproducible and branchable. A historical point in a running simulation may also include active Jobs, Plans, actor-relative observations/perceptions, unresolved DecisionPoints, and structured decisions already produced by a decision provider.

If these were treated only as disposable runtime objects, ordinary replay or a branch created after such a decision could require calling an LLM/human/provider again merely to rediscover what the actor had already observed, decided, or planned. That would violate the existing replay invariant.

At the same time, actor cognition/execution state must not be confused with objective world reality. GRASS therefore needs an umbrella concept for authoritative simulation state while preserving those semantic boundaries.

## Decision 1: Introduce `SimulationState`

`SimulationState` is the authoritative reconstructed state of one branch at one committed logical/history position.

Conceptually:

```text
SimulationState
    WorldState
    ExecutionState
    CognitionState
```

The exact DTO/module boundaries remain provisional. The important architectural rule is that these are **projections of one canonical Event history**, not three independent sources of truth.

```text
EventStore / committed branch history
        ↓
   deterministic projections
        ↓
SimulationState
    ├── WorldState
    ├── ExecutionState
    └── CognitionState
```

Snapshots/checkpoints of any projection are rebuild optimizations only. Canonical authority remains the committed Event history.

## Decision 2: `WorldState` remains objective simulated reality

`WorldState` contains authoritative in-world reality at the scenario-selected resolution, including the relevant projections of:

- Entities and their active/properties state;
- Relations;
- entity-associated Resources;
- scenario-defined state variables;
- authoritative Information items where they are part of world reality;
- other generic world structures introduced through accepted core Event types.

`WorldState` does **not** absorb actor beliefs, observations, decision prompts, Plans, or scheduler cache data merely because those are also authoritative/reproducible simulation data.

This preserves the existing distinction:

```text
world truth
!= represented semantic content
!= observation
!= interpretation
!= belief
```

## Decision 3: `ExecutionState` represents persistent execution/intention state

`ExecutionState` contains the authoritative materialized state required to continue already-decided execution without re-running cognition.

It includes, as required by the implementation:

- immutable/versioned Plans and their PlanSteps;
- Job lifecycle/progress state;
- references connecting PlanSteps to Jobs;
- currently applicable execution relationships/dependencies that are not merely derivable scenario definitions;
- other persistent scheduler-facing execution facts that are authoritative rather than disposable optimization indexes.

`ScheduledResolution` and other reconstructable scheduler indexes explicitly do **not** belong to `ExecutionState`; ADR-0003 remains authoritative for their ephemeral semantics.

A Plan is actor intention and a Job is concrete execution state. Their inclusion in `ExecutionState` does not grant the scheduler authority over world reality.

## Decision 4: `CognitionState` represents reproducible actor-relative decision state

`CognitionState` contains the authoritative actor-relative state needed for replay, branch continuation, and later cognition calls.

It may include, as the relevant models become concrete:

- Observations/perceived facts delivered to an actor;
- current actor beliefs/interpretations where GRASS materializes them as persistent cognition state;
- unresolved/resolved DecisionPoints;
- structured DecisionOutcomes/decision records;
- actor memory state or references required by the selected reproducibility level;
- provider-binding changes affecting actor cognition;
- other structured cognition metadata required to continue from a branch without inventing historical decisions again.

Private chain-of-thought is never required and must not be persisted as authoritative cognition state. Persist structured decisions, rationale summaries/provenance where explicitly useful, and externally meaningful provider output only to the degree required by the reproducibility/observability policy.

## Decision 5: Observations and DecisionPoints are persistable historical state

Actor-relative `Observation` and `DecisionPoint` objects are not merely transient UI/provider-call helpers when they affect historical cognition or branch continuation.

When materially relevant, their creation/resolution must be representable in Event history and therefore reconstructable into `CognitionState`.

Initial semantic Event types may include, as implementation requires:

```text
ObservationCreated
DecisionPointCreated
DecisionRecorded
```

and execution/intention Event types may include:

```text
PlanCreated
PlanRevised
PlanReplaced
```

The exact v0.1 event catalog/payloads remain deferred and must remain consistent with ADR-0005's semantic, domain-neutral Event-type rules.

Not every low-level intermediate object or provider message must become an Event. The persistence criterion is whether the information is required to reconstruct a materially equivalent `SimulationState`, preserve accepted history, support configured observability, or continue/replay/branch without silently regenerating a historical choice.

## Decision 6: Replay reconstructs all authoritative projections without providers

Ordinary replay of recorded history must be able to rebuild a materially equivalent `SimulationState` using persisted Events and deterministic reducers/projections only.

Replay must not call:

- DecisionProviders or humans;
- ModelProviders/LLMs;
- WorldResolutionProviders;
- GEL mechanics;
- random samplers;
- planners to rediscover already-recorded plans/decisions.

For example, if historical Events record that Alice observed Bob's request, received a bounded DecisionPoint, chose to answer, and created/revised a Plan, replay restores those facts rather than asking Alice's provider what she would do again.

Calling cognition/planning/resolution again from a historical point creates **new continuation/history**, such as an explicit branch or regeneration operation.

## Decision 7: Branch continuation starts from reconstructed SimulationState

Creating a branch at a historical point reconstructs the complete relevant `SimulationState` at the fork point and continues independently from there.

A fork created **before** a recorded decision may legitimately invoke the actor's DecisionProvider again when that branch reaches the DecisionPoint.

A fork created **after** a recorded decision inherits that recorded decision/Plan state as part of the shared prefix unless the user explicitly forks at an earlier position or performs an explicit intervention/regeneration that creates new history.

This preserves a clean distinction between:

```text
replay / inherited prefix
```

and:

```text
new cognition / branch continuation
```

## Decision 8: Historical positions are committed-transition boundaries

Because ADR-0005 defines `transition_id` as the atomic authoritative commit unit, a normally branchable/replayable state position must correspond to a coherent committed transition boundary, not an intermediate Event inside an atomic transition.

Events within one `transition_id` may have stable sequence ordering for storage/replay, but external history/fork APIs must not expose a semantically valid `SimulationState` that contains only a partial atomic transition.

Conceptually:

```text
T41 committed
    ↓
valid SimulationState / possible fork point

T42 event 1 of 4
T42 event 2 of 4
    ✗ not a valid externally visible partial state

T42 fully committed
    ↓
valid SimulationState / possible fork point
```

A storage engine may of course process Events internally while applying a transition, but readers must observe atomic state publication.

## Decision 9: Projections may evolve independently but remain deterministic

Different projections may consume different subsets of Event types:

```text
EntityCreated / ResourceChanged / RelationCreated
    -> WorldState

PlanCreated / JobCreated / JobCompleted
    -> ExecutionState

ObservationCreated / DecisionPointCreated / DecisionRecorded
    -> CognitionState
```

An Event may contribute to more than one projection when appropriate.

Projection code may evolve/version, but a supported historical event stream must reconstruct the same semantic state for that schema/version contract. Migrations/upcasters must not silently change historical meaning.

## Core invariants

```text
Event history is the canonical source of truth

SimulationState is reconstructed from committed Event history

SimulationState contains distinct world, execution, and cognition projections

WorldState is objective modeled reality, not all simulator runtime state

Plans and Jobs are persistent execution/intention state

material Observations and DecisionPoints are reconstructable when they affect history/continuation

private chain-of-thought is never required state

ScheduledResolution remains ephemeral and reconstructable

ordinary replay never regenerates past cognition/planning/resolution/randomness

branch continuation starts from reconstructed SimulationState

partial atomic transitions are not externally valid SimulationState/fork points
```

## Consequences

### Positive

- `WorldState` keeps a clean meaning as objective simulated reality.
- Replay and branching can reproduce actor/execution context without re-calling probabilistic providers.
- Plans, Jobs, observations, and decisions can be inspected historically and compared across branches.
- Scheduler optimization state remains clearly separated from persistent execution state.
- Atomic transition boundaries become natural stable history/fork positions.
- Multiple specialized projections can serve simulation runtime, UI, audit, and analytics without creating competing sources of truth.

### Costs

- More semantic Event types/reducers are required than a world-only state projection would need.
- Cognition persistence requires deliberate decisions about what structured provider output is materially necessary versus disposable/unsafe detail.
- Branch reconstruction must restore multiple projections coherently.
- Projection compatibility/versioning becomes part of persistence maintenance.

## Deferred details

This ADR intentionally does not freeze:

- exact `SimulationState`, `WorldState`, `ExecutionState`, or `CognitionState` DTOs;
- exact boundary between persistent actor memory, belief, interpretation, and derived caches;
- complete Observation/Decision/Plan Event-type payload catalog;
- snapshot/checkpoint physical layout;
- projection storage/database technology;
- memory compaction/summarization strategy;
- provider raw-response retention policy beyond the no-private-chain-of-thought rule;
- exact branch API and fork-position identifier format;
- historical projection migration/upcasting implementation.
