# GRASS — GRASS Roots Agentic Systems Simulator

## Architecture Working Draft

**Status:** Pre-baseline working draft  
**Audience:** coding agents, maintainers, reviewers, simulation designers  
**License:** GPL-3.0-only  
**Implementation status:** not started

---

## 1. Purpose

GRASS is a general-purpose simulation engine for dynamic systems composed of humans, groups, institutions, resources, information, rules, relationships, and changing incentives.

A scenario should be able to represent a corporation, political party, state, community, expedition, or another social system without embedding domain-specific semantics in the core engine.

The simulator is intended to support emergent behavior, imperfect knowledge, configurable needs and resources, cooperation and competition, communication and rumor, human intervention, multiple cognition backends, replay, branching, counterfactual comparison, and post-run analysis.

GRASS is not assumed to be scientifically predictive by default. Scientific claims require scenario-specific calibration, validation, uncertainty analysis, and evidence. It does not make any claims about it's prediction precission. It is rather intended to be a tool which can help people understand social systems they happen to be a part of.

## 2. Architectural thesis

> **The simulation engine owns reality; cognition providers propose behavior.**

LLMs, humans, scripts, or deterministic policies may decide what an actor wants to attempt, what it believes, how it interprets observations, what it says, and which strategy it prefers. They MUST NOT directly mutate authoritative world state.

All authoritative changes pass through the simulation engine, which is the only component allowed to commit reality. The mechanism used to determine a candidate outcome is replaceable: a deterministic resolver may derive it from explicit mechanics, while a generative resolver may use an LLM or another model to interpret the situation creatively. In either case the resolver proposes outcomes; it does not directly mutate authoritative state.

A more precise formulation is:

> **Only the simulation engine commits reality. Decision providers propose actor behavior; world-resolution providers determine candidate outcomes.**

This separation exists to preserve reproducibility, interpretability, provider independence, security, replay, and branchability.

## 3. Fundamental abstractions

### 3.1 WorldDefinition

A versioned formal description of scenario mechanics and initial conditions. It may define:

- logical clock semantics, initial simulation time, and scheduling/time-resolution configuration;
- actor templates and initial actors;
- scenario-defined state variables;
- entity, relation, and resource type vocabularies;
- resources and their scenario-defined handling semantics;
- relationships and memberships;
- reusable process/creation blueprints;
- channels and information topology;
- action capabilities and primitive semantics;
- rules and institutions;
- transition and utility functions;
- initial events;
- provider defaults;
- termination conditions.

A natural-language World Builder may generate a candidate `WorldDefinition`, but the formal definition is authoritative.

### 3.2 WorldState

The authoritative state of one simulation branch at a logical time. It contains the current values required to continue the simulation but does not replace history.

Actors never receive unrestricted `WorldState` as decision context.

### 3.3 Entity and Actor

`Entity` is the common persistent identity abstraction for scenario-relevant things that need to be referred to across time. GRASS does not require every physical object to be an entity; something should normally receive entity identity only when the chosen simulation resolution needs to track, reference, relate, observe, control, modify, or preserve its history.

A minimal entity concept provides:

- stable `entity_id`;
- `entity_type`;
- `active`;
- scenario-defined mechanical/state properties;
- optional `semantic_content`.

`active` is authoritative entity state. Deactivation preserves identity and history rather than deleting the entity, so inactive entities may remain referenced by past events, relations, observations, and analytics.

GRASS provides a small built-in vocabulary of broadly useful entity types. The initial vocabulary includes at least:

- `Person`;
- `Organization`;
- `Group`;
- `Location`;
- `Artifact`;
- `Commitment`.

Scenarios may extend this vocabulary with domain-specific types such as `Company`, `Department`, `Camp`, `GardenBed`, `Vehicle`, or `PoliticalParty`. A scenario-defined type may optionally identify a built-in base type when useful for validation, planning, UI, or analytics. Core mechanics MUST NOT gain domain behavior merely because a type name exists.

`Commitment` represents a persistent promise, agreement, contract-like arrangement, or future coordination between one or more parties. Its existence does not force future behavior. Actors may comply with, modify, reject, violate, ignore, or otherwise react to a commitment according to normal decision and world mechanics.

`Actor` is an entity with cognition, perception, and decision capability rather than a separate parallel identity system. The implementation should prefer composition (for example an `ActorFacet` or equivalent component keyed by `entity_id`) over a deep inheritance hierarchy.

The first implementation focuses on actor-capable `Person` entities. Persistence, action, event, relationship, membership, information, and provider boundaries MUST nevertheless remain extensible to future collective or institutional actors. A `Group` or `Organization` entity may later acquire actor capability without changing its historical entity identity.

Actor cognition state such as beliefs, plans, drives, utility configuration, and memory is authoritative simulation state for replay and branching purposes, but it is not ordinary objective entity state. It SHOULD remain separated from general entity properties so that world truth, represented semantic content, actor observation, and actor belief do not collapse into one namespace.

### 3.4 StateVariable and Resource

State variables are scenario-defined rather than hard-coded. Examples include energy, stress, fulfillment, security, influence, health, or public support.

A state variable may define range, initialization, thresholds, visibility, decay/recovery behavior, and transition rules.

Resources represent scenario-defined quantities, stocks, rights, or other transferable/consumable values that may be gathered, transferred, consumed, produced, reserved, delegated, shared, or competed over. Examples include money, food, budget, water, fuel, access, attention, or time allocations.

Every authoritative resource quantity MUST be associated with an `Entity`; resources do not exist as detached global quantities without context. Conceptually:

`ResourceState(entity_id, resource_type, quantity, unit?, properties?)`

Examples include a `Company` entity having a `budget` resource, a `GardenBed` entity having a `food` resource representing harvestable carrots, a water tank having a `water` resource, or a forest/location entity having a `wood` resource.

This association provides spatial, organizational, or logical context for resource access and capability checks. A transfer of resources is therefore a transition between entity-associated resource states rather than a mutation of an unscoped global number.

Resources should not be exploded into individual entities merely because they have physical instances. A quantity of carrots may remain `food` on a garden-bed entity. If one particular object becomes individually important to the scenario, such as the only working radio, it may instead be modeled as an `Entity`.

Resource meaning and granularity belong to the scenario. A corporate scenario may model a meal simply as `food`, while a survival scenario may distinguish `carbs`, `proteins`, `fats`, and `water`. GRASS should not force a more detailed physical model than the scenario needs.

The `TRANSFER` action primitive may use a mode to describe the intended resource operation without introducing a separate primitive for each resource process. Initial examples include ordinary transfer, `GATHER`, and `CONSUME`. Scenarios may also define delegation/sharing semantics for resources such as `access`, where granting a resource does not necessarily remove it from the source holder.

The exact transfer-mode vocabulary may remain scenario- or execution-model extensible. Core GRASS MUST NOT encode biological digestion, detailed manufacturing physics, or similarly unnecessary low-level processes merely to support resource consumption or gathering.

The boundary between `StateVariable` and `Resource` is semantic: resources are quantities for which ownership/location, transfer, consumption, production, reservation, delegation, sharing, or aggregation is meaningful; other actor/world attributes may remain state variables.

Resource types may define authoritative structural constraints such as minimum/maximum quantity, units, or other invariant metadata required to keep a `ResourceState` valid. Core GRASS MUST NOT assume that every resource is non-negative; for example a credit-like balance may explicitly allow negative values. Candidate resource effects are validated against the scenario's `ResourceDefinition` and the full atomic effect batch before commit.

### 3.5 Drives, Utility and Plans

Actors may have relatively persistent `Drives`, a configurable `UtilityModel`, and dynamic `Plans`.

Utility is not restricted to a linear weighted sum. Scenario-defined utility may include thresholds, saturation, asymmetric penalties, interactions, and time horizon effects.

An actor may value different states differently from another actor. For example, one actor may strongly avoid stress while another tolerates stress in exchange for influence.

`Plan` represents an actor's current intended sequence/graph of future primitive attempts used to pursue a temporary strategy or objective such as seeking promotion, leaving an organization, forming a coalition, or acquiring a resource.

