# ADR-0023: Runnable world composition v1

- Status: Accepted
- Date: 2026-09-19

## Context

Slices 0-13 provide runtime orchestration, GEL, provider bindings, deterministic
scenario-occurrence resolution, and durable local history. Ordinary authored worlds
still require Python-specific resolver objects and have no immutable per-run package
snapshot. ADR-0021 accepts WorldPackage as a delivery boundary but deliberately leaves
its first concrete format and mechanic catalogue to Slice 14.

## Decision

### World identity and package format

Editable worlds use `worlds/<world-slug>/`, where the slug matches
`[a-z0-9]+(?:-[a-z0-9]+)*` and is the existing `WorldDefinitionId`. Package format 1 is
a directory containing a strict `package.json`, one referenced `world.json`, and any GEL
files referenced by that definition. The manifest contains only `package_version` and
`world_definition`.

Paths are canonical relative POSIX paths. Absolute paths, traversal, symlinked material,
non-regular files, arbitrary Python references, and unsupported versions are rejected.
Only the manifest, world document, and referenced GEL files are material in format 1.

### WorldDefinition schema version 3

Schema version 3 preserves the version-2 root shape and requires every AT_TIME rule to
contain one direct, usage-specific `mechanic`. There is no mechanic registry. Versions 1
and 2 retain their exact existing fields and semantics.

The first usage is `SET_STATE_VARIABLE`, with exactly two variants:

- `BUILTIN` / `CONSTANT`, containing a StateVariable target and immutable value;
- `GEL`, containing the same target and one canonical `GelProgram`.

The GEL program has an exact-object input containing only `current_value` and an
exact-object output containing only `new_value`; both fields use the same GEL schema.
The trusted adapter reads the target from immutable request state, executes GEL, and
constructs one existing `SetStateVariableEffect`. GEL never returns effect descriptions.

Authored world documents refer to GEL through `source_file`. Package loading resolves
that reference to exact UTF-8 source. The semantic WorldDefinition and SQLite snapshot
contain canonical `source`, language version, input schema, and output schema, never a
filesystem path or prepared AST. `prepare_gel` validates source before publication and
prepared programs are rebuilt after reopen. Programs referencing `random_int` are
unsupported in this composition version because production random streams are deferred.

### Per-run snapshots

Every package-backed run publishes one immutable filesystem snapshot at
`world_snapshots/<run_id>/`. RunId path use is restricted by the filesystem layer to one
safe lowercase hyphenated segment without changing the nominal RunId contract. Snapshots
duplicate material per run and use no package identity, content-addressing, sharing, or
reference counting.

The creation order is validate package, publish a complete temporary snapshot by atomic
rename, then register the run in SQLite. Registration failure may remove the snapshot;
failure to clean it leaves a recoverable orphan. A registered run is never created before
its complete snapshot exists. Reopen loads the run snapshot, reconstructs its semantic
definition, and requires exact equality with SQLite's definition. It never falls back to
the editable author directory.

SQLite continues to store run metadata, semantic WorldDefinition, run configuration,
branches, transitions, and Events. The unreleased local schema remains storage version 1;
WorldDefinition v3 fits the existing versioned definition JSON column. Ordinary replay
uses Events and does not load packages or execute GEL.

### Runtime composition

Slice 14 composes an existing `ScenarioOccurrenceResolutionProvider`. Mechanics produce
candidate effects only; the existing engine validates, materializes, and commits them.
No engine authority or frontier behavior changes.

The accepted vertical slice is occurrence-only. It adds no ActorFacet, actor bootstrap,
initial DecisionPoint, perception mechanic, Job mechanic, or provider selection to the
WorldDefinition. Unsupported Job or cognition state fails explicitly rather than being
silently treated as quiescent. Package validation rejects duplicate occurrence times
because multiple same-time scenario occurrences remain unsupported.

Provider/model routing remains non-secret `SimulationRunConfig` material and never enters
WorldPackage or WorldDefinition.

## Consequences

- a data-defined directory can execute BUILTIN and GEL scenario occurrences without
  Python scenario code;
- exact authored material survives edits or deletion of the author directory;
- canonical GEL remains part of immutable scenario semantics while paths remain delivery
  concerns;
- runtime authority, replay, branching, and closed WorldEffect validation are unchanged;
- the first format is intentionally narrow and rejects valid GEL randomness and currently
  unsupported scheduler frontiers before run registration.

## Deferred details

- Application and Query APIs, CLI, and templates;
- ActorFacet, actor bootstrap, perception, and automatic DecisionPoints;
- Job, Blueprint, capability, and additional mechanic usages;
- IMPLEMENTATION plugins and arbitrary Python;
- archives, registries, signing, dependencies, remote packages, and shared snapshots;
- random streams, RANDOM_TIME, recurrence, and generative resolution;
- generic GEL effect output, custom WorldEffects, and mixed/multiple scenario frontiers.
