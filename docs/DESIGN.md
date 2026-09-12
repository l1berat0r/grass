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

`ProjectionPosition` records the branch-origin history completely applied to a `SimulationState`: `branch_id`, optional last `TransitionRef`, last Event sequence, and optional logical time. Empty history has sequence zero and no transition/time. This is projection metadata, not the ancestry-aware branch cursor introduced with branching.

`HistoryPosition` is that separate ancestry-aware cursor: a viewed branch ID plus an optional last visible complete `TransitionRef`. The reference may originate on an ancestor and denotes state after the whole transition. Logical time and sequence are derived from canonical history rather than duplicated in this cursor.

Projection applies one complete `CommittedTransition` to private candidate data and publishes one new immutable `SimulationState` only after every Event and final structural invariant succeeds. Unknown Events, unsupported versions, malformed payloads, sequence gaps, wrong branches, and invalid lifecycle history fail explicitly rather than producing partial state.

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

### 3.4 LogicalTime

`LogicalTime` is a non-negative integer number of nanoseconds from a run-local logical origin. `LogicalTime(0)` identifies that run's configured logical origin and has no wall-clock, UTC, timezone, calendar, or system-clock meaning.

Nanoseconds provide exact coordinate precision; they do not define a simulation tick. Slice 0 exposes immutable, hashable values with equality and total ordering only. Duration arithmetic, implicit current-time factories, mutable clocks, scheduling behavior, and calendar conversion are deferred.

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

Slice 4 defines `WorldDefinition` document schema version 1 as a strict already-parsed mapping. It contains an opaque `world_definition_id`, an opaque non-empty semantic version string, a positive `schema_version`, explicit vocabulary registries, initial conditions, and immutable structured metadata. The loader performs no file I/O.

`WorldDefinitionRef(world_definition_id, version)` is the semantic definition identity. The document `schema_version` describes representation and is not part of that identity.

The version-1 vocabulary registries contain unique non-empty legal names for Entity, Relation, Resource, and StateVariable types. Individual registries may be empty. They define names only: property schemas, relation role/arity constraints, Resource units/bounds, StateVariable schemas/defaults, mechanics, Blueprints, and schema-expression infrastructure remain deferred.

Version-1 initial conditions contain one logical time and ordered Entity, Relation, Resource, and StateVariable declarations. Empty initial conditions are valid. Initial Resource declarations use `quantity`, and initial StateVariable declarations use `value`; genesis translates these declarations to the existing resulting-state Event payload fields.

Slice 4 `SimulationRunConfig` contains only the exact `world_definition_ref`. Fields owned by future resolver, provider, randomness, execution, and reproducibility slices are not represented by opaque placeholders.

Slice 11 provider routing is immutable, non-secret run configuration and remains
separate from WorldDefinition and credentials. It may select a run default, named
routing-group bindings with at most one group per actor, and actor-specific
bindings. Precedence is actor-specific, then the actor's routing group, then the
run default. Credentials are execution-environment inputs, never run
configuration.

Every genesis transition begins with exactly one version-1 `SimulationInitialized` Event, followed by Entity, Relation, Resource, and StateVariable Events in that category order. Declaration order is preserved within each category. Relation participants remain semantically unordered and use deterministic `(role, entity_id)` payload ordering. Event sequence remains replay/storage ordering rather than causality or intermediate-world semantics.

`SimulationInitialized` records the nested `WorldDefinitionRef` and the document schema version separately. It is an explicitly recognized semantic historical Event that does not mutate `WorldState`, `ExecutionState`, or `CognitionState`; no `RunState` or WorldDefinition reference is added to `WorldState`.

The caller supplies the genesis `TransitionId` and every `EventId`. The pure genesis builder requires an exact, unique, sufficient Event-ID sequence, creates `ENGINE` provenance tied to the definition version, validates the complete candidate initial world, and returns a `TransitionToCommit` without committing it. The EventStore remains responsible only for generic structural history invariants.

