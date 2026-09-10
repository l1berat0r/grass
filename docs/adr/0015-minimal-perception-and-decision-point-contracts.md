# ADR-0015: Minimal perception and DecisionPoint contracts

- Status: Accepted
- Date: 2026-09-10

## Context

Slice 8 introduces the first persistent cognition state and actor decision
boundary. The design baseline already separates actor-relative Observation from
objective WorldState, invokes actors only at DecisionPoints, requires FULL and
BOUNDED scopes, and requires replay without regenerating historical cognition.
Exact identities, Event payloads, lifecycle rules, provider input, structured
outcomes, Plan materialization, and branch-visible transition boundaries were
intentionally deferred.

This slice must prove those contracts with scripted deterministic policies and
providers. It does not add automatic perception processing, production provider
adapters, ActionProposal execution, or the complete engine loop.

## Decision 1: Cognition identities and state

`ObservationId` and `DecisionPointId` are opaque nominal identifiers. There is
no separate DecisionId. Exactly one accepted `DecisionRecorded` may resolve one
DecisionPoint in one branch-visible history.

```text
CognitionState
    observations: Mapping[ObservationId, Observation]
    decision_points: Mapping[DecisionPointId, DecisionPoint]
    decisions: Mapping[DecisionPointId, Decision]
```

A DecisionPoint is pending when it exists without a corresponding Decision and
resolved when a Decision has been recorded. Status is derived rather than
stored. Cancellation, reopening, supersession, merging, and multiple accepted
decisions remain deferred.

Actor identity remains Entity-backed. Observation, DecisionPoint, Decision, and
resulting Plan actor references must agree and reference an Entity in the final
candidate WorldState. ActorFacet persistence is not required.

## Decision 2: Observation

Observation is actor-relative cognition, not objective truth, belief, or an
unrestricted copy of WorldState. A minimal Observation contains:

```text
observation_id
actor_id
content
provenance
observed_at
```

`content` is an immutable structured mapping. Version-1 `ObservationCreated`
contains exactly:

```text
observation_id
actor_id
content
```

Event-envelope provenance and logical time project as Observation `provenance`
and `observed_at`; they are not duplicated in the payload. Explicit Event
causation references connect an Observation to source Events where appropriate.

## Decision 3: DecisionPoint

The version-1 reason vocabulary is exactly:

```text
PLAN_REQUIRED
PLAN_EXHAUSTED
PLAN_BLOCKED
INTERACTION_REQUEST
JOB_FAILED
JOB_PAUSED
ASSUMPTION_INVALIDATED
MATERIAL_OBSERVATION
EXTERNAL_EVENT
OPERATOR_INTERVENTION
```

The version-1 scopes are exactly `FULL` and `BOUNDED`.

A minimal DecisionPoint contains:

```text
decision_point_id
actor_id
reason
scope
observation_ids
subject_plan_ref
```

`observation_ids` is an immutable set of actor-owned Observation references and
may be empty for reasons such as `PLAN_REQUIRED`. `subject_plan_ref` is nullable
and identifies one exact Plan version being reconsidered. Core does not infer a
global or current Plan.

Version-1 `DecisionPointCreated` contains exactly those six fields. A
DecisionPoint may be created in the same complete transition as its referenced
Observations. Non-observation engine conditions may create a standalone
DecisionPoint with no Observation Events in that transition.

## Decision 4: Trigger policy

The narrow replaceable trigger boundary is:

```text
DecisionTriggerPolicy.evaluate(DecisionTriggerContext)
    -> CONTINUE | DecisionPointProposal
```

The context contains one actor-relative Observation and an optional exact
subject Plan snapshot. It does not expose unrestricted SimulationState,
WorldState, Jobs, hidden simulator state, or other actors' cognition.

Trigger-policy `CONTINUE` is distinct from DecisionOutcome `CONTINUE_PLAN`.
Trigger-policy `CONTINUE` creates no DecisionPoint and never invokes a
DecisionProvider. A DecisionPoint proposal supplies reason, scope, referenced
Observation identities, and nullable subject Plan reference; the trusted caller
supplies authoritative Event and DecisionPoint identities.

## Decision 5: DecisionProvider and proposed Plans

The narrow provider boundary is:

```text
DecisionProvider.decide(DecisionRequest) -> DecisionProposal
```

DecisionRequest is immutable and actor-relative. It contains the pending
DecisionPoint, exactly its referenced Observations, and the exact subject Plan
snapshot when `subject_plan_ref` is present. It contains no unrestricted
SimulationState or WorldState, unrelated Jobs, other actors' cognition, or
hidden simulator state.

When a decision requires Plan creation, revision, or replacement, the provider
proposes complete semantic Plan content. `ProposedPlan` contains the same fields
as the strict Plan Event snapshot:

```text
plan_id
version
actor_id
objective
steps
replaces_plan_ref
```

