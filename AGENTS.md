# GRASS — Coding Agent Instructions

GRASS has reached the **`design-0.1` architecture baseline**. Read `docs/DESIGN.md` and accepted ADRs before changing core contracts.

## Mission

Build GRASS (GRASS Roots Agentic Systems Simulator), a general-purpose simulator of dynamic human/social systems without hard-coding domain behavior into core abstractions.

## Non-negotiable authority rules

1. Only the simulation engine commits reality. Decision providers propose actor behavior; world-resolution providers determine candidate outcomes.
2. Committed Event history is canonical. `SimulationState` is reconstructed from deterministic projections of that history.
3. Do not mutate authoritative state directly from actors, providers, planners, executors, API handlers, frontend code, scenario adapters, GEL, or resolvers.
4. `WorldEffect != Event`. WorldEffects are candidate transitions; Events are immutable accepted facts.
5. All Events in one `transition_id` commit atomically. Never expose partial transition state as a replay/fork point.
6. Ordinary replay never regenerates historical cognition, planning, resolution, GEL execution, or randomness.
7. Branches share an immutable prefix and continue independently from committed-transition boundaries.
8. Provenance is mandatory; private chain-of-thought is not.
9. Event sequence is replay/storage ordering, not evidence of causality.

## SimulationState boundaries

Treat authoritative runtime state conceptually as:

```text
SimulationState
    WorldState
    ExecutionState
    CognitionState
```

- `WorldState`: objective modeled reality.
- `ExecutionState`: Plans, PlanSteps, Jobs, and material execution relationships.
- `CognitionState`: materially relevant Observations, DecisionPoints, structured decisions, and persistent actor cognition state where configured.

Keep world truth, semantic content, observation, interpretation, and belief distinct.

`ScheduledResolution` is disposable/rebuildable scheduler data, never canonical SimulationState.

## WorldDefinition / run configuration

Keep `WorldDefinition` separate from `SimulationRunConfig`.

`WorldDefinition` owns scenario vocabulary, mechanics, scenario Blueprints, scenario event rules, initial conditions, and optional termination rules. A used version is immutable.

`SimulationRunConfig` owns one run's resolution mode, provider/model bindings, random seeds/streams, execution options, and reproducibility configuration.

InitialConditions are declarations. Starting a run validates/materializes them through genesis Event transition(s).

Scenario-defined Blueprints live in WorldDefinition; actor-created Blueprints live in runtime history/state.

## Scenario mechanics and GEL

Do not restrict scenario mechanics to simple min/max/linear built-ins. Support the conceptual forms:

```text
BUILTIN
GEL
IMPLEMENTATION
```

- BUILTIN: trusted library models.
- GEL: restricted, versioned GRASS Expression Language suitable for LLM/human generation.
- IMPLEMENTATION: explicitly installed/authorized trusted host-language plugin code.

### GEL guardrails

- Never execute LLM-generated Python/host-language code through eval/exec/import.
- GEL reads only explicitly supplied typed inputs/read-only views.
- No filesystem, network, process, environment, database, import, reflection, or dynamic-code capability.
- Initial GEL may support arithmetic, comparisons, boolean logic, local variables, `if/else`, safe functions, typed collections, and bounded iteration.
- Do not introduce unbounded `while` or recursion initially.
- Enforce hard source/AST/operation/loop/collection/result/numeric/time budgets.
- GEL returns typed calculations/structured results and never directly mutates SimulationState or appends Events.
- Randomness must use explicit deterministic run streams, never hidden global RNG.
- Persist canonical GEL source + language version + schemas; AST/bytecode is derived/cache data.

## Entity / actor / relation / resource rules

- `Entity` is the persistent identity anchor for scenario-relevant things that need identity across time.
- Model at scenario resolution; do not make every physical item an Entity.
- Deactivate rather than delete identities that remain historically relevant.
- Initial generic entity vocabulary includes `Person`, `Organization`, `Group`, `Location`, `Artifact`, and `Commitment`.
- Actors are entity-backed composition/facets, not a parallel identity hierarchy.
- Relations are first-class persistent objects; domain concepts such as employment/membership/ownership are scenario relation types.
- Every Resource quantity is associated with an Entity.
- Resource bounds belong to scenario definitions. Do not hard-code universal non-negativity.
- Use Resource when transfer/consumption/production/reservation/control/sharing/aggregation matters; otherwise StateVariable may be more appropriate.
- Information received by an actor is not automatically belief.

