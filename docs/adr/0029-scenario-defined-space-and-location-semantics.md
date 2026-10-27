# ADR-0029: Scenario-defined space and location semantics

- Status: Draft
- Date: 2026-10-15

## Context

Slice 18 actor-capable composition now depends on stable generic spatial semantics for `MOVE`, passive perception, recipient selection, actor interaction, and later scenario mechanics.

GRASS must not hard-code scenario-domain concepts such as room, building, city, vehicle, grid cell, or zone. At the same time, location cannot remain an opaque Entity property or an arbitrary scenario-defined Relation because core mechanics need one unambiguous spatial authority model.

This ADR records the accepted Slice-17.2 direction so far. It remains Draft until the remaining mutation, Event, genesis, query, and mechanic-integration decisions are resolved.

## Decision 1: Space is a first-class scenario-defined abstraction

`Space` is distinct from Entity and Relation.

A WorldDefinition may author simple spaces as stable identifiers:

```json
{
  "spaces": [
    "warsaw",
    "acme-building",
    "server-room"
  ]
}
```

or use richer object definitions:

```json
{
  "space_id": "server-room",
  "location_id": "acme-building",
  "properties": {
    "floor": 2,
    "security_zone": "restricted"
  }
}
```

Package loading normalizes both forms into one semantic SpaceDefinition model.

Conceptually:

```text
SpaceDefinition
    space_id
    initial location_id?
    properties
```

`space_id` is a stable scenario-defined identifier. `properties` is scenario-defined structured data. Core does not assign built-in meaning to values such as `floor`, `security_zone`, geometry, coordinates, adjacency, or visibility unless a later accepted contract explicitly does so.

The simple string form is equivalent to a SpaceDefinition with no scenario properties and no authored parent/root location.

A scenario may separately model an Entity corresponding to a place when that place also needs ordinary Entity semantics, but Entity and Space are not implicitly the same object.

## Decision 2: `location_id` is the single first-class representation of `located_in`

GRASS uses one spatial containment/location semantic: `located_in`.

Its canonical first-class state representation is `location_id`. The architecture does not introduce a parallel `SpatialMembership` model, and a generic scenario Relation named `located_in` is not a second source of spatial truth.

Conceptually:

```text
EntityState
    ...
    location_id: SpaceId

SpaceState
    space_id
    location_id: SpaceId?
```

For Entity:

- `location_id` is required;
- every Entity exists in one direct Space;
- the referenced Space must exist under the accepted lifecycle/reference rules.

For Space:

- `location_id` is first-class runtime state and may change during a run;
- `location_id = null` is permitted for a root Space;
- otherwise it identifies the one direct containing Space.

An authored SpaceDefinition `location_id` supplies the initial runtime `SpaceState.location_id`; it is not buried inside opaque `properties`.

A generic Relation may still use the scenario-defined string `located_in` for unrelated authored domain semantics, but core spatial algorithms do not interpret that Relation as location. There is only one canonical spatial authority source: first-class `location_id` state.

## Decision 3: Direct location is canonical; enclosing spatial context is derived

Only the direct `location_id` is canonical state.

For example:

```text
Alice.location_id = server-room
server-room.location_id = acme-building
acme-building.location_id = warsaw
warsaw.location_id = null
```

Core/scenario mechanics may derive the enclosing chain from these direct links. The engine does not duplicate all ancestors onto Alice or onto the child Space.

Therefore moving a containing Space can change the effective enclosing context of all nested subjects without rewriting each nested Entity or Space:

```text
Alice -> vehicle-cabin -> warsaw

vehicle-cabin.location_id changes to poznan

Alice -> vehicle-cabin -> poznan
```

Alice's direct canonical `location_id` remains `vehicle-cabin`.

The exact higher-level query vocabulary for direct location versus transitive containment/reachability remains to be fixed later in this ADR.

## Decision 4: Cyclic Space containment is optional world semantics

Ordinary worlds default to acyclic Space containment.

WorldDefinition may explicitly opt into cyclic Space containment through a world-level spatial policy flag, conceptually:

```text
SpatialPolicy
    allow_cycles: bool = false
```

The exact final serialization placement may be refined with the WorldDefinition schema work, but the semantic choice belongs to WorldDefinition rather than SimulationRunConfig because it changes what constitutes a valid world.

When `allow_cycles = false`, accepted initial state and every later Space relocation must reject a containment cycle.

When `allow_cycles = true`, cycles such as the following are structurally valid:

```text
A.location_id = B
B.location_id = C
C.location_id = A
```

Core traversal must be cycle-safe regardless of policy. Algorithms following `location_id` links must track visited Space identities and terminate on revisit rather than relying on eventual arrival at a root. The option therefore adds unusual world semantics but must never permit an infinite engine traversal.

Because each Space has at most one direct `location_id`, enabling cycles does not create an unrestricted multi-parent graph. It creates a functional directed graph in which each Space has zero or one outgoing containment edge; components may contain a cycle with trees feeding into it.

Exact semantic answers for unusual self-reachability questions such as whether a cyclic Space should be considered transitively "inside itself" are deliberately not frozen yet. Direct location remains unambiguous.


## Decision 5: Location mutation uses one closed candidate path for Entity and Space

Changing direct spatial state uses one explicit closed world-mutation contract for both Entities and Spaces rather than separate mutation systems.

Conceptually:

```text
SetLocationEffect
    subject_ref
    location_id_after
```

where the subject is a typed spatial subject reference:

```text
SpatialSubjectRef
    kind
        ENTITY | SPACE
    id
```

The effect remains transient candidate data under the existing WorldEffect authority boundary. It does not mutate WorldState directly.

Trusted validation/materialization converts an accepted location candidate into one semantic Event:

```text
LocationChanged
    subject_ref
    location_id_after
```

The common authority flow is:

```text
resolver / scenario mechanic
    -> SetLocationEffect
    -> candidate validation
    -> LocationChanged
    -> WorldState projection
```

Entity movement and Space movement share this same authoritative spatial consequence contract. GRASS does not introduce separate MoveEntityEffect and MoveSpaceEffect families merely because the producing mechanics differ.

For an Entity subject, location_id_after is mandatory and must reference an accepted existing Space; Entity location may never become null.

For a Space subject, location_id_after may reference another accepted Space or be null. Null makes the Space a root Space.

Direct self-location is always invalid:

```text
A.location_id = A
```

even when SpatialPolicy.allow_cycles = true. Longer containment cycles are accepted only when the world spatial policy allows them.

### MOVE is actor intent, not spatial write authority

The actor-facing primitive MOVE does not directly set location_id.

Conceptually:

```text
MOVE PlanStep / Job
    -> movement resolution mechanic
    -> typed movement result
    -> trusted movement contract
    -> existing Job outcome
    -> optional SetLocationEffect
```

Therefore:

```text
MOVE
    = actor-facing movement intent

SetLocationEffect
    = proposed authoritative spatial consequence
```

An actor cannot gain arbitrary spatial mutation authority merely by naming a target in a MOVE PlanStep.

A scenario mechanic may relocate a Space by producing the same SetLocationEffect with a SPACE subject. No actor-facing MOVE_SPACE primitive is introduced.

### LocationChanged records direct location only

LocationChanged means that the subject's own canonical direct location_id changed.

Moving a containing Space may alter the derived enclosing spatial context of nested subjects, but GRASS does not generate synthetic descendant LocationChanged Events for those derived changes.

For example:

```text
Alice.location_id = vehicle-cabin
vehicle-cabin.location_id = warsaw
```

followed by:

```text
LocationChanged(
    subject_ref = SPACE(vehicle-cabin),
    location_id_after = poznan
)
```

changes Alice's derived enclosing chain to:

```text
Alice -> vehicle-cabin -> poznan
```

but Alice.location_id remains vehicle-cabin and no synthetic LocationChanged(Alice, poznan) is emitted.

> LocationChanged records only a change of a subject's direct location_id. Changes to transitive/enclosing location caused by movement of an ancestor Space are derived and do not generate descendant location Events.

## Decision 6: MOVE is resolved through a world-defined MovementContract

MOVE remains a generic actor-facing primitive. Core does not hard-code walking, doors, vehicles, portals, teleportation, rooms, or other scenario movement vocabulary.

A world-defined typed movement mechanic resolves the attempt:

```text
MovementInput
    -> BUILTIN | GEL | IMPLEMENTATION
    -> MovementResult
```

The mechanic receives only explicitly bound typed inputs. It does not receive unrestricted WorldState/SimulationState, mutate location_id, create Events, or bypass the normal candidate-validation boundary.

The typed result is interpreted by the trusted movement adapter under a world-defined
MovementContract, conceptually:

```text
MovementContract
    contract_id
    input_schema
```

MovementResult itself has one standard core shape, defined by Decision 32. MovementContract
therefore does not define a second arbitrary result schema or an outcome/effect mapping DSL.

The semantic boundary is:

- the mechanic returns one existing ResolutionOutcome classification;
- it may also return one resolved destination for the moving subject;
- trusted preparation converts the outcome to the normal per-Job resolution outcome;
- trusted preparation converts a present resolved destination to zero or one
  SetLocationEffect for the moving subject;
- the requested MOVE target and the resolved authoritative destination are distinct concepts;
- blocked, failed, partial, redirected, portal-like, or otherwise unusual movement remains
  scenario-defined rather than core movement behavior.

A scenario may therefore resolve:

```text
requested target = server-room
resolved destination = security-checkpoint
```

without changing the meaning of the core MOVE primitive.

BUILTIN, GEL, and IMPLEMENTATION are alternate ways to compute the same typed MovementResult. More expressive mechanics do not gain additional simulation authority.

## Decision 7: MovementRule selection is world-owned, deterministic, and non-priority-based

A Plan/PlanStep expresses what the actor attempts, not which technical movement implementation should run. Actor/provider-authored MOVE steps therefore do not select implementation mechanics directly.

WorldDefinition owns movement-mechanic selection through a small rule hierarchy,
conceptually:

```text
MovementRule
    rule_id
    input_bindings
    movement_contract_ref
    mechanic_binding

ConditionalMovementRule(MovementRule)
    selector

DefaultMovementRule(MovementRule)
    # no selector
```

`MovementRule` is the shared semantic/execution contract. Conditional rules add the
matching condition; the default rule is the same kind of movement-resolution rule without a
selector.

The flow is:

```text
MOVE PlanStep / Job
    -> trusted MovementRule selection
    -> resolve explicit typed inputs
    -> BUILTIN | GEL | IMPLEMENTATION
    -> MovementResult
    -> MovementContract
    -> Job outcome + optional SetLocationEffect
```

Selectors exist only on ConditionalMovementRule and may use only accepted
generic/explicitly bound scenario information, such as the requested target, current direct
location, PlanStep parameters, Blueprint references/parameters, or scenario-defined
type/property values. Core does not compile in domain selector vocabulary such as walking,
room, vehicle, portal, or door.

Ordinary worlds may configure one explicit DefaultMovementRule for cases where no
ConditionalMovementRule matches. The default is not represented as an always-matching
selector and does not participate in ordinary matching.

Selection semantics are:

```text
exactly one applicable ConditionalMovementRule
    -> use it

no applicable ConditionalMovementRule
    + default_rule != null
    -> use DefaultMovementRule

no applicable ConditionalMovementRule
    + default_rule == null
    -> movement cannot be resolved

more than one applicable ConditionalMovementRule
    -> invalid ambiguity
```

Declaration order is not semantic priority. Slice 17.2 does not introduce numeric or
implicit rule priorities.

> ConditionalMovementRule selection must resolve to at most one applicable rule.
> Ambiguous matching is invalid rather than resolved by declaration order or implicit
> priority. DefaultMovementRule is consulted only after zero conditional matches and never
> participates in matching.


## Decision 8: Creation materializes complete initial spatial state

Creation and initial direct placement are one semantic fact.

Entity creation always materializes its mandatory direct location:

```text
EntityCreated
    entity_id
    entity_type
    location_id
    properties
```

Space creation always materializes the Space plus its initial direct container/root state:

```text
SpaceCreated
    space_id
    location_id?   # null = root Space
    properties
```

For Entity, location_id is required and must resolve to an accepted Space in the final candidate state of the atomic transition.

For Space, location_id may reference another accepted Space or be null for a root Space.