A plan is not scoped to a fixed simulation turn. Once formed, it may remain active across arbitrary amounts of logical time and across several completed `PlanStep` / `Job` executions. The scheduler may continue through already-planned steps without invoking cognition again until the plan is exhausted, blocked, invalidated, interrupted by a relevant world event/interaction, or explicitly revised by the actor.

`Plan` is an actor intention structure, not a workflow that the scheduler must force to completion. A `DecisionPoint` may leave the existing plan unchanged, revise part of it, or cause the actor to abandon it and create a different plan. Plan revision must preserve historical provenance rather than rewriting what the actor previously intended.

Conceptually, a plan version contains stable plan identity/version, actor identity, an objective/summary, a collection of `PlanStep`s, source decision/proposal references where applicable, provenance, and creation metadata. Plan versions are immutable; a material revision creates a successor version. Whether a materially different intention is represented as a new plan identity rather than another revision may initially remain a planner/decision-provider choice with preserved provenance rather than a hard-coded semantic classifier.

Each `PlanStep` declares exactly one actor-facing primitive. A step MAY optionally reference an exact immutable `Blueprint` version when process knowledge is needed for that attempt; many primitives can also be attempted without any blueprint. When a blueprint is present, `Blueprint.primitive` MUST equal `PlanStep.primitive`.

Conceptually a step may contain `step_id`, `primitive`, optional `blueprint_ref`, primitive parameters/bindings, dependencies, origin/provenance, and optional semantic description. Planner-derived operational steps must retain provenance to the actor intention from which they were derived and MUST NOT silently invent unrelated psychological goals.

Plan steps form a DAG in v0.1. The initial dependency semantics are intentionally small: `SUCCESS` (the default) and `TERMINAL`. Steps without dependencies between them may be eligible for concurrent execution, subject to normal scheduler checks for actor attention/time, resources, participants, conflicts, capabilities, and world mechanics. GRASS does not initially need arbitrary conditional branches, loops, or workflow retry policies; when materially new choice is required, normal events/observations can create a `DecisionPoint` and the actor may revise or replace the plan.

Runtime PlanStep status is derived rather than independently mutated. A step with no associated Job has not started; once started it is associated with exactly one Job, whose lifecycle/events determine the step's execution state. v0.1 therefore does not require a separate persistent `PlanExecution` aggregate or mutable `PlanStep.status`.

### 3.6 Belief, Memory and PerceivedWorld

Reality, observation, memory, and belief are distinct.

An actor reasons from a `PerceivedWorld` constructed from observations, remembered information, beliefs, relationships, and actor-local state. Beliefs may be false, incomplete, contradictory, or uncertain.

Memory should eventually distinguish recent context, episodic events, and longer-term summaries/models of other actors. Exact storage and retrieval semantics remain unresolved.

### 3.7 Relationship and Membership

Relationships are first-class and may carry scenario-defined dimensions such as trust, affinity, perceived competence, influence, hostility, or communication frequency.

A relation has persistent identity and may conceptually include `relation_id`, scenario-defined `relation_type`, role/participant entity references, scenario-defined properties, and `active`. Relation modeling should not assume every relation is a fixed binary `source -> target`; role bindings may represent multi-party relations when a scenario needs them.

Creating a relation is sufficiently distinct from creating a world entity to justify the actor-facing `RELATE` primitive. Employment, membership, reporting, ownership, alliance, or another scenario-defined relation may therefore be established through `RELATE` without introducing domain actions such as `HIRE`, `JOIN`, or `MARRY` into core. Changing or ending an existing relation uses `MODIFY`; deactivation preserves its history rather than deleting it.

Relation creation may require participation, consent, authorization, resources, or contributions from more than one actor/entity. These requirements belong to the blueprint/process used to realize the relation and are resolved through normal planning, bounded reaction, capability evaluation, scheduling, and world resolution.

Membership is dynamic. Actors may join, leave, be removed from, or move between groups and organizations without losing historical identity.

### 3.8 DecisionPoint

A `DecisionPoint` represents a moment at which an actor's existing plan is insufficient, may need reconsideration, or a bounded response is required, so cognition must be invoked again. Decision providers are event-driven rather than periodically polled on a fixed simulation tick.

Conceptually, a decision point contains at least:

- `decision_point_id`;
- `actor_id`;
- logical time;
- `reason`;
- `scope`;
- triggering event references;
- relevant actor-relative observation references;
- optional current plan, job, or interaction references;
- provenance.

The initial v0.1 reason vocabulary is:

- `PLAN_REQUIRED`;
- `PLAN_EXHAUSTED`;
- `PLAN_BLOCKED`;
- `INTERACTION_REQUEST`;
- `JOB_FAILED`;
- `JOB_PAUSED`;
- `ASSUMPTION_INVALIDATED`;
- `MATERIAL_OBSERVATION`;
- `EXTERNAL_EVENT`;
- `OPERATOR_INTERVENTION`.

This reason vocabulary is an initial contract, not a permanent closed ontology. Additional reasons may be introduced when later execution models require them without changing the principle that a DecisionPoint is a cognition boundary rather than an authoritative world transition.

Decision scope is initially:

- `FULL` — the actor may broadly reconsider the current plan, revise it, replace it, or otherwise choose a new course of action;
- `BOUNDED` — cognition is constrained to a specific triggering interaction/problem and the relevant current context rather than becoming an automatic global replanning round.

The initial decision-result vocabulary is conceptually:

- `CONTINUE_PLAN`;
- `REVISE_PLAN`;
- `REPLACE_PLAN`;
- `BOUNDED_REACTION`.

These result kinds are likewise versionable/extensible and are not intended to freeze all future cognition semantics into core. A `DecisionPoint` provides context for cognition; the resulting decision says what the actor intends to do with that context. It does not itself mutate authoritative reality.

`BOUNDED_REACTION` allows an actor to respond to a concrete interaction or interruption without automatically revising its main plan. For example, an actor on the way to log in may briefly answer another actor, accept or refuse a request, or communicate a constrained response and then continue the existing plan if no further decision is needed.

Any world-affecting bounded reaction still follows the normal actor-execution path. Conceptually:

`DecisionPoint -> DecisionProvider -> DecisionOutcome -> ActionProposal/planning -> PlanStep -> Job -> WorldResolution -> Events`

There is no direct `DecisionOutcome -> WorldState` shortcut. The exact planner-level representation of a bounded reaction may remain provisional in v0.1: it may become a small plan revision, a transient reaction fragment, or another explicit representation, provided provenance is preserved and the normal `PlanStep -> Job -> resolution` authority boundary is not bypassed.

Not every observation creates a `DecisionPoint`. Passive observations may update actor-relative information/memory without interrupting current execution. This distinction is necessary both for realistic continuity of behavior and to avoid invoking expensive cognition providers for mechanically irrelevant details.

Every committed event that produces an actor-relative observation or otherwise materially reaches an actor should be evaluated by an actor-specific `DecisionTriggerPolicy`. Perception/propagation mechanics first determine **which actors are affected and what each actor observes**. The policy is evaluated only after that actor-relative observation exists.

Conceptually:

`Event -> perception/propagation -> Observation(actor) -> DecisionTriggerPolicy.evaluate(...) -> CONTINUE | CREATE_DECISION_POINT`

The policy should receive at least the actor, the new observation/event context, the actor's current plan, relevant active jobs, and actor-relative perceived context. The same world event may therefore be ignored by one actor and interrupt another. For example, a loud impact on an office door may be passively noted by most workers but create a decision point for a security guard or for an actor already expecting a threat.

The initial policy SHOULD be inexpensive and may be deterministic/rule-based. GRASS MUST NOT require an LLM call merely to decide whether every individual observation is salient enough for an LLM call. More advanced learned/generative salience policies may be introduced later behind the same conceptual boundary.

When several events with the same logical timestamp are resolved as one coherent batch, decision-trigger evaluation should occur against the actor-relative observations produced by that committed batch rather than leaking arbitrary internal queue order.

## 4. Cognition boundaries

