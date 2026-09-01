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

- logical time and turn duration;
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

### 3.5 Drives, Utility and Plans

Actors may have relatively persistent `Drives`, a configurable `UtilityModel`, and dynamic `Plans`.

Utility is not restricted to a linear weighted sum. Scenario-defined utility may include thresholds, saturation, asymmetric penalties, interactions, and time horizon effects.

An actor may value different states differently from another actor. For example, one actor may strongly avoid stress while another tolerates stress in exchange for influence.

`Plan` represents a temporary strategy or objective such as seeking promotion, leaving an organization, forming a coalition, or acquiring a resource.

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

1. **ActionProposal / intention** — open-ended behavior proposed by a `DecisionProvider`.
2. **Planning** — translate the semantic intention into something the current execution model can attempt.
3. **Validation / capability evaluation** — evaluate physical, temporal, resource, membership, access, authorization, and scenario constraints.
4. **Resolution / execution** — resolve the attempted behavior, including simultaneous or conflicting actions.
5. **World effects** — produce explicit candidate changes to authoritative state.
6. **State transition** — apply accepted effects through the world engine.
7. **Event emission** — record material attempts, outcomes, and state changes.

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

Each blueprint is bound to exactly one actor-facing primitive. A blueprint MUST NOT contain an internal workflow, nested action list, or multi-primitive graph. If an intention requires several primitives, composition belongs to `Plan`; each plan step may select one primitive and one blueprint and declare dependencies on other steps.

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

Blueprint lifecycle is orthogonal to feasibility. At minimum a blueprint is versioned and may be active/inactive. Deactivation prevents new use while preserving historical identity; modification creates a new immutable version for future jobs. A job remains bound to the exact blueprint version with which it started.

### 5.4 Plan and Job boundaries

Composition belongs to `Plan`, not to `Blueprint`. Conceptually:

`ActionProposal -> Plan -> PlanStep(primitive + blueprint) -> Job`

A plan may contain several dependent primitive executions. For example, employing a person and then granting access may become a `RELATE` step followed by a dependent `TRANSFER` step. A blueprint does not become a hidden workflow engine.

A `Job` is one concrete execution of one blueprint and therefore one primitive. Every blueprint-backed execution always creates a `Job`, even when creation and completion occur within one atomic transition. This provides a uniform trace:

`ActionProposal -> PlanStep -> Blueprint -> Job -> WorldResolution -> WorldEffects -> Events`

Conceptual job state includes:

- `job_id`;
- originating proposal/plan-step references;
- exact `blueprint_id` and blueprint version;
- primitive;
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

`COMPLETED`, `FAILED`, and `CANCELLED` are terminal. A retry after terminal failure/cancellation creates a new job.

Progress is not universally a percentage. v0.1 should support at least simple `LINEAR` and `BINARY` structured progress models. Detailed contribution and state-change history belongs in events; `Job` is the materialized execution state required to continue simulation.

World resolution may discover new information while a job is running, such as an invalid blueprint assumption, an additional required resource, or an incompatibility. Such discovery may continue, pause, fail, or trigger later plan revision and should become normal events/information when materially relevant.

One blueprint/job execution may legitimately result in several candidate `WorldEffects` and authoritative events as one atomic transition. Blueprint scope and effect scope are deliberately different.

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

## 9. Simulation lifecycle

Actors form their primary intentions against the same authoritative snapshot at the start of a turn. Intent generation is therefore conceptually simultaneous: one actor MUST NOT receive another actor's newly generated intention as if it were already an observed fact merely because the implementation queried that actor first.

A conceptual turn is:

1. **Snapshot / perception** — establish `WorldState(t)` and derive actor-relative observations/context.
2. **Primary decision** — all eligible actors independently generate their primary `ActionProposal` from the same start-of-turn reality.
3. **Planning** — translate proposals into candidate plans using the selected planning model.
4. **Interaction and conflict discovery** — identify targeted interactions, shared-resource claims, exclusive attention/time requirements, dependencies, mutually exclusive outcomes, and other constraints between candidate plans.
5. **Bounded reaction phase** — actors affected by incoming interaction requests or discovered conflicts may accept, refuse, defer, prioritize, or modify participation within the scope of those already identified interactions.
6. **Joint resolution / scheduling** — resolve connected conflict/dependency components together and construct a feasible within-turn execution schedule or simultaneous-resolution groups.
7. **Execution-time revalidation** — immediately before an action or resolution group executes, validate that its relevant preconditions and capabilities still hold after earlier committed events in the same turn.
8. **Execution and state transition** — resolve the action/group, convert accepted results into authoritative events, and atomically apply the corresponding state transitions.
9. **End-of-turn dynamics** — apply configured decay, recovery, background processes, rule/institution mechanics, information propagation, and other scenario dynamics whose semantics belong at the end of the turn.
10. **Finalize** — emit derived metrics, evaluate lifecycle/termination conditions, and continue to the next logical time.

The reaction phase is deliberately bounded. It is not a second unrestricted primary decision round. Its purpose is to let actors respond to conflicts and participation requests that could not have been known when primary intentions were formed, without creating unbounded recursive chains of "reaction to reaction".

