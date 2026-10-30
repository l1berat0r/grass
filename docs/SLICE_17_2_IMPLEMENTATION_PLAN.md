# GRASS Slice 17.2 — implementation plan

- Status: Ready for implementation; no production code in this plan commit
- Architecture authority: [ADR-0029](adr/0029-scenario-defined-space-and-location-semantics.md) (Accepted, 2026-10-30)
- Related GEL contract: [ADR-0017](adr/0017-minimal-gel-v1-language-and-execution-contracts.md)
- Prerequisite: Slices 0–17.1 and the Diagnostics Readiness checkpoint are complete
- Next milestone: Slice 18 actor-capable WorldPackage composition (not included here)

## Goal and invariant boundaries

Bring the existing pre-spatial GRASS implementation into conformance with ADR-0029
without replacing the EventStore, WorldState authority, semantic-transition model,
replay/branch system, existing runnable WorldPackage workflow, or local `.grass`
workspace boundary. A world may define first-class nested or moving Spaces and
an explicit direct location for every Entity; MOVE is a world-owned deterministic
mechanic returning a typed MovementResult, never an imperative mutation API.

The acceptance target is an executable vertical slice, not the presence of DTOs:
authored world -> validated package -> atomic spatial genesis -> deterministic
movement/consequence -> committed semantic Events -> exact-position read-only Query
-> replay/branch reconstruction, with rejection paths and invariants tested.

All stages use the **one current pre-stable version** of their respective
contracts: WorldDefinition schema 1, Event payload version 1, GEL language 1,
WorldPackage format 1. Do not introduce compatibility fallback loaders for
obsolete unreleased local shapes; migrate repository fixtures/templates together.

## Stage A — canonical spatial state and atomic world consequences

**Build first; the other stages depend on this semantic foundation.**

- Introduce nominal `SpaceId`, immutable `Space`, required `Entity.location_id`,
  typed Entity/Space spatial references, and `WorldState.spaces`.
- Enforce universal structural invariants (existing location targets, active
  subjects with active direct locations, no direct self-location), leaving
  longer-cycle permission to WorldDefinition-aware validation.
- Extend closed WorldEffects, Event types and payloads for creation, relocation,
  deactivation and optional reactivation. Use location-bearing creation Events.
- Refactor effect preparation and projection to evaluate one complete
  transition write-set, validating conflicts **per semantic field** for Entity
  and Space. Event order never supplies mutation precedence.
- Compute Space-deactivation union closure from the topology after explicit
  creation/relocation. Reject duplicate explicit roots, conflicts with
  reactivation/creation, and invalid final active/inactive references.
- Keep existing Relation, Resource, StateVariable and Job behavior unchanged
  except for interactions explicitly fixed by ADR-0029.

**Primary integration points:** `src/grass/core/identifiers.py`,
`state.py`, `world_effects.py`, `world_events.py`,
`world_effect_materialization.py`, `world_resolution.py`,
`projections.py`, `replay.py`.

**Gate A:** deterministic batch projection and complete replay equivalence
for: same-transition create/cross-reference; reactivation + relocation;
conflicting double writes; nested/overlapping cascade roots; relocation
outside a cascade; cycles when permitted; inactive historical topology.

## Stage B — world authoring, genesis and durable material

- Extend strict `WorldDefinition` with mandatory `spatial_policy`,
  `lifecycle_policy`, `movement`, initial `spaces`, and each initial
  Entity's required `location_id`. No implicit defaults; explicit empty
  movement is allowed.
- Validate initial Space and Entity references against the complete candidate,
  and apply world-specific acyclic/cyclic and lifecycle policies before commit.
- Generate genesis as one semantic batch: `SimulationInitialized`, SpaceCreated,
  location-bearing EntityCreated, followed by existing world materialization.
- Update canonical WorldDefinition/SQLite encode/decode, WorldPackage loading,
  per-run immutable snapshots, and repository examples/templates together.
- Preserve `grass init`, managed `.grass/worlds`, snapshots and external-path
  behavior from ADR-0027; no stray working directories.
- Preserve exact WorldDefinition semantic identity/version behavior under
  ADR-0026 despite `schema_version = 1`.

**Primary integration points:** `src/grass/core/world_definitions.py`,
`genesis.py`, `src/grass/persistence/_serialization.py`,
`src/grass/worlds/package.py`, `snapshots.py`, `templates.py`,
`template_installations.py`, existing template material.

**Gate B:** strict loading rejects missing policy/space/location/movement
fields; nested/forward-reference genesis succeeds atomically; run reopen and
snapshot verification remain equivalent after author material changes.

## Stage C — reusable typed inputs, GEL and spatial capability boundary

- Implement global `ValueSchema`, `ValueBinding`, constrained
  `BindingContext`, flat `QueryValue`, bounded ValuePath, and distinct
  missing/NULL/optional/field-required semantics. QueryValue has no nested
  arbitrary expression engine.
- Extend the current pre-stable GEL v1 parser, schema/validator and interpreter
  for accepted NULL/OPTIONAL/ENUM behavior and registered qualified host calls
  without enabling ordinary object methods or first-class host objects.
- Introduce the runtime-provided `space` namespace with
  `direct_location`, `enclosing`, `is_within`, and `property`.
  A single spatial query implementation backs both dynamic calls and QueryValue.
- Register operation signatures/default availability; prepare effective
  permissions from selected rule overrides and trusted host ceiling.
  Validate names/types/property allowlists statically and again at execution.
  `space.property` is default-disabled; the other three spatial calls are
  default-enabled within the authorized spatial context.
