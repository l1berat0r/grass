# ADR-0026: Pre-stable WorldDefinition schema reset

- Status: Accepted
- Date: 2026-10-03
- Amended: 2026-10-20

## Context

The unreleased `WorldDefinition` document evolves while the local 0.1 runtime and the
first complete authoring model are still being designed. No stable WorldDefinition
representation or migration promise has been published.

Numbering every incompatible internal development shape would turn `schema_version`
into development archaeology rather than a compatibility contract. At the same time,
repository-maintained examples and documentation must describe one current shape rather
than accumulate multiple incompatible meanings for schema 1.

## Decision

The pre-stable `WorldDefinition` document keeps `schema_version = 1` until the first
stable complete WorldDefinition representation is explicitly frozen.

Before that stabilization point, an incompatible architecture/implementation change may
replace the current schema-1 representation in place. Earlier internal schema-1 shapes
become unsupported immediately; the loader does not detect, migrate, or preserve them.

Whenever the pre-stable schema-1 shape changes, all WorldDefinition documents,
WorldPackages, templates, examples, fixtures, and current architecture documentation
maintained in the repository must be migrated to the new current shape as part of the
corresponding implementation change. We keep one supported pre-stable schema-1 shape in
the repository rather than parallel compatibility variants.

Pre-release local SQLite databases, immutable run snapshots, installed package/template
copies, or other material created under an earlier incompatible internal shape remain
disposable development data and may require recreation. GRASS does not provide a
compatibility loader or migration promise for those external/local pre-stable copies.

At the first explicitly stable complete WorldDefinition release, the then-current
representation becomes the definitive schema version 1 compatibility contract. After
that point, incompatible representation changes must advance `schema_version` and define
their compatibility/migration policy deliberately.

This policy does not renumber or couple SQLite storage schema 1, WorldPackage format 1,
GEL language version 1, Event payload versions, SimulationRunConfig version 1, or CLI
JSON schema version 1. These remain independent version domains. Event payload versions
follow their own ADR-0005 pre-stable policy and may also remain at version 1 without being
coupled to WorldDefinition schema_version.

A used WorldDefinition remains immutable. Material edits to a concrete world/template
must still change the semantic `WorldDefinition.version`, even while the document
`schema_version` remains 1.

Engine authority, Event sourcing, replay, branching, package snapshots, GEL isolation,
and runtime composition boundaries are unchanged.

This ADR supersedes WorldDefinition schema-number and pre-stable compatibility statements
in ADR-0011, ADR-0016, and ADR-0023 wherever they conflict. Their historical slice
rationale and all unrelated decisions remain accepted. Later ADRs may replace the current
schema-1 shape without changing the number while this pre-stable policy remains active.

## Consequences

- `schema_version = 1` means "the current pre-stable WorldDefinition representation"
  until the first stable complete contract is frozen;
- old internal shapes carrying the same number are intentionally unsupported;
- repository-maintained documents/examples are migrated forward instead of supported
  through compatibility branches;
- local pre-release data may require recreation rather than migration;
- the first stable complete WorldDefinition representation can still be published as
  schema version 1;
- after that stabilization point, `schema_version` resumes normal incompatible-format
  versioning semantics.
