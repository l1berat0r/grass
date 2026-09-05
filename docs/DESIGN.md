# GRASS — GRASS Roots Agentic Systems Simulator

## Architecture Baseline 0.1

**Status:** Design baseline `design-0.1`  
**Audience:** maintainers, coding agents, reviewers, scenario designers  
**License:** GPL-3.0-only  
**Implementation status:** implementation may begin from this baseline

This document describes the current architecture of GRASS. Accepted ADRs explain why particular decisions were made. After this baseline, material changes to core contracts should normally be introduced through a new ADR and then reflected here.

---

## 1. Purpose

GRASS is a general-purpose, AI-assisted simulator of dynamic human and social systems. A scenario may model a corporation, political party, state, community, expedition, castaway group, or another social environment without embedding domain-specific behavior in the core engine.

GRASS is designed for emergent behavior, imperfect knowledge, configurable world mechanics, cooperation and competition, communication and information flow, human intervention, replaceable cognition providers, replay, branching, counterfactual comparison, and post-run analysis.

GRASS is not assumed to be scientifically predictive by default. Scientific claims require scenario-specific calibration, validation, uncertainty analysis, and evidence.

## 2. Central authority principle

> **Only the simulation engine commits reality. Decision providers propose actor behavior; world-resolution providers determine candidate outcomes.**

LLMs, humans, scripts, deterministic policies, planners, scenario mechanics, and world resolvers may propose intentions, plans, calculations, and candidate outcomes. They do not directly mutate authoritative simulation state.

All authoritative changes are committed as immutable Events through the engine's validated transition boundary and deterministic projections.

This separation preserves replay, branchability, observability, security, and provider independence.

## 3. Canonical history and SimulationState

Committed Event history is the canonical source of truth.

`SimulationState` is the reconstructed authoritative state of one branch at one committed history position:

```text
SimulationState
    WorldState
    ExecutionState
    CognitionState
```

These are deterministic projections of the same Event history, not independent sources of truth.

### 3.1 WorldState

`WorldState` is objective modeled reality at the scenario-selected resolution. It includes relevant projections of Entities, Relations, entity-associated Resources, state variables, authoritative Information items, and other generic world structures.

Actors never receive unrestricted `WorldState` as cognition context.

### 3.2 ExecutionState

`ExecutionState` contains persistent intention/execution facts required to continue the simulation without regenerating previous choices, including versioned Plans, PlanSteps, Jobs, and their material lifecycle relationships.

Ephemeral scheduler indexes such as `ScheduledResolution` are not part of `ExecutionState`.

### 3.3 CognitionState

`CognitionState` contains actor-relative state that must be reproducible/branchable, including materially relevant Observations, DecisionPoints, structured DecisionOutcomes/decision records, persistent belief/memory state where configured, and cognition-provider binding history where it affects continuation.

Private chain-of-thought is never required or persisted as authoritative state.

The fundamental semantic split remains:

```text
world truth
!= represented semantic content
!= observation
!= interpretation
!= belief
```

## 4. WorldDefinition and SimulationRunConfig

`WorldDefinition` defines scenario semantics. `SimulationRunConfig` defines how one experimental run executes that scenario.

A used `WorldDefinition` version is immutable. Material scenario changes create a new version.

Conceptually:

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
        channel/information types?

    mechanics
        blueprints
        primitive_mechanics
        resource_mechanics
        state_variable_mechanics
        temporal_mechanics
        scenario_event_rules
        capability rules/evaluator binding
        perception mechanics
        decision-trigger policy binding
        validation mechanics?

    initial_conditions
        logical_time
        entities
        actor_facets
        relations
        resources
        state_variables
        information?
        commitments?

    termination_rules?
    metadata
```

`WorldDefinition` does not contain runtime WorldState, Events, Plans, Jobs, DecisionPoints, branch/checkpoint state, scheduler indexes, credentials, or one run's provider/model/seed choices.

Conceptually:

```text
SimulationRunConfig
    world_definition_ref
    resolution_mode
    world_resolution_provider_binding
    decision_provider_bindings
    model_provider_bindings
    random_seed / random-stream configuration
    execution_options
    reproducibility_options