Slice 9 adds WorldDefinition document schema version 2 while preserving strict
version-1 loading. Version 2 adds only required `scenario_event_rules`, an ordered
collection that may be empty. Each rule has a unique opaque `rule_id` and one
strict `AT_TIME` trigger containing an exact LogicalTime that cannot precede the
initial logical time. Version 1 retains its exact original field set and projects
an empty rule collection. Scenario rules remain declarations and add no genesis
Events. RANDOM_TIME, AFTER_DURATION, recurrence, conditions, mechanic bindings,
and sampling remain deferred.

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

### 5.2 Slice 10 GEL v1 runtime

Slice 10 implements GEL as a standalone side-effect-free runtime only. A canonical
`GelProgram` retains exact source, language version, an exact-object input schema,
and output schema. `prepare_gel` produces a `PreparedGelProgram` containing a
private disposable parsed/validated representation; AST and bytecode are not
canonical or persisted. `execute_gel` receives only schema-validated explicit
input plus an optional invocation-scoped random context and returns one immutable
schema-validated typed value.

GEL v1 values are boolean, signed bounded integer, bounded string, homogeneous
bounded list, and exact-field object. There are no floats, nulls, unions, enums,
arbitrary maps, dynamic values, or implicit conversions. Integers use checked
signed-64-bit semantics. Arithmetic is unary minus, addition, subtraction,
multiplication, floor division, and modulo. Division/modulo by zero and overflow
fail explicitly.

The statement language has local declaration/reassignment, lexical `if/else`,
bounded `for` over bounded lists, and exactly one final top-level return. It has no
while, early return, loop control, user functions, recursion, imports, exceptions,
methods, reflection, indexing, or dynamic calls. Locals have one static type,
inputs and loop variables are read-only, and boolean `and`/`or` short-circuit.

The closed function set is `abs`, `min`, `max`, `clamp`, `length`, and
`random_int`. Random values come only from an explicit invocation-scoped
`GelRandomContext`; no hidden/global RNG exists. Slice 10 adds no production PRNG,
seed, stream derivation, distribution, run configuration, or random provenance.

GEL v1 fixes deterministic hard limits for source/tokens/AST/depth, executed
operations, aggregate loop iterations, collection/string sizes, structured
input/result size and depth, and integer magnitude. It uses no semantic wall-clock
timeout. Parse, static, input, execution, numeric, output, random-context, and
budget failures are explicit and produce no Events, state mutation, or partial
authoritative result.

Slice 10 does not integrate GEL with WorldDefinition mechanics, scheduling,
resolution, WorldEffects, Events, or the engine. A future trusted adapter may turn
a typed result into candidate effects below the normal authoritative validation
boundary. Ordinary replay never invokes GEL to reconstruct history.

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

### 6.1 Slice 9 one-shot AT_TIME occurrences

Slice 9 gives each rule a `ScenarioEventRuleRef` containing the exact
WorldDefinitionRef and rule ID. Because the supported rule is one-shot, its one
concrete `ScenarioOccurrenceRef` nominally wraps that rule reference without an
occurrence index or runtime-generated identity.

A separate pure history-aware projector validates the branch's
`SimulationInitialized` definition reference, reads complete branch-visible
history, and emits `ScheduledResolution[ScenarioOccurrenceRef]` values with kind
`SCENARIO_EVENT` only for unresolved rules. A resolved occurrence is identified
solely by a committed version-1 `ScenarioOccurrenceResolved` Event. An unresolved
occurrence before current time is an integrity error rather than silently skipped.
No occurrence queue or consumed marker is added to SimulationState.

Scenario occurrence resolution has a separate narrow request/proposal/provider
boundary rather than broadening the Job-oriented ResolutionRequest. One request
contains one exact occurrence, its AT_TIME rule, due candidate, base
HistoryPosition, target time, elapsed duration, and immutable SimulationState.
The deterministic provider proposes only existing closed WorldEffects. The
trusted preparation boundary reads the exact ancestry-visible history for the
request position, owns Event identities and provenance, validates the complete
candidate projection, and returns an expected-head-protected transition.
`ScenarioOccurrenceResolved` commits atomically with all effect-derived Events and
is emitted even for a valid no-effect resolution.

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