## Action-system guardrails

Model v0.1 `ActionProposal` as a typed/discriminated union with a small common envelope:

```text
proposal_id
actor_id
primitive
intent_description
content?
time_budget?
job_id?
payload
```

`intent_description` is actor purpose, not outcome. `time_budget` is intended time, not actual duration. Keep generic targets, calculated resource claims, required participants, dependencies, resolved preconditions, expected completion, and world deltas out of the common envelope.

Initial actor-facing primitives:

```text
CREATE
MODIFY
RELATE
TRANSFER
MOVE
COMMUNICATE
OBSERVE
WAIT
REST
```

Do not add core `PERFORM`, `DESTROY`, `SCHEDULE`, or `GRANT_ACCESS` merely for domain convenience.

## Blueprint / Plan / Job guardrails

> **One Blueprint = one primitive. Multi-primitive composition belongs in Plan.**

- Blueprint is process knowledge/hypothesis, not a feasibility certificate.
- Actor-created/LLM-generated Blueprints are untrusted hypotheses.
- Plan versions are immutable and provenance-preserving.
- Each PlanStep declares exactly one primitive and may optionally pin one exact Blueprint version for that primitive.
- v0.1 PlanStep dependencies form a DAG with `SUCCESS` (default) and `TERMINAL` conditions.
- Do not introduce arbitrary Plan if/else/loops/retry workflow DSL in v0.1; new material choices produce DecisionPoints and Plan revision/replacement.
- Do not add independently mutable PlanStep status or a persistent PlanExecution aggregate unless a concrete need appears.

> **Every started PlanStep creates exactly one Job, with or without a Blueprint.**

Initial Job statuses: `PENDING`, `ACTIVE`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`. The final three are terminal. Retry after a terminal attempt is a new PlanStep/new Job.

Progress is structured; do not assume universal percentage completion. Support at least LINEAR and BINARY initially.

## Decision / perception guardrails

Actors are invoked at DecisionPoints, not periodically.

```text
committed Event
    -> perception/propagation
    -> Observation(actor)
    -> DecisionTriggerPolicy
    -> CONTINUE or DecisionPoint