```

The same world can therefore be run with different providers, models, resolver modes, or random seeds without redefining scenario truth.

### 4.1 Initial conditions and genesis

`InitialConditions` are declarations, not Events. Starting a run performs a validated genesis transition that emits normal immutable history and produces the initial `SimulationState`.

```text
WorldDefinition.initial_conditions
    -> validation / genesis transition
    -> Event batch
    -> SimulationState
```

## 5. Scenario mechanics and GEL

Built-in formulas are convenience models, not the expressiveness boundary of GRASS.

Scenario mechanics use a conceptual binding with at least:

```text
MechanicBinding
    BUILTIN
    GEL
    IMPLEMENTATION
```

- `BUILTIN`: library-provided models such as bounded linear evolution, thresholds, decay, or common distributions.
- `GEL`: a restricted, versioned GRASS Expression Language program intended to be safely generated by humans or LLMs.
- `IMPLEMENTATION`: explicitly trusted installed scenario/plugin code for advanced models that cannot reasonably be expressed by built-ins or GEL.

All forms remain below the same authoritative Event/transition boundary.

### 5.1 GRASS Expression Language (GEL)

GEL is a deterministic, resource-bounded DSL.

```text
GEL source
    -> parser
    -> AST
    -> static/type validation
    -> bounded interpreter
    -> typed result
```

Never:

```text
LLM output -> host-language eval/exec
```

A GEL mechanic declares its input and output schemas. It may read only explicitly supplied typed variables/read-only views. It receives no unrestricted WorldState handle and no ambient filesystem, network, process, environment, database, import, reflection, or dynamic-code capability.

Initial GEL may support arithmetic, comparisons, boolean logic, local variables, `if`/`else`, safe mathematical functions, typed objects/lists, and bounded `for` iteration. Unbounded `while`, recursion, imports, reflection, concurrency, and dynamic code generation are excluded initially.

The interpreter enforces hard limits for source/AST size, operation count, loop iterations, collection/result size, numeric behavior, and execution time/operation budget.

GEL is side-effect-free with respect to authoritative simulation state. It computes values or structured candidate results; world-affecting consequences still pass through normal mechanics/resolution, validation, Events, and reducers.

Randomness, where exposed to GEL, comes only from an explicit deterministic run random context/stream, never from a hidden process-global RNG.

Canonical scenario data preserves GEL source, language version, input/output schema, and a source hash where useful. Parsed AST/bytecode may be cached as derived data.

## 6. Scenario events and stochastic time

A scenario may define future material occurrences through `ScenarioEventRule`.

Initial trigger families include:

- `AT_TIME`;
- `AFTER_DURATION`;
- `RANDOM_TIME` from a configured probability distribution.

A scenario event rule is a definition, not a committed Event. The scheduler derives an ephemeral future resolution candidate; when due, the normal mechanics/resolution path produces candidate effects and committed Events.

```text
ScenarioEventRule
    -> ScheduledResolution
    -> mechanic/resolution
    -> ResolutionProposal / WorldEffects
    -> validation
    -> Events
```

Probability distributions belong to `WorldDefinition`; run seed/random-stream configuration belongs to `SimulationRunConfig`.

Material random choices must be reproducible and must not accidentally depend on unrelated consumption of one global RNG stream. Keyed/sub-stream RNG based on run seed plus mechanic/rule/occurrence identity is the preferred direction; exact implementation remains open.

Replay never resamples already-recorded history.

## 7. Entity, Actor, Relation, Resource, and Information

### 7.1 Entity

An `Entity` is something the scenario needs to identify and refer to persistently across time.

Conceptually:

```text
Entity
    entity_id
    entity_type
    active
    properties
    semantic_content?
```

`active` is authoritative. Deactivation preserves identity/history.

Initial generic entity vocabulary includes:

- `Person`;
- `Organization`;
- `Group`;
- `Location`;
- `Artifact`;
- `Commitment`.

Scenarios may define domain-specific types without requiring new core classes.

### 7.2 Actor

Actor capability is composition over Entity identity, conceptually:

```text
ActorFacet
    entity_id
    actor_kind
    decision_provider_binding
