# ADR-0009: SimulationState projection and initial world-state contracts

- Status: Accepted
- Date: 2026-09-06

## Context

Slice 2 introduces the first authoritative state reconstructed from committed Event history. The design baseline already separates `WorldState`, `ExecutionState`, and `CognitionState`, but implementation requires precise initial lifecycle, identity, payload, and projection rules.

These rules must preserve atomic transitions and deterministic replay without moving scenario definitions, branching, execution, cognition, or world-resolution authority into the projection layer.

## Decision 1: Branch-origin projection position

`ProjectionPosition` describes the branch-origin history completely applied to one `SimulationState`. It is not the future ancestry-aware branch cursor or fork-position API.

```text
ProjectionPosition
    branch_id
    last_transition_ref?
    last_sequence
    logical_time?
```

For empty history, `branch_id` is present, `last_transition_ref` is absent, `last_sequence` is `0`, and `logical_time` is absent.

For non-empty history, the optional fields identify the last completely applied transition and `last_sequence` is that transition's final Event sequence. Position advances only after the complete transition projects successfully.

Slice 2 projects branch-origin transitions only. Inherited Events retain their original branch identities and sequences when ancestry is introduced later.

## Decision 2: Initial SimulationState boundaries

```text
SimulationState
    position
    world
    execution
    cognition
```

`WorldState`, `ExecutionState`, and `CognitionState` are distinct immutable projections of the same history. Slice 2 gives `WorldState` its initial Entity, Relation, Resource, and StateVariable contents. `ExecutionState` and `CognitionState` are intentionally empty immutable projection boundaries until their owning slices.

`ScheduledResolution` and other scheduler data are not part of any authoritative projection.

## Decision 3: Entity lifecycle

An `EntityCreated` Event creates one active Entity. `entity_type` is immutable. `EntityUpdated` replaces the complete properties value through `properties_after`; it does not merge or patch properties. Semantic content is deferred.

Duplicate creation, update of a missing or inactive Entity, deactivation of a missing Entity, and repeated deactivation are invalid history. No reactivation or deletion semantics exist in Slice 2.

Entity deactivation does not implicitly mutate Relations, Resources, or StateVariables. Such changes require explicit Events.

## Decision 4: Relation identity, participants, and lifecycle

A Relation has a stable `RelationId`, immutable `relation_type`, an active flag, properties, and an unordered immutable set of unique `(role, entity_id)` participant bindings.

At least one participant is required. Repeated roles for different Entities and multiple roles for one Entity are valid. An exact duplicate binding is invalid.

`RelationUpdated` replaces the complete participant set and properties through `participants_after` and `properties_after`. Relation update/deactivation follows the same strict active lifecycle rules as Entity update/deactivation.

All referenced Entities must exist in the final candidate state of the complete atomic transition. Core does not require referenced Entities to be active; scenario lifecycle and role constraints are deferred.

## Decision 5: Resource state

Resource identity is `(entity_id, resource_type)`; Slice 2 introduces no `ResourceId`.

`ResourceChanged` is an upsert carrying the authoritative resulting `quantity_after`, not a delta. Version 1 accepts exact built-in `int` or finite built-in `float` quantities. `bool`, NaN, and infinities are invalid. Negative quantities are structurally valid.

The associated Entity must exist in the final candidate transition state. Resource bounds, units, properties, ownership, reservations, and other scenario constraints are deferred.

## Decision 6: StateVariable state

Version 1 supports only explicitly tagged `WORLD` and `ENTITY` scopes:

```text
{"kind": "WORLD"}

{"kind": "ENTITY", "entity_id": "<opaque EntityId>"}
```

An `ENTITY` scope contains an `EntityId`. StateVariable identity is `(scope, state_variable_type)`. `StateVariableChanged` is an upsert carrying the complete immutable structured `value_after`.

An Entity-scoped value requires its Entity to exist in the final candidate state. Additional scope kinds, schema/type constraints, and deletion semantics are deferred.

## Decision 7: Initial version-1 world Event payloads

The initial generic Event payloads are:

```text
EntityCreated
    entity_id
    entity_type
    properties

EntityUpdated
    entity_id
    properties_after

EntityDeactivated
    entity_id

RelationCreated
    relation_id
    relation_type
    participants
    properties

RelationUpdated
    relation_id
    participants_after
    properties_after

RelationDeactivated
    relation_id

ResourceChanged
    entity_id
    resource_type
    quantity_after

StateVariableChanged
    scope
    state_variable_type
    value_after
```

All fields are required for version 1. Missing or extra fields are invalid. Payloads remain recursively immutable structured mappings in the generic Event envelope; Slice 2 does not introduce Event subclasses, a general Event registry, serialization, upcasters, or migration infrastructure.

## Decision 8: Atomic strict projection

Projection consumes complete `CommittedTransition` values. It validates and applies each transition to private candidate data and returns one new immutable `SimulationState` only after the complete transition succeeds.

Within one transition, more than one write to the same `EntityId`, `RelationId`, Resource key, or StateVariable key is invalid. Event sequence cannot choose between conflicting writes.

Structural cross-references are validated against the final candidate state, not intermediate Event order. A Relation, Resource, or Entity-scoped StateVariable may therefore reference an Entity created elsewhere in the same transition.

Unknown Event types, unsupported versions, malformed payloads, missing/extra fields, sequence gaps, wrong branches, and invalid lifecycle operations fail explicitly and publish no partial state.

Strict Event routing belongs at the `SimulationState` projection boundary. As later slices introduce known ExecutionState and CognitionState Events, those Events must be routed to the appropriate projection rather than rejected merely because `WorldState` does not consume them. Events unknown to all current projections must never be silently ignored.

## Consequences

### Positive

- Replay is deterministic and does not rerun producers.
- Projection cannot expose partial transition state.
- Full-result payloads avoid patch languages and reducer arithmetic.
- Event ordering cannot silently resolve conflicting same-transition writes.
- World, execution, and cognition authority remain distinct.
- Scenario constraints remain outside generic structural reduction.

### Costs

- Invalid world history fails loudly during projection.
- Full properties and participant sets are repeated in update Events.
- Initial StateVariable scope and Resource quantity vocabularies are intentionally narrow.
- A later engine coordinator must validate candidate transitions before commit when full world-resolution validation is implemented.

## Deferred details

- branch ancestry, shared-prefix replay, forks, and ancestry-aware cursors;
- WorldDefinition, SimulationRunConfig, InitialConditions, and genesis;
- scenario type registries, relation arity/role rules, resource bounds/units, and StateVariable schemas;
- Entity semantic content, ActorFacet, Information, and belief;
- Plans, Jobs, Observations, DecisionPoints, and substantive execution/cognition projections;
- reactivation, deletion, lifecycle cascades, Resource reservations, and additional StateVariable scopes;
- WorldEffects, resolver validation, scheduler behavior, and engine commit coordination;
- durable serialization, databases, snapshots, projection schema versions, upcasters, and migrations.