### 4.1 DecisionProvider

`DecisionProvider` answers the conceptual question: what does this actor attempt to do now?

Possible implementations include:

- LLM-backed providers;
- `HumanDecisionProvider` for actor possession;
- scripted policies;
- deterministic test providers;
- random or heuristic policies.

The engine must not depend on which provider is used.

### 4.2 ModelProvider

`ModelProvider` is a lower-level abstraction for language-model access. It isolates GRASS from vendor SDKs and may support OpenAI APIs, Ollama, OpenAI-compatible local endpoints, vLLM, or future providers.

Decision policy, model transport, provider identity, and provider execution location are separate concepts. An actor must not be coupled directly to a specific LLM SDK.

A provider binding should be able to declare at least:

- a logical provider identifier;
- adapter/protocol type;
- model identifier and non-secret configuration;
- execution location (`SERVER_MANAGED` or `CLIENT_MANAGED`);
- session/user scope where applicable;
- explicit fallback policy;
- provider/model metadata required for reproducibility.

`SERVER_MANAGED` providers execute from the GRASS backend. Their credentials are server secrets and MUST NOT be sent to the frontend. A server-managed default provider may be used when a session has no explicit provider override and may be unavailable at a given time.

`CLIENT_MANAGED` providers execute through the user's client session. They are intended for user-supplied providers such as hosted APIs, OpenAI-compatible endpoints, or a locally reachable Ollama instance. The provider credential MUST NOT be transmitted to or stored by the GRASS backend in this mode. The backend may know a logical provider handle and non-secret metadata needed to route a model request, while transport details and credentials may remain client-local.

### 4.3 Client-managed provider execution and secret handling

For a client-managed provider, the backend may request a model call through the active frontend session. The frontend performs the provider request using the client-local credential and returns only the model response and non-secret call metadata required by the simulation.

The returned model response is untrusted cognition output. A modified or malicious frontend may fabricate it, but it MUST NOT be able to submit authoritative `WorldEffects` or mutate `WorldState`. Client-managed responses follow the normal `ModelProvider -> DecisionProvider -> ActionProposal -> planning -> validation -> resolution` path.

Client-managed credentials should initially be kept only in browser memory and scoped to the active session. They MUST NOT be stored in `localStorage` or `sessionStorage` by the initial implementation. Durable user-side credential storage, if added later, requires a separate security design.

Direct browser execution depends on the target provider allowing browser access, including appropriate CORS configuration. A future local bridge may support local providers when direct browser access is insufficient. A future server relay is also possible, but it is a separate security mode because it would make the backend handle user credentials and user-selected outbound destinations. GRASS MUST NOT provide an unrestricted generic server-side HTTP proxy; any future relay requires explicit SSRF protections, destination validation, egress restrictions, timeout/size limits, and dedicated secret handling.

Provider fallback MUST be explicit. Failure of a user-selected provider must not silently switch cognition to a different model. A session may choose a policy such as `PAUSE`, `FAIL`, or an explicit fallback provider. Any provider/model switch that affects a running simulation must be recorded in reproducibility metadata and, where historically relevant, in the event history.

If no client-managed provider is configured, the session may use the server-managed default provider. If the default is unavailable and no explicit fallback exists, the backend should surface provider unavailability rather than silently changing execution semantics.

The initial frontend/backend transport should support long-lived session communication so the backend can suspend a pending cognition call and receive its result from the client. WebSocket is the initial transport choice for these interactive/session exchanges; ordinary configuration and query operations may use REST.

### 4.4 Explainability metadata

GRASS must not require or persist private chain-of-thought. When decision explainability is useful, providers should return structured metadata such as intent, considered alternatives, expected effects, confidence, and observations used.

## 5. Actions and world mechanics

Actors need creative freedom, so the intention space must not be limited to a tiny enum such as `WORK`, `REST`, and `TALK`.

The core architectural requirement is separation of **actor intention**, **action planning**, **action execution/resolution**, and **authoritative world mutation**. The concrete representation used inside planning and execution is intentionally replaceable.

A stable conceptual flow is:

1. **DecisionPoint** — the scheduler/world determines that an actor needs a new choice.
2. **ActionProposal / intention** — a `DecisionProvider` proposes what the actor intends to attempt.
3. **Planning** — translate the semantic intention into a persistent plan of primitive/blueprint-backed steps.
4. **Scheduling / execution start** — start or continue eligible jobs and schedule their next material completion/interruption points.
5. **World resolution** — adjudicate attempted behavior at the relevant logical time, including simultaneous/conflicting attempts.
6. **World effects** — produce explicit candidate changes to authoritative state.
7. **State transition / events** — validate and atomically commit accepted events through deterministic reducers.
8. **Decision-trigger evaluation** — determine which actors, if any, now require a new `DecisionPoint`; otherwise continue existing plans and advance the clock.

The current candidate design may use an action interpreter, scenario-defined processes, composable actor-facing operations, and explicit world effects. This is an **initial execution model**, not a permanent public contract of GRASS.

### 5.1 Replaceable planning and execution boundaries

The core engine MUST NOT depend on one specific way of translating intentions into executable behavior. Future implementations may use an LLM-based action interpreter, deterministic schema matching, a symbolic planner, affordance-graph planning, tool-like structured calls, behavior trees, or another model not yet designed.

Conceptually, the implementation should preserve narrow boundaries similar to:

`DecisionProvider -> ActionProposal -> ActionPlanningPort -> Plan -> Job -> WorldResolutionProvider -> WorldEffects -> Events -> WorldState`

The exact interfaces remain provisional. The important requirements are dependency direction, replaceability, and the distinction between semantic intention, planning, execution state, world adjudication, and authoritative state transition.

Planning and world resolution are separate axes of change: GRASS should be able to replace a planner without replacing world resolution, and replace deterministic world resolution with generative world resolution without changing how actors express intentions or how authoritative state is committed.

### 5.2 ActionProposal and actor-facing primitives

`ActionProposal` represents what an actor intends to attempt. It must remain semantically expressive but MUST NOT contain resolver-derived mechanical facts or authoritative world effects.

The v0.1 contract is a discriminated union: a small common envelope plus a typed payload selected by `primitive`.

Conceptually:

- `proposal_id`;
- `actor_id`;
- `primitive`;
- `intent_description`;
- optional `content`;
- optional `time_budget`;
- optional `job_id`;
- primitive-specific `payload`.

`proposal_id` and the authoritative `actor_id` binding should be assigned or validated by the engine rather than trusted from arbitrary provider output.

`intent_description` states what the actor is trying to accomplish. `content` is the represented or communicated semantic material itself where relevant, such as document text, spoken words, or the semantic content of a created artifact. These are not authoritative outcome fields.

`time_budget` is requested/intended actor time, not a guaranteed duration or execution result. `job_id`, when present, means continuation of an existing execution rather than starting another equivalent job.

The common envelope intentionally does not contain generic `targets[]`. Each primitive payload names world references according to its own semantics (`target`, `source`, `destination`, `recipients`, `bindings`, and so on).

World references should use a common form that can either identify a known persistent object or preserve an unresolved semantic selector for planner resolution against the actor's perceived world. Conceptually:

`WorldRef(kind, id?, description?)`

Initial kinds include at least `ENTITY`, `RELATION`, and `BLUEPRINT`.

`ActionProposal` should not contain planner/resolver-derived fields such as calculated resource claims, required participants, attention claims, dependencies, resolved preconditions, expected completion, actual completion, or authoritative state deltas.

When practical, history should preserve the actor's semantic `ActionProposal` separately from planner-, scheduler-, and resolver-specific details. This supports debugging, comparing planners against the same intention, branch/regeneration experiments, and measurement of how much outcomes depend on interpretation architecture. Private planner intermediates are not automatically authoritative history; persist only what replay, observability, or reproducibility requires, and version execution-model-specific persisted data explicitly.

The candidate v0.1 primitive set is:

- `CREATE`;
- `MODIFY`;
- `RELATE`;
- `TRANSFER`;
- `MOVE`;
- `COMMUNICATE`;
- `OBSERVE`;
- `WAIT`;
- `REST`.