Initial projection semantics create Entities active, keep `entity_type` immutable, and replace complete properties on update. Updating or repeatedly deactivating an inactive Entity is invalid. Deactivation never cascades implicitly.

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

Initial Relation participants are an unordered immutable set of unique `(role, entity_id)` bindings with at least one member. Relation type is immutable; update replaces the complete participant set and properties. Relation lifecycle follows the same strict active-state rules as Entity lifecycle. Referenced Entities must exist after the complete atomic transition, but core does not universally require them to be active.

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

Initial Resource identity is `(entity_id, resource_type)`. `ResourceChanged` upserts the authoritative resulting quantity rather than a delta. Version 1 accepts built-in integers and finite floats, excludes booleans, and permits negative quantities. Units, properties, bounds, and scenario constraints remain definitions for later validation.

### 7.5 StateVariable

Initial StateVariable identity is `(scope, state_variable_type)`. Version 1 supports tagged `WORLD` scope and tagged `ENTITY` scope containing an Entity ID. `StateVariableChanged` upserts the complete immutable structured value. Entity-scoped values require final-transition Entity existence; additional scopes and scenario schemas are deferred.

### 7.6 Commitment

`Commitment` is a generic Entity representing promises, agreements, contracts, or future coordination. It may project a future due resolution, but it does not force actor behavior. An actor may comply, renegotiate, violate, ignore, or reject it through normal decisions/mechanics.

### 7.7 Information

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

Slice 5 uses nominal `PlanId`, `PlanStepId`, `JobId`, and `BlueprintId` values. `PlanRef` is a PlanId plus positive integer version; `PlanStepRef` pins one PlanRef and globally unique logical PlanStepId; `BlueprintRef` is identity-only BlueprintId plus positive integer version. Blueprint existence and primitive compatibility remain deferred, while the PlanStep's primitive is authoritative.

The version-1 primitive vocabulary is `CREATE`, `MODIFY`, `RELATE`, `TRANSFER`, `MOVE`, `COMMUNICATE`, `OBSERVE`, `WAIT`, and `REST`. PlanStep origin is `ACTOR_INTENT` or `PLANNER_DERIVED`. Dependencies are unordered unique `(step_id, condition)` values with explicit `SUCCESS` or `TERMINAL`; they target the same complete Plan version and must form a DAG. Authored step order has no dependency/readiness meaning.

`PlanCreated` creates version 1. `PlanRevised` creates the exact next version as a complete immutable snapshot and preserves `replaces_plan_ref`. `PlanReplaced` creates a new PlanId at version 1 and points to the current latest version of an unreplaced pre-transition PlanId. Replacement is final for that PlanId in one branch continuation. At most one Plan operation affects a PlanId per transition, and replacement affects both old and new IDs. Existing Jobs remain pinned to their original exact PlanStepRef.

Plan Events contain only a complete `plan` snapshot with `plan_id`, `version`, `actor_id`, non-empty `objective`, non-empty ordered `steps`, and nullable `replaces_plan_ref`. Step snapshots contain `step_id`, primitive, nullable BlueprintRef, required structured bindings/parameters, explicit dependencies, origin, and nullable non-empty description. Event provenance and logical time project as Plan `provenance` and `recorded_at`. The actor Entity must exist in the complete transition's final WorldState; active state and ActorFacet are not required in Slice 5.

`JobCreated` is the unique PlanStep-start fact. It creates one PENDING Job with an exact PlanStepRef and explicit initial progress. Across all versions containing one logical PlanStepId, at most one Job may exist in branch-visible state. Retry therefore uses a new PlanStepId and JobId.

Legal Job lifecycle edges are `PENDING -> ACTIVE|COMPLETED|FAILED|CANCELLED`, `ACTIVE -> PAUSED|COMPLETED|FAILED|CANCELLED`, and `PAUSED -> ACTIVE|FAILED|CANCELLED`. COMPLETED, FAILED, and CANCELLED are terminal. Per Job, one transition may contain at most one creation, one lifecycle Event, and one full-result progress Event; projection validates their combined candidate without assigning precedence to Event sequence.

