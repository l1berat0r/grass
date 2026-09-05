# ADR-0005: Semantic Event types and atomic transition boundary

- Status: Accepted
- Date: 2026-09-05

## Context

GRASS uses event sourcing as the authoritative history model. `WorldEffect` already represents a candidate state transition proposed by deterministic or generative world resolution, while `Event` represents an immutable accepted historical fact.

The event contract now needs to become concrete enough for implementation without turning history into either:

1. an opaque technical log consisting only of generic `WorldEffectApplied` records; or
2. an ever-growing catalog of scenario-domain verbs such as `EmployeeHired`, `ElectionWon`, or `ServerRestarted`.

GRASS also needs to preserve atomic commits, deterministic replay ordering, branchability, provenance, same-time concurrency, and historically meaningful non-mutating facts such as refusals or failed attempts.

## Decision 1: Minimal Event envelope

The initial conceptual Event contract is:

```text
Event
    event_id
    branch_id
    sequence
    logical_time

    transition_id

    event_type
    event_version
    payload

    provenance

    causation_refs?
    correlation_id?
```

The exact serialized DTO remains provisional, but these semantic fields are accepted.

### `event_id`

`event_id` is a globally unique opaque identity for the immutable Event. It does not define ordering and must not encode scenario semantics.

The concrete identifier technology (for example UUID/UUIDv7/ULID) is an implementation choice.

### `branch_id`

Every Event belongs to exactly one branch continuation. Shared history before a fork is represented by branch ancestry/storage semantics rather than by rewriting or duplicating historical Events as new facts.

### `sequence`

`sequence` is monotonically ordered within a branch and provides deterministic replay/storage order.

> Sequence establishes replay order, not causal truth.

Two Events with the same `logical_time` may have different sequence numbers solely because an append-only log requires a stable physical/logical ordering. The larger sequence must not be interpreted as evidence that one same-time fact caused another.

### `logical_time`

`logical_time` is the absolute logical simulation time associated with the Event. Many Events and multiple independent transitions may share the same logical time.

Event envelopes do not contain a turn/tick concept. Elapsed duration belongs in a type-specific payload/provenance when it is semantically relevant.

## Decision 2: `transition_id` is the atomic commit identity

`transition_id` is mandatory and identifies one **atomic authoritative commit unit**.

A single resolution/initialization/override operation may produce several Events. All Events with the same `transition_id` that belong to that commit are appended atomically: either the complete transition becomes authoritative history or none of it does.

Example:

```text
transition_id = T42

ResourceChanged
RelationCreated
JobCompleted
ActionSucceeded
```

This does not mean that every Event in the transition mutates `WorldState`; it means they jointly describe one accepted atomic historical transition.

`transition_id` is deliberately more general than a resolver-specific identifier because authoritative transitions may originate from:

- normal world resolution;
- genesis/run initialization;
- scenario events;
- explicit operator override/intervention paths;
- other future engine-authorized transition sources.

A scheduler same-time batch is **not** a transition and is not persisted as one. The scheduler may collect several due items at the same timestamp and derive one or more independent/interacting atomic transitions from that ephemeral batch.

```text
same-time scheduler batch
        !=
atomic authoritative transition
```

## Decision 3: Use semantic, generic core Event types

GRASS will use **semantic but domain-neutral Event types** rather than representing normal history solely as `WorldEffectApplied`.

The initial core vocabulary should include, as required by implementation, semantic structural Events such as:

### Entity events

```text
EntityCreated
EntityUpdated
EntityDeactivated
```

### Relation events

```text
RelationCreated
RelationUpdated
RelationDeactivated
```

### Resource/state events

```text
ResourceChanged
StateVariableChanged
```

### Job lifecycle events

```text
JobCreated
JobActivated
JobPaused
JobCompleted
JobFailed
JobCancelled
```

### Information events

```text
InformationCreated
```

Additional generic structural Event types may be introduced deliberately when the core state model requires them.

The exact initial list is not required to be frozen before implementation proves which structural types are necessary. The accepted rule is that Events should describe generic simulator semantics clearly enough for replay, debugging, analytics, and UI inspection without embedding scenario domains into core.

For example, employment remains representable as:

```text
RelationCreated
    relation_type = employed_by
```

rather than introducing:

```text
EmployeeHired
```

Likewise a server restart, election result, marriage, or shelter construction must not require a corresponding domain Event class in core.

## Decision 4: Event is broader than accepted WorldEffect

Not every historically meaningful Event corresponds to a state-mutating `WorldEffect`.

GRASS history may also contain semantic/audit Events such as, when materially useful:

```text
ActionProposed
ActionAttempted
ActionRejected
ActionFailed
ActionSucceeded
ActorRefused
DecisionMade
ProviderChanged
ScenarioOccurrenceTriggered
OperatorIntervention
```

This vocabulary is illustrative and versionable rather than a frozen mandatory list.

Such Events may be important for replay context, observability, analysis, causation tracing, or audit while producing no direct mutation in the main reality projection.

Conceptually there are therefore two useful categories:

```text
state-transition Events
historical/semantic Events
```

This distinction need not require an inheritance hierarchy in code.

A `WorldState` reducer may legitimately ignore a historical Event that has no authoritative state effect, while another projection (audit timeline, analytics, actor history, provenance graph) may consume it.

## Decision 5: Event types are versioned independently

Each Event type has its own payload version:

```text
event_type = ResourceChanged
event_version = 1
```

A later incompatible payload change may introduce `ResourceChanged` version 2 without forcing one global schema migration/version bump across unrelated Event types.