LocationChanged is not used to initialize newly created subjects. It records only a later change of an already-existing subject's direct location_id.

Therefore an authored genesis may conceptually materialize:

```text
SpaceCreated(earth, null)
SpaceCreated(warsaw, earth)
SpaceCreated(acme-building, warsaw)
SpaceCreated(server-room, acme-building)

EntityCreated(
    alice,
    Person,
    location_id = server-room,
    properties = ...
)
```

inside one atomic genesis transition.

All spatial cross-references in one atomic creation/genesis transition are validated against the final candidate state rather than Event append order. A newly created Entity or Space may therefore reference a Space created elsewhere in the same transition.

The same rule applies to runtime creation. A newly created Entity never has an authoritative intermediate state with no location. A newly created Space always has an explicit initial location value, including null when it is a root.

WorldDefinition/WorldPackage declarations are authoring input. Genesis materializes them into canonical Event history and WorldState. After creation, authoritative runtime location comes from canonical state/history rather than the original editable definition.

Because GRASS is still pre-stable and ADR-0026 already permits the current WorldDefinition schema reset, Slice 17.2 does not preserve backward compatibility by making EntityCreated.location_id optional. Existing internal local data that predates this contract is recreated rather than silently interpreted under weaker semantics.


## Decision 9: Space deactivation cascades over contained spatial subjects

Deactivating an active Space is allowed even when active Entities or child Spaces are contained within it.

The authoritative candidate consequence is conceptually:

```text
DeactivateSpaceEffect
    space_id
```

Space deactivation is not an actor-facing primitive. It is an authoritative consequence available only through trusted world/scenario semantics, for example an explicitly authorized ScenarioReactionRule/ReactionContract consequence mapping.

A mechanic still returns only its typed result. It does not call an imperative deactivate-space API or mutate WorldState directly.

Before commit, trusted core computes the complete active spatial closure rooted at the target Space using direct location_id links.

Conceptually:

```text
target Space
    + every active Space directly/transitively located in it
    + every active Entity directly/transitively located in it
```

The traversal is cycle-safe regardless of SpatialPolicy.allow_cycles.

The complete cascade is validated and committed atomically. For example:

```text
building
└── server-room
    ├── Alice
    └── rack-1
```

may materialize in one transition as:

```text
SpaceDeactivated(building)
SpaceDeactivated(server-room)
EntityDeactivated(Alice)
EntityDeactivated(rack-1)
```

There is no committed intermediate state in which an active Entity or active Space points through location_id to a newly inactive Space.

The invariant after every committed transition is:

> No active Entity or active Space may have a direct location_id that references an inactive Space.

Deactivation preserves the subject's last direct location_id as historical canonical state. Therefore inactive historical structures such as:

```text
Alice inactive -> server-room inactive -> building inactive
```

are valid and do not require synthetic LocationChanged Events.

The cascade does not automatically deactivate generic Relations, delete Resources, or clear unrelated StateVariables. Existing lifecycle/history semantics for those concepts remain separate. A scenario reaction may explicitly produce additional accepted consequences when its world semantics require them.

Active subjects may not be created in, moved into, or relocated under an inactive Space:

```text
MOVE Alice -> inactive-space
CreateEntity(location_id = inactive-space)
CreateSpace(location_id = inactive-space)
SetLocationEffect(..., inactive-space)
```

must not produce an accepted active spatial state.

Slice 17.2 keeps Space properties immutable after SpaceCreated. Runtime Space lifecycle is therefore conceptually:

```text
SpaceCreated
LocationChanged*
SpaceDeactivated
```

No generic SpaceUpdated contract is introduced by this slice.


## Decision 10: Spatial state is first-class WorldState data

Slice 17.2 extends the existing WorldState model rather than introducing a parallel spatial projection or separate EntityState hierarchy.

A dedicated opaque SpaceId is introduced alongside existing identifiers such as EntityId and RelationId.

Conceptually:

```text
SpaceId
    opaque stable identifier of a persistent Space
```

SpaceId and EntityId remain distinct identifier types even if their underlying authored string values happen to be equal. A scenario may therefore deliberately model both:

```text
SpaceId("acme-building")
EntityId("acme-building")
```

when the place and the domain Entity are separate concepts.

The existing Entity value gains mandatory direct location state:

```text
Entity
    entity_id: EntityId
    entity_type: str
    location_id: SpaceId
    properties
    active: bool
```

A new first-class immutable Space value is added:

```text
Space
    space_id: SpaceId
    location_id: SpaceId | None
    properties
    active: bool
```

Space properties are immutable structured scenario-defined data after creation. Spatial relocation is represented only through LocationChanged and therefore changes location_id rather than properties.

WorldState gains one additional canonical mapping:

```text
WorldState
    entities: Mapping[EntityId, Entity]
    spaces: Mapping[SpaceId, Space]
    relations: Mapping[RelationId, Relation]
    resources: ...
    state_variables: ...
```

Space belongs to WorldState because it is objective modeled world reality, not execution or cognition state.

### SpatialSubjectRef is a typed closed union

The conceptual generic kind/id shape is implemented as a closed typed union:

```text
EntitySpatialRef
    entity_id: EntityId
    kind = ENTITY

SpaceSpatialRef
    space_id: SpaceId
    kind = SPACE

SpatialSubjectRef =
    EntitySpatialRef
    | SpaceSpatialRef
```

SetLocationEffect and LocationChanged use SpatialSubjectRef.

This avoids invalid combinations such as a SPACE kind paired with an EntityId and keeps spatial authority strongly typed.

### WorldState owns structural invariants, not world policy

WorldState/projection validates structural consistency that must hold for every accepted world:

- every Entity.location_id references an existing Space;
- every non-null Space.location_id references an existing Space;
- a Space never directly references itself;
- an active Entity references an active direct Space;
- an active Space with a non-null parent references an active direct Space;
- inactive Entities and Spaces may preserve location references to inactive Spaces;
- referenced Spaces still exist even when inactive because deactivation is not deletion.

WorldState does not decide whether longer Space-containment cycles are permitted.

Cycle permission belongs to WorldDefinition spatial policy:

```text
candidate validation
    + WorldDefinition.spatial_policy
    -> accepted / rejected
```

This preserves the projection boundary:

```text
WorldState
    structural invariants

WorldDefinition-aware candidate validation
    scenario/world policy invariants
```

A canonical WorldState must therefore be capable of representing a cyclic containment graph when the active WorldDefinition explicitly permits one.


## Decision 11: Spatial mechanic access uses bounded query capabilities over an immutable invocation view

Spatial mechanics do not receive unrestricted WorldState/SimulationState access.

GRASS supports both resolved value bindings and bounded read-only spatial query bindings.

Resolved value bindings are appropriate when all arguments are known before mechanic invocation.

Bounded query bindings are appropriate when the mechanic must decide dynamically which spatial subject or Space to inspect during execution.

Conceptually:

```text
SpatialQueryCapability
    direct_location(subject_ref)
    enclosing_spaces(subject_ref)
    is_within(subject_ref, space_id)
    space_property(space_id, property_name)
```

These are pure read-only capabilities. They do not expose Event history, cognition, scheduler state, arbitrary resources, unrestricted world traversal, mutation, Event creation, or commit authority.

The mechanic binding declares its available spatial query surface statically. Query arguments such as subject_ref or space_id may be dynamic at runtime, but the available query operations and readable Space property names are declared before invocation.

For example, a mechanic may be authorized for:

```text
SpatialQueryBinding
    direct_location: enabled
    enclosing_spaces: enabled
    is_within: enabled
    readable_space_properties:
        - security_zone
        - floor
```

A GEL mechanic may then dynamically inspect:

```text
spatial.space_property(target_space, "security_zone")
```

but may not read an undeclared property such as:

```text
spatial.space_property(target_space, "secret_code")
```

The invariant is:

> Query arguments may be dynamic, but the mechanic's readable semantic surface is declared statically.

The same capability declaration principle applies to BUILTIN, GEL, and IMPLEMENTATION mechanics.

### Immutable invocation spatial view

All spatial queries within one mechanic invocation read the same immutable authoritative base state captured for that invocation.

Conceptually:

```text
InvocationSpatialView
    = authoritative base state at invocation start
```

A mechanic does not observe candidate effects that it has proposed during the same invocation.

For example, if movement resolution starts with:

```text
Alice.location_id = room
```

and the mechanic's eventual result maps to:

```text
SetLocationEffect(Alice, corridor)
```

then every spatial query made during that invocation still observes Alice in room.

This preserves deterministic pure-function reasoning and prevents mechanic behavior from depending on partially materialized candidate state.

## Decision 12: Core spatial query semantics are cycle-safe and preserve canonical topology

Slice 17.2 keeps ENCLOSING_SPACES as a first-class spatial query operation.

For an Entity:

```text
Alice -> server-room -> acme-building -> warsaw -> null
```

the enclosing sequence is:

```text
ENCLOSING_SPACES(Alice)
    = [server-room, acme-building, warsaw]
```

For a Space, traversal begins from its direct parent and never includes the subject Space itself.

When a cycle is encountered, each Space appears at most once and traversal stops before the first repeated Space.

For example:

```text
A -> B -> C -> A
```

produces:

```text
ENCLOSING_SPACES(A)
    = [B, C]
```

not:

```text
[B, C, A]
```

IS_WITHIN is defined by membership in ENCLOSING_SPACES:

```text
IS_WITHIN(subject, space)
    = space in ENCLOSING_SPACES(subject)
```

Therefore:

```text
IS_WITHIN(A, A) = false
```

even when cyclic containment eventually reaches A again.

DIRECT_LOCATION returns only the subject's canonical direct location_id.

SPACE_PROPERTY reads one explicitly authorized property from one Space. Space properties do not inherit implicitly through enclosing Spaces.

If a world wants inherited or aggregate property semantics, its mechanic may explicitly traverse ENCLOSING_SPACES and compute that scenario-defined meaning.

## Decision 13: Spatial Query API exposes canonical topology without hiding inactive state

The read-only Query API exposes spatial concepts directly rather than a generic graph API.

The minimal semantic surface includes:

```text
get_spaces(...)
get_space(space_id)

get_direct_location(subject_ref)
get_enclosing_spaces(subject_ref)
is_within(subject_ref, space_id)
```

A Space query view exposes at least the canonical Space identity, direct location_id, properties, and active lifecycle state.

Direct location and enclosing location remain distinct Query concepts.

Inactive Entities and Spaces remain queryable.

For example, after a cascading deactivation:

```text
Alice inactive
    -> server-room inactive
    -> building inactive
```

get_direct_location(Alice) still returns server-room, and get_enclosing_spaces(Alice) still returns the canonical enclosing chain.

Spatial traversal does not silently filter inactive Spaces. Activity is returned as state rather than used to rewrite topology.

Similarly:

```text
is_within(Alice, building)
```

may remain true for inactive canonical state.

List-style queries such as get_spaces may support lifecycle filters, but topology queries such as get_enclosing_spaces do not use include_inactive switches that would change the meaning of the location graph.


## Decision 14: Pre-stable WorldDefinition schema remains version 1 while spatial authoring becomes explicit

Slice 17.2 changes the current pre-stable WorldDefinition representation without advancing
`schema_version`.

Under ADR-0026, `schema_version = 1` remains the single current pre-stable shape until the
first stable complete WorldDefinition representation is explicitly frozen. Earlier
internal schema-1 documents are not compatibility targets.

The current schema-1 WorldDefinition gains explicit world-level spatial and lifecycle
policies:

```text
spatial_policy
    allow_cycles: bool

lifecycle_policy
    allow_entity_reactivation: bool
    allow_space_reactivation: bool
```

Both policy sections and all listed fields are mandatory in the current strict
representation.

Worlds that use ordinary acyclic containment author `allow_cycles = false` explicitly.
Worlds that do not permit reactivation author both lifecycle flags as `false` explicitly.

The ordinary semantic policy values are therefore:

```text
allow_cycles = false
allow_entity_reactivation = false
allow_space_reactivation = false
```

but these are not loader fallbacks. Omitting `spatial_policy`, `lifecycle_policy`, or any
required policy field is a schema error. A serialized WorldDefinition must state the
complete policy semantics it uses.

Initial conditions gain Space declarations:

```text
initial_conditions
    logical_time
    spaces
    entities
    relations
    resources
    state_variables
```