- Resolve tagged Entity/Space subject references, validate canonical
  SpaceId target arguments, and apply explicit lossless semantic-to-GEL adapters.
  Missing declared Space property means GEL execution error; optional
  QueryValue may yield absence as specified in the ADR.
- Keep invocation views immutable, execution/traversal bounded, and existing
  bare `random_int` behavior unchanged. Future `random.*`, `time.*`, and
  `resource.*` namespaces are **not** delivered here.
- BUILTIN/GEL/registered IMPLEMENTATION variants share the same read
  authority and typed-result boundaries.

**Primary integration points:** `src/grass/core/gel.py`,
`_gel_syntax.py`, `_gel_validation.py`, `_gel_interpreter.py`;
new narrowly scoped semantic-binding/query/capability modules as needed;
`src/grass/worlds/mechanics.py`, composition and material loaders.

**Gate C:** GEL rejects unauthorized/unknown calls and dynamic method
access; cap defaults and overrides behave correctly; typed subject confusion,
undeclared/absent properties and illegal schema conversions fail
deterministically; QueryValue does not inherit mechanic grants; no GEL
callback mutates WorldState or affects replay.

## Stage D — movement rule selection and runtime integration

- Add one global `MechanicBinding` selection contract
  (BUILTIN/GEL/trusted registered IMPLEMENTATION) with
  `MovementRule.capabilities` owned at rule level, not inside the binding.
- Implement explicit `movement.selection_bindings` shared by every
  conditional selector, bounded `ALL/ANY/NOT/EQ/IN/EXISTS` predicates,
  deterministic unique-match/default semantics, and validation of overlapping
  or ambiguous matches under ADR-0029.
- Resolve chosen rule `input_bindings` to the exact
  `MovementContract.input_schema` ValueSchema object; enforce requiredness,
  optionality and lossless GEL representation mapping.
- Implement `MovementResult(outcome, resolved_destination)` with an existing
  canonical SpaceId or None. The trusted adapter alone materializes
  `SubjectResolutionOutcome` and optional `SetLocationEffect`.
- Integrate with existing Jobs, PlanStep.parameters and deterministic
  world-resolution candidate validation. No direct WorldEffects or Events
  from mechanics; no new actor bootstrap/perception architecture.
- Resolve GEL `source_file` references for movement mechanics through
  the same contained WorldPackage material rules already used for
  scenario-occurrence GEL, including snapshot/reopen equivalence.

**Primary integration points:** `src/grass/core/world_resolution.py`,
`world_definitions.py`, `mechanics.py`, `src/grass/worlds/composition.py`,
`mechanics.py`, `package.py`, `src/grass/runtime/engine.py`.

**Gate D:** same MOVE request and history state produce the same rule,
typed input, result, outcome and Events; zero/one/multiple selector match
cases are covered; no implicit movement fallback; reruns/replay never invoke
GEL/plugin mechanics to reconstruct accepted Events.

## Stage E — Query API, end-to-end validation and delivery

- Add read-only `SpaceView` and `get_spaces` / `get_space` /
  `get_direct_location` / `get_enclosing_spaces` / `is_within` to the
  existing exact-history-position Query boundary. Preserve inactive topology
  and cycle-safe semantics without property inheritance.
- Keep CLI and human/JSON output consistent with the existing Application/
  Query API; add only the minimal surface needed to expose accepted facts,
  not a new Diagnostics API or frontend.
- Update `docs/ACCEPTANCE_SCENARIO.md` examples, example packages and tests
  so Office is a first-class Space and every Entity has a direct location.
- Extend existing world, GEL, run, package, replay, query, CLI and verification
  test suites; add dedicated spatial/movement suites where useful.
- Run the complete project checks from `pyproject.toml` and all tests
  after integrating the stages; reconcile only issues allowed by ADR-0029.

**Gate E — Slice 17.2 done only when:**

1. a nested-Space world is accepted from a strict format-1 package and initialized
   through one atomic genesis;
2. MOVE resolves through world-owned rules and typed mechanics and produces
   proper committed location/outcome Events;
3. cascading deactivation, cycle policy, reactivation, same-transition conflicts
   and deterministic CreationRef IDs pass positive and negative tests;
4. exact-position Query and branch/replay reconstruct identical canonical
   spatial/lifecycle facts without running mechanics or providers;
5. permissions are bounded and tested across GEL, QueryValue and all
   mechanic-binding variants;
6. existing occurrence-only packages, refreshed for current pre-stable schema
   1, still run/reopen and honor `.grass` workspace defaults;
7. all repository tests, lint/type checks and relevant CLI smoke tests pass;
8. `ROADMAP.md` can truthfully be updated from implementation pending to complete.

## Builder execution rules

- Implement in dependency order A -> B -> C -> D -> E; internal substeps and
  exact module layout may be adjusted without changing accepted semantics.
- Begin with tests/invariants for each stage, commit coherent, green slices,
  and never claim full completion from DTO scaffolding alone.
- Treat ADR-0029 and ADR-0017 as binding semantics; favor the current accepted
  decisions over pre-spatial code or obsolete examples.
- Where an implementation detail is open, choose a minimal deterministic
  solution and record it. Escalate only genuine semantic/authority/replay
  contradictions rather than improvising a different architecture.
- Do not extend Slice 17.2 into actor bootstrap, perception/reaction
  orchestration, new random/time/resource capabilities, geometry/physics,
  property inheritance, Diagnostics API or frontend work.