For example, an engineer may intend to work while a CTO independently intends to talk with that engineer. The scheduler may identify an attention/time conflict, but it MUST NOT invent the engineer's preference. The engineer's bounded reaction may accept, refuse, defer, or otherwise prioritize the meeting relative to the original work intention.

Likewise, if an engineer requests a conversation with a CTO while the CTO intends to speak with someone else, the CTO decides how to respond; the resolver only exposes the conflict and enforces mechanical constraints.

### 9.1 Conflict and dependency resolution

The resolver should not be modeled as a simple global action queue or as recursive actor-by-actor execution. Candidate plans form a dependency/conflict graph whose nodes are plans or plan fragments and whose edges may represent:

- competition for exclusive actor attention or time;
- shared or insufficient resources;
- mutual targeting or required participation;
- ordering dependencies;
- mutually exclusive state transitions;
- preemption or invalidation;
- scenario-defined interaction constraints.

Independent connected components may be resolved independently. Mutually dependent or cyclic components must be resolved jointly rather than by recursive traversal. Cycles are therefore normal resolution cases, not exceptional errors.

The exact graph representation and algorithm (for example SCC detection, constraint solving, heuristics, or another approach) remain implementation details and may evolve.

### 9.2 Time, attention and partial execution

Within-turn time and actor attention are explicit mechanical constraints. An actor cannot normally participate in two interactions that require the same exclusive attention interval.

A conflict does not imply that one whole intention must be discarded. Where scenario/process semantics permit, a plan may be delayed, shortened, partially executed, or resumed after another interaction. For example a 20-minute conversation may consume part of an engineer's one-hour work turn rather than automatically cancelling all work.

The exact representation of duration, interruptibility, resumability, and partial progress is scenario/process-specific and remains open beyond the minimal v0.1 scheduler contract.

### 9.3 Execution-time revalidation

Planning and scheduling do not guarantee that a later action remains feasible. Earlier actions in the same turn may change state or capabilities.

For example, an engineer may intend to deploy while a CTO independently intends to revoke the engineer's access. Both intentions are valid against the same start-of-turn snapshot. If access is revoked before the scheduled deployment attempt, the deployment is revalidated against the new authoritative state and may fail or be cancelled with an explicit event such as `ActionFailed` / `ActionCancelled(reason=preconditions_changed)`.

Execution-time revalidation does not regenerate the actor's original intention and does not reveal future state to the actor retroactively.

### 9.4 Simultaneous resolution groups

Some interactions cannot be represented correctly by arbitrarily ordering actions. The scheduler/resolver must therefore support a set of actions being resolved as one simultaneous-resolution group.

Examples include two actors competing for a single indivisible resource, mutually interacting actions, or scenario mechanics in which outcomes depend on several actions occurring at the same logical instant.

Ordering (`A before B`) and simultaneous grouping (`A with B`) are both valid resolver outcomes. The scenario/execution model determines the resulting world effects for a simultaneous group.

Sequentially mutating the world while querying decision providers in arbitrary actor order remains forbidden because it creates artificial ordering bias.

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

Calling providers again creates new history. This occurs when continuing a simulation beyond recorded history, regenerating behavior by explicit request, or continuing a new branch after a fork. GRASS should therefore distinguish clearly between **replay** and **branch continuation/regeneration**.

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

A useful acceptance scenario is a small organization with roughly ten individual actors, hourly logical turns, configurable state variables such as energy/stress/fulfillment, a resource such as money, trust relationships, simple membership, one-to-one and one-to-many communication, actor exit/entry, a deterministic provider for tests, at least one LLM adapter, operator information disclosure, actor possession, event history, checkpoint/replay, and a branch fork with independent continuation.

Explicitly deferred: true collective/institutional decision semantics, society-scale distributed execution, complex economy, calibrated psychology, advanced geography, multiplayer networking, automatic population-resolution changes, rich graphical UI, and causal-inference claims.

## 16. Major unresolved questions

The following are intentionally open and should not be silently decided by implementation:

1. exact `Actor` and shared entity schemas;
2. `WorldDefinition` serialization and validation;
3. event schema and storage technology;
4. snapshot cadence and restoration strategy;
5. safe runtime for scenario-defined functions;
6. exact `Plan` / planner boundary and execution-plan representation/versioning;
7. degree of LLM use in action interpretation versus deterministic/schema-based planning;
8. extension/versioning policy for primitive payload parameters, world-reference selectors, resource transfer modes, and the minimal `WorldEffects` algebra;
9. remaining blueprint schema details, discovery/versioning, assumption representation, and how execution discoveries feed later planning/cognition;
10. belief representation;
11. memory storage and retrieval;
12. conversation granularity and advanced job interruption/resumption/contribution semantics beyond v0.1;
13. exact interaction between utility estimation and LLM reasoning;
14. causal-reference semantics between events;
15. durable storage/security design for client-managed credentials, if persistent BYOK is added;
16. whether and how a future local provider bridge or secured server relay should be implemented;
17. exact `WorldResolutionProvider` / `ResolutionProposal` contract and minimal structured effects accepted from generative resolution;
18. exact set of engine-level structural invariants versus scenario-level deterministic mechanics;
19. generative resolver context construction, prompt/policy/versioning, model-provider integration, and cost controls;
20. whether a future explicit hybrid deterministic/generative resolution policy should exist;
21. cost controls, batching, caching, and concurrency for LLM calls.

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