```

The first implementation focuses on actor-capable Persons; Groups/Organizations may later become actor-capable without changing historical Entity identity.

### 7.3 Relation

Relations are first-class persistent objects with stable identity, scenario-defined type, participant/role bindings, properties, and active state.

Employment, membership, reporting, ownership, alliance, marriage, and similar domain concepts are scenario relation types rather than core action verbs.

### 7.4 Resource

Every authoritative Resource quantity is associated with an Entity:

```text
ResourceState(
    entity_id,
    resource_type,
    quantity,
    unit?,
    properties?
)
```

Use Resource where transfer, consumption, production, reservation, control, sharing/delegation, location/ownership, or aggregation matters; otherwise use a StateVariable.

Resource bounds such as min/max are scenario/resource definitions. Core does not hard-code `quantity >= 0`.

### 7.5 Commitment

`Commitment` is a generic Entity representing promises, agreements, contracts, or future coordination. It may project a future due resolution, but it does not force actor behavior. An actor may comply, renegotiate, violate, ignore, or reject it through normal decisions/mechanics.

### 7.6 Information

Information/claims are first-class and provenance-aware. Received information is not automatically belief.

A useful model may include claim/content, source/provenance, sender/recipients, channel, logical time, credibility/confidence, retransmission ancestry, and transformations/summaries.

## 8. Actor-facing action model

`ActionProposal` states what an actor intends to attempt. It does not contain resolver-calculated mechanics or authoritative outcome deltas.

Conceptual common envelope:

```text
ActionProposal
    proposal_id
    actor_id
    primitive
    intent_description
    content?
    time_budget?
    job_id?
    payload
```

`intent_description` is required purpose. `content` is optional represented/communicated semantic content. `time_budget` is intended actor time, not actual duration. `job_id` represents continuation where appropriate.

World references may be concrete or unresolved semantic selectors:

```text
WorldRef
    kind        # ENTITY / RELATION / BLUEPRINT initially
    id?
    description?
```

The v0.1 actor-facing primitive set is:

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

No separate core `PERFORM`, `DESTROY`, `SCHEDULE`, or `GRANT_ACCESS` primitive is required. Work composes through existing primitives/Jobs, destruction through MODIFY/deactivation, future coordination through Commitment, and access through scenario-defined resource/relation semantics.

## 9. Blueprint, Plan, PlanStep, and Job

### 9.1 Blueprint

> **One Blueprint = one primitive. Multi-primitive composition belongs in Plan.**

A Blueprint is reusable process knowledge/hypothesis, not proof of feasibility.

Conceptually it may include stable id/version, active state, origin, one primitive, parameter schema, roles, expected resources, execution/progress spec, result spec, and semantic assumptions.

Scenario-defined Blueprints belong to `WorldDefinition`; actor-created Blueprints are runtime authoritative history/state. Actor-created/LLM-generated Blueprints are untrusted hypotheses.

### 9.2 Plan

A Plan is a persistent actor intention structure, not a scheduler workflow that must be forced to completion.

Conceptually:

```text
Plan
    plan_id
    version
    actor_id
    source_decision_point_id?
    source_proposal_id?
    objective
    steps[]
    provenance
    created_at
```

Plan versions are immutable. A material revision creates a new version; a materially replaced intention may create a new Plan identity.

### 9.3 PlanStep

Each PlanStep explicitly declares exactly one primitive and may optionally reference an exact immutable Blueprint version for that same primitive.

```text
PlanStep
    step_id
    primitive
    blueprint_ref?
    bindings
    parameters
    dependencies[]
    origin
    description?