Each initial Entity carries its mandatory direct location:

```text
InitialEntity
    entity_id
    entity_type
    location_id: SpaceId
    properties
```

Space authoring accepts the already-defined compact and expanded forms. A simple string
such as `"world"` normalizes to:

```json
{
  "space_id": "world",
  "location_id": null,
  "properties": {}
}
```

The expanded form may declare a parent Space and scenario properties:

```json
{
  "space_id": "office",
  "location_id": "building",
  "properties": {
    "floor": 2
  }
}
```

All forms normalize to one InitialSpace/SpaceDefinition semantic model before genesis
validation.

Conceptually, a current world document may therefore contain:

```json
{
  "schema_version": 1,
  "spatial_policy": {
    "allow_cycles": false
  },
  "lifecycle_policy": {
    "allow_entity_reactivation": false,
    "allow_space_reactivation": false
  },
  "initial_conditions": {
    "logical_time": 0,
    "spaces": [
      "world",
      {
        "space_id": "office",
        "location_id": "world",
        "properties": {}
      }
    ],
    "entities": [
      {
        "entity_id": "alice",
        "entity_type": "Person",
        "location_id": "world",
        "properties": {}
      }
    ],
    "relations": [],
    "resources": [],
    "state_variables": []
  }
}
```

WorldPackage format remains version 1. Only the semantic `world.json` representation is
changing; the package container boundary does not change.

Repository-maintained WorldDefinition documents, templates, examples, and fixtures are
migrated to the new current schema-1 shape together with the Slice-17.2 implementation.
No compatibility loader is added for the previous internal shape.

The design acceptance scenario also moves from an informal `Office: Location Entity`
convention to first-class Space semantics. `Office` is a Space, MOVE targets its SpaceId,
and every initial Entity receives an explicit `location_id`.


## Decision 15: Runtime Space creation is a normal world consequence with GRASS-controlled identity

Space creation is part of the closed authoritative world-effect model.

The candidate effect is:

```text
CreateSpaceEffect
    space_id: SpaceId
    location_id: SpaceId | None
    properties
```

and trusted materialization is:

```text
CreateSpaceEffect
    -> candidate validation
    -> SpaceCreated
    -> WorldState.spaces
```

Runtime Space creation is not a privileged imperative API and does not introduce a
Space-specific actor primitive.

Ordinary creation flows through the existing execution/world-semantics boundaries:

```text
Job
    -> world mechanic
    -> typed result
    -> trusted contract mapping
    -> GRASS allocates SpaceId
    -> CreateSpaceEffect
```

or:

```text
ScenarioOccurrence / ScenarioReaction
    -> scenario mechanic
    -> typed result
    -> trusted contract mapping
    -> GRASS allocates SpaceId
    -> CreateSpaceEffect
```

A mechanic/provider does not choose canonical runtime Space identity. Runtime Space IDs are
allocated by GRASS under the same engine-controlled identity principle used for other
runtime-created canonical simulation objects.

The mechanic result may describe the requested semantic creation data, for example initial
location and properties. The trusted layer allocates SpaceId before constructing the closed
CreateSpaceEffect candidate.

Genesis-authored Space IDs remain scenario-authored stable identifiers because they are
part of immutable WorldDefinition authoring rather than runtime identity generation.

Runtime creation obeys the same final-candidate spatial validation as genesis:

- the allocated SpaceId must be new;
- null location creates a root Space;
- a non-null location must reference an accepted active Space in the final candidate;
- direct self-location is invalid;
- longer cycles are validated against SpatialPolicy.allow_cycles;
- Spaces created in one atomic transition may reference other Spaces created in that same
  transition because cross-references are validated against the complete final candidate,
  not effect/Event ordering.

The generic actor primitive CREATE may causally lead to Space creation only when the
world-defined Job mechanic/contract maps that attempt to CreateSpaceEffect. CREATE itself
does not grant direct Space mutation authority.

## Decision 16: Entity and Space reactivation are optional explicit world lifecycle semantics

WorldDefinition owns whether inactive Entities and Spaces may be reactivated.

Conceptually:

```text
LifecyclePolicy
    allow_entity_reactivation: bool = false
    allow_space_reactivation: bool = false
```

LifecyclePolicy is separate from SpatialPolicy because Entity reactivation is not itself a
spatial rule.

When enabled, the closed world-effect/Event model includes:

```text
ReactivateEntityEffect
    entity_id

EntityReactivated
    entity_id
```

and:

```text
ReactivateSpaceEffect
    space_id

SpaceReactivated
    space_id
```

Reactivation is explicit and non-cascading.

For example:

```text
building inactive
└── room inactive
    └── Alice inactive
```

followed by:

```text
ReactivateSpaceEffect(building)
```

reactivates only building. room and Alice remain inactive.

A scenario may reactivate a larger structure by proposing multiple explicit reactivation
effects in one atomic candidate. Validation considers the complete final candidate rather
than effect/Event order.

ReactivateEntityEffect is valid only when:

- LifecyclePolicy.allow_entity_reactivation is true;
- the Entity exists and is inactive;
- its direct location is an active Space in the final candidate state.

ReactivateSpaceEffect is valid only when:

- LifecyclePolicy.allow_space_reactivation is true;
- the Space exists and is inactive;
- its preserved non-null parent is active in the final candidate state, or its location is
  null;
- the resulting topology satisfies SpatialPolicy.

Attempting to reactivate an already-active subject is invalid.

Deactivation preserves the last canonical location_id and reactivation restores activity
without changing that location_id. Therefore:

```text
deactivate
    -> location_id preserved

reactivate
    -> same location_id becomes active again
```

If scenario semantics require restoration at another location, the same atomic transition
may combine explicit reactivation with SetLocationEffect, provided the complete final
candidate is valid.

Space properties remain unchanged by reactivation. Reactivation restores lifecycle state;
it is not recreation, property replacement, or identity replacement.

The lifecycle models are therefore:

```text
Entity
    create -> active
    deactivate -> inactive
    reactivate -> active       # only when world policy permits
```

and:

```text
Space
    create -> active
    LocationChanged*
    deactivate -> inactive
    reactivate -> active       # only when world policy permits
```

A later deactivation/reactivation cycle may repeat whenever the relevant world policy
permits and each transition satisfies normal lifecycle validation.


## Decision 17: Atomic write conflicts are defined per authoritative semantic field

The projection/candidate model does not treat every write touching the same EntityId or
SpaceId as an automatic conflict.

For composite world objects, authoritative state is divided into explicit semantic write
dimensions.

For Entity:

```text
Entity
    identity / entity_type     # fixed by creation
    lifecycle                  # active
    location                   # location_id
    properties                 # complete properties value
```

For Space:

```text
Space
    identity                   # fixed by creation
    lifecycle                  # active
    location                   # location_id
    properties                 # fixed by creation in Slice 17.2
```

Within one atomic transition, more than one write to the same authoritative semantic field
of the same projected identity/key is invalid.

Writes to distinct semantic fields of the same identity may coexist only when their
combination is explicitly supported and their final meaning is independent of Event/effect
ordering.

Accepted examples include:

```text
ReactivateEntityEffect(Alice)
SetLocationEffect(Alice, office)
```

because lifecycle and location are separate dimensions, and:

```text
UpdateEntityEffect(Alice, properties_after=...)
ReactivateEntityEffect(Alice)
```

because the complete final candidate may restore lifecycle and replace properties
atomically.

Likewise:

```text
ReactivateSpaceEffect(room)
SetLocationEffect(room, building)
```

may restore and relocate the Space in one atomic candidate.

Conflicting examples remain invalid:

```text
SetLocationEffect(Alice, A)
SetLocationEffect(Alice, B)

ReactivateEntityEffect(Alice)
DeactivateEntityEffect(Alice)

UpdateEntityEffect(Alice, properties_after=X)
UpdateEntityEffect(Alice, properties_after=Y)
```

Creation is a special full-state write. CreateEntityEffect and CreateSpaceEffect establish
the complete initial canonical object, including active lifecycle and initial location.
Therefore creation may not be combined with another write to that newly created object's
lifecycle, location, or properties in the same transition.

For example:

```text
CreateSpaceEffect(A, location_id=X, ...)
SetLocationEffect(A, Y)
```

is invalid even though location is otherwise an independently writable dimension.

The same final-candidate principle applies to lifecycle preconditions. An operation that
would be invalid against the base state alone may be valid when another explicitly
composable effect in the same atomic candidate establishes the required final lifecycle
state. Event ordering never supplies semantic precedence.

Relation, Resource, StateVariable, Job, and other projected types keep their existing
conflict semantics unless a later accepted contract explicitly decomposes them into
independently composable semantic write dimensions.

The general invariant is:

> Within one atomic transition, more than one write to the same authoritative semantic
> field of the same projected identity/key is invalid. Multiple writes to distinct fields
> are allowed only when their combination is explicitly defined as composable and the
> complete final state is order-independent.


## Decision 18: Space-deactivation cascade is derived from the composed candidate topology

Space-deactivation cascade membership is not computed from the untouched base state and is
not determined by effect/Event ordering.

For one atomic candidate, trusted validation conceptually performs these semantic phases:

```text
authoritative base state
    + explicit topology-changing candidate writes
        CreateEntityEffect / CreateSpaceEffect
        SetLocationEffect
    -> candidate spatial topology

candidate spatial topology
    + DeactivateSpaceEffect roots
    -> cycle-safe contained active closure
    -> derived lifecycle deactivation writes

explicit + derived writes
    -> semantic-field conflict validation
    -> complete final-candidate validation
```

These are validation semantics, not a persisted execution order. Events remain deterministic
history encoding and do not acquire mutation precedence.

Therefore an explicit relocation can remove a subject from a Space's deactivation closure
within the same atomic transition.

For example:

```text
building
└── Alice

SetLocationEffect(Alice, outside)
DeactivateSpaceEffect(building)
```

composes a candidate topology in which Alice is no longer contained by building. The
deactivation closure therefore does not derive an Entity-deactivation write for Alice, and
Alice may remain active if the complete final candidate is otherwise valid.

The same applies to nested Spaces:

```text
building
└── room

SetLocationEffect(room, other-building)
DeactivateSpaceEffect(building)
```

may preserve room as active under other-building because room is outside the closure in the
composed candidate topology.

Conversely, lifecycle effects do not remove subjects from spatial closure. For example:

```text
DeactivateSpaceEffect(building)
ReactivateEntityEffect(Alice)
```

with Alice still spatially contained in building derives a cascade write setting
Alice.lifecycle inactive. The explicit reactivation writes the same semantic lifecycle
field to active, so the candidate is invalid under Decision 17.

Likewise, creating a new active Entity or Space under a Space that is deactivated in the
same transition causes that new subject to enter the candidate closure. Because creation is
a full-state write including active lifecycle, the derived deactivation would conflict with
creation, making that candidate invalid rather than creating an immediately inactive
subject.

The invariant is:

> Explicit topology-changing writes are composed first into the candidate spatial topology.
> Space-deactivation closure is derived from that topology. Derived cascade lifecycle writes
> then participate in the same semantic-field conflict validation as explicit lifecycle
> writes.

This preserves one order-independent atomic meaning for combinations such as
relocate-and-destroy without introducing effect priorities.


## Decision 19: Non-lifecycle mutation of an inactive subject requires active participation in the candidate

Inactive Entity and Space state remains canonical historical state, but it is not an
ordinary editable dormant object.

A non-lifecycle mutation of an existing Entity or Space is valid only when the subject
participates as active in the atomic transition. Active participation means either:

```text
subject is active in the authoritative base state
```

or:

```text
subject is inactive in the base state
    + explicit valid reactivation of that subject in the same atomic candidate
```

Therefore these candidates are invalid:

```text
# Alice is inactive in base state
SetLocationEffect(Alice, office)

# Alice is inactive in base state
UpdateEntityEffect(Alice, properties_after=...)

# room is inactive in base state
SetLocationEffect(room, building)
```

These candidates may be valid when the relevant LifecyclePolicy permits reactivation:

```text
# Alice is inactive in base state
ReactivateEntityEffect(Alice)
SetLocationEffect(Alice, office)
```

```text
# Alice is inactive in base state
ReactivateEntityEffect(Alice)
UpdateEntityEffect(Alice, properties_after=...)
```

