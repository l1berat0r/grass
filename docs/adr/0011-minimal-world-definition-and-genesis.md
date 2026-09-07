# ADR-0011: Minimal WorldDefinition and genesis contracts

- Status: Accepted
- Date: 2026-09-07

## Context

Slice 4 introduces the first executable `WorldDefinition`, the separation of one
run's configuration from scenario semantics, and materialization of declarative
initial conditions into canonical Event history. ADR-0004 establishes these
boundaries but deliberately defers the exact data-transfer objects and genesis
Event vocabulary.

The initial contract must be strict enough to reject invalid scenario documents
before history is committed without introducing mechanics, execution, providers,
or schema languages owned by later slices.

## Decision 1: WorldDefinition schema version 1

`WorldDefinition` schema version 1 contains:

```text
WorldDefinition
    world_definition_id
    version
    schema_version
    vocabulary
        entity_types
        relation_types
        resource_types
        state_variable_types
    initial_conditions
        logical_time
        entities
        relations
        resources
        state_variables
    metadata
```

`WorldDefinitionId` is an opaque non-empty identifier. `version` is an opaque
non-empty semantic version string: core does not parse, normalize, or order it.
`schema_version` is a positive document representation version. Version 1 is the
only supported document schema in this slice.

Each vocabulary registry contains unique non-empty type names and may be empty.
Registries declare legal names only. They do not define property schemas,
relation role or arity constraints, Resource units or bounds, StateVariable
schemas, defaults, mechanics, Blueprints, or schema expressions.

The core loader consumes an already parsed mapping and performs no file I/O. It
strictly rejects missing fields, extra fields, unsupported schema versions,
malformed structured values, duplicate declarations, undeclared type usage, and
invalid references.

Initial Resource declarations use `quantity`; genesis translates it to the
existing `ResourceChanged.quantity_after` Event field. Initial StateVariable
declarations use `value`; genesis translates it to the existing
`StateVariableChanged.value_after` Event field.

## Decision 2: WorldDefinitionRef identity

The semantic identity of a WorldDefinition version is:

```text
WorldDefinitionRef(world_definition_id, version)
```

`schema_version` describes document representation and is not part of semantic
definition identity. It may be recorded separately for provenance and
reproducibility.

## Decision 3: Minimal SimulationRunConfig

Slice 4 `SimulationRunConfig` contains only `world_definition_ref`. Resolver
mode, provider bindings, random streams, execution options, and reproducibility
options remain owned by later slices. No opaque placeholder fields are added.

## Decision 4: SimulationInitialized Event

`SimulationInitialized` version 1 is a semantic historical Event that does not
mutate `WorldState`, `ExecutionState`, or `CognitionState`. Its payload is:

```text
SimulationInitialized
    world_definition_ref
        world_definition_id
        version
    world_definition_schema_version
```

The current projection boundary explicitly recognizes and validates this Event.
It remains strict for unknown Event types and unsupported versions. This slice
does not add a `RunState` or put the WorldDefinition reference in `WorldState`.

## Decision 5: Genesis transition

Every genesis transition begins with exactly one `SimulationInitialized` Event,
including a genesis transition for an empty world. Initial conditions are
materialized using the existing version-1 `EntityCreated`, `RelationCreated`,
`ResourceChanged`, and `StateVariableChanged` Event contracts.

Event order is deterministic:

1. `SimulationInitialized`;
2. `EntityCreated` Events;
3. `RelationCreated` Events;
4. `ResourceChanged` Events;
5. `StateVariableChanged` Events.

Declaration order is preserved within each category. Relation participants are
semantically unordered and are encoded in canonical `(role, entity_id)` order.
This ordering is replay/storage encoding only and does not express causality,
dependency, or an intermediate world state.

The caller supplies the `TransitionId` through a `TransitionRef` and supplies
every `EventId`. The complete Event ID sequence must contain exact `EventId`
values, be unique, and have exactly the required length. Slice 4 introduces no
ID generator, `RunId`, or identity-provider abstraction.

Genesis Events use builder-created `ENGINE` provenance that references the
WorldDefinition ID and records the semantic version and document schema version
as metadata.

The genesis builder validates the complete candidate initial world before it
returns a `TransitionToCommit`. It does not commit history. The EventStore
continues to enforce only generic structural history invariants.

## Consequences

- Empty worlds produce non-empty canonical genesis history without inventing a
  mandatory scenario object.
- Scenario declarations remain distinct from committed Events and runtime state.
- Replay can reconstruct genesis without loading the WorldDefinition or invoking
  providers, mechanics, randomness, or resolution.
- The semantic WorldDefinition identity is stable across representation-schema
  concerns.
- Later schema versions can add mechanics and richer definition constraints
  without placing placeholders in version 1.

## Deferred details

- JSON, YAML, or another physical file/serialization format;
- durable definition repositories, replacement prevention, and migrations;
- run identity, lifecycle coordination, and atomic root registration;
- production Event/Transition ID generation;
- Actor facets, Information, and Commitments in initial conditions;
- property schemas, relation role/arity rules, Resource units/bounds, and
  StateVariable schemas/defaults;
- mechanics, Blueprints, ScenarioEventRules, scheduler behavior, GEL, world
  resolution, providers, and later SimulationRunConfig fields.