```

v0.1 dependencies form a DAG. Initial dependency conditions:

- `SUCCESS` (default);
- `TERMINAL`.

Missing dependency permits potential concurrency but does not bypass scheduler checks for resources, actors, participation, capabilities, conflicts, or mechanics.

No arbitrary v0.1 plan if/else/loop/retry workflow DSL is required. Material failures/observations create DecisionPoints and the actor may revise/replace the Plan.

### 9.4 Job

> **Every started PlanStep creates exactly one Job, whether or not the step uses a Blueprint.**

Before start: 0 Jobs for the step. Once started: exactly 1 stable Job for that step.

Initial statuses:

```text
PENDING
ACTIVE
PAUSED
COMPLETED
FAILED
CANCELLED
```

The final three are terminal. Retry after terminal failure/cancellation is a new PlanStep (normally in a new Plan revision) and therefore a new Job.

Progress is structured, not universally a percentage; v0.1 supports at least LINEAR and BINARY models.

## 10. Capability evaluation

Capability/feasibility evaluation is a replaceable boundary:

```text
CapabilityEvaluator.evaluate(context) -> CapabilityAssessment
```

The default v0.1 evaluator may use dimensions such as physical, technical, authorization, preventive enforcement, and detectability, with values such as SATISFIED/UNSATISFIED/UNKNOWN. Those exact dimensions are provisional and must not become a fixed ontology in core.

Important distinctions:

```text
authorized != mechanically possible
unauthorized != mechanically impossible
detectable != prevented
```

Capabilities are derived dynamically from state, relations, resources, location, controlled entities, roles, scenario rules, and environment. Do not create static domain action booleans such as `actor.can_restart_server`.

UNKNOWN must not silently equal success or failure.

## 11. DecisionPoints, perception, and cognition

Actors are invoked at DecisionPoints, not on turns.

Every committed Event that reaches/affects an actor first passes through perception/propagation mechanics and becomes an actor-relative Observation where appropriate. `DecisionTriggerPolicy` then evaluates the Observation together with the actor's current Plan, relevant Jobs, and perceived context.

```text
Event
    -> perception/propagation
    -> Observation(actor)
    -> DecisionTriggerPolicy
    -> CONTINUE | DecisionPoint
```

The same Event may interrupt one actor and be passive for another.

Initial DecisionPoint reasons include:

```text
PLAN_REQUIRED
PLAN_EXHAUSTED
PLAN_BLOCKED
INTERACTION_REQUEST
JOB_FAILED
JOB_PAUSED
ASSUMPTION_INVALIDATED
MATERIAL_OBSERVATION
EXTERNAL_EVENT
OPERATOR_INTERVENTION
```

Initial scopes:

- `FULL` — broad reconsideration of the Plan;
- `BOUNDED` — response to one concrete interaction/problem without automatic global replanning.

Initial DecisionOutcome kinds:

```text
CONTINUE_PLAN
REVISE_PLAN
REPLACE_PLAN
BOUNDED_REACTION
```

These vocabularies are versionable/extensible.

A bounded reaction that affects the world still follows the normal path:

```text
DecisionPoint
    -> DecisionProvider
    -> DecisionOutcome
    -> ActionProposal/planning
    -> PlanStep
    -> Job
    -> WorldResolution
    -> Events
