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

The typed result is interpreted by a trusted world-defined MovementContract, conceptually:

```text
MovementContract
    contract_id
    input_schema
    result_schema
    outcome_mapping
    consequence_mapping
```

Exact DTO fields remain open. The semantic boundary is fixed:

- the contract may map accepted result values to existing Job outcomes;
- the contract may map accepted result values to zero or one SetLocationEffect for the moving subject;
- the requested MOVE target and the resolved authoritative destination are distinct concepts;
- blocked, failed, partial, redirected, portal-like, or otherwise unusual movement remains scenario-defined rather than core movement behavior.

A scenario may therefore resolve:

```text
requested target = server-room
resolved destination = security-checkpoint
```

without changing the meaning of the core MOVE primitive.

BUILTIN, GEL, and IMPLEMENTATION are alternate ways to compute the same typed MovementResult. More expressive mechanics do not gain additional simulation authority.

## Decision 7: MovementRule selection is world-owned, deterministic, and non-priority-based

A Plan/PlanStep expresses what the actor attempts, not which technical movement implementation should run. Actor/provider-authored MOVE steps therefore do not select implementation mechanics directly.

WorldDefinition owns movement-mechanic selection through world-defined rules, conceptually:

```text
MovementRule
    rule_id
    selector
    input_bindings
    movement_contract_ref
    mechanic_binding
```

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

Selectors may use only accepted generic/explicitly bound scenario information, such as the requested target, current direct location, PlanStep parameters, Blueprint references/parameters, or scenario-defined type/property values. Core does not compile in domain selector vocabulary such as walking, room, vehicle, portal, or door.

Ordinary worlds may configure an explicit default movement binding for cases where no specific MovementRule matches.

Selection semantics are:

```text
exactly one applicable MovementRule
    -> use it

no applicable MovementRule
    + explicit default movement binding
    -> use default

no applicable MovementRule
    + no default
    -> movement cannot be resolved

more than one applicable MovementRule
    -> invalid ambiguity
```

Declaration order is not semantic priority. Slice 17.2 does not introduce numeric or implicit rule priorities.

> MovementRule selection must resolve to at most one applicable rule. Ambiguous matching is invalid rather than resolved by declaration order or implicit priority. If no rule matches, an explicitly configured default movement binding may be used.


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
- movement behavior stays world-defined and replaceable through BUILTIN, GEL, or IMPLEMENTATION mechanics;
- deterministic rule selection avoids hidden declaration-order semantics;
- moving a container/vehicle Space updates nested effective context without Event fan-out over every contained subject;
- creation never exposes an Entity without its mandatory direct location;
- genesis may create nested Spaces and located Entities atomically without relying on Event order;
- destructive scenario semantics may deactivate an entire nested spatial subtree/closure atomically;
- deactivation preserves historical spatial structure without synthetic relocation Events.

### Costs and constraints

- WorldState and WorldDefinition must gain explicit Space/location concepts rather than reusing only existing Entity/Relation state;
- every Entity must receive a valid initial location;
- Space relocation requires normal authoritative runtime semantics rather than editing WorldDefinition;
- enabling cycles removes assumptions that every containment walk reaches a root and requires visited-set traversal;
- query and mechanics code must distinguish direct `location_id` from derived enclosing context;
- the closed WorldEffect/Event/projection contracts must gain typed spatial mutation support;
- MovementRule authoring must avoid ambiguous overlapping selectors;
- mechanics that move Spaces or Entities must preserve the same validation boundary;
- EntityCreated and the new SpaceCreated Event contracts must carry initial spatial state;
- pre-stable local data using the earlier EntityCreated payload must be recreated rather than supported through optional compatibility fields;
- Space deactivation requires cycle-safe closure computation and atomic multi-subject lifecycle validation;
- generic Relation/Resource/StateVariable cleanup is not implied by spatial deactivation.

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

## Remaining Slice-17.2 decisions

This ADR remains Draft. The next architecture work must resolve:

- exact WorldState projection placement and immutable DTO/value-object shapes;
- how direct/enclosing location is exposed as explicit typed input to BUILTIN/GEL/IMPLEMENTATION mechanics;
- Query API semantics for direct location, enclosing spaces, cycle-safe reachability, and inspection;
- package schema/version and acceptance-scenario migration consequences.