```text
# room is inactive in base state
ReactivateSpaceEffect(room)
SetLocationEffect(room, building)
```

The rule does not require the subject to be active in the final candidate. A subject that
is active in the base state may be mutated and deactivated atomically:

```text
# Alice is active in base state
SetLocationEffect(Alice, hospital)
DeactivateEntityEffect(Alice)
```

This represents one final state in which Alice is inactive and her preserved canonical
location_id is hospital.

Likewise, an active Space may be relocated and deactivated in one candidate when the
resulting topology and cascade semantics are valid.

Validation does not infer a semantic order such as "move first, deactivate second" or
"reactivate first, update second". Instead, active participation is a candidate-level
precondition:

```text
may_mutate_non_lifecycle(subject)
    =
        active_in_base_state(subject)
        OR explicit_valid_reactivation_in_candidate(subject)
```

The candidate is then validated as one complete order-independent final state under the
field-conflict, topology, lifecycle, and reference rules already defined.

The invariant is:

> Inactive state is preserved canonical history, not a mutable dormant object. An existing
> inactive Entity or Space may receive non-lifecycle writes only when the same atomic
> candidate explicitly and validly reactivates it. A subject active in the base state may
> receive non-lifecycle writes and be deactivated in that same candidate.


## Decision 20: Runtime creation uses transient CreationRefs resolved to deterministic GRASS-controlled identities

A mechanic may need to create multiple new objects that reference one another before any
canonical runtime identifiers exist.

Mechanics therefore use transient local CreationRef values inside one typed result/candidate
preparation. CreationRef is not a SpaceId, EntityId, EventId, or any other canonical
simulation identity.

Conceptually:

```text
CreationRef
    transient
    local to one mechanic result / trusted preparation
    non-canonical
    never persisted as world identity
```

A mechanic may choose CreationRef values only to express relationships among objects it
proposes to create.

For example:

```text
CreateSpaceSpec
    creation_ref = "building"
    location = ExistingSpaceRef(world)
    properties = ...

CreateSpaceSpec
    creation_ref = "room"
    location = CreatedSpaceRef("building")
    properties = ...

CreateEntitySpec
    creation_ref = "alice"
    entity_type = Person
    location = CreatedSpaceRef("room")
    properties = ...
```

The trusted preparation layer resolves the local creation graph and allocates canonical
identities:

```text
"building" -> SpaceId(...)
"room"     -> SpaceId(...)
"alice"    -> EntityId(...)
```

Only after that resolution does GRASS construct canonical closed effects:

```text
CreateSpaceEffect(
    space_id = allocated_building,
    location_id = world,
    ...
)

CreateSpaceEffect(
    space_id = allocated_room,
    location_id = allocated_building,
    ...
)

CreateEntityEffect(
    entity_id = allocated_alice,
    location_id = allocated_room,
    ...
)
```

CreationRefs may reference only creations in the same typed result/preparation context.
References to already-existing world objects use their normal canonical typed IDs.

The distinction is:

```text
CreationRef
    mechanic-chosen local handle
    transient
    scoped to one preparation
    not canonical

SpaceId / EntityId
    GRASS-controlled canonical identity
    persistent after commit
    used by Events and WorldState
```

### Deterministic allocation

Canonical runtime identity allocation occurs in trusted preparation, not inside the
mechanic/provider.

For an identical authoritative preparation context and identical ordered creation
specifications, GRASS must allocate the same canonical identities.

The architectural requirement is deterministic allocation; this ADR does not freeze the
concrete identifier encoding, UUID/hash scheme, or implementation algorithm.

The preparation context must bind allocation to authoritative facts sufficient to prevent
accidental dependence on process-global mutable counters or nondeterministic host state.
At minimum, allocation is scoped by the exact branch-visible base HistoryPosition, the
authoritative source/resolution context, and deterministic creation-spec ordering.

A retry of the same semantic preparation against the same authoritative base must therefore
not randomly produce different canonical IDs.

A candidate that fails validation or loses expected-head publication does not reserve
identity in authoritative state. If work is re-resolved against a different authoritative
base HistoryPosition, it is a new preparation context and need not preserve IDs from the
never-committed candidate.

Replay never reallocates runtime-created identities. It reads canonical IDs from committed
Events.

Branching follows normal history semantics:

- a branch forked after creation inherits the committed canonical IDs;
- a branch forked before creation may independently prepare a new creation and therefore
  allocate IDs from its own authoritative branch/preparation context.

CreationRef resolution happens before final candidate validation, so same-transition
cross-references use canonical typed IDs by the time closed WorldEffects and semantic
Events enter the normal validation/materialization path.


## Decision 21: Spatial/lifecycle WorldEffects and semantic Events use one closed canonical catalogue

After CreationRef resolution, the closed WorldEffect layer contains canonical typed
identities only. CreationRef never appears in WorldEffect, Event, or WorldState contracts.

The Entity/spatial portion of the closed WorldEffect catalogue is:

```text
CreateEntityEffect
    entity_id: EntityId
    entity_type
    location_id: SpaceId
    properties

UpdateEntityEffect
    entity_id: EntityId
    properties_after

DeactivateEntityEffect
    entity_id: EntityId

ReactivateEntityEffect
    entity_id: EntityId


CreateSpaceEffect
    space_id: SpaceId
    location_id: SpaceId | None
    properties

SetLocationEffect
    subject_ref: EntitySpatialRef | SpaceSpatialRef
    location_id_after: SpaceId | None

DeactivateSpaceEffect
    space_id: SpaceId

ReactivateSpaceEffect
    space_id: SpaceId
```

For SetLocationEffect, the typed subject determines the valid location value:

```text
EntitySpatialRef
    -> location_id_after must be SpaceId

SpaceSpatialRef
    -> location_id_after may be SpaceId | None
```

There is no UpdateSpaceEffect in Slice 17.2. Space properties remain immutable after
SpaceCreated; later Space relocation and lifecycle changes use their dedicated effects.

The corresponding semantic Event catalogue is:

```text
EntityCreated
    entity_id
    entity_type
    location_id
    properties

EntityUpdated
    entity_id
    properties_after

EntityDeactivated
    entity_id

EntityReactivated
    entity_id


SpaceCreated
    space_id
    location_id
    properties

SpaceDeactivated
    space_id

SpaceReactivated
    space_id


LocationChanged
    subject_ref
    location_id_after
```

SpaceCreated.location_id may be null for a root Space. EntityCreated.location_id is always
a SpaceId.

LocationChanged remains one semantic Event for both Entity and Space rather than splitting
into EntityLocationChanged and SpaceLocationChanged.

Its serialized subject reference is a strict tagged union, conceptually:

```json
{
  "kind": "ENTITY",
  "entity_id": "alice"
}
```

or:

```json
{
  "kind": "SPACE",
  "space_id": "room"
}
```

For a Space subject, LocationChanged.location_id_after may be null to make that Space a
root. For an Entity subject it may not be null.

Closed-effect materialization is conceptually:

```text
CreateEntityEffect       -> EntityCreated
UpdateEntityEffect       -> EntityUpdated
DeactivateEntityEffect   -> EntityDeactivated
ReactivateEntityEffect   -> EntityReactivated

CreateSpaceEffect        -> SpaceCreated
SetLocationEffect        -> LocationChanged
ReactivateSpaceEffect    -> SpaceReactivated
```

DeactivateSpaceEffect is the intentional non-1:1 case. Trusted candidate expansion first
derives the complete deactivation closure under Decision 18 and then materializes one
lifecycle Event for every subject whose active state changes:

```text
DeactivateSpaceEffect(building)
    -> derive closure
    -> SpaceDeactivated(building)
       SpaceDeactivated(room)
       EntityDeactivated(alice)
       ...
```

The transient DeactivateSpaceEffect itself is not persisted as a generic effect-applied
record. Canonical history records the resulting semantic lifecycle facts.

ReactivateSpaceEffect remains non-cascading and therefore materializes only the explicit
SpaceReactivated event for its target.

The authority boundary is:

```text
mechanic-facing typed creation result
    may contain CreationRef
        |
        v
trusted creation preparation
    resolves CreationRef -> canonical EntityId / SpaceId
        |
        v
closed WorldEffect
    canonical IDs only
        |
        v
semantic Event
    canonical IDs only
        |
        v
WorldState
    canonical IDs only
```

This decision freezes semantic type names and payload meaning for Slice 17.2. Event payload
version-number handling remains an independent Event-contract concern and is not changed
merely by this catalogue decision.


## Decision 22: Projection applies each committed transition as one semantic batch

Projection does not assign mutation precedence to Event sequence within one
CommittedTransition.

The projection boundary consumes the complete decoded transition and first classifies its
authoritative writes by projected identity and semantic field.

Conceptually:

```text
CommittedTransition
    -> decode all Events
    -> classify complete write-set
    -> validate write conflicts and lifecycle shape
    -> derive each final projected object from:
           authoritative base object
           + complete transition write-set
    -> validate complete structural candidate
    -> publish one new immutable SimulationState
```

For an existing Entity, the final candidate is derived independently per field:

```text
properties_after =
    EntityUpdated.properties_after
    OR base.properties

location_after =
    LocationChanged.location_id_after
    OR base.location_id

active_after =
    EntityReactivated -> true
    EntityDeactivated -> false
    otherwise base.active
```

Space uses the same principle for lifecycle and location; its properties remain creation-only
in Slice 17.2.

Therefore:

```text
# base: Alice inactive
EntityReactivated(Alice)
EntityUpdated(Alice, ...)
```

has the same meaning regardless of the storage order of those two Events. The complete
transition write-set establishes one final candidate in which Alice is active with the new
properties.

Likewise:

```text
# base: Alice active
LocationChanged(Alice, hospital)
EntityDeactivated(Alice)
```

projects to one inactive Alice whose preserved canonical location is hospital, independent
of Event order.

Creation remains a full-state write. EntityCreated and SpaceCreated establish the complete
initial projected object and conflict with same-transition writes to that new object's
lifecycle, location, or properties under Decision 17.

Relation, Resource, StateVariable, Job, cognition, and other projections may retain their
existing reducers where their accepted contracts are already order-independent. Any
projection that permits multiple independently composable writes to one identity must use
the same complete-transition principle rather than sequential mutation precedence.

### Projection validation versus WorldDefinition-aware candidate validation

Projection remains a deterministic reducer of committed history and does not require the
WorldDefinition to reconstruct WorldState.

Before commit, WorldDefinition-aware candidate validation decides whether a proposed
transition is legal under scenario semantics, including:

```text
SpatialPolicy.allow_cycles
LifecyclePolicy.allow_entity_reactivation
LifecyclePolicy.allow_space_reactivation
movement / mechanic / scenario rules
other world-defined constraints
```

After commit, projection validates universal structural/history invariants required to
reconstruct the recorded fact, including:

```text
known Event type/version/payload
valid complete-transition write-set
identity existence/creation rules
typed references exist in the complete candidate
Entity has a direct Space location
active Entity/Space direct location references an active Space
Space direct self-location is invalid
valid structural lifecycle transition shape
complete final WorldState structural consistency
```

Projection does not re-adjudicate whether the historical WorldDefinition permitted a
reactivation or a longer containment cycle. A committed EntityReactivated/SpaceReactivated
Event is an authoritative lifecycle fact; a committed cyclic topology must remain
projectable because cycle permission belongs to the immutable WorldDefinition used when the
transition was validated.

Thus:

```text
candidate validation
    knows WorldDefinition
    decides whether the transition may be committed

projection / replay
    knows committed Events
    deterministically reconstructs what was committed
```

Event sequence remains deterministic storage/replay encoding. It may be used for canonical
serialization and stable history order, but never to decide which same-transition
authoritative field write wins or which lifecycle precondition happens "first".

The invariant is:

> Projection applies one CommittedTransition as one semantic batch. For composite
> projected objects, final authoritative fields are derived from the base state plus the
> complete transition write-set, and Event sequence supplies no mutation precedence.


## Decision 23: Spatial/lifecycle Event payloads remain provisional version 1 before the first stable history contract

Slice 17.2 does not advance Event payload version numbers.

Under the amended ADR-0005 pre-stable Event policy, incompatible internal Event payload
changes replace the current version-1 shape in place until the first stable complete
Event-history contract is explicitly frozen.

Therefore the Slice-17.2 catalogue uses:

```text
EntityCreated v1
    entity_id
    entity_type
    location_id
    properties

EntityUpdated v1
EntityDeactivated v1
EntityReactivated v1

SpaceCreated v1
SpaceDeactivated v1
SpaceReactivated v1
LocationChanged v1
```

The previous internal EntityCreated v1 shape without location_id is unsupported once the
Slice-17.2 implementation lands. Pre-release local histories/snapshots using that older
shape are recreated rather than accepted through optional fields, upcasters, or a parallel
v2 contract.

New spatial/lifecycle Event types begin at version 1 because they are entering the same
pre-stable history contract.

This policy does not couple Event versions to WorldDefinition schema_version, storage
schema, WorldPackage format, GEL language version, SimulationRunConfig version, or CLI JSON
version. These remain separate version domains even when several happen to remain at 1
during pre-stable development.

At the first stable complete Event-history release, each then-current Event payload shape
becomes that Event type's definitive v1 contract. After that point, incompatible changes
advance only the affected Event type's event_version under normal ADR-0005 semantics.


## Decision 24: Mechanic-facing creation references are typed and may be used across the full same-result reference graph

CreationRef is not limited to spatial parent/location links. A mechanic may need other
same-result consequences to reference an object whose canonical runtime identity has not
yet been allocated.

Mechanic-facing typed results therefore use typed unresolved reference wrappers.

Conceptually:

```text
EntityResultRef
    ExistingEntityRef(EntityId)
    | CreatedEntityRef(CreationRef)

SpaceResultRef
    ExistingSpaceRef(SpaceId)
    | CreatedSpaceRef(CreationRef)
```

The wrappers are nominally typed. A CreatedEntityRef is valid only where an Entity reference
is required; a CreatedSpaceRef is valid only where a Space reference is required. GRASS
does not expose one untyped CreatedRef that can cross Entity/Space reference domains.

This allows one mechanic result to describe a complete internally linked creation graph.

For example:

```text
CreateEntitySpec
    creation_ref = "alice"
    entity_type = Person
    location = ExistingSpaceRef(world)
    properties = ...

CreateRelationSpec
    relation_type = employment
    participants =
        employee -> CreatedEntityRef("alice")
        employer -> ExistingEntityRef(acme)

ChangeResourceSpec
    entity = CreatedEntityRef("alice")
    resource_type = money
    quantity_after = ...

SetStateVariableSpec
    scope = CreatedEntityScope(CreatedEntityRef("alice"))
    state_variable_type = ...
    value_after = ...
```

Likewise, spatial creation can continue to use:

```text
CreateSpaceSpec
    creation_ref = "building"
    location = ExistingSpaceRef(world)

CreateSpaceSpec
    creation_ref = "room"
    location = CreatedSpaceRef("building")

CreateEntitySpec
    creation_ref = "alice"
    location = CreatedSpaceRef("room")
```

The exact mechanic-facing DTO names may evolve, but the semantic boundary is fixed:

> Any same-result reference that would normally require a canonical EntityId or SpaceId may
> reference a newly created object through the corresponding typed Created*Ref wrapper.

CreationRefs remain scoped to one typed result/preparation context. A Created*Ref may not
reference a creation from another mechanic result, another transition, or already committed
history.

Trusted preparation resolves the complete typed reference graph before constructing any
closed WorldEffect:

```text
typed mechanic result
    ExistingEntityRef / CreatedEntityRef
    ExistingSpaceRef  / CreatedSpaceRef
        |
        v
resolve complete CreationRef graph
allocate canonical EntityId / SpaceId
validate reference kinds
        |
        v
closed WorldEffects
    canonical IDs only
```

After resolution:

```text
CreateRelationEffect
ChangeResourceEffect
SetStateVariableEffect
CreateEntityEffect
CreateSpaceEffect
SetLocationEffect
...
```

contain only canonical typed identities. No unresolved Created*Ref or CreationRef may cross
the WorldEffect boundary.

The reference-resolution phase must fail explicitly when:

- a CreatedEntityRef points to a CreationRef that does not denote an Entity creation;
- a CreatedSpaceRef points to a CreationRef that does not denote a Space creation;
- a CreationRef is missing or duplicated within the preparation context;
- the same-result creation/reference graph cannot be resolved under the accepted typed
  contracts.

Resolution of the graph itself does not establish Event order or candidate mutation
precedence. It only replaces preparation-local handles with canonical typed identities
before the normal closed-effect validation path.


## Decision 25: WorldDefinition has a mandatory explicit movement section

The current strict pre-stable WorldDefinition schema includes a mandatory top-level
`movement` section.

Conceptually:

```text
movement
    contracts
    rules
    default_rule
```

The current serialized empty form is explicit:

```json
{
  "movement": {
    "contracts": [],
    "rules": [],
    "default_rule": null
  }
}
```

The section itself is mandatory even when a world deliberately provides no MOVE
resolution.

Therefore:

```text
movement section absent
    -> invalid WorldDefinition

movement present with:
    contracts = []
    rules = []
    default_rule = null
    -> valid WorldDefinition that deliberately provides no MOVE resolution
```

There is no loader-level implicit movement configuration and no built-in fallback merely
because the section is missing or empty.

Ordinary actor-capable worlds are expected to define movement rules; an empty movement
configuration is valid primarily for scenarios where MOVE is intentionally unsupported or
irrelevant.

The section owns scenario-authored MovementContract and MovementRule declarations plus the
explicit default movement rule/binding already accepted by Decision 7. It remains part of
WorldDefinition because it changes scenario semantics rather than run execution policy.

This decision freezes the mandatory placement and empty representation. The exact selector,
input-binding, mechanic-binding, and contract mapping DTO details may still be refined by
the following authoring decisions, provided they remain inside this explicit `movement`
section and preserve Decision 6/7 semantics.


## Decision 26: MovementRule is a shared base contract with conditional and default variants

MovementRule is not duplicated into two unrelated DTO families.

The accepted conceptual hierarchy is:

```text
MovementRule
    rule_id
    input_bindings
    movement_contract_ref
    mechanic_binding

ConditionalMovementRule(MovementRule)
    selector

DefaultMovementRule(MovementRule)
```

The base type owns the common movement-resolution contract. ConditionalMovementRule adds
only the selector used during deterministic rule matching. DefaultMovementRule adds no
selector because it is selected by fallback position, not by matching.

This hierarchy may be represented in implementation through inheritance, a discriminated
union over a shared base model, or an equivalent type-safe construction. The architectural
requirement is semantic rather than tied to one Python inheritance mechanism:

- shared fields are defined once;
- conditional rules require a selector;
- the default rule has no selector;
- the default rule is never evaluated as an always-matching conditional rule;
- both variants remain MovementRule values for common validation, provenance, mechanic
  invocation, and diagnostics.

The WorldDefinition movement section therefore contains:

```text
movement
    contracts: [MovementContract, ...]
    rules: [ConditionalMovementRule, ...]
    default_rule: DefaultMovementRule | null
```

A DefaultMovementRule keeps a rule_id because it is still material world semantics that may
be referenced in diagnostics, provenance, deterministic invocation context, and package
validation.

The default rule is not stored in rules and is not referenced from that collection. This
prevents one authored rule from participating both in conditional matching and fallback
selection.


## Decision 27: MovementSelector is a bounded declarative matcher, not a mechanic binding

ConditionalMovementRule.selector is a declarative selection contract owned by core
authoring semantics. It is not another BUILTIN, GEL, or IMPLEMENTATION mechanic.

Conceptually:

```text
immutable movement-selection context
    -> resolve selector-visible typed values
    -> MovementSelector
    -> MATCH | NO_MATCH
```

The selector answers only:

```text
Does this ConditionalMovementRule apply?
```

It does not resolve MOVE, compute MovementResult, create effects, invoke plugins, or gain
world-mutation authority.

Only after deterministic rule selection does GRASS execute the chosen rule's
`mechanic_binding`:

```text
MovementSelector
    -> select exactly one ConditionalMovementRule
       or fall back to DefaultMovementRule
    -> resolve input_bindings
    -> BUILTIN | GEL | IMPLEMENTATION mechanic
    -> MovementResult
    -> MovementContract
    -> trusted consequences
```

MovementSelector operates only on an explicit bounded selection context derived by trusted
code. It receives no unrestricted WorldState/SimulationState, EventStore, scheduler,
filesystem, network, or implementation/plugin handle.

Selectors are typed and declarative rather than arbitrary JSONPath/string expressions over
serialized state. Their initial operator/predicate vocabulary is intentionally left to the
next authoring decision, but it must remain bounded, deterministic, side-effect-free, and
sufficient to express generic scenario matching over explicitly exposed values such as
requested target, current direct location, PlanStep/Blueprint data, and declared
scenario-defined type/property values.

The selector itself has no random context and no failure mode equivalent to mechanic
execution. Invalid selector authoring is a WorldDefinition/package validation error;
runtime evaluation of a valid selector deterministically returns MATCH or NO_MATCH.

This separation preserves:

```text
selector
    = choose which movement semantics apply

mechanic
    = execute the chosen movement semantics
```

and prevents movement-rule discovery from recursively depending on arbitrary GEL/plugin
execution.


## Decision 28: Overlapping Space-deactivation cascades compose as one union closure

When one atomic candidate contains multiple accepted DeactivateSpaceEffect roots, trusted
candidate preparation computes all cascades against the same composed candidate spatial
topology and combines their contained active subjects as a set union.

Conceptually:

```text
candidate spatial topology
    + accepted DeactivateSpaceEffect roots
    -> cycle-safe closure(root_1)
       cycle-safe closure(root_2)
       ...
    -> union of contained active subjects
    -> at most one derived lifecycle deactivation write per subject
```

For example:

```text
building
└── room
    └── Alice

DeactivateSpaceEffect(building)
DeactivateSpaceEffect(room)
```

Both roots reach room and Alice, but the accepted candidate contains only one derived
lifecycle deactivation write for room and one for Alice.

The overlap itself is not a semantic-field conflict. Conflict detection operates after
cascade expansion on the deduplicated derived lifecycle write-set.

This matters because derived writes represent the same final lifecycle fact rather than two
independent attempts to write the same field. Treating overlap as duplicate writes would
make a valid nested destructive consequence fail merely because two independently valid
deactivation roots share descendants.

Explicit lifecycle writes remain distinct from derived cascade writes. Therefore an
explicit ReactivateEntityEffect/ReactivateSpaceEffect that targets a subject included in
the union closure still conflicts with the derived deactivation of that same lifecycle
field under Decision 17.

Likewise, explicit topology-changing writes are composed before every root closure is
calculated, exactly as defined by Decision 18. A subject relocated outside all root closures
is not included merely because it belonged to one of those roots in the base state.

The union operation applies to derived cascade membership/writes. This decision does not
require accepting duplicate identical DeactivateSpaceEffect entries for the same root in a
proposal; proposal-level duplicate-intent validation may reject such redundant explicit
entries independently.

Invariant:

> Multiple Space-deactivation roots are evaluated over one composed candidate topology.
> Their cascade closures are unioned, and each affected subject contributes at most one
> derived lifecycle deactivation write.


## Decision 29: MovementSelector uses a minimal closed boolean expression algebra

MovementSelector is a recursive closed declarative boolean expression.

The initial operator set is exactly:

```text
MovementSelector
    ALL(selectors...)
    | ANY(selectors...)
    | NOT(selector)
    | EQ(value_ref, literal)
    | IN(value_ref, literals...)
    | EXISTS(value_ref)
```

The operators have ordinary deterministic boolean semantics:

- `ALL` matches only when every child selector matches;
- `ANY` matches when at least one child selector matches;
- `NOT` negates one child selector;
- `EQ` compares one typed selector-visible value with one compatible literal;
- `IN` tests one typed selector-visible value against a finite non-empty collection of
  compatible literals;
- `EXISTS` tests whether an optional selector-visible value is present.

The initial algebra deliberately does not include separate NEQ, NOT_IN, comparison
operators, regex, glob matching, arithmetic, user functions, arbitrary method calls, or
embedded expressions. Simple negation composes through NOT, for example:

```text
NOT(EQ(...))
```

instead of a separate NEQ operator.

Operands are only:

```text
typed selector-visible value references
or
typed literals
```

They are never arbitrary JSONPath/string paths into serialized WorldState, Event payloads,
PlanStep structures, or package documents.