```

No DecisionOutcome directly mutates reality.

Material Observations, DecisionPoints, Decisions, and Plans are persisted through semantic Events to the degree required for replay, branching, continuation, observability, and the configured reproducibility level.

## 12. Provider architecture and security

`DecisionProvider` may be LLM-backed, human, scripted, deterministic, random, or future implementations.

`ModelProvider` is separate from decision policy. Initial model transport targets include OpenAI, Ollama, and OpenAI-compatible/local endpoints.

Provider execution location is explicit:

- `SERVER_MANAGED`;
- `CLIENT_MANAGED`.

Server-managed secrets never reach frontend code. Client-managed secrets should initially remain in browser memory and not be persisted in localStorage/sessionStorage or passed through the backend.

Client-returned model output is untrusted cognition input and cannot supply authoritative world mutations.

No unrestricted server-side user-selected URL proxy is permitted; any future relay requires explicit SSRF/egress security design.

Provider fallback is explicit, never silent. Provider/model changes affecting a run are recorded as experimental/provenance data.

## 13. Event-driven scheduler

GRASS does not use mandatory global turns/ticks. Logical time advances to the next material resolution point.

The scheduler coordinates time, active/pending Jobs, dependency-ready PlanSteps, scenario/commitment/temporal future candidates, conflicts, simultaneous groups, and DecisionPoints. It does not own reality.

Conceptual loop:

1. resolve DecisionPoints at the current logical time;
2. derive/update Plans;
3. start eligible PlanSteps and create Jobs;
4. derive future material resolution candidates;
5. choose the earliest logical time;
6. gather all current/non-stale candidates at that time;
7. determine interacting/conflicting groups;
8. advance the clock;
9. accrue elapsed progress/dynamics;
10. resolve each coherent group;
11. atomically commit Events;
12. derive actor-relative Observations;
13. evaluate DecisionTriggerPolicy;
14. create DecisionPoints where required;
15. otherwise continue existing Plans/Jobs and jump again.

If an actor sleeps 23:00-07:00 and nothing else matters, the clock can jump directly eight hours. If an alarm is due at 02:00, the clock jumps only to 02:00, accrues three hours of sleep progress, resolves the interruption, and reprojects future work.

### 13.1 ScheduledResolution

`ScheduledResolution` is an **ephemeral derived scheduler optimization**, not authoritative state and not an Event.

Conceptually:

```text
ScheduledResolution = derive(
    authoritative SimulationState,
    Plans,
    Jobs,
    Commitments,
    temporal/scenario mechanics
)
```

Minimal v0.1 shape:

```text
ScheduledResolution
    logical_time
    kind
    source_ref
    metadata?
```

Example kinds include JOB_CHECKPOINT, JOB_EXPECTED_COMPLETION, SCENARIO_EVENT, COMMITMENT_DUE, DEADLINE, TEMPORAL_THRESHOLD.

The scheduler index may be discarded and rebuilt at any time. Generation tokens, heap layout, queue-entry IDs, compaction strategy, and exact index structure are implementation details.

Strong invariant:

> Rebuilding the scheduler index from the same authoritative state must produce a semantically equivalent set of future material resolution candidates.

For deterministic runs:

```text
incremental scheduler maintenance
vs
full rebuild after every committed batch
=> same authoritative history
```

This should become a regression/property test.

### 13.2 Same-time semantics

Queue ordering among entries with identical `logical_time` has no world semantics. The scheduler gathers all due entries at the earliest time before semantic resolution.

Independent components may resolve separately. Interacting components sharing resources, participants, exclusive control, incompatible transitions, or other conflicts must be jointly/coherently resolved.

Stable technical secondary ordering may aid debugging but does not create causality.

### 13.3 TemporalProjection and continuous/rate mechanics

Temporal projections are predictions, not promises. Use anchor + elapsed-time models where practical instead of tiny periodic writes. Schedule material thresholds/completions rather than fixed ticks.

When relevant state changes, predictions are invalidated/rederived. Continuous/recurring processes resolve one material boundary and then project the next.

## 14. World resolution and WorldEffects

World adjudication is replaceable behind a narrow conceptual boundary:

```text
WorldResolutionProvider.resolve(ResolutionRequest)
    -> ResolutionProposal
```

Initial modes:

- `DETERMINISTIC`;
- `GENERATIVE`.

Deterministic mode derives outcomes from explicit scenario mechanics/current state. Generative mode may use an LLM/model as a creative adjudicator. Generative output is still untrusted structured input and has no structural privilege.

Possible valid resolution outcomes include SUCCESS, PARTIAL, BLOCKED, FAILED, and INTERRUPTED.

Resolvers never return an authoritative replacement SimulationState/WorldState. They propose structured effects/outcomes.

### 14.1 Closed core WorldEffect algebra

Initial generic candidate mutation operations include:

```text
CREATE_ENTITY
UPDATE_ENTITY
DEACTIVATE_ENTITY
CREATE_RELATION
UPDATE_RELATION
DEACTIVATE_RELATION
CHANGE_RESOURCE
SET_STATE_VARIABLE
UPDATE_JOB
CREATE_INFORMATION
```

No arbitrary `ScenarioCustomEffect` escape hatch exists. If a generic effect is missing, core may be deliberately extended through architecture/versioning rather than allowing opaque scenario mutation opcodes.

`TemporalProjection` is separate from WorldEffects.

### 14.2 Validation and failure

The authoritative validator checks the complete atomic candidate batch against current state, schemas, references/IDs, branch isolation, resource/state constraints, compatibility, and engine invariants.

World/social/legal illegality is not the same as structural invalidity. Actors may attempt illegal or unethical behavior if scenario mechanics permit an attempt.

Invalid deterministic resolver output is a fatal execution/integrity error. Generative output may receive bounded repair attempts; if still invalid, execution stops without partial effects/events or authoritative time advancement. The branch remains valid at the last committed transition.

Normal infeasibility is a valid FAILED/BLOCKED/PARTIAL/etc. world outcome, not an integrity failure.

## 15. Event contract and semantic Event types

`WorldEffect != Event`.

A WorldEffect is a candidate authoritative transition. An Event is an immutable accepted historical fact.

Minimal Event envelope:

```text
Event
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