These primitives describe broad categories of intended interaction, not guaranteed outcomes.

#### 5.2.1 CREATE

`CREATE` expresses an intention whose meaningful result is a new persistent scenario object. Conceptual payload fields include `output_kind`, optional `entity_type`, optional `blueprint_id`, and optional `intended_properties`.

Initial output kinds include at least `ENTITY` and `BLUEPRINT`; relations use `RELATE`. `intended_properties` are desired characteristics, not authoritative result fields. Examples include writing a report, creating an artifact, digging an excavation represented as an `Artifact`, creating an organization, creating a `Commitment`, or creating a new blueprint.

Work is not a separate `PERFORM` primitive. Work that creates a persistent result normally uses `CREATE`; work that changes an existing result uses `MODIFY`.

#### 5.2.2 MODIFY

`MODIFY` expresses an intention to change an existing persistent object or relation. Its payload identifies a `target`, optional `intended_changes`, and optional `blueprint_id`.

Destructive intent also uses `MODIFY`; GRASS does not require a separate `DESTROY` primitive. Resolution may deactivate the original identity, mark it damaged, create relevant remnants at scenario resolution, or fail. Deactivation means that the old identity is no longer active; it does not claim that underlying physical matter disappeared.

#### 5.2.3 RELATE

`RELATE` expresses an intention to establish a new scenario-defined relation. Its payload carries `relation_type`, role-based `bindings`, optional `blueprint_id`, and optional `proposed_properties`.

Role bindings avoid assuming that all relations are binary. For example an employment blueprint may bind `employer` and `employee`, require employer-side authorization and candidate consent, and create the relation only when world resolution determines that the concrete attempt succeeds.

#### 5.2.4 TRANSFER

`TRANSFER` expresses an intended operation on entity-associated resource state. Its payload carries `mode`, `resource_type`, optional `quantity`, optional `unit`, `source`, optional `destination`, and optional scenario-defined properties.

Initial modes may include ordinary transfer, `GATHER`, and `CONSUME`; scenarios may define additional semantics such as delegation or sharing. Core does not interpret scenario-specific resource names or impose unnecessary physical detail.

#### 5.2.5 MOVE

`MOVE` expresses an intended change of modeled location. Its payload uses `subject` and `destination`. The subject may be the actor itself or another entity the actor attempts to move. Domain verbs such as `CARRY`, `PUT`, `TAKE`, `ENTER`, or `LEAVE` should not become core primitives unless a later design need proves them irreducible.

#### 5.2.6 COMMUNICATE

`COMMUNICATE` expresses an intention to transmit semantic information. Its payload uses `recipients` and optional scenario-defined `channel`; the semantic message belongs in `content`.

Communication outcome does not imply persuasion, belief change, or even successful receipt. Channels remain subject to access/capability mechanics.

#### 5.2.7 OBSERVE

`OBSERVE` expresses an attempt to acquire actor-relative information. Its payload may identify a `subject` when different from the acting actor, one or more `targets`, optional `aspect`, and optional `channel`.

Examples include reading a report, watching an entrance, listening to a conversation, or searching for an object. Observation produces observations/information according to world mechanics; it does not directly create belief.

#### 5.2.8 WAIT

`WAIT` deliberately allocates actor time without assuming restorative effects. Its payload may carry semantic `condition_description`; v0.1 should not introduce a full executable condition DSL merely to model waiting.

#### 5.2.9 REST

`REST` expresses an actor's intention to recover/rest. Its payload may carry a scenario-defined `mode` such as sleep, nap, or break. Actual recovery remains a world outcome, not an actor-declared state delta.

### 5.3 Blueprints

A `Blueprint` is a reusable process hypothesis/recipe describing how an actor or planner intends to attempt exactly one primitive at the scenario's chosen level of abstraction. It is not a microscopic physics recipe and it is not a certificate that the process is feasible.

This distinction is fundamental:

- `Blueprint` = how we think/intend to do it;
- `Job` = what happens when we actually try;
- world resolution = what is actually possible here and now.

The same blueprint may succeed in one context and fail in another. GRASS therefore MUST NOT require a blueprint to pass a global `EXECUTABLE`/`REJECTED` feasibility lifecycle before actors can attempt it.

Each blueprint is bound to exactly one actor-facing primitive. A blueprint MUST NOT contain an internal workflow, nested action list, or multi-primitive graph. If an intention requires several primitives, composition belongs to `Plan`; each plan step declares one primitive, may optionally select a blueprint for that same primitive, and may declare dependencies on other steps.

Conceptually, a blueprint may define:

- stable `blueprint_id` and immutable version;
- `active` state;
- origin/provenance, including scenario-defined or actor-created;
- exactly one `primitive`;
- description and parameter schema;
- intended output kind/type;
- participant roles/bindings and expected consent/participation/authorization/contribution needs;
- expected resource requirements or budgets;
- expected effort/time and a progress model;
- expected preconditions/capabilities;
- optional semantic `assumptions`;
- expected completion/result specification.

Expected requirements and assumptions are process knowledge, not guaranteed laws of reality unless a scenario explicitly defines a deterministic rule as authoritative mechanics. During concrete execution the resolver may discover that quantities are insufficient, assumptions are false, additional dependencies/resources are required, or the process cannot continue.

`assumptions` may initially remain semantic structured content rather than executable predicates. Examples include "barrels are watertight", "the legacy API is backwards compatible", or "two people can lift the assembly".

Blueprints may be supplied by the scenario and may also be created by actors during a run. Actor-created/LLM-generated blueprints are untrusted hypotheses: describing an unlimited-food process does not grant authority to create unlimited food or bypass resource/capability/state-transition boundaries.

Blueprint lifecycle is orthogonal to feasibility. At minimum a blueprint is versioned and may be active/inactive. Deactivation prevents new use while preserving historical identity; modification creates a new immutable version for future jobs. When a PlanStep uses a blueprint, both the step and its resulting job remain bound to the exact blueprint version selected for that attempt.

### 5.4 Plan and Job boundaries

Composition belongs to `Plan`, not to `Blueprint`. Conceptually:

`ActionProposal -> Plan -> PlanStep(primitive, blueprint?) -> Job`

A plan may contain several dependent primitive executions. For example, employing a person and then granting access may become a `RELATE` step followed by a dependent `TRANSFER` step. Either step may use a blueprint if its mechanics require one, but a blueprint does not become a hidden workflow engine.

A `Job` is one concrete execution attempt of one `PlanStep` and therefore exactly one primitive. Every started PlanStep creates exactly one Job, whether or not the step references a blueprint and even when creation and completion occur within one atomic transition. This provides a uniform trace for both simple primitives and blueprint-backed work:

`ActionProposal -> Plan -> PlanStep -> Job -> WorldResolution -> WorldEffects -> Events`

with optional process knowledge:

`PlanStep -> Blueprint?`

Before a step starts it has no Job. Once it starts, its single Job identity is stable through `PENDING`, `ACTIVE`, and `PAUSED` execution and into a terminal state. A terminal retry is not a second Job attached to the same step: it is a new PlanStep in a later plan revision, which creates a new Job. This keeps historical attempt identity unambiguous.

Conceptual job state includes:

- `job_id`;
- originating proposal plus exact `plan_id`, plan version, and `step_id` references;
- primitive;
- optional exact `blueprint_id` and blueprint version;
- initiator and participant bindings;
- output references when applicable;
- status;
- structured progress;
- aggregate participant contributions;
- allocated/consumed resources;
- timing metadata required by the execution model.

The initial lifecycle is:

- `PENDING` — the attempt exists but awaits consent, dependency, scheduling opportunity, prerequisite, or another required condition;
- `ACTIVE` — the attempt is an active execution that may receive progress/contributions;
- `PAUSED` — execution has begun but is suspended and may resume with the same `job_id`;
- `COMPLETED` — the completion condition was satisfied;
- `FAILED` — this concrete attempt cannot reasonably continue under the resolver's adjudication;
- `CANCELLED` — the attempt was intentionally abandoned without completing its goal.