MovementSelector does not perform spatial/world queries by itself. Trusted selection-context
preparation resolves or exposes every allowed selector-visible value before evaluation.
For example, a future selector-visible reference may expose a derived boolean or SpaceId
that trusted code computed using accepted spatial semantics; the boolean expression layer
only compares/tests that value.

The exact selector-visible value catalogue is defined by Decision 31. This Decision freezes only the boolean expression algebra and its authority boundary.

The expression tree must be finite, structurally validated, deterministic, and
side-effect-free. Implementation may impose ordinary depth/node/list-size limits as
resource-safety constraints without changing selector semantics.


## Decision 30: MOVE request arguments live in PlanStep.parameters and bindings interpret them

GRASS does not add a dedicated core `requested_target`, `movement_target`, or other
MOVE-specific field to PlanStep.

PlanStep.parameters remains the generic location for primitive-specific requested action
arguments. A MOVE step may therefore author parameters such as:

```text
PlanStep
    primitive = MOVE
    parameters:
        target = "server-room"
        mode = "walk"
```

The exact parameter names and their scenario meaning are world/Blueprint semantics rather
than core MOVE field names.

Movement selection/context bindings and mechanic input_bindings may explicitly read named
PlanStep parameters and resolve/convert them into typed values used by MovementSelector or
MovementInput.

Conceptually:

```text
PlanStep.parameters["target"]
    -> trusted binding
    -> SpaceId("server-room")
    -> selector-visible value and/or MovementInput field
```

This preserves the distinction:

```text
PlanStep.parameters
    = what the actor/planner requested

movement bindings
    = how world semantics interpret and type that request

MovementSelector
    = which movement rule applies

movement mechanic
    = what actually happens
```

A MovementRule may therefore bind, for example:

```text
requested_destination
    <- STEP_PARAMETER("target")

movement_mode
    <- STEP_PARAMETER("mode")

current_location
    <- actor direct location
```

The trusted binding layer validates missing values, expected types, canonical references,
and any declared conversion/resolution rules before selector/mechanic execution. A raw
structured parameter does not automatically become a canonical SpaceId or EntityId merely
because its string value resembles one.

PlanStep.bindings remains a separate existing PlanStep field. This Decision does not merge
PlanStep.bindings with PlanStep.parameters or with MovementRule.input_bindings.
PlanStep.parameters carries action arguments; MovementRule/input bindings describe how
movement semantics obtain typed inputs from allowed request/state/context sources.

The invariant is:

> PlanStep.parameters carries primitive-specific requested action arguments. Movement
> selection and mechanic input bindings may explicitly read named parameters and resolve
> them into typed selector/mechanic inputs. MOVE introduces no dedicated requested-target
> field into the core PlanStep contract.


## Decision 31: MovementSelector sees a closed typed selection-context value catalogue

MovementSelector may reference only a small closed set of trusted selector-visible values.

The initial catalogue is:

```text
ACTOR_ID
ACTOR_ENTITY_TYPE
CURRENT_LOCATION
BLUEPRINT_ID
BLUEPRINT_VERSION
STEP_PARAMETER(name)
STEP_BINDING(name)
NAMED_VALUE(name)
```

Their meanings are:

- `ACTOR_ID` is the canonical EntityId of the actor whose MOVE Job is being resolved;
- `ACTOR_ENTITY_TYPE` is that actor Entity's scenario-defined entity_type;
- `CURRENT_LOCATION` is the actor Entity's canonical direct SpaceId at movement-selection time;
- `BLUEPRINT_ID` and `BLUEPRINT_VERSION` expose the PlanStep BlueprintRef when one is present;
- `STEP_PARAMETER(name)` reads the named entry from PlanStep.parameters;
- `STEP_BINDING(name)` reads the named entry from the existing PlanStep.bindings mapping;
- `NAMED_VALUE(name)` reads one explicitly declared typed derived value prepared by trusted movement-selection context binding.

MovementSelector does not gain generic object/property traversal from these references.
There is no selector syntax such as:

```text
actor.properties.foo
target.properties.security_zone
world.spaces[...]
```

Scenario-defined or derived values required for matching are exposed through named trusted
selection-context values instead.

For example, trusted context preparation may declare and resolve:

```text
NAMED_VALUE("target_security_zone")
    <- SPACE_PROPERTY(
           resolve STEP_PARAMETER("target") as SpaceId,
           "security_zone"
       )

NAMED_VALUE("target_is_within_building")
    <- IS_WITHIN(
           resolve STEP_PARAMETER("target") as SpatialSubjectRef,
           SpaceId("building")
       )
```

and the selector remains only:

```text
EQ(NAMED_VALUE("target_security_zone"), "restricted")
EQ(NAMED_VALUE("target_is_within_building"), true)
```

The binding/context-preparation layer obtains and derives values; MovementSelector only
compares/tests them.

### Optional and missing values

`ACTOR_ID`, `ACTOR_ENTITY_TYPE`, and `CURRENT_LOCATION` are required for an actor MOVE
selection context.

The following may be absent by normal semantics:

```text
BLUEPRINT_ID
BLUEPRINT_VERSION
STEP_PARAMETER(name)
STEP_BINDING(name)
NAMED_VALUE(name)
```

For NAMED_VALUE, absence is possible only when its declared binding itself yields an
optional value.

For a valid selector-visible reference whose runtime value is absent:

```text
EXISTS(ref) -> false
EQ(ref, literal) -> NO_MATCH
IN(ref, literals...) -> NO_MATCH
```

`NOT`, `ALL`, and `ANY` then compose those ordinary boolean results.

This missing-value behavior is distinct from invalid authoring. An unknown core value-ref
kind, an undeclared NAMED_VALUE name, an invalid binding, or a type-incompatible literal is
a WorldDefinition/package validation error rather than a runtime NO_MATCH.

### Type boundary

STEP_PARAMETER and STEP_BINDING source data remain generic StructuredValue at PlanStep
storage level. Trusted selection-context preparation validates/resolves the referenced value
against the typed selector contract before exposing it to MovementSelector.

For example:

```text
STEP_PARAMETER("target")
    raw value: "server-room"
    trusted resolution: SpaceId("server-room")
    exposed as typed selector-visible SpaceId
```

A raw string is never treated as a canonical SpaceId merely because the text matches an
existing identifier.

The initial selector-visible catalogue is deliberately small. Additional direct core refs
require an explicit architecture extension; scenario-specific values should ordinarily use
NAMED_VALUE rather than expanding core vocabulary.

Invariant:

> MovementSelector reads only the closed typed selection context. Trusted bindings may
> derive named values from explicitly authorized request/state/query inputs, but the
> selector itself performs no state traversal or query execution.


## Decision 32: MovementResult has one standard core shape

MOVE does not use an arbitrary world-specific result schema followed by
`outcome_mapping`/`consequence_mapping`.

Every movement mechanic returns the same typed core result:

```text
MovementResult
    outcome: ResolutionOutcome
    resolved_destination: SpaceResultRef | None
```

`ResolutionOutcome` is the existing closed resolution vocabulary:

```text
SUCCESS
PARTIAL
BLOCKED
FAILED
INTERRUPTED
```

The trusted movement adapter materializes the result as:

```text
MovementResult.outcome
    -> SubjectResolutionOutcome(job_id, outcome)

resolved_destination != None
    -> resolve SpaceResultRef to canonical SpaceId
    -> SetLocationEffect(
           subject_ref = EntitySpatialRef(actor_id),
           location_id_after = resolved_destination
       )
```

No movement mechanic returns WorldEffect or Event directly.

### Resolved destination semantics

A present `resolved_destination` means that the movement attempt produced a proposed
authoritative change of the actor's direct canonical location.

It is not narration, an intended target, or advisory metadata.

Therefore:

```text
resolved_destination != None
    -> proposed spatial relocation

resolved_destination == None
    -> no spatial relocation consequence
```

The presence of a destination is independent from the ResolutionOutcome classification.

For example:

```text
SUCCESS + server-room
PARTIAL + security-checkpoint
INTERRUPTED + corridor
BLOCKED + None
FAILED + None
```

are all natural results.

Core does not impose the stronger rule that only SUCCESS may relocate, nor that BLOCKED or
FAILED must always have a null destination. A scenario mechanic may model a failed or
blocked attempt that nevertheless changed location if that is the scenario's accepted
semantics. The outcome classifies the resolution; `resolved_destination` states whether
the accepted candidate contains a direct spatial consequence.

This keeps unusual movement semantics world-defined while preserving one universal
mechanic/result adapter contract.

### MovementContract responsibility

MovementContract now defines the typed input boundary needed by the selected movement
mechanic:

```text
MovementContract
    contract_id
    input_schema
```

The result type is not scenario-defined; it is always MovementResult.

A selected MovementRule supplies its input_bindings and mechanic_binding. Trusted
preparation resolves and validates those inputs against MovementContract.input_schema,
invokes BUILTIN/GEL/IMPLEMENTATION, validates the returned MovementResult, and then creates
the normal ResolutionOutcome/WorldEffect candidate data.

The requested action arguments remain separate from the result:

```text
PlanStep.parameters
    -> movement input bindings
    -> MovementInput
    -> mechanic
    -> MovementResult
```

This preserves the distinction between requested target and resolved destination.

Invariant:

> Movement mechanics return one standard typed MovementResult. Outcome projection and the
> optional SetLocationEffect are trusted core adapter semantics, not scenario-authored
> mapping rules.


## Decision 33: ValueBinding is a global typed read-only value-resolution contract

GRASS uses one global ValueBinding architecture concept rather than defining separate
movement-, reaction-, and perception-specific binding mechanisms.

Conceptually:

```text
ValueBinding
    = declarative recipe for resolving one typed value
```

Every ValueBinding has the same core invariants:

```text
deterministic
side-effect-free
typed
read-only
no unrestricted WorldState / SimulationState
no Event or WorldEffect creation
no commit authority
no ambient filesystem/network/process access
validated against an explicit usage context
```

ValueBinding is not a second GEL or general expression language. It answers primarily:

```text
Where does this value come from,
and how is it validated/resolved as the required type?
```

It does not provide arbitrary user computation. Computation belongs to the selected
mechanic, for example BUILTIN, GEL, or IMPLEMENTATION.

### BindingContext bounds readable authority

The global ValueBinding contract does not imply one global namespace containing every
possible source.

Each semantic usage defines a bounded BindingContext and the source/query vocabulary that
is legal in that context.

Conceptually:

```text
ValueBinding + MovementBindingContext
ValueBinding + ReactionBindingContext
ValueBinding + PerceptionBindingContext
...
```

The implementation need not use Python generics or these exact class names. The invariant is
that a binding is always validated and resolved relative to one explicit semantic usage
context.

For example:

```text
MovementBindingContext
    may expose:
        actor identity/type
        current direct location
        PlanStep parameters/bindings
        BlueprintRef
        declared bounded spatial queries

ReactionBindingContext
    may expose:
        matched semantic Event data
        declared reaction inputs
        explicitly authorized world/query values

PerceptionBindingContext
    may expose:
        actor
        OBSERVE request or Stimulus data
        explicitly authorized perception/query values
```

A source legal in one context is not automatically legal in another.

### Movement uses the global contract in two places

Movement rule authoring uses ValueBinding for both selector preparation and mechanic input
preparation:

```text
MovementRule
    selection_bindings:
        name -> ValueBinding

    input_bindings:
        mechanic_input_name -> ValueBinding
```

`selection_bindings` resolve named typed values exposed to MovementSelector through
`NAMED_VALUE(name)`.

`input_bindings` resolve the typed fields required by MovementContract.input_schema.

The same underlying ValueBinding machinery therefore supplies both paths:

```text
ValueBinding
    -> selection value
    -> NAMED_VALUE(name)
    -> MovementSelector
```

or:

```text
ValueBinding
    -> mechanic input field
    -> MovementInput
    -> mechanic
```

### Other scenario mechanics reuse the same contract

The `input_bindings` already accepted for ScenarioReactionRule and PerceptionRule use the
same global ValueBinding abstraction under their own bounded contexts.

This does not make movement-specific sources such as STEP_PARAMETER globally readable by
reaction/perception bindings. Reuse is at the value-resolution contract level; readable
authority remains usage-specific.

### Query capabilities remain explicit