```

Observation and DecisionPoint are distinct. Do not call an LLM for every observation.

Initial DecisionPoint reasons include `PLAN_REQUIRED`, `PLAN_EXHAUSTED`, `PLAN_BLOCKED`, `INTERACTION_REQUEST`, `JOB_FAILED`, `JOB_PAUSED`, `ASSUMPTION_INVALIDATED`, `MATERIAL_OBSERVATION`, `EXTERNAL_EVENT`, and `OPERATOR_INTERVENTION`.

Initial scopes are `FULL` and `BOUNDED`; initial outcomes are `CONTINUE_PLAN`, `REVISE_PLAN`, `REPLACE_PLAN`, and `BOUNDED_REACTION`.

A bounded reaction never bypasses ActionProposal/planning -> PlanStep -> Job -> resolution -> Events.

Persist materially relevant Observation/Decision/Plan state sufficiently for replay/branching without regenerating historical cognition. Never persist private chain-of-thought for convenience.

## Capability evaluation

Keep capability/feasibility evaluation replaceable:

```text
CapabilityEvaluator.evaluate(context) -> CapabilityAssessment
```

The current default direction may use physical, technical, authorization, preventive-enforcement, and detectability dimensions, but those exact dimensions remain provisional.

Authorization != possibility. Unauthorized != impossible. Detectability != prevention. UNKNOWN must not silently mean success or failure.

Derive capabilities dynamically from current state, relations, resources, location, roles, controlled entities, scenario rules, and environment. Avoid static domain flags such as `actor.can_restart_server`.

## Event-driven scheduler guardrails

- No mandatory global tick/turn loop.
- Advance logical time to the earliest material resolution point.
- Allow direct long clock jumps when nothing else can affect the world.
- Accrue concurrent Job progress over the same elapsed interval.
- Scheduler coordinates time/work; it does not own reality.
- Use anchor + elapsed-time models and material threshold/completion projections instead of tiny periodic writes where practical.
- Reproject/invalidate future expectations when relevant state changes.

`ScheduledResolution` is ephemeral derived data and may be discarded/rebuilt from authoritative state at any time.

For deterministic simulations test:

```text
incremental scheduler maintenance
vs
full rebuild after every committed transition
=> same authoritative Event history
```

At the earliest timestamp, gather all current/non-stale entries before semantic resolution. Queue order among same-time entries has no world semantics. Group interacting/conflicting items coherently.

## World resolution guardrails

Keep `WorldResolutionProvider.resolve(ResolutionRequest) -> ResolutionProposal` behind a narrow replaceable boundary.

Initial modes are `DETERMINISTIC` and `GENERATIVE`. Generative mode has no structural privilege and cannot bypass identity/reference validity, Event sourcing, atomicity, branch isolation, schemas, or validation.

Resolvers never return authoritative replacement SimulationState/WorldState.

Keep the core WorldEffect algebra closed/versioned. Do not add arbitrary `ScenarioCustomEffect` escape hatches.

Validate the complete atomic candidate batch before commit. Normal infeasibility is a valid FAILED/BLOCKED/PARTIAL/INTERRUPTED/etc. outcome. Invalid deterministic output is an integrity error; generative output may receive bounded repair but never partial commit or guessed reality.

## Event guardrails

Use semantic, domain-neutral Event types rather than only `WorldEffectApplied` and rather than domain verbs.

Event envelope conceptually contains:

```text
event_id
branch_id
sequence
logical_time
transition_id
event_type
event_version
payload
provenance
causation_refs?
correlation_id?
```

Examples include Entity/Relation create-update-deactivate, ResourceChanged, StateVariableChanged, Job lifecycle Events, InformationCreated, ObservationCreated, DecisionPointCreated, DecisionRecorded, and PlanCreated/Revised/Replaced.

Historically meaningful non-mutating Events are allowed where material. Version Event payloads independently. Reducers/projections must reconstruct supported history without re-running producers.

## Provider security guardrails

Treat `SERVER_MANAGED` and `CLIENT_MANAGED` as distinct execution/security modes.

- Server-managed secrets never reach frontend code.
- Client-managed credentials do not pass through backend; initial browser storage is memory-only.
- Client-returned provider output is untrusted cognition input.
- Do not build an unrestricted backend provider URL proxy. Any future relay requires explicit SSRF/egress/destination/redirect/limit/timeout/secret design.
- Provider fallback is explicit, never silent.
- Persist provider/model/config metadata affecting experimental reproducibility.

## Operator guardrails

Support conceptually Observer, Director/in-world intervention, explicit Override, and actor possession/HumanDecisionProvider. Operator changes must be explicit and auditable. Actor possession should see actor-relative information unless an explicit debug/omniscient mode is chosen.

## Change methodology after design-0.1

- `docs/DESIGN.md` describes current architecture; accepted ADRs explain significant decisions.
- `design-0.1` is the baseline. Do not treat core architecture as an unconstrained working draft anymore.
- Material changes to authority, persistence, Event semantics, branching/replay, provider boundaries, action/Plan/Job contracts, scheduler semantics, world resolution, or scenario-mechanics/GEL contracts should normally be proposed through a new ADR first.
- Small implementation choices that preserve accepted contracts may be decided locally.
- Keep changes small and reviewable; implement bounded vertical slices rather than the whole simulator at once.
- Once persistence formats exist, preserve backward-readable historical data unless an accepted ADR explicitly defines migration/supersession.

## Coding expectations

- Core: Python, independent of FastAPI.
- Backend/API: FastAPI around the core.
- Frontend: React, with no simulation-domain authority in frontend code.
- REST for ordinary configuration/query; WebSocket for interactive/session/client-managed provider round trips.
- Favor typed interfaces/schemas and pure deterministic transition logic.
- Separate I/O/provider calls from reducers/projections.
- Use deterministic fake/scripted providers for core tests.
- Add tests for atomic transitions, replay consistency, branch isolation, scheduler rebuild equivalence, action validation, information provenance, provider substitution, and GEL sandbox/budget constraints as those modules appear.
- Do not optimize prematurely for millions of actors.

## Scope discipline for v0.1

Implement the smallest individual-actor vertical slice required to prove the architecture. Do not build sophisticated economics, psychology, law, politics, biology, collective actor cognition, or distributed society-scale execution into core.

Use `docs/ACCEPTANCE_SCENARIO.md` as the end-to-end architectural integration target.

## Prior art

Prior-art references in `docs/DESIGN.md` are informational only. Do not copy external project APIs, schemas, class layouts, package structures, prompts, or implementation details merely because they are mentioned.