`COMPLETED`, `FAILED`, and `CANCELLED` are terminal. A retry after terminal failure/cancellation requires a new PlanStep (normally in a later immutable plan revision), and that step creates a new job.

Progress is not universally a percentage. v0.1 should support at least simple `LINEAR` and `BINARY` structured progress models. Detailed contribution and state-change history belongs in events; `Job` is the materialized execution state required to continue simulation.

World resolution may discover new information while a job is running, such as an invalid blueprint assumption, an additional required resource, or an incompatibility. Such discovery may continue, pause, fail, or trigger later plan revision and should become normal events/information when materially relevant.

One job execution may legitimately result in several candidate `WorldEffects` and authoritative events as one atomic transition. When a blueprint is present, its one-primitive scope still does not constrain the number of effects/events required to realize that primitive outcome.

### 5.5 Scenario-resolution entities and semantic content

GRASS models authoritative reality at the resolution chosen by the scenario, not at an imagined microscopic physical ground truth below that resolution. The engine MUST NOT require irrelevant low-level entities merely to reconstruct an outcome.

A novel action may create or modify a generic scenario-level `Entity` rather than forcing core to introduce domain-specific outcome primitives/classes such as `VisualMarker`, `Document`, `Shelter`, or `Barricade`.

Mechanically relevant properties remain explicit and are determined by world resolution. Optional `semantic_content` describes what an entity represents, contains, depicts, or communicates. For example an SOS signal may be one `Artifact` with location/material/visibility properties and semantic content describing the letters SOS; individual stones need not exist unless their identity matters at scenario resolution.

Actor-proposed semantic content does not declare authoritative success or mechanical properties. Partial or failed execution may realize a different object/content/state than intended.

Semantic content is also not synonymous with world truth. A document can objectively exist and contain the claim that revenue was `$10M` while authoritative revenue is `$4.2M`.

GRASS therefore keeps distinct:

- authoritative entity state and mechanical properties;
- semantic content represented by an entity;
- actor-relative observation;
- actor interpretation;
- actor belief.

World effects should operate on a formal scenario-state model using generic structural operations rather than an ever-growing catalog of domain outcomes.

### 5.6 World resolution modes

World adjudication is replaceable behind a `WorldResolutionProvider` (exact interface/name still provisional). The provider receives the mechanically relevant execution context and returns a candidate `ResolutionProposal` / `WorldEffects`; it never mutates `WorldState` or appends authoritative events directly.

The initial design supports two explicit modes:

- `DETERMINISTIC`;
- `GENERATIVE`.

The frontend may label `GENERATIVE` as **Generative / LLM Crazy**. Persistence and API contracts use the neutral `GENERATIVE` identifier.

Conceptually:

`Plan/Job -> WorldResolutionProvider -> candidate WorldEffects -> structural validation -> Events -> deterministic reducers -> WorldState`

#### 5.6.1 Deterministic resolution

In `DETERMINISTIC` mode, outcomes are derived from explicit scenario mechanics and current authoritative state. A blueprint still represents process knowledge rather than globally proven feasibility; concrete success/failure is adjudicated when its job executes.

This mode is preferred for controlled experiments, reproducibility, calibrated mechanics, regression tests, and branch comparisons where deterministic adjudication matters.

#### 5.6.2 Generative resolution

In `GENERATIVE` mode, an LLM/model acts as a creative world adjudicator. It may infer whether an attempted blueprint works, discover that assumptions are wrong, propose unexpected uses of available entities/resources, or produce surprising and intentionally loose outcomes that the scenario author did not enumerate explicitly.

The freedom is intentional. Generative mode may be weakly realistic or implausible and is intended for exploratory simulations where emergent creativity is more important than strict repeatability.

Generative output remains untrusted structured resolution input. It MUST NOT mutate `WorldState`, append events, bypass branch/history rules, create malformed references/identities, or treat arbitrary natural-language output as authoritative state.

#### 5.6.3 Structural invariants apply in every mode

Resolution mode changes world semantics, not GRASS integrity rules. Engine-level invariants always include stable/unique identities, valid references where required, append-only authoritative history, branch isolation, event-only authoritative state transition through deterministic reducers, atomic transition semantics, and versioned structural payload validation.

These are structural invariants, not realism rules.

#### 5.6.4 Replay, branching and provenance

Ordinary replay of an already-recorded branch remains deterministic in every resolution mode. Replay reapplies persisted events and does not call the world resolver again.

Calling a world-resolution provider again from a historical state creates new history, such as during branch continuation or explicit regeneration. In `GENERATIVE` mode identical starting state and actor intentions may therefore yield different continuations.

Run/event provenance should record resolution mode, logical resolution-provider identifier, and where applicable model/provider/version and relevant non-secret generation metadata.

A future hybrid deterministic/generative policy is possible but explicitly deferred. It must not be introduced as a silent fallback.

#### 5.6.5 Resolution request/proposal boundary

The conceptual provider contract is:

`WorldResolutionProvider.resolve(ResolutionRequest) -> ResolutionProposal`

A `ResolutionRequest` is a read-only, mechanically relevant context for one material adjudication point. It may represent one job, several interacting jobs, an interruption, a temporal boundary, or a simultaneous conflict group. The provider should receive only the world/actor/resource/relation/job context required to adjudicate that resolution rather than unrestricted mutable world state.

A `ResolutionProposal` is a candidate adjudication, not authoritative history. Conceptually it contains:

- an outcome such as success, partial success, blocked, failed, or interrupted;
- zero or more candidate `WorldEffects`;
- optional discoveries/structured explanatory metadata;
- zero or more scheduler-facing `TemporalProjection`s;
- resolver/provider provenance metadata.

Normal world infeasibility belongs in the proposal outcome. For example, if an actor attempts to spend a resource it does not have, a correct resolver should return a failed/blocked outcome (or another mechanically justified result), not knowingly propose an impossible balance.

The creation of a new `Job` from an eligible `PlanStep` is engine/job-lifecycle behavior rather than world adjudication. The resolver may update the state/progress/outcome of an existing job through the normal authoritative transition path, but it does not gain arbitrary job-store mutation authority.

#### 5.6.6 Closed core WorldEffect algebra

Scenarios may extend world vocabulary, data types, blueprints, resources, relations, and mechanics, but they do not define arbitrary new authoritative mutation opcodes. Authoritative state changes must be reducible to a small, versioned core `WorldEffect` algebra.

The exact v0.1 schemas remain to be finalized, but the algebra should cover at least the structural needs already identified, such as:

- create/update/deactivate an `Entity`;
- create/update/deactivate a `Relation`;
- change an entity-associated `Resource`;
- set/update a scenario-defined state variable;
- update authoritative `Job` state/progress;
- create/record information where the information model requires an authoritative item.

If a future scenario cannot express a legitimate state transition using the core algebra, that is evidence that the core algebra may be missing a generic operation. The default response is to improve the core algebra deliberately, not to add `ScenarioCustomEffect` escape hatches.

`TemporalProjection` is deliberately outside `WorldEffects`: a projected completion/checkpoint time is a replaceable expectation that may be invalidated without rewriting history, while an accepted world effect becomes part of authoritative history through Events/reducers.

#### 5.6.7 Authoritative validation and invalid resolver output

Resolvers are responsible for semantic/mechanical adjudication, but their output is never trusted as the final authority. Before commit, the transition boundary validates the complete candidate effect batch against current authoritative state, schemas, references, branch ownership, configured resource/state constraints, atomicity, and other engine invariants.

Validation is performed on the resulting atomic transition as a whole. Two effects that are individually valid may be invalid together, for example two simultaneous expenditures that would exceed one shared resource balance.

An invalid resolver proposal is not automatically converted into an in-world action failure. It represents a resolution-system failure because the resolver has failed to produce a valid candidate transition.

In `DETERMINISTIC` mode, an invalid `ResolutionProposal` is fatal for the current simulation execution and should raise an integrity/resolution exception. It normally indicates a bug or inconsistent deterministic mechanic.