A ValueBinding may use a bounded query operation only when that operation is explicitly
permitted by its BindingContext and declared capability surface. It never receives an
unrestricted state handle.

For spatial queries this preserves Decision 11:

```text
ValueBinding
    + usage BindingContext
    + declared SpatialQueryBinding
    -> typed value
```

### Failure boundary

Invalid binding authoring, unsupported source kinds, undeclared query capabilities, or
incompatible expected types are definition/package validation errors where they can be
detected statically.

Runtime absence remains an explicit typed/optional-value semantic defined by the binding
source and consuming contract; it is not silently converted into arbitrary defaults.

The exact initial ValueBinding leaf/source variants and serialized DTO shape remain the next
authoring decision.

Invariant:

> ValueBinding is the universal typed, deterministic, read-only value-resolution contract.
> Each semantic usage defines its own bounded BindingContext and permitted source/query
> vocabulary; ValueBinding never creates one unrestricted global readable-state namespace.

## Consequences

### Positive

- `MOVE`, perception, recipient selection, and later spatial mechanics can use one explicit location authority model;
- scenario authors keep domain vocabulary and arbitrary Space properties outside core;
- nested spaces model rooms/buildings/cities as well as moving containers such as vehicles without rewriting all contained Entities;
- Entity location cannot silently diverge between magic properties, Relations, and a separate membership subsystem;
- unusual cyclic/SF topologies remain possible without making them the default;
- cycle-safe traversal prevents pathological spatial topology from hanging the runtime;
- Entity and Space relocation share one closed validated spatial authority path;
- actor MOVE intent remains distinct from authoritative location mutation;
- movement behavior stays world-defined and replaceable through BUILTIN, GEL, or IMPLEMENTATION mechanics, while every movement mechanic returns the same core `MovementResult(outcome, resolved_destination)` and trusted preparation alone maps that result to `SubjectResolutionOutcome` plus optional `SetLocationEffect`;
- deterministic rule selection avoids hidden declaration-order semantics;
- moving a container/vehicle Space updates nested effective context without Event fan-out over every contained subject;
- creation never exposes an Entity without its mandatory direct location;
- genesis may create nested Spaces and located Entities atomically without relying on Event order;
- destructive scenario semantics may deactivate an entire nested spatial subtree/closure atomically;
- deactivation preserves historical spatial structure without synthetic relocation Events;
- spatial identity and state integrate directly into the existing WorldState model rather than creating a second authority projection;
- typed spatial references prevent Entity/Space identifier-kind mismatches;
- projection stays independent from WorldDefinition-specific cycle policy;
- mechanics can perform dynamic spatial inspection without receiving unrestricted WorldState;
- readable spatial capabilities and property dependencies remain explicit in mechanic authoring;
- all queries within one invocation observe one deterministic immutable spatial snapshot;
- cycle-safe enclosing/containment semantics are defined once in core and reused by mechanics and Query API;
- inactive spatial topology remains inspectable instead of being rewritten by presentation logic.

### Costs and constraints

- WorldState and WorldDefinition must gain explicit Space/location concepts rather than reusing only existing Entity/Relation state;
- every Entity must receive a valid initial location;
- Space relocation requires normal authoritative runtime semantics rather than editing WorldDefinition;
- enabling cycles removes assumptions that every containment walk reaches a root and requires visited-set traversal;
- query and mechanics code must distinguish direct `location_id` from derived enclosing context;
- the closed WorldEffect/Event/projection contracts must gain typed spatial mutation support;
- MovementRule authoring must avoid ambiguous overlapping selectors; MovementSelector is a bounded declarative core matcher rather than a BUILTIN/GEL/IMPLEMENTATION mechanic, using only the closed `ALL`/`ANY`/`NOT`/`EQ`/`IN`/`EXISTS` boolean algebra over the closed initial selector-visible catalogue `ACTOR_ID`, `ACTOR_ENTITY_TYPE`, `CURRENT_LOCATION`, `BLUEPRINT_ID/VERSION`, `STEP_PARAMETER`, `STEP_BINDING`, and trusted `NAMED_VALUE`; MOVE-specific request arguments remain in generic `PlanStep.parameters`; selector preparation and mechanic `input_bindings` use the global typed read-only `ValueBinding` contract under a bounded `MovementBindingContext`;
- mechanics that move Spaces or Entities must preserve the same validation boundary;
- EntityCreated and the new SpaceCreated Event contracts must carry initial spatial state;
- pre-stable local data using the earlier EntityCreated payload must be recreated rather than supported through optional compatibility fields;
- Space deactivation requires cycle-safe closure computation and atomic multi-subject lifecycle validation;
- generic Relation/Resource/StateVariable cleanup is not implied by spatial deactivation;
- existing Entity/Event/projection DTOs must be updated to carry mandatory SpaceId location data;
- WorldState gains a new spaces mapping and new cross-reference validation;
- candidate validation must retain access to WorldDefinition spatial policy because cycle legality is intentionally not encoded into projection construction;
- mechanic composition must validate declared spatial query capabilities and readable Space property names;
- GEL/BUILTIN/IMPLEMENTATION adapters need an invocation-scoped immutable SpatialQuery view rather than direct WorldState access;
- Query API/DTOs must expose Space inspection and direct/enclosing location semantics consistently with core traversal;
- the current strict WorldDefinition schema-1 document gains mandatory spatial_policy, mandatory lifecycle_policy, mandatory movement configuration, and initial Spaces/Entity location fields;
- repository-maintained worlds/examples must migrate atomically with the Slice-17.2 implementation instead of relying on compatibility parsing;
- runtime Space creation uses a first-class CreateSpaceEffect and GRASS-controlled identity allocation;
- Entity/Space reactivation extends the closed lifecycle effect/Event model only when enabled by WorldDefinition LifecyclePolicy;
- reactivation preserves canonical location_id and never implies automatic descendant reactivation;
- atomic conflict detection is field-aware for Entity/Space, allowing explicitly composable lifecycle/location/properties changes without Event-order semantics;
- Space-deactivation cascades are derived from the composed candidate topology, so explicit relocation may remove a subject from the closure while lifecycle conflicts remain explicit; multiple accepted cascade roots are unioned and each affected subject contributes at most one derived lifecycle deactivation write;
- inactive Entity/Space state is queryable historical state but not ordinarily mutable; non-lifecycle mutation requires base-state activity or same-candidate explicit reactivation;
- mechanics may link multiple runtime creations through transient CreationRefs, while GRASS resolves them to deterministic canonical IDs during trusted preparation;
- CreationRef is eliminated before the closed WorldEffect boundary; WorldEffects, semantic Events, and WorldState use canonical typed IDs only;
- the spatial/lifecycle effect and Event catalogue is explicit, with DeactivateSpaceEffect intentionally expanding to multiple semantic lifecycle Events;
- replay/projection applies the complete committed transition as one semantic write batch, so composable Entity/Space field changes never depend on Event sequence;
- WorldDefinition-aware candidate validation remains precommit authority, while projection rechecks only universal structural/history invariants needed for deterministic reconstruction;
- all current spatial/lifecycle Event payloads remain pre-stable `event_version = 1`; the older internal EntityCreated-v1 shape is unsupported rather than upcast;
- same-result references to newly created Entities/Spaces use typed `CreatedEntityRef` / `CreatedSpaceRef` wrappers across the full mechanic-facing reference graph, including Relation, Resource, StateVariable, and spatial consequences.

## Alternatives considered

### Represent location as a generic `located_in` Relation

Rejected because core would either need a magic interpretation of one scenario Relation type or every spatial mechanic would need to rediscover the same convention. It would also create ambiguity if another first-class spatial representation existed.

### Keep `location_id` inside generic Entity/Space properties

Rejected because `MOVE`, validation, perception, recipient selection, and Query need stable core semantics. A magic property name would be first-class semantics disguised as opaque data.

### Add separate SpatialMembership records beside `located_in`

Rejected because it would create two concepts for one spatial fact. `location_id` is the first-class canonical representation of the existing `located_in` semantic.

### Require an acyclic hierarchy unconditionally

Rejected as unnecessarily restrictive for deliberately unusual worlds. Acyclic containment remains the safe default while a WorldDefinition policy may explicitly permit cycles.

### Give every Space a mandatory parent

Rejected because root Spaces would require an artificial universal container. Entity location is mandatory; Space location is optional for roots.

### Let MOVE write Entity.location_id directly

Rejected because an actor-facing primitive expresses intent, not authority to mutate WorldState. Scenario mechanics must resolve the attempt and produce an accepted candidate spatial consequence through the normal validation/commit boundary.

### Use separate mutation/Event contracts for Entity movement and Space movement

Rejected because both operations change the same canonical semantic fact: subject.location_id. Different producing mechanics do not justify parallel authority models.

### Emit LocationChanged for every nested subject when an ancestor Space moves

Rejected because descendant enclosing location is derived from direct canonical location_id links. Synthetic descendant Events would duplicate derived facts, create potentially large Event fan-out, and falsely imply that each descendant's direct location changed.

### Permit direct self-location when cycles are enabled

Rejected because A -> A adds no material expressiveness beyond supported longer cyclic topologies and makes direct containment semantics needlessly degenerate.

### Put implementation mechanic bindings directly in actor-authored MOVE PlanSteps

Rejected because Plans should express actor intent rather than technical world implementation choices. Movement selection belongs to world semantics.

### Resolve overlapping MovementRules by list order or numeric priority

Rejected for Slice 17.2 because hidden/stacked priority semantics would make movement behavior harder to reason about. Ambiguous matching is invalid; a separate explicit default handles the ordinary fallback case.

### Initialize location with a separate LocationChanged after creation

Rejected because Entity location is mandatory canonical state. Splitting creation and placement would create an unnecessary intermediate semantic model and weaken the meaning of LocationChanged.

### Make EntityCreated.location_id optional for backward compatibility

Rejected because the project is pre-stable and the spatial contract intentionally requires every Entity to have a location. Compatibility with earlier internal local payloads is not worth weakening the invariant.

### Reject Space deactivation whenever active contents exist

Rejected because scenario mechanics need to represent destructive world changes such as collapse, explosion, removal, or destruction of a containing area. Atomic cascade semantics preserve the active-location invariant without forbidding those scenarios.

### Expose Space deactivation as a normal actor primitive

Rejected because Space destruction/removal is world/scenario authority, not a generic actor-facing action. Actor behavior may causally trigger scenario reactions, but the authoritative consequence is produced through trusted scenario-mechanic mapping.

### Clear descendant location_id values during Space deactivation

Rejected because location_id is historical canonical state and Entity location is otherwise mandatory. Inactive subjects may retain references to inactive Spaces without violating active-world invariants.

### Cascade Space deactivation into generic Relation/Resource/StateVariable cleanup

Rejected because those concepts have separate semantics and may remain historically meaningful. Spatial lifecycle does not imply generic deletion semantics.

### Put Space into a separate spatial projection

Rejected because Space is objective world reality and naturally belongs beside Entity, Relation, Resource, and StateVariable in WorldState. A separate spatial authority projection would duplicate world-state ownership.

### Represent Space identifiers as plain strings

Rejected because Space participates in canonical references, effects, Events, Query, and validation. A dedicated SpaceId preserves the same opaque-identifier discipline used elsewhere in core.

### Use one generic kind/id SpatialSubjectRef

Rejected because a generic identifier field would permit invalid type combinations. A closed EntitySpatialRef | SpaceSpatialRef union makes the reference structurally valid.

### Validate allow_cycles inside WorldState construction

Rejected because allow_cycles is WorldDefinition policy, not a universal structural invariant. WorldState must be able to represent accepted cyclic worlds without depending on mutable/external WorldDefinition context during projection.

### Precompute every possible spatial query before mechanic invocation

Rejected because a mechanic may need to choose query arguments dynamically. Bounded read-only query capabilities preserve explicit authority without requiring impossible or wasteful precomputation of all argument combinations.

### Give mechanics unrestricted WorldState access for spatial reads

Rejected because it would erase declared dependency boundaries and allow spatial mechanics to inspect unrelated world state. Spatial access is provided through a narrow explicit capability surface.

### Allow dynamic access to arbitrary Space property names

Rejected because it would make Space properties effectively unrestricted data access. Space targets may be dynamic, but readable property names are declared statically by the mechanic binding.