Reducers/readers must explicitly support the Event versions they consume. Historical Event payloads are not rewritten in place merely because a newer version exists.

## Decision 6: Payloads support deterministic reduction without becoming snapshots

The Event envelope is stable; `payload` is typed/versioned according to `event_type`.

A state-transition Event payload must contain enough authoritative information for deterministic reduction. It should not require re-running the original planner, resolver, GEL mechanic, LLM, or random decision in order to reconstruct state.

At the same time, Events should not routinely duplicate complete `WorldState` snapshots. Snapshots/checkpoints remain separate reconstruction optimizations.

Exact per-type payload contracts are deferred to implementation.

## Decision 7: Provenance is mandatory

Every Event has `provenance` describing where the authoritative fact originated.

Conceptually:

```text
Provenance
    source_kind
    source_ref?
    metadata?
```

Possible source kinds include, as appropriate:

```text
ACTOR
SCENARIO_RULE
WORLD_RESOLVER
ENGINE
OPERATOR
PROVIDER_CHANGE
```

The exact vocabulary is versionable.

Provenance may carry or reference relevant structured identifiers such as:

- actor/action proposal;
- decision point;
- plan/plan version/step;
- job;
- scenario event rule/occurrence;
- resolver/provider binding;
- model/provider metadata;
- operator intervention;
- run/configuration metadata.

Do not place every possible provenance attribute as a top-level optional Event field.

Private chain-of-thought is never required provenance.

## Decision 8: Causation and correlation are explicit but not inferred from sequence

`causation_refs` is optional and plural because one transition/fact may depend on multiple material sources.

Conceptually:

```text
CauseRef
    kind
    id
```

A cause reference may identify a relevant Event, Job, ActionProposal, DecisionPoint, scenario occurrence, operator action, or another durable/traceable source as defined by the corresponding schema.

GRASS must not fabricate causal links merely from temporal or sequence adjacency.

`correlation_id` is optional trace/observability metadata used to group a larger process that spans multiple transitions, for example a conversation, job lifecycle, interaction, or operator workflow. It has no independent authority over `WorldState`.

## Decision 9: Same-time semantics remain separate from append order

Several transitions may occur at the same logical timestamp.

The scheduler first gathers all current entries due at that time, identifies interacting/conflicting groups, and resolves them coherently. Independent components may become separate transitions; interacting components may become one joint transition.

After those transitions are semantically established, the EventStore may need a stable append sequence. That technical ordering does not retroactively impose world causality among same-time independent transitions.

True causal ordering at one logical timestamp must come from explicit transition/event semantics, causation references, or a committed state dependency, not from arbitrary queue/append order.

## Decision 10: Genesis becomes normal immutable history

`WorldDefinition.initial_conditions` remain declarations rather than Events.

When a run starts, the engine validates/materializes them through a genesis transition (or a small set of explicitly defined initialization transitions) that emits normal immutable Events, for example structurally:

```text
SimulationInitialized?
EntityCreated
RelationCreated
ResourceInitialized / ResourceChanged
StateVariableChanged
...
```

The exact genesis Event vocabulary is deferred, but after initialization the resulting history follows the same immutability, branch, sequence, provenance, transition, and replay rules as all later history.

## Decision 11: Immutability and replay

Committed Events are append-only and immutable.

Normal operation never updates or deletes an Event to change what happened. Corrections/experiments are represented by later Events where semantically appropriate or by branching/forking history.

Replay reconstructs an existing branch from persisted Events and deterministic reducers only. It does not re-call cognition providers, world resolvers, scenario random samplers, or GEL mechanics to rediscover already-recorded facts.

## Core invariants

The following are binding architecture rules:

```text
WorldEffect != Event

Event is immutable historical fact

Event history is append-only

Only accepted committed Events drive authoritative projections

One authoritative transition may emit multiple Events

All Events of one transition commit atomically

transition_id identifies the atomic commit boundary

sequence defines deterministic replay order, not causality

logical_time may be shared by many Events/transitions

scheduler same-time batches are ephemeral and are not Event structure

Event types are semantic and generic, not scenario-domain verbs

some Events may be historically meaningful but non-mutating

provenance is mandatory

causal relationships are explicit, not inferred from append order

replay consumes recorded Events and does not regenerate past resolution/cognition
```

## Consequences

### Positive

- Event history is directly useful for debugging, analysis, timelines, and UI without decoding opaque effect opcodes everywhere.
- Core remains domain-neutral.
- Atomic transition identity makes multi-Event commits explicit.
- Same-time concurrency is not confused with append ordering.
- Non-mutating facts such as refusal/failure can remain visible without forcing artificial state mutations.
- Independent Event-type versioning reduces migration coupling.
- Replay does not depend on original resolver/provider availability.

### Costs

- Core requires a maintained Event-type registry/schema set and corresponding reducers/projections.
- Some information overlaps conceptually with `WorldEffect`, so conversion from accepted effects/outcomes to semantic Events must be implemented carefully.
- Multiple projections may consume different subsets of Events.
- Causation/provenance discipline must be maintained rather than inferred automatically from log adjacency.

## Deferred details

This ADR intentionally does not freeze:

- exact serialized Event DTO/Pydantic schema;
- exact identifier formats;
- complete v0.1 Event-type catalog;
- exact payload of each Event type;
- EventStore/database technology;
- branch-prefix physical storage representation;
- whether `SimulationInitialized` is a distinct Event type;
- precise provenance/source-kind vocabulary;
- precise `CauseRef` vocabulary;
- correlation-ID generation policy;
- snapshot/checkpoint cadence;
- upcasting/migration implementation for historical Event versions.