`transition_id` identifies one atomic authoritative commit. All Events in one transition commit atomically.

`sequence` defines deterministic replay/storage order within a branch; it does not prove causality.

### 15.1 Semantic generic Event types

Core uses semantic, domain-neutral Event types rather than only `WorldEffectApplied` and rather than domain verbs.

Examples include:

```text
EntityCreated
EntityUpdated
EntityDeactivated
RelationCreated
RelationUpdated
RelationDeactivated
ResourceChanged
StateVariableChanged
JobCreated
JobActivated
JobPaused
JobCompleted
JobFailed
JobCancelled
InformationCreated
ObservationCreated
DecisionPointCreated
DecisionRecorded
PlanCreated
PlanRevised
PlanReplaced
```

The exact complete v0.1 catalog is implementation-driven and versioned.

Historically meaningful non-mutating Events may include ActionProposed/Attempted/Rejected/Failed/Succeeded, ActorRefused, ProviderChanged, ScenarioOccurrenceTriggered, and OperatorIntervention where useful.

Each Event type versions its payload independently.

A state-transition payload contains enough information for deterministic reduction without re-running planners, LLMs, GEL, resolvers, or random samplers, but should not duplicate full snapshots routinely.

Provenance is mandatory. Causal relationships are explicit through cause refs and are never inferred merely from sequence adjacency.

## 16. Atomic history positions, replay, and branching

Events are append-only and immutable.

Normal replay reconstructs `SimulationState` using persisted Events and deterministic projections only. It does not call DecisionProviders, humans, ModelProviders, WorldResolutionProviders, GEL mechanics, planners, or random samplers to rediscover past choices/outcomes.

Calling those components again from a historical point creates new continuation/history.

A branch has a parent and fork position. Shared prefix is immutable; continuation is independent.

A branch created before a recorded decision may invoke cognition again when it reaches the DecisionPoint. A branch created after a recorded decision inherits that decision/Plan as part of the shared prefix unless an explicit earlier fork/regeneration/intervention is selected.

Because `transition_id` is atomic, externally valid replay/fork positions are **committed transition boundaries**, not intermediate Events inside one transition. Readers observe state before or after the complete transition, never a partial authoritative state.

Snapshots/checkpoints accelerate reconstruction but are not canonical history.

## 17. Operator interaction

Operator roles/modes conceptually include:

- Observer — read-only simulation inspection;
- Director / in-world intervention — introduces something that could exist in the world and passes through normal mechanics;
- Override — explicit audited simulator-state intervention outside normal in-world causality;
- Actor possession — temporarily substitutes an actor's DecisionProvider with a HumanDecisionProvider.

Operator actions must be explicit and provenance-bearing. Actor possession should expose actor-relative information, not omniscient observer state, unless an explicit debug mode is chosen.

## 18. Observability and analysis

Observability is architectural. Desired surfaces include global and actor timelines, state/resource histories, Plans/Jobs/DecisionPoints, conversations, information propagation, relationships, provider/resolver provenance, branches, and filters by time/type/actor/source.

A Simulation Analyst is external/read-only. Deterministic metric computation should be separable from optional LLM interpretation.

