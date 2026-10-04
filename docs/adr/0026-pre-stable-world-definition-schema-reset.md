# ADR-0026: Pre-stable WorldDefinition schema reset

- Status: Accepted
- Date: 2026-10-03

## Context

The unreleased `WorldDefinition` document evolved incrementally while the local 0.1
runtime was being built. No stable WorldDefinition representation or migration promise
has been published, so carrying the intermediate internal schema numbers would create
compatibility obligations without protecting released data.

## Decision

Reset the current complete `WorldDefinition` document to the initial schema version 1.
Its strict root shape requires `scenario_event_rules`, which may be empty. Every current
`AT_TIME` rule requires its direct usage-specific `mechanic`; the supported BUILTIN and
GEL `SET_STATE_VARIABLE` forms and all existing validation remain unchanged.

The superseded intermediate internal WorldDefinition shapes are unsupported. There is no
loader compatibility or migration path for them. Pre-release local SQLite databases,
run snapshots, and installed package/template copies containing those shapes must be
recreated manually.

This reset does not renumber or change SQLite storage schema 1, WorldPackage format 1,
GEL language version 1, Event payload versions, SimulationRunConfig version 1, or CLI
JSON schema version 1. These are independent version domains.

A used WorldDefinition remains immutable. Material edits to a local template or other
WorldPackage must change the semantic `WorldDefinition.version`, even when
`schema_version` remains 1.

Engine authority, Event sourcing, replay, branching, package snapshots, GEL isolation,
and runtime composition boundaries are unchanged. Slice 18 remains deferred.

This ADR supersedes the WorldDefinition schema-number and backward-compatibility
statements in ADR-0016 and ADR-0023. Their scenario-occurrence and runnable-composition
rationale and all other decisions remain accepted.

## Consequences

- the first supported WorldDefinition representation is the current complete schema 1;
- implementations need no compatibility branches for unreleased internal shapes;
- local pre-release data may require manual recreation rather than migration;
- future incompatible WorldDefinition representation changes must deliberately advance
  its schema version and define compatibility policy.