LINEAR progress contains exact finite numeric `completed` and `total`, rejects booleans, requires `total > 0` and `0 <= completed <= total`, starts at zero, and keeps total immutable. BINARY progress contains `complete: bool` and starts false. Progress is monotonic and model kind is immutable. Standalone progress requires ACTIVE; it may also accompany activation, instantaneous PENDING completion, or an ACTIVE Job's pause/completion/failure/cancellation. JobCompleted requires terminal final progress.

Slice 5 `ExecutionState` contains only immutable `plans: Mapping[PlanRef, Plan]` and `jobs: Mapping[JobId, Job]`. It contains no current/latest/readiness/job-by-step indexes, PlanStep status, PlanExecution, or scheduler data. Job creation provenance/time are retained; later lifecycle audit remains in canonical Events.

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

Slice 8 uses nominal `ObservationId` and `DecisionPointId` values and no separate DecisionId. `CognitionState` contains immutable Observation, DecisionPoint, and Decision mappings; Decisions are keyed by DecisionPointId. A DecisionPoint is pending when no Decision has been recorded for it and resolved otherwise. Exactly one accepted Decision may resolve a DecisionPoint in one branch-visible history.

Version-1 `ObservationCreated` contains exactly `observation_id`, Entity-backed `actor_id`, and immutable structured `content`. Event provenance and logical time project as Observation provenance and `observed_at`. Source Events are connected through explicit Event causation references where appropriate; content is actor-relative cognition and is not an unrestricted WorldState copy.

Version-1 `DecisionPointCreated` contains exactly `decision_point_id`, `actor_id`, reason, scope, immutable referenced `observation_ids`, and nullable exact `subject_plan_ref`. Observation references may be empty for non-observation conditions such as `PLAN_REQUIRED`; core never infers a global/current Plan. Referenced Observations, the DecisionPoint, and any subject Plan belong to the same actor.

`DecisionTriggerPolicy` receives one actor-relative Observation and an optional exact subject Plan. It returns trigger-policy `CONTINUE` or a DecisionPoint proposal. Trigger-policy `CONTINUE` creates no DecisionPoint and never calls a DecisionProvider; it is distinct from DecisionOutcome `CONTINUE_PLAN`, which records an explicit provider-generated choice for an existing DecisionPoint.

Slice 8 `DecisionRequest` contains only the pending DecisionPoint, its exact referenced Observations, and its exact subject Plan snapshot when present. It exposes no unrestricted SimulationState/WorldState, unrelated Jobs, other actors' cognition, or hidden simulator state. A scripted deterministic DecisionProvider returns an untrusted structured Decision proposal and fails explicitly when no script exists.

When revision or replacement is chosen, the provider supplies a typed `ProposedPlan` containing `plan_id`, version, actor, objective, steps, and nullable replacement reference, but no Event envelope fields. `REVISE_PLAN` requires the exact subject and next Plan version. `REPLACE_PLAN` with a subject creates a new version-1 Plan replacing that exact PlanRef; without a subject it adopts a new version-1 Plan through `PlanCreated` with no replacement reference. Existing ADR-0012 Plan validation remains authoritative.

Version-1 `DecisionRecorded` contains exactly `decision_point_id` and a discriminated outcome. `CONTINUE_PLAN` has no Plan data. `REVISE_PLAN` and `REPLACE_PLAN` contain only `resulting_plan_ref`. `BOUNDED_REACTION` contains one `bounded_reaction` value with a required non-empty `intent_description` and nullable immutable structured `content`; it remains cognition and creates no ActionProposal, PlanStep, Job, or world effect in Slice 8. Event provenance and logical time project as Decision provenance and `recorded_at`.

`DecisionRecorded` and any resulting existing version-1 Plan Event commit atomically. The Decision's resulting PlanRef must exactly match that Event; complete Plan content is not duplicated in the Decision payload. Perception/DecisionPoint creation and later Decision/Plan recording are separate transitions, preserving a valid fork point before provider cognition. Preparation validates against an exact expected history head; replay and checkpoint reconstruction invoke neither trigger policy nor DecisionProvider.

Slice 11 retains the synchronous DecisionProvider boundary for semantic policies:

```text
DecisionProvider.decide(DecisionRequest) -> DecisionProposal
```