It contains no provenance, recorded time, EventId, TransitionId, causation, or
correlation. Exact Plan and PlanStep identifiers may be part of the untrusted
candidate. Raw-model identifier allocation is deferred to production provider
or orchestration adapters.

The engine does not invent or complete actor intention. It validates the entire
provider proposal against the DecisionPoint, branch-visible state, and existing
Plan contracts before materializing Events. A scripted deterministic provider
keyed by DecisionPointId is sufficient for Slice 8 and fails explicitly when no
decision is configured. Provider fallback is never silent.

## Decision 6: Structured outcomes and Decision Event

The version-1 DecisionOutcome kinds are exactly:

```text
CONTINUE_PLAN
REVISE_PLAN
REPLACE_PLAN
BOUNDED_REACTION
```

`CONTINUE_PLAN` records that a provider was invoked for an existing
DecisionPoint and the actor explicitly chose to continue its exact subject Plan.
It contains no additional Plan data and creates no Plan Event.

`REVISE_PLAN` and `REPLACE_PLAN` each contain one `resulting_plan_ref`.
`BOUNDED_REACTION` contains one `bounded_reaction` field with:

```text
bounded_reaction
    intent_description    # required non-empty string
    content               # nullable immutable StructuredValue
```

A bounded reaction remains cognition in Slice 8. It contains no primitive,
targets, bindings, parameters, JobId, time budget, WorldEffects, or execution
fields and creates no execution or world Events.

Version-1 `DecisionRecorded` contains exactly:

```text
decision_point_id
outcome
```

The complete Plan snapshot is not duplicated. Event-envelope provenance and
logical time project as Decision `provenance` and `recorded_at`.

## Decision 7: Plan materialization

Decision preparation validates and materializes provider-proposed Plans as
follows:

- `REVISE_PLAN` requires `subject_plan_ref`; PlanId is unchanged, version is
  exactly subject version plus one, and all ADR-0012 revision rules apply.
- `REPLACE_PLAN` with `subject_plan_ref` requires a new PlanId, version 1, and
  `replaces_plan_ref` equal to the exact subject; all ADR-0012 replacement rules
  apply.
- `REPLACE_PLAN` without `subject_plan_ref` adopts a new Plan using
  `PlanCreated`; version is 1 and `replaces_plan_ref` is null.
- `CONTINUE_PLAN` requires an existing exact subject Plan and creates no Plan
  Event.
- `BOUNDED_REACTION` creates no Plan Event in Slice 8.

The proposed Plan actor must equal the DecisionPoint actor. `DecisionRecorded`
and the corresponding `PlanCreated`, `PlanRevised`, or `PlanReplaced` belong to
one atomic transition. `resulting_plan_ref` must exactly match that Plan Event.
The strict Plan Event version-1 schema does not change. Decision and Plan
history are linked through the Decision outcome plus explicit Event provenance
and causation.

## Decision 8: Historical boundaries and validation

Perception and decision use separate branch-visible transitions:

```text
ObservationCreated + optional DecisionPointCreated
later DecisionRecorded + optional Plan Event
```

The DecisionProvider is invoked only after the first transition commits. A fork
therefore may occur after DecisionPoint creation but before cognition is
generated. A fork before `DecisionRecorded` may record an independent decision;
a fork after it inherits the accepted decision and resulting Plan.

Preparation does not commit. Each prepared transition carries the exact
ancestry-aware expected head against which it was validated. Provider failure,
malformed output, invalid references, duplicate decisions, stale expected-head
validation, or any invalid combined Decision/Plan candidate commits nothing.

Reducers only project committed Events. Ordinary and checkpoint replay rebuild
Observations, DecisionPoints, Decisions, and Plans without invoking trigger
policies or DecisionProviders.

## Consequences

- Actor cognition becomes persistent, branch-aware, and replayable without
  provider regeneration.
- Provider input is intentionally narrower than world-resolution input.
- One immutable Event history remains the source of truth for accepted actor
  decisions and Plan content.
- Plan version-1 persistence remains compatible with ADR-0012.
- Bounded reactions can later feed planning without pretending to be executable
  actions in this slice.

## Deferred details

- production DecisionProvider/ModelProvider adapters, execution location,
  credentials, fallback configuration, and raw-model identifier allocation;
- ActorFacet, beliefs, interpretation, memory, retrieval, compaction, and raw
  provider transcripts;
- WorldDefinition perception mechanics and trigger-policy bindings;
- automatic post-commit perception processing, propagation latency,
  exactly-once processing, same-time coordination, and the complete engine loop;
- ActionProposal, planner separation, Plan readiness, automatic PlanStep/Job
  creation, and execution of bounded reactions;
- Information identity/state, communication propagation, GEL, APIs, frontend,
  durable persistence, serialization, and migrations;
- DecisionPoint cancellation, reopening, supersession, merging, arbitration,
  and multiple accepted decisions.