In `GENERATIVE` mode, the adapter may perform a bounded number of repair/retry attempts using validation feedback. Those attempts occur entirely within the unresolved resolution boundary: they do not commit effects/events, do not advance the authoritative simulation clock as a consequence of that resolution, and do not partially mutate world state. If no valid proposal is produced within the configured repair budget, the simulation execution enters an error/stopped state rather than guessing a fallback world outcome.

In both modes, the branch remains valid at its last committed event/state. Execution failure must preserve enough diagnostics/provenance to inspect the failed request/proposal. A later explicit retry, resolver change, or branch continuation may be supported, but must be auditable and must not silently rewrite committed history.

> **No invalid authoritative transition is recoverable by guessing.**

### 5.7 Ethics, illegality and enforcement

The core engine MUST NOT equate physical possibility with legality or ethics.

If world mechanics permit an act, an actor may attempt it even if it violates a formal rule, social norm, or its own values. Rules, detection, evidence, reporting, institutional response, social response, and punishment are separate mechanisms.

A violation therefore need not generate an automatic penalty. A useful conceptual chain is:

`action -> traces -> observation -> information -> interpretation/reporting -> institutional/social response -> consequence`

Actor motivation may distinguish internal moral cost, expected social cost, expected formal sanctions, perceived detection probability, and expected gain.

Provider safety policies are treated as a property of the cognition provider, not as the moral law of the simulated world. Provider choice is experimental metadata and different providers may produce different behavioral priors.

## 6. Information model

Information flow is first-class rather than a side effect of conversation.

A sender may communicate to one actor, selected actors, a group, an institution, or a public channel.

Core concepts should include:

- `InformationItem` / claim;
- source and provenance;
- sender and recipient set;
- channel;
- logical time;
- confidence/credibility metadata where applicable;
- retransmission ancestry;
- transformations or summaries introduced during retransmission.

Receiving information does not automatically create belief. Each recipient interprets the information through its own memories, trust, prior beliefs, and context.

One-to-many communication must support scenarios such as an executive addressing employees, a political leader speaking to supporters, a news organization publishing a claim, or a rumor spreading through a social network.

Not every channel should be accessible for everyone. For example an employee in an organization can choose to talk to other employee in the same office, but only CTO is able to schedule an all-hands meeting when he speaks to the whole company.

Information provenance should make it possible to inspect how a claim propagated and changed over time.

## 7. Entry, exit and actor lifecycle

The set of active actors is dynamic.

An actor may voluntarily leave when its expected utility or scenario-specific thresholds make departure attractive. A modeled organization or authority may remove an actor. New actors may enter through scenario events or future recruitment/generation mechanics.

Leaving MUST deactivate participation rather than delete historical identity.

The initial implementation may use simple actor creation. A future Actor Factory may generate candidates from templates or distributions.

## 8. Operator interaction

Human influence is a first-class capability and must remain auditable.

### 8.1 Observer mode

Inspect state, actors, events, conversations, information propagation, relationships, metrics, and branches without changing the simulation.

### 8.2 Director / in-world intervention

The operator may cause something that could exist inside the modeled world, such as revealing information to a group, introducing a regulation, triggering an external event, or making a resource available.

An in-world intervention passes through normal simulation mechanics. Revealing a claim does not directly force all recipients to believe it.

### 8.3 Simulation override

The operator may explicitly change simulator state for experimentation. This bypasses ordinary in-world causality but MUST be clearly marked as an override with provenance.

### 8.4 Actor possession

A human may temporarily replace an actor's normal `DecisionProvider` with `HumanDecisionProvider`.

Actor mode should expose only information available to the possessed actor, not the operator's omniscient observer knowledge, unless an explicit debug mode is chosen.

Multiple actors may eventually be human-controlled simultaneously.

## 9. Event-driven simulation lifecycle and scheduler

GRASS uses an event-driven logical clock rather than fixed simulation turns/ticks. Logical time advances according to scheduled work, world events, interactions, and other material resolution points. Actors are not periodically asked what they want to do merely because a fixed interval elapsed.

The scheduler is responsible for coordinating:

- the current `SimulationClock`;
- active/pending jobs and plan steps;
- scheduled scenario/world events;
- known future job completion/checkpoint times;
- interaction/conflict dependencies;
- simultaneous-resolution groups;
- actor `DecisionPoint`s.

The core loop is conceptually:

1. **Resolve pending decision points at the current logical time** — invoke cognition only for actors that actually require a new choice and translate resulting `ActionProposal`s into plans.
2. **Start/continue eligible plan steps** — create/activate blueprint-backed jobs whose dependencies, participation, and immediately relevant mechanical constraints allow an attempt.
3. **Determine the next material time** — find the earliest known scheduled event, job completion/checkpoint, interaction boundary, or other resolution point that can affect authoritative history.
4. **Advance the logical clock** — move directly to that time; do not simulate empty intermediate ticks.
5. **Accrue elapsed-time progress/dynamics** — update candidate job progress and explicitly configured time-dependent processes for the elapsed interval.
6. **Resolve all relevant events at that timestamp** — handle completion, failure, world events, interactions, conflicts, and simultaneous groups coherently.
7. **Commit accepted events/state transitions** — only through the authoritative event/reducer boundary.
8. **Derive observations and decision triggers** — update actor-relative information and create new `DecisionPoint`s only where a choice is actually required.
9. **Continue** — if no actor needs a decision, continue executing existing plans/jobs and jump to the next material time.

If a lone actor starts an eight-hour sleep job at 23:00 and nothing else can affect the simulation before completion, the scheduler may advance directly from 23:00 to 07:00 and resolve the sleep completion. If another event occurs at 02:00 that interrupts the actor, 02:00 becomes the next material time instead; elapsed sleep progress is preserved and the interruption may create a decision point.

Likewise an actor may create a plan such as breakfast -> drive to office -> enter office -> log in -> work. The scheduler may execute several steps without new cognition. If entering the office causes another actor to observe the arrival and initiate a conversation, that interaction may create a `DecisionPoint` for the first actor before the next planned step. The actor may accept, refuse, defer, revise the plan, or later resume it.

### 9.1 Plans persist until exhausted, blocked, or interrupted

A plan is an executable intention structure, not a one-turn output. Completed steps remain historical; pending steps may continue automatically when their dependencies become satisfied.

The scheduler SHOULD NOT ask an actor to re-decide between every already-planned step. New cognition is warranted when:

- the plan is exhausted and the actor has no next action;
- a required choice/consent is missing;
- a job fails or pauses in a way the existing plan does not resolve;
- an assumption/discovery materially invalidates future plan steps;
- another actor/world event creates an interaction requiring response;
- the operator explicitly takes control/intervenes;
- scenario policy defines another material decision trigger.

Plan revision must be explicit and provenance-preserving. Revising a plan creates a new revision/successor representation rather than rewriting historical intentions or jobs.

GRASS does not require a separate persistent `PlanExecution` model in v0.1. Runtime plan state should be derived from the plan definition together with step-to-job references and the authoritative `Job` states/events already tracked by the scheduler/world state. `PlanStep` therefore does not require its own independently mutable lifecycle status when that status can be derived from whether a job exists and the job's current state.

### 9.2 Decision points, observations, and bounded reaction

Observation and decision are separate. An actor may observe many facts while continuing its current activity; those observations may update `PerceivedWorld`, memory, or information state without causing an LLM/human/scripted provider call.

A `DecisionPoint` is created only when the existing plan no longer determines acceptable behavior or an incoming event requires the actor to choose.

An incoming interaction is a common example. If Actor B wants to talk to Actor A while A's plan says to log in to a computer, the scheduler exposes the conflict/interaction to A through a bounded decision point. A may accept, refuse, defer, prioritize, or alter its participation. The scheduler MUST NOT invent A's psychological preference.

Bounded reaction therefore remains an architectural concept, but it is no longer a phase executed for every actor on every turn. It is a constrained event-driven decision point associated with a particular interaction/conflict.

### 9.3 Concurrency, conflict, and simultaneous resolution

Many jobs may be active concurrently over the same logical interval. Advancing the clock does not mean that only one actor was active.