Metrics may later include resource concentration/Gini/quantiles, mobility, network centrality, formal authority, social influence, information centrality, trust capital, and information flow. Observer/analyst knowledge may exceed actor knowledge; this must not leak into actor cognition.

## 19. Acceptance scenario

The baseline architecture is exercised in [`ACCEPTANCE_SCENARIO.md`](ACCEPTANCE_SCENARIO.md).

The scenario covers genesis, actor decision and Plan creation, Job start, direct clock jumps, interaction and bounded reaction, same-time resource conflict, scenario events, GEL mechanics, Commitments, Job failure, replay without providers, and branch continuation.

Implementation should progressively turn this walkthrough into integration/acceptance tests.

## 20. Initial implementation scope and sequence

Implementation begins with pure Python core; FastAPI/React come later.

Recommended v0.1 sequence:

1. identifiers, logical time, provenance/value objects;
2. minimal `WorldDefinition` definitions and run configuration;
3. Event envelope/types, in-memory EventStore, transition atomicity;
4. `SimulationState` projections and deterministic reducers;
5. Entity/Relation/Resource/StateVariable core state;
6. branch ancestry, replay, fork/reconstruction;
7. Plan/PlanStep/Job execution projection;
8. ScheduledResolution index with full-rebuild equivalence tests;
9. deterministic temporal/world resolver and validator;
10. DecisionPoint/Observation plus scripted/fake DecisionProvider;
11. acceptance-scenario vertical slice;
12. GEL parser/validator/interpreter and safe execution budgets;
13. provider adapters (OpenAI/Ollama/OpenAI-compatible/Human) behind existing contracts;
14. FastAPI/backend and React frontend after core contracts prove stable.

The first executable milestone should prioritize architecture/invariants over realism.

Explicitly later: collective/institutional actor cognition, society-scale distribution, sophisticated economics/psychology/law/biology, advanced geography, rich UI, automatic population-resolution changes, and causal-inference claims.

## 21. Remaining implementation-level open questions

The design baseline intentionally leaves lower-level choices open where they do not change the accepted architecture. Examples include:

- exact Pydantic/serialization schemas and identifier formats;
- EventStore/database technology and snapshot cadence;
- exact initial Event payload catalog and historical upcasting implementation;
- exact `WorldDefinition` file format and schema tooling;
- exact GEL textual grammar, primitive type set, safe standard library, numeric policy, and parser implementation;
- random-stream key derivation;
- exact scheduler priority/index data structure, stale-entry compaction/rebuild thresholds, and conflict-component algorithm;
- exact source-ref/TemporalProjection schemas;
- exact `ResolutionRequest` / `ResolutionProposal` DTOs;
- detailed capability-evaluator default dimensions/UNKNOWN policy;
- belief representation and memory retrieval/compaction;
- exact bounded-reaction materialization in planning;
- conversation/job contribution granularity beyond v0.1;
- provider/resolver prompt/version/cost policies;
- durable client-managed credential storage if BYOK persistence is ever added;
- secured relay/local-provider bridge design if ever required.

Implementation may choose local details that preserve accepted ADRs and this baseline. Material changes to core authority, persistence, replay, provider, action, scheduler, world-resolution, or scenario-mechanics contracts require a new ADR.

## 22. Prior art

Concordia, AgentSociety 2, OASIS/CAMEL-AI, MiroFish, AgentTorch, AI Town/Smallville, Mesa, AnyLogic, Simudyne, Sapien, and related systems provide useful prior art.

They are not GRASS architecture templates. Do not copy external APIs, class hierarchies, schemas, package structures, prompts, or implementation details merely because a project is referenced.

## 23. Licensing

GRASS is licensed under **GNU General Public License version 3 only (GPL-3.0-only)**.

Project-owned source files should use `SPDX-License-Identifier: GPL-3.0-only` where practical. Dependencies and incorporated third-party code must be reviewed for GPLv3 compatibility.

## 24. Guiding principle

> **Keep the world's rules explicit, keep actors' knowledge incomplete, keep decisions replaceable, keep execution bounded, and keep history inspectable.**

Complexity should emerge from interactions among composable mechanics rather than from a monolithic prompt or an opaque model-generated story.