It adds an asynchronous `DecisionInvoker` for external acquisition. Invocation is
separate from trusted Decision/Plan transition preparation. On return, the exact
actor-relative request is rebuilt from current branch-visible state and must be
semantically unchanged with its DecisionPoint still pending; existing proposal
and expected-head validation then apply. Invocation latency and completion order
have no logical-time effect.

## 12. Provider architecture and security

`DecisionProvider` may be LLM-backed, human, scripted, deterministic, random, or future implementations.

`ModelProvider` is separate from decision policy and is an asynchronous generic
structured-generation transport. A model-backed DecisionInvoker renders an
actor-relative invocation request, requires output against an exact structured
schema, translates the result to a typed untrusted DecisionProposal, and assigns
new Plan/PlanStep identities through trusted GRASS ID sources. Raw model output
does not choose GRASS identifiers or Event envelopes.

The initial transports are the OpenAI Responses API and a deliberately limited
structured-output Chat Completions contract for explicitly installed or
operator-trusted OpenAI-compatible endpoints, including Ollama's compatible API.
Endpoint origins are deployment configuration rather than arbitrary run input;
this is not an unrestricted provider URL proxy and does not imply native Ollama
or arbitrary compatible surface support.

Decision routing is non-secret and deterministic. Actor-specific binding takes
precedence over the actor's single routing-group binding, which takes precedence
over the run default. The selected binding is final: missing configuration or
invocation failure is explicit, with no silent fallback to another binding,
provider, or model.

Optional invocation context is immutable, versioned, extensible, and
actor-relative. It never exposes unrestricted SimulationState/WorldState, other
actors' private cognition, or hidden simulator state. Model transport and human
input remain untrusted cognition and cannot supply authoritative world mutations.

Independent provider acquisition may execute concurrently. Candidates and
returned results use canonical `(actor_id, decision_point_id)` order; completion
order has no causality or Event-order semantics. Every completed result undergoes
exact request semantic revalidation before preparation.

A successful call produces a post-invocation receipt containing only non-secret
binding/invoker/provider/model and available structured response/usage metadata. If its
proposal is accepted, the receipt is included in existing provenance for
`DecisionRecorded` and any atomic Plan Event. No new Event type or Event payload
version is introduced, and replay never invokes providers.

Provider execution location is explicit:

- `SERVER_MANAGED`;
- `CLIENT_MANAGED`.

Server-managed secrets never reach frontend code. Client-managed secrets should initially remain in browser memory and not be persisted in localStorage/sessionStorage or passed through the backend.

No unrestricted server-side user-selected URL proxy is permitted; any future relay requires explicit SSRF/egress security design.

Credentials never appear in run bindings, requests, receipts, or Event
provenance. Routing, credential, transport, timeout, refusal, malformed output,
schema, translation, stale-request, and proposal-validation failures are explicit
and commit nothing. Provider/model choices affecting accepted behavior are
recorded as experimental/provenance data.

Human decisions use the same asynchronous DecisionInvoker boundary without being
modeled as ModelProvider calls. Human session transport, actor-possession
workflow, client-managed execution, backend/API/WebSocket integration, frontend,
and credential storage remain Slice 12 work; this section claims no such
backend/frontend behavior.

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

### 13.4 Slice 6 scheduler contracts

Slice 6 represents exact elapsed time as immutable non-negative integer-nanosecond `LogicalDuration`. It supports only `LogicalTime + LogicalDuration` and later/equal `LogicalTime - earlier LogicalTime`; backward elapsed-time calculation is invalid. This adds no wall-clock, calendar, mutable-clock, timer, sleeping, or tick semantics.

The scheduler receives current `LogicalTime` explicitly and never infers it from branch-origin-local `ProjectionPosition`. A branch-history-aware scheduler helper validates that explicit time against the current branch-visible committed history position. Selecting a target time does not commit an authoritative clock change.

For currently ACTIVE Jobs, `ProgressAnchor(job_id, baseline_progress, anchor_time)` is ephemeral derived input. Baseline progress is always the latest committed Job progress. Anchor time is the activation/resume beginning the current active segment or a later committed JobProgressUpdated boundary in that segment. Pause/resume establishes the resume time as the new anchor while retaining committed baseline progress. No anchor field is added to Job or SimulationState, and no uncommitted progress is inferred.