For example, at 08:00 Alice may start a 30-minute drive while Bob starts a 60-minute report-writing job. If Alice's arrival at 08:30 is the next material event, the clock advances to 08:30; Bob's job simultaneously accrues 30 minutes of eligible progress and remains active.

Candidate/active work forms a dependency/conflict structure whose edges may represent:

- competition for exclusive actor attention or time;
- shared or insufficient resources;
- mutual targeting or required participation;
- ordering dependencies;
- mutually exclusive state transitions;
- preemption/interruption/invalidation;
- scenario-defined interaction constraints.

Independent components may proceed concurrently. Mutually dependent/cyclic components are resolved jointly rather than by recursive actor-by-actor traversal.

When several events/actions share the same logical timestamp and their outcomes interact, the scheduler/resolver must support a simultaneous-resolution group instead of imposing an arbitrary sequential order.

### 9.4 Logical time, duration, and interruption

Action/job duration is part of world/execution semantics, not a global tick size. Different jobs may naturally span seconds, minutes, hours, days, or longer without forcing the whole scenario to use the smallest unit as its simulation step.

`time_budget` in `ActionProposal` remains actor intent. Actual elapsed time, progress, interruption points, and completion are determined by planning/world resolution.

Interruptible/resumable jobs preserve progress under the same `job_id` when paused. A material interruption may:

- leave the current job active if it can continue concurrently;
- pause it and preserve progress;
- fail/cancel it;
- create a decision point;
- leave later plan steps pending.

The scheduler advances only to the earliest material event known to the simulation, not to the end of whichever actor/job happens to be inspected first.

### 9.5 Time-dependent world dynamics without turns

There is no generic "end-of-turn" phase. Scenario dynamics such as decay, recovery, background production, deadlines, or periodic institutional behavior must be represented explicitly in time-aware mechanics.

Initial implementations may support two broad mechanisms:

- **scheduled dynamics** — discrete future events at known logical times;
- **elapsed-time dynamics** — deterministic or resolver-defined changes/progress evaluated for the interval when the clock advances.

The exact contract for continuous/rate-based state variables remains to be defined, but implementations MUST NOT reintroduce hidden fixed ticks merely to update them.

### 9.6 Temporal projection and elapsed-time dynamics

Advancing the logical clock MUST NOT directly mutate arbitrary world state inside the scheduler. The scheduler provides an elapsed interval (`from_time`, `to_time`, `delta_t`) to the relevant temporal/world-resolution mechanics, which determine what the elapsed time means.

The scheduler coordinates time; it does not own physics, biology, economics, progress, or scenario semantics.

A useful conceptual temporal-process boundary is:

`project_next(state, now) -> TemporalProjection?`

and:

`resolve_interval(state, from_time, to_time, reason) -> ResolutionProposal`

A `TemporalProjection` is not an event or fact. It is a scheduler-facing prediction of the next time at which a process may require material resolution. It may include:

- source/process/job reference;
- projection anchor time;
- next material resolution time;
- expected resolution kind;
- opaque/versioned execution-model data where required.

A projection may become invalid when the world changes. If an eight-hour sleep job projects completion at 07:00 but an alarm interrupts the actor at 02:00, the scheduler resolves the elapsed 23:00-02:00 interval, preserves applicable progress, and recalculates future projections rather than pretending the original 07:00 projection was historical fact.

Temporal mechanics fall conceptually into at least three useful families:

1. **Scheduled processes** — a known future logical time, such as a meeting, deadline, train arrival, or explicit scenario event.
2. **Progress-based processes** — long-running jobs such as sleep, driving, writing, or construction whose progress is evaluated over elapsed time and may have predicted completion/checkpoint times.
3. **Rate/continuous processes** — state evolution such as hunger, recovery, fuel discharge, interest accrual, or background production that can be evaluated from an anchor state and elapsed time without generating intermediate ticks.

The implementation SHOULD avoid materializing continuous state changes on every small interval. Where practical, store an anchor value/time and an evolution model, calculate the current value when required, and schedule only **material boundaries** that may change world behavior or constraints.

For example, if a state variable evolves linearly and crossing a threshold changes actor capabilities or should generate an observation, the temporal mechanic can project the threshold-crossing timestamp as a future `ScheduledResolution`. If the variable's evolution model changes before that timestamp, the previous projection is invalidated and a new one is calculated.

Similarly, job progress need not be rewritten every minute. For a simple `LINEAR` job, progress may be derived from the last materialized progress anchor plus eligible elapsed time. When participation, resources, rate, or another relevant condition changes, progress is materialized to the current time and the next projection is recalculated.

In `DETERMINISTIC` resolution, projections and elapsed effects may come from explicit scenario/execution rules. In `GENERATIVE` resolution, the generative resolver may estimate duration, progress, interruption consequences, or the next material checkpoint. Both use the same scheduler boundary; generative estimates remain non-authoritative until resolved into structured effects/events.

A **material boundary** is a time at which a process may affect authoritative behavior, capability, observability, plan feasibility, or another resolution decision. Tiny numerical drift that has no modeled consequence does not require an event merely because time passed.

### 9.7 Execution-time revalidation

Planning and scheduling do not guarantee that a future step remains feasible. State may change before its scheduled start/completion because another concurrent job/event commits first.

Immediately before a material resolution, the relevant capabilities, references, dependencies, resources, and world assumptions must be re-evaluated against the current authoritative state. A previously planned deployment may therefore fail after access was revoked, or a construction job may pause after another process consumed its resources.

Execution-time revalidation does not regenerate the actor's original intention. If the changed condition requires a new choice, it produces a `DecisionPoint`; otherwise the existing plan/job semantics determine what happens next.

### 9.8 Same-time decision fairness and ordering bias

Although the simulation is event-driven, provider call order must not create artificial causality.

When multiple actors receive decision points from the same committed state/event batch at the same logical timestamp, their decision contexts should be derived from the same appropriate authoritative snapshot unless one actor's decision is itself an observable committed event that legitimately precedes the other's decision.

Newly generated intentions are not world facts merely because one provider call happened first in implementation order. Same-time conflict/interaction sets should be gathered and resolved coherently.

## 10. History, replay and branching

Simulation history is designed as a tree rather than only a linear log.

Canonical authoritative simulation history is event-sourced. `WorldState` is a materialized projection of accepted historical events for one branch at one logical point in time; checkpoints or snapshots are reconstruction optimizations rather than an alternative source of truth.

`WorldEffect` and `Event` are distinct concepts. A `WorldEffect` represents a candidate authoritative transition produced by resolution. It is not yet a historical fact. After invariant checks and authoritative acceptance, the engine emits immutable events describing what actually occurred. Only accepted events applied through deterministic state-transition logic may mutate authoritative `WorldState`.

Components outside the state-transition boundary MUST NOT mutate `WorldState` directly. Planners, executors, providers, UI components, and scenario adapters should receive read-only views or explicit interfaces rather than unrestricted mutable references.

Not every event must mutate world state. Every material occurrence, attempted action, authoritative decision, and state change should be representable by immutable events when it matters for replay, observability, or analysis. Failed attempts, refusals, provider changes, or deliberate non-actions may therefore be historically meaningful even when they cause no immediate state mutation.

A minimal event envelope should preserve stable identity and ordering independently of payload shape. The initial schema should provide equivalents of:

- `event_id`;
- `branch_id`;
- monotonically ordered `sequence` within the branch;
- logical simulation time;
- event type and versioned payload;
- provenance;
- optional causation/correlation references where useful.

Sequence establishes deterministic replay order but does not by itself imply causal ordering between events resolved at the same logical time.

One authoritative transition may produce multiple events. Such an event set must be committed atomically: either all events representing that accepted transition become part of the branch history, or none do. The storage technology may change, but it must preserve this semantic guarantee.

A branch has a parent and fork point. History before the fork is conceptually shared and immutable; continuation after the fork is independent.

Checkpoints/snapshots may accelerate reconstruction but are not the semantic source of truth.

Required future capabilities include:

- reconstruct state at historical points;
- fork from a selected point;
- change an intervention or actor decision;
- replay the same semantic action proposal through a different planning/execution model where practical;
- continue branches independently;
- compare branch outcomes and metrics;
- identify which events arose from AI, humans, rules, scenario events, institutions, or overrides.

Replay means deterministic reconstruction of recorded history. Replaying an existing branch MUST NOT re-invoke an LLM, human provider, or other cognition provider in order to rediscover past decisions. Recorded events and the historical decision/action data required by the selected reproducibility level are reused instead.

Calling cognition or world-resolution providers again creates new history. This occurs when continuing a simulation beyond recorded history, regenerating behavior by explicit request, or continuing a new branch after a fork. GRASS should therefore distinguish clearly between **replay** and **branch continuation/regeneration**.

The exact event-store technology, serialization format, checkpoint cadence, and physical representation of shared history remain implementation decisions, provided they preserve these semantics.

## 11. Scenario-defined functions

Scenario dynamics may range from simple formulas to more complex functions.

GRASS should allow scenario authors, and optionally an LLM-assisted World Builder, to propose functions for state transition, utility, detection, consequence, or other domain mechanics.

Unrestricted `eval` or `exec` of LLM-generated Python is forbidden. A future ADR must select a constrained mechanism such as a safe expression language, AST whitelist, isolated sandbox worker, WebAssembly-like boundary, or another validated runtime.

Generated mechanics must be inspectable by the user before being treated as scenario truth.

## 12. Observability and analysis

Observability is part of the architecture, not an afterthought.

The system should eventually provide:

- global timeline;
- actor timeline and state history;
- actor beliefs, memories, plans, relationships, memberships, and decision metadata;
- conversations and one-to-many communications;
- information-propagation graphs;
- relationship/network evolution;
- state-variable and resource metrics;
- branch comparison;
- filters by actor, event type, provenance, time, and information item.

A `Simulation Analyst` is external to simulated reality. It may inspect event history, metrics, hierarchical summaries, and selected raw events to answer questions such as:

- What were the main turning points?
- Why did an actor leave?
- Which information chain triggered a later event?
- Who accumulated informal influence?
- Which operator interventions mattered most?
- How did two branches diverge?
- What is the resource distribution over actors and their position in the social hierarchy.

Analyst statements should reference source events where practical and distinguish observed correlation from stronger causal claims.

## 13. Reproducibility and provider bias

A simulation run should persist enough metadata to understand its configuration, including scenario/version identifiers, seeds, provider/model metadata, relevant generation parameters, branch ancestry, and operator interventions.

LLM-backed cognition and generative world resolution are probabilistic and provider-dependent. Runs using different models or world-resolution modes may differ systematically. Decision-provider choice, world-resolution mode, and generative resolver/model choice should therefore be treated as experimental variables rather than hidden infrastructure.

Core engine tests must not depend on live LLM behavior. Deterministic fake/scripted providers are required for replay, branch isolation, action validation, and state-transition tests.

## 14. Future actor scales

The initial implementation supports detailed individual actors only.

The architecture must nevertheless leave room for:

- `CollectiveActor` representing distributions or weighted populations;
- `InstitutionActor` representing formal organizations;
- mixed-resolution simulations where a small number of important individuals coexist with aggregate population actors;
- future adaptive expansion/collapse of population resolution.

These are extension points, not v0.1 implementation requirements.

## 15. Initial implementation scope

The first executable milestone should prove architecture rather than realism.

### 15.1 Initial technology choices

The initial implementation stack is:

- **GRASS core:** Python;
- **backend/API:** FastAPI;
- **frontend:** React;
- **frontend/backend transport:** REST for ordinary API operations and WebSocket for interactive simulation/session traffic, including client-managed provider round trips.

These are implementation choices for the initial architecture, not permission to couple simulation-domain code to FastAPI or React. GRASS core must remain usable and testable independently of the web application. Provider, persistence, planning/execution, and simulation-domain boundaries must remain explicit.

A useful acceptance scenario is a small organization with roughly ten individual actors, event-driven logical time, configurable state variables such as energy/stress/fulfillment, a resource such as money, trust relationships, simple membership, one-to-one and one-to-many communication, actor exit/entry, a deterministic provider for tests, at least one LLM adapter, operator information disclosure, actor possession, event history, checkpoint/replay, and a branch fork with independent continuation.

The acceptance scenario should explicitly prove scheduler time jumps and interruption: an actor can sleep for eight hours with the clock jumping directly to completion when nothing happens, while another run contains an earlier interaction/event that interrupts the job; an actor can also execute several already-planned steps without additional cognition until another actor's interaction creates a `DecisionPoint`.

Explicitly deferred: true collective/institutional decision semantics, society-scale distributed execution, complex economy, calibrated psychology, advanced geography, multiplayer networking, automatic population-resolution changes, rich graphical UI, and causal-inference claims.

## 16. Major unresolved questions

The following are intentionally open and should not be silently decided by implementation:

1. exact `Actor` and shared entity schemas;
2. `WorldDefinition` serialization and validation;
3. event schema and storage technology;
4. snapshot cadence and restoration strategy;
5. safe runtime for scenario-defined functions;
6. exact `Plan` / `PlanStep` schema, dependency/failure semantics, and immutable revision/provenance model; v0.1 should derive step runtime state from associated jobs/events rather than persist a separate `PlanExecution` lifecycle;
7. exact `DecisionPoint` schema and `DecisionTriggerPolicy` contract, including salience/interrupt rules after actor-relative perception;
8. scheduler event-queue contract, representation of next material times, simultaneous timestamps, and deterministic ordering of independent events;
9. exact temporal-process/projection schema for scheduled, progress-based, and rate/continuous dynamics, including projection invalidation and material-boundary detection without fixed ticks;
10. degree of LLM use in action interpretation versus deterministic/schema-based planning;
11. exact versioned schemas for the closed core `WorldEffects` algebra and its validation rules;
12. exact `ResolutionRequest` / `ResolutionProposal` schemas and resolver context construction;
13. remaining blueprint schema details, discovery/versioning, assumption representation, and how execution discoveries feed later planning/cognition;
14. exact set of engine-level structural invariants versus scenario-defined deterministic mechanics;
15. belief representation;
16. memory storage and retrieval;
17. conversation granularity and advanced job interruption/resumption/contribution semantics beyond v0.1;
18. exact interaction between utility estimation and LLM reasoning;
19. causal-reference semantics between events;
20. durable storage/security design for client-managed credentials, if persistent BYOK is added;
21. whether and how a future local provider bridge or secured server relay should be implemented;
22. generative resolver context/prompt/policy/versioning, bounded repair strategy, model-provider integration, and cost controls;
23. whether a future explicit hybrid deterministic/generative resolution policy should exist;
24. cost controls, batching, caching, and concurrency for LLM calls.

During the current pre-baseline phase these assumptions may still be edited directly. Draft ADRs may capture candidate decisions. After a design baseline is declared, material architecture changes should normally proceed through accepted ADRs.

## 17. Prior art

Existing systems including Concordia, AgentSociety, OASIS, MiroFish, AgentTorch, Mesa, AnyLogic, and Simudyne demonstrate useful ideas such as generative actors, explicit world adjudication, information diffusion, population-scale modeling, interventions, replay, and experimental observability.

They are **prior art, not architecture templates** for GRASS. No external project's APIs, class hierarchy, schemas, package structure, prompts, or implementation should be copied merely because it is mentioned here. GRASS architecture is intentionally developed from its own requirements.

## 18. Licensing

GRASS is licensed under **GNU General Public License version 3 only (GPL-3.0-only)**.

New project-owned source files should use an appropriate GPL notice or SPDX identifier where practical:

`SPDX-License-Identifier: GPL-3.0-only`

Dependencies and incorporated third-party code must be reviewed for GPLv3 compatibility.

## 19. Guiding principle

> **Keep the world's rules explicit, keep actors' knowledge incomplete, keep decisions replaceable, and keep history inspectable.**

Complexity should emerge from interactions among simple, configurable mechanics rather than from a monolithic prompt or opaque model-generated story.