### Let a mechanic observe its own proposed spatial effects during the same invocation

Rejected because partially visible candidate state complicates deterministic reasoning and creates order-sensitive behavior inside one resolution. All spatial queries use the invocation's immutable base state.

### Treat graph reachability as self-containment in cyclic worlds

Rejected because A -> B -> C -> A should not make A conceptually contained within itself. ENCLOSING_SPACES excludes the subject Space and IS_WITHIN follows that semantic.

### Filter inactive Spaces from enclosing-space Query results

Rejected because deactivation preserves canonical location topology. Activity is a lifecycle attribute, not a reason to rewrite the spatial chain returned by Query.

### Let runtime mechanics choose canonical SpaceId

Rejected because canonical simulation identity belongs to GRASS. Mechanics describe semantic
creation results; the trusted layer allocates the runtime SpaceId before constructing
CreateSpaceEffect.

### Expose runtime Space creation as an imperative API

Rejected because creation must use the same Job/scenario-mechanic -> typed result -> trusted
effect -> validation -> Event authority path as other world changes.

### Always permit reactivation

Rejected because reactivation changes world lifecycle semantics and some scenarios require
deactivation to be terminal. WorldDefinition controls Entity and Space reactivation
independently.

### Cascade reactivation automatically

Rejected because restoring a containing Space does not imply restoring every previously
deactivated child Space or Entity. Larger restoration is represented by explicit effects in
one atomic candidate.

### Clear or recompute location_id on reactivation

Rejected because deactivation preserves canonical location history. Reactivation restores
activity at that same direct location unless an explicit SetLocationEffect changes it in
the same atomic transition.

### Reject every same-identity multi-write

Rejected because Entity and Space have independently meaningful lifecycle, location, and
property dimensions. A blanket same-ID rule would forbid useful atomic compositions such as
reactivate-and-relocate and would force artificial compound effects.

### Let Event order resolve multiple writes to one semantic field

Rejected because replay/storage order must not become hidden state-transition precedence.
Two writes to the same semantic field are invalid rather than resolved by ordering.

### Treat creation as merely another independent field write

Rejected because creation establishes the complete initial canonical object. Combining
creation with same-transition lifecycle/location/property rewrites would weaken the
complete-initial-state invariant and reintroduce order-sensitive semantics.

### Compute deactivation closure only from base state

Rejected because it would make an atomic relocate-and-destroy candidate behave as though
the relocation had not happened, forcing arbitrary effect ordering or unnecessary separate
transitions.

### Let lifecycle writes remove subjects from deactivation closure

Rejected because containment is spatial topology, not lifecycle intent. Only topology-
changing writes affect cascade membership; conflicting lifecycle writes are detected
normally after closure expansion.

### Let Event/effect order decide whether relocation happens before cascade

Rejected because sequence is deterministic encoding, not semantic precedence. Candidate
topology and derived closure give one order-independent result.

### Allow ordinary mutation of inactive subjects without reactivation

Rejected because inactive state is preserved historical state rather than an editable
dormant object. Silent mutation while inactive would weaken lifecycle meaning and make
reactivation policy largely cosmetic.

### Require the subject to be active in the final candidate for any mutation

Rejected because a valid atomic consequence may mutate an active subject and deactivate it
in the same transition, for example relocating an Entity before preserving it as inactive
at the resulting location.

### Use Event order to satisfy inactive-subject mutation preconditions

Rejected because reactivation/update/deactivation combinations are validated as one atomic
candidate. Active participation is derived from base activity or explicit same-candidate
reactivation, not from Event sequence.

### Make lifecycle_policy optional with implicit false values

Rejected because lifecycle policy changes what transitions are valid world semantics.
Serialized WorldDefinition snapshots must state those semantics explicitly rather than
depend on loader defaults. The ordinary no-reactivation policy is authored as explicit
false values.

### Let creation specs use canonical IDs chosen by the mechanic

Rejected because canonical runtime identity belongs to GRASS. Mechanic-chosen values may be
used only as transient CreationRefs within one preparation context.

### Allocate runtime IDs nondeterministically during preparation

Rejected because retrying the same semantic preparation against the same authoritative base
must not change candidate identity merely due to host/process randomness.

### Persist or reserve IDs for rejected/stale candidates

Rejected because uncommitted candidates are not authoritative history. Failed validation or
stale-head publication consumes no persistent identity reservation.

### Reallocate IDs during replay

Rejected because committed Events already contain canonical runtime identities. Replay
projects recorded facts and never reruns identity allocation.

### Carry CreationRef into WorldEffect or Event payloads

Rejected because CreationRef is preparation-local linkage, not simulation identity. The
closed authority/history layers use canonical typed IDs only.

### Split LocationChanged into EntityLocationChanged and SpaceLocationChanged

Rejected because both represent the same canonical semantic field change. A strict typed
SpatialSubjectRef preserves subject kind without duplicating mutation semantics.

### Persist DeactivateSpaceEffect as one generic effect Event

Rejected because Events record accepted semantic facts, not transient candidate opcodes.
Cascade materialization records the actual SpaceDeactivated/EntityDeactivated lifecycle
facts produced by the accepted closure.

### Add UpdateSpaceEffect for Slice 17.2

Rejected because Space properties are immutable after creation in the accepted spatial
model. Location and lifecycle have dedicated mutation contracts.

### Project composite writes by mutating state sequentially in Event order

Rejected because accepted same-transition combinations such as reactivate-and-update or
relocate-and-deactivate would gain different meaning when their storage order changed.
Sequence is encoding order, not mutation precedence.

### Require WorldDefinition during ordinary replay projection

Rejected because canonical Events must be sufficient to reconstruct authoritative state.
WorldDefinition-aware policy decides whether a transition may be committed; replay projects
the accepted facts and validates only universal structural/history invariants.

### Re-evaluate lifecycle policy during replay

Rejected because reactivation permission is world semantics checked before commit. Once a
valid reactivation Event is canonical history, projection must reconstruct it rather than
re-adjudicate historical policy.

### Bump EntityCreated to version 2 during pre-stable development

Rejected because the first stable Event-history contract has not yet been frozen. Internal
pre-release payload evolution replaces provisional v1 in place rather than accumulating
development-only version archaeology.

### Keep supporting the old EntityCreated v1 shape

Rejected because mandatory location is now part of Entity creation semantics. Compatibility
with an unreleased internal payload would weaken the invariant or require migration
machinery before the first stable history contract.

### Use one untyped CreatedRef for all creation-reference kinds

Rejected because Entity and Space references have different semantic contracts. Typed
CreatedEntityRef/CreatedSpaceRef wrappers catch kind errors before the closed WorldEffect
boundary.

### Limit CreationRef usage to spatial location links

Rejected because same-transition creation may also feed Relation participants, Resource
owners, Entity-scoped StateVariables, and other typed consequences. Restricting local
references to location would force artificial multi-transition workflows or premature
canonical-ID exposure.

### Let unresolved Created*Ref values cross into WorldEffect

Rejected because WorldEffect is already inside the canonical authority boundary. Trusted
preparation must resolve the complete reference graph first.

### Make movement optional and infer an empty configuration

Rejected because movement rules are world semantics. Strict WorldDefinition snapshots should
state explicitly whether MOVE is configured instead of relying on loader defaults.

### Treat an empty movement section as invalid

Rejected because some deliberately unusual scenarios may have no meaningful MOVE semantics.
Such worlds express that choice explicitly with empty contracts/rules and a null default.

### Add an implicit built-in movement fallback

Rejected because core must not invent scenario movement semantics. A default exists only
when the WorldDefinition authors one explicitly.

### Model DefaultMovementRule as an unrelated duplicated DTO

Rejected because the conditional and default variants share the same movement-resolution
contract. Duplicating rule_id/input bindings/contract/mechanic fields would create avoidable
schema drift.

### Model DefaultMovementRule as a normal conditional rule with an always-true selector

Rejected because the default must not participate in ordinary matching. An always-true
selector would create ambiguity whenever any conditional rule also matches.

### Put selector on the MovementRule base and ignore it for the default

Rejected because that makes the base contract admit semantically invalid states. Selector
belongs only to ConditionalMovementRule.

### Implement MovementSelector through BUILTIN/GEL/IMPLEMENTATION

Rejected because rule discovery should be deterministic declarative matching, not recursive
mechanic execution with its own invocation/failure surface. Mechanic bindings execute only
after one movement rule has been selected.

### Use arbitrary JSONPath/string predicates over serialized state

Rejected because selectors should operate on typed explicitly exposed values rather than
serialization layout or unrestricted world-state traversal.

### Treat overlapping cascade-derived deactivations as duplicate field-write conflicts

Rejected because overlapping roots describe the same resulting inactive lifecycle state for
shared descendants. Derived closures are unioned before field-conflict validation.

### Apply each DeactivateSpaceEffect cascade sequentially

Rejected because cascade membership and resulting lifecycle writes must be derived from one
composed candidate topology, not from mutation order between roots.

### Add a general expression language to MovementSelector

Rejected because selector matching does not need a second GEL-like language. A small closed
boolean algebra is easier to validate, reason about, and keep independent from mechanic
execution.

### Add regex/glob/arithmetic/comparison operators preemptively

Rejected because no current scenario contract requires them. The closed selector algebra can
be extended deliberately when a concrete matching requirement cannot be expressed by the
initial operators.

### Let selector expressions perform spatial queries directly

Rejected because query authority belongs to trusted context preparation and bounded query
capabilities. MovementSelector consumes already exposed typed values and remains a pure
boolean matcher.

### Add requested_target as a core PlanStep field

Rejected because PlanStep already has generic structured parameters for primitive-specific
request arguments. A dedicated MOVE field would specialize the core PlanStep model
unnecessarily.

### Standardize one mandatory parameter name such as movement_target

Rejected because parameter names belong to scenario/Blueprint action semantics. Movement
bindings explicitly identify which named parameter supplies a given typed input.

### Treat raw PlanStep parameter strings as canonical IDs automatically

Rejected because request data and canonical identity are distinct semantic layers. Trusted
bindings must explicitly validate/resolve parameters into typed EntityId/SpaceId values.

### Let MovementSelector traverse arbitrary Entity/Space properties

Rejected because selector matching should not become a second query language. Scenario-
specific state/property values are exposed deliberately through typed NAMED_VALUE bindings.

### Treat missing optional selector values as runtime errors

Rejected because optional Blueprint/parameter/binding/derived values are normal matching
inputs. EXISTS observes presence; EQ/IN simply do not match absent values. Invalid
references or types remain authoring-validation errors.

### Treat raw STEP_PARAMETER strings as EntityId/SpaceId automatically

Rejected because PlanStep request data is not canonical identity. Trusted context binding
must validate and resolve raw values before exposing typed selector-visible references.

### Give each MovementContract an arbitrary result_schema and mapping DSL

Rejected because MOVE currently needs one universal result meaning: resolution classification
plus an optional resolved destination. A second scenario mapping language would add
complexity without adding required semantics.

### Let movement mechanics return SetLocationEffect directly

Rejected because mechanics remain below the authoritative candidate-effect boundary.
MovementResult is typed data; trusted preparation constructs the closed WorldEffect.

### Require resolved_destination only for SUCCESS

Rejected because PARTIAL, INTERRUPTED, and unusual scenario-defined FAILED/BLOCKED outcomes
may still have a real spatial consequence. Outcome classification and relocation are
orthogonal fields.

### Define separate ValueBinding mechanisms for movement, reactions, and perception

Rejected because all three usages need the same typed deterministic read-only value-resolution
contract. Duplicating that machinery would make later convergence harder and invite subtly
different authority/type/absence semantics.

### Give global ValueBinding one unrestricted global source namespace

Rejected because reuse of the binding contract must not imply cross-domain read authority.
Each usage supplies a bounded BindingContext and its own permitted source/query vocabulary.

### Make ValueBinding a general expression language

Rejected because value acquisition/resolution and arbitrary computation are separate
responsibilities. Computation belongs to BUILTIN/GEL/IMPLEMENTATION mechanics.

## Remaining Slice-17.2 decisions

The material Slice-17.2 semantic decisions are now recorded. Before changing this ADR from
Draft to Accepted, perform one final consistency review against the existing core/Event/
WorldDefinition contracts and identify any implementation-blocking gaps rather than adding
new spatial semantics by default.