`ScheduleProjector` is a pure deterministic boundary receiving explicit SimulationState, current LogicalTime, and derived progress anchors. It returns ephemeral `ScheduledResolution` values and does not infer temporal mechanics from opaque PlanStep data. ScheduledResolution is generic over a typed hashable source reference, has absolute logical time, a non-empty operational kind, and immutable derived metadata. Candidates before current time fail; candidates at current time are valid.

`ScheduledResolutionIndex` is disposable and supports full rebuild plus complete source-level replacement/removal, including multiple candidates from one source. It owns no clock and stores no persisted entry IDs or generation tokens. Earliest reads are non-destructive.

One invocation gathers the complete earliest same-time candidate set, then computes undirected connected conflict components using an injected pure deterministic symmetric pairwise predicate. The scheduler does not invent conflict semantics, allocate resources, select winners, or assign causal meaning to ordering. `SchedulerStep` records explicit current/target time, elapsed LogicalDuration, the complete due set, and conflict components. Zero-duration steps are valid. Newly projected same-time work is handled by a subsequent invocation rather than an internal fixed-point loop.

Incremental maintenance and complete reconstruction from identical authoritative inputs must produce semantically equivalent candidates and, with deterministic test orchestration, identical authoritative history. Slice 6 may prove this with a test-only Job Event materializer but adds no production resolution or Event-materialization path. Plan selection, dependency readiness, capability checks, and Job creation remain deferred.

Slice 9 composes Job scheduling with a separate scenario-occurrence projector.
Both feed the existing generic ScheduledResolution index; the Job-oriented
ScheduleProjector protocol remains unchanged. Complete visible history, rather
than scheduler-local removal, suppresses resolved one-shot occurrences after a
rebuild or inherited fork. The Slice 9 acceptance fixture exercises one isolated
scenario occurrence and one interacting same-time Job component. Mixed
Job/occurrence components and publication of multiple independent same-time
components remain deferred.

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

### 14.3 Slice 7 deterministic resolution contracts

Slice 7 resolves one coherent scheduler conflict component per immutable
`ResolutionRequest`. Initial resolution subjects are Jobs only. One Job subject
groups all due `ScheduledResolution[JobId]` values for that Job in the component.
The request records its exact ancestry-aware base `HistoryPosition`, target
LogicalTime, scheduler-supplied elapsed LogicalDuration, one or more unique Job
subjects, and the immutable authoritative SimulationState at that base position.

Each subject receives exactly one `SUCCESS`, `PARTIAL`, `BLOCKED`, `FAILED`, or
`INTERRUPTED` outcome. A ResolutionProposal has no required request-level
outcome; it must cover every request subject exactly once and no others. Outcome
does not imply a Job lifecycle transition.

The closed transient Slice 7 WorldEffect union contains Create/Update/Deactivate
Entity, Create/Update/Deactivate Relation, ChangeResource, SetStateVariable,
and UpdateJob effects. Effects use resulting-state semantics and are not Events
or persisted data. ChangeResource carries `quantity_after`. UpdateJob carries a
Job ID plus optional `status_after` and/or `progress_after`, requires at least one
resulting field, cannot target PENDING status, and may materialize both progress
and one lifecycle Event. Multiple UpdateJob effects for one Job in a proposal
are invalid. Information remains deferred.

Slice 7 uses an injected pure deterministic WorldResolutionProvider. It does not
change WorldDefinition schema version 1 or SimulationRunConfig. Candidate
validation enforces only currently expressible state, vocabulary, Event, and Job
contracts. Normal infeasibility is represented by outcomes. Malformed or invalid
deterministic output is a `DeterministicResolutionIntegrityError`, never an
invented FAILED/BLOCKED outcome.

