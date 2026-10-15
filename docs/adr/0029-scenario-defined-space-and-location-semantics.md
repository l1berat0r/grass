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

## Consequences

### Positive

- `MOVE`, perception, recipient selection, and later spatial mechanics can use one explicit location authority model;
- scenario authors keep domain vocabulary and arbitrary Space properties outside core;
- nested spaces model rooms/buildings/cities as well as moving containers such as vehicles without rewriting all contained Entities;
- Entity location cannot silently diverge between magic properties, Relations, and a separate membership subsystem;
- unusual cyclic/SF topologies remain possible without making them the default;
- cycle-safe traversal prevents pathological spatial topology from hanging the runtime.

### Costs and constraints

- WorldState and WorldDefinition must gain explicit Space/location concepts rather than reusing only existing Entity/Relation state;
- every Entity must receive a valid initial location;
- Space relocation requires normal authoritative runtime semantics rather than editing WorldDefinition;
- enabling cycles removes assumptions that every containment walk reaches a root and requires visited-set traversal;
- query and mechanics code must distinguish direct `location_id` from derived enclosing context.

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

## Remaining Slice-17.2 decisions

This ADR remains Draft. The next architecture work must resolve:

- the closed candidate mutation and semantic Event contract for changing Entity/Space `location_id`;
- how actor-facing `MOVE` maps onto spatial mutation and how scenario mechanics may block, redirect, or otherwise resolve movement;
- the authoritative mechanic for moving a Space and whether it reuses the same candidate mutation path as Entity movement;
- genesis Events/projections for initial Spaces and Entity/Space locations;
- lifecycle/reference validation for inactive/deactivated Entities and Spaces;
- exact WorldState projection placement and immutable DTO/value-object shapes;
- how direct/enclosing location is exposed as explicit typed input to BUILTIN/GEL/IMPLEMENTATION mechanics;
- Query API semantics for direct location, enclosing spaces, cycle-safe reachability, and inspection;
- package schema/version and acceptance-scenario migration consequences.
