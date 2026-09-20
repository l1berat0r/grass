# ADR-0024: Application and Query API v1

- Status: Accepted
- Date: 2026-09-20

## Context

ADR-0019 established transport-neutral Application and Query boundaries, ADR-0022
fixed runtime frontier semantics, and ADR-0023 made ordinary package-backed worlds
runnable. Slice 15 needs concrete local lifecycle, recovery, status, branching, query,
and verification contracts without exposing write-capable storage or freezing future
transport and actor-memory designs.

Run registration and genesis commit cannot be one atomic operation across SQLite and
the EventStore abstraction. Queries also need stable meaning while branches can continue
concurrently, and package-backed and definition-only runs require different reopen and
verification behavior.

## Decision

### Run lifecycle and material identity

`SimulationRunRecord` explicitly records `WorldMaterialKind.DEFINITION_ONLY` or
`PACKAGE_SNAPSHOT`. Reopen and verification follow only this persisted discriminator;
they do not infer material kind from filesystem presence. Normal package-backed creation
allocates a canonical UUID RunId in the Application layer, publishes the package snapshot,
registers the run, then requests trusted runtime initialization.

A registered run with an empty parentless root is a recoverable internal lifecycle state.
`initialize_root` is a constrained trusted runtime operation: it either commits exactly
one validated genesis transition against the empty head or validates the existing exact
genesis after reopen or a stale-write race. Other nonempty root history is an integrity
failure. The unreleased SQLite format remains storage schema version 1 and adds the
material-kind field in place.

### Runtime composition and command authority

`RuntimeComposer` is the trusted replaceable boundary that validates a
WorldDefinition/run-configuration pair and builds a `SimulationEngine` from installed
components. Validation performs no I/O, identity allocation, provider invocation,
mechanic execution, or commits. `OccurrenceRuntimeComposer` remains the default
production composition for the Slice-14 occurrence-only world subset. DecisionInvoker
bindings are execution-environment inputs and are not persisted secrets.

`LocalSimulationApplication` exposes create, open, verify, and read-only queries.
`OpenedRun` is an opaque command handle exposing only step, advance, exact-position
branch creation, status inspection, verification, and stable run/root identifiers. It
does not expose `SimulationEngine`, EventStore, mutable state, or arbitrary Event commit.
Branch creation requires a concrete committed `HistoryPosition`; there is no symbolic
fork-at-head command.

Server-managed scripted, model, and human DecisionInvokers use the existing runtime
acquisition, validation, provenance, stale-head, and commit path. Client-managed
bindings remain waiting-only in this slice; a transport-neutral submission protocol is
deferred until a client/session transport exists.

### Derived status

The first application status set is `READY`, `WAITING_FOR_DECISION`, and `QUIESCENT`.
Status is derived from canonical history/state and current runtime composition; it is not
persisted mutable truth. Inspection invokes no provider, resolver, GEL execution, identity
allocation, commit, or logical-time advance. Consistent with ADR-0022, independent future
scheduler work makes a run ready before a client-managed decision wait is reported.

### Exact-position queries

Every branch-dependent query captures one exact branch head, reconstructs visible history
and state at that `HistoryPosition`, and returns that position with the result. An explicit
historical position must name the viewed branch. `HistoryScope.VISIBLE` includes immutable
ancestry; `HistoryScope.BRANCH_ORIGIN` includes only transitions committed on the viewed
branch. `BranchView` reports topology, the exact viewed head, and visible/origin transition
counts.

The initial read surface includes run and branch catalogs, status, state, canonical
history, Jobs, Decisions, actors, actor observations, actor decisions, actor Plans, actor
Jobs, and actor history. DTOs are immutable read models, not authoritative aggregates.

Until ActorFacet is implemented, actor membership is the exact union of actor identifiers
present in Plans, Observations, and DecisionPoints. Actor history is mechanically
attributed through cognition Events, exact Plans and PlanSteps, Jobs, and Job resolution.
When any Event in an atomic transition is attributed, the complete transition is returned;
Event sequence is not presented as causality.

### Read-only verification

Verification reloads exact run material, validates material-kind consistency, branch
topology, exact root genesis, identity uniqueness, branch-visible/origin agreement, and
full replay at every branch head. Counts include each branch-origin transition and Event
once rather than recounting inherited prefixes. Static package/GEL parsing and preparation
are allowed; provider invocation, resolver execution, randomness, mechanics execution,
initialization, and commits are not.

## Consequences

- later CLI and transport layers can reuse one authority-preserving local API;
- interrupted creation can be recovered without accepting malformed nonempty history;
- callers receive coherent exact-position read models even as a branch later advances;
- branch ancestry and origin-only inspection are explicit rather than inferred;
- actor inspection is useful before the final ActorFacet and memory model exist;
- runtime composition remains replaceable without making providers or resolvers public
  write surfaces;
- status and verification remain reproducible read operations rather than new persisted
  sources of truth.

## Deferred details

- client-managed decision submission, sessions, and transport correlation;
- CLI, JSON/wire schemas, HTTP, FastAPI, and WebSocket APIs;
- final ActorFacet, provider/memory views, and actor-memory retrieval semantics;
- termination and persisted operational-failure status;
- branch rename, delete, merge, rebase, and symbolic fork commands;
- indexes, checkpoints, pagination, filters, and derived read stores;
- storage migration policy once a persistence format is released.

## Alternatives considered

### Return the engine or EventStore from open-run

Rejected because clients could bypass validation and the single authoritative commit path.

### Infer package-backed runs from snapshot-directory presence

Rejected because missing, orphaned, or malicious filesystem material would silently
change run semantics.

### Let every query read the current head independently

Rejected because one response could combine projections from different branch positions.

### Persist a mutable run-status column

Rejected because it would duplicate derivable canonical/runtime truth and could become
stale after replay, recovery, or branch continuation.