Preparation materializes outcome and effect Events, validates the complete
candidate transition through existing deterministic projection rules, and
returns an immutable prepared value containing the expected HistoryPosition and
TransitionToCommit. It never commits. Resolution commits use EventStore
expected-head protection so a stale candidate consumes no history identity or
sequence. The trusted caller supplies TransitionRef, exact EventIds, optional
resolver provenance metadata/source reference, explicit CauseRefs, and optional
CorrelationId; the resolver supplies none of those authoritative envelope
values.

Preparation receives read-only branch-visible committed history ending at the
base HistoryPosition so it can validate elapsed time against canonical logical
time even when a child has no local ProjectionPosition time. This history is not
resolver input.

One version-1 non-mutating `ResolutionOutcomeRecorded(job_id, outcome)` Event is
persisted per request subject. Projection explicitly validates and recognizes
it. Outcome Events precede effect Events in deterministic storage encoding;
effect order follows proposal order, and combined UpdateJob progress precedes
lifecycle. None of this ordering implies causality or priority.

Future handling of several independent same-time components must derive every
request from the same pre-step authoritative snapshot. Slice 7 deliberately
does not implement the coordinator needed to publish them without accidental
sequential same-time semantics.

### 14.4 Slice 9 scenario-occurrence resolution

`ScenarioOccurrenceResolutionProvider` is separate from the Job-only
WorldResolutionProvider. It receives one immutable occurrence request and returns
only a `ScenarioOccurrenceResolutionProposal` containing existing WorldEffects.
It cannot create Events, replace SimulationState, choose Event identity or
provenance, or commit history. Validation reuses the closed WorldEffect Event
materialization and vocabulary checks while preserving ADR-0014's public Job
contracts unchanged. Invalid deterministic output is an integrity error and no
partial occurrence/effect transition is committed.

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

`SimulationInitialized` version 1 is the Slice 4 non-mutating genesis Event. Its payload contains `world_definition_ref` (`world_definition_id` plus semantic `version`) and a separate `world_definition_schema_version`. Projection validates and recognizes it explicitly while leaving all authoritative state projections unchanged apart from their shared history position.

Slice 5 defines strict version-1 `PlanCreated`, `PlanRevised`, and `PlanReplaced` Events containing one complete `plan` snapshot. It also defines `JobCreated`, `JobActivated`, `JobPaused`, `JobProgressUpdated`, `JobCompleted`, `JobFailed`, and `JobCancelled`. JobCreated carries only Job identity, exact PlanStepRef, and initial progress; JobProgressUpdated carries complete `progress_after`; other lifecycle payloads carry Job identity.

Slice 7 defines strict version-1 `ResolutionOutcomeRecorded` with `job_id` and
`outcome`. It is a historically meaningful non-mutating Event. Every Job subject
in one ResolutionRequest produces exactly one such Event, including when no
WorldEffect is proposed. Projection requires the referenced Job to exist and
rejects duplicate outcome records for one Job in one transition.

Slice 9 defines strict version-1 `ScenarioOccurrenceResolved` containing one
complete `ScenarioOccurrenceRef`. It is a historically meaningful non-mutating
Event recording that one deterministic one-shot occurrence was consumed. It is
the first Event in the occurrence's atomic transition, followed by ordinary
effect-derived semantic Events. This deterministic encoding does not imply Event
sequence causality or priority. Cross-transition duplicate consumption is rejected
by occurrence preparation and complete visible-history scheduling validation.

The exact complete v0.1 catalog is implementation-driven and versioned.

Slice 2 defines version 1 payloads for Entity/Relation create-update-deactivate, `ResourceChanged`, and `StateVariableChanged`. Update payloads contain complete `properties_after`/`participants_after` values; Resource and StateVariable payloads contain complete `quantity_after`/`value_after` values. All fields are required and extra fields are invalid. Multiple writes to the same projected identity/key within one transition are invalid.

Strict routing occurs at the `SimulationState` boundary. A known Event routed to another projection is not unknown merely because `WorldState` does not consume it; Events unknown to every current projection still fail explicitly.

Historically meaningful non-mutating Events may include ActionProposed/Attempted/Rejected/Failed/Succeeded, ActorRefused, ProviderChanged, ScenarioOccurrenceTriggered, and OperatorIntervention where useful.

Each Event type versions its payload independently.

A state-transition payload contains enough information for deterministic reduction without re-running planners, LLMs, GEL, resolvers, or random samplers, but should not duplicate full snapshots routinely.

Provenance is mandatory. Causal relationships are explicit through cause refs and are never inferred merely from sequence adjacency.

## 16. Atomic history positions, replay, and branching

Events are append-only and immutable.

Normal replay reconstructs `SimulationState` using persisted Events and deterministic projections only. It does not call DecisionProviders, humans, ModelProviders, WorldResolutionProviders, GEL mechanics, planners, or random samplers to rediscover past choices/outcomes.

Calling those components again from a historical point creates new continuation/history.

A branch has a parent and fork position. Roots are registered explicitly; a child is created from an explicit non-empty `HistoryPosition` in its direct parent's visible history. The referenced transition may originate on any ancestor visible through that parent. Shared prefix is immutable; continuation is independent.

Branch topology is canonical EventStore metadata, not simulated world state. Origin-history reads contain only transitions committed directly to one branch. Visible-history reads traverse the captured root-to-fork prefixes and return the original transitions without copying, rewriting, or renumbering inherited Events.

Child-origin Event sequence starts at one. Its first transition cannot precede the fork transition's logical time. Parent transitions committed after the fork do not enter the child's visible history.

Resolution commits use optimistic expected-head protection. The expected
ancestry-aware HistoryPosition must match the transition branch and equal its
current visible head under the same atomic store lock used for publication.
Stale rejection consumes no Event sequence, EventId, or TransitionRef. Unchecked
structural commit remains available for genesis and lower-level history use.

A branch created before a recorded decision may invoke cognition again when it reaches the DecisionPoint. A branch created after a recorded decision inherits that decision/Plan as part of the shared prefix unless an explicit earlier fork/regeneration/intervention is selected.

Likewise, a branch created before a scenario occurrence is resolved may resolve
the same occurrence independently. A branch created after resolution inherits
`ScenarioOccurrenceResolved`; rebuilding its scheduler from complete visible
history does not schedule the occurrence again. Ordinary replay recognizes the
recorded occurrence and effect Events without invoking either scenario scheduling
or the scenario-occurrence resolver.

Because `transition_id` is atomic, externally valid replay/fork positions are **committed transition boundaries**, not intermediate Events inside one transition. Readers observe state before or after the complete transition, never a partial authoritative state.

Snapshots/checkpoints accelerate reconstruction but are not canonical history.

An optional checkpoint loader may provide a trusted derived `SimulationState` at an applicable `HistoryPosition`. Reconstruction validates that the checkpoint history is a prefix of the target history, then applies subsequent canonical transitions. Full Event replay remains available and authoritative when no checkpoint exists.

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
13. asynchronous provider invocation and OpenAI Responses/limited trusted-compatible adapters behind existing contracts;
14. FastAPI/backend and React frontend after core contracts prove stable.

The first executable milestone should prioritize architecture/invariants over realism.

Explicitly later: collective/institutional actor cognition, society-scale distribution, sophisticated economics/psychology/law/biology, advanced geography, rich UI, automatic population-resolution changes, and causal-inference claims.

## 21. Remaining implementation-level open questions

The design baseline intentionally leaves lower-level choices open where they do not change the accepted architecture. Examples include:

- exact Pydantic/serialization schemas and identifier formats;
- EventStore/database technology and snapshot cadence;
- exact initial Event payload catalog and historical upcasting implementation;
- physical `WorldDefinition` file format and schema tooling beyond the strict Slice 4 parsed-mapping schema;
- exact GEL textual grammar, primitive type set, safe standard library, numeric policy, and parser implementation;
- random-stream key derivation;
- exact scheduler priority/index data structure, stale-entry compaction/rebuild thresholds, and conflict-component algorithm;
- exact source-ref/TemporalProjection schemas;
- detailed capability-evaluator default dimensions/UNKNOWN policy;
- belief representation and memory retrieval/compaction;
- exact bounded-reaction materialization in planning;
- conversation/job contribution granularity beyond v0.1;
- provider/resolver prompt, retry, timeout, version, and cost policies;
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
