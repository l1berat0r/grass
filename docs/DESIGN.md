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

All authoritative changes pass through simulation mechanics that validate, resolve, apply, and record outcomes.

This separation exists to preserve reproducibility, interpretability, provider independence, security, replay, and branchability.

## 3. Fundamental abstractions

### 3.1 WorldDefinition

A versioned formal description of scenario mechanics and initial conditions. It may define:

- logical time and turn duration;
- actor templates and initial actors;
- scenario-defined state variables;
- resources;
- relationships and memberships;
- channels and information topology;
- action capabilities/primitives;
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
- `Artifact`.

Scenarios may extend this vocabulary with domain-specific types such as `Company`, `Department`, `Camp`, `GardenBed`, `Vehicle`, or `PoliticalParty`. A scenario-defined type may optionally identify a built-in base type when useful for validation, planning, UI, or analytics. Core mechanics MUST NOT gain domain behavior merely because a type name exists.

`Actor` is an entity with cognition, perception, and decision capability rather than a separate parallel identity system. The implementation should prefer composition (for example an `ActorFacet` or equivalent component keyed by `entity_id`) over a deep inheritance hierarchy.

The first implementation focuses on actor-capable `Person` entities. Persistence, action, event, relationship, membership, information, and provider boundaries MUST nevertheless remain extensible to future collective or institutional actors. A `Group` or `Organization` entity may later acquire actor capability without changing its historical entity identity.

Actor cognition state such as beliefs, plans, drives, utility configuration, and memory is authoritative simulation state for replay and branching purposes, but it is not ordinary objective entity state. It SHOULD remain separated from general entity properties so that world truth, represented semantic content, actor observation, and actor belief do not collapse into one namespace.

### 3.4 StateVariable and Resource

State variables are scenario-defined rather than hard-coded. Examples include energy, stress, fulfillment, security, influence, health, or public support.

A state variable may define range, initialization, thresholds, visibility, decay/recovery behavior, and transition rules.

Resources represent fungible or aggregatable quantities that may be transferred, consumed, produced, reserved, or competed over. Examples include money, food, budget, water, fuel, attention, or time allocations.

Every authoritative resource quantity MUST be associated with an `Entity`; resources do not exist as detached global quantities without context. Conceptually:

`ResourceState(entity_id, resource_type, quantity, unit?, properties?)`

Examples include a `Company` entity having a `budget` resource, a `GardenBed` entity having a `food` resource representing harvestable carrots, a water tank having a `water` resource, or a forest/location entity having a `wood` resource.

This association provides spatial, organizational, or logical context for resource access and capability checks. A transfer of resources is therefore a transition between entity-associated resource states rather than a mutation of an unscoped global number.

Resources should not be exploded into individual entities merely because they have physical instances. A quantity of carrots may remain `food` on a garden-bed entity. If one particular object becomes individually important to the scenario, such as the only working radio, it may instead be modeled as an `Entity`.

The boundary between `StateVariable` and `Resource` is semantic: resources are quantities for which ownership/location, transfer, consumption, production, reservation, or aggregation is meaningful; other actor/world attributes may remain state variables.

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

The core engine MUST NOT depend on one specific way of translating intentions into executable behavior. Future implementations may use, for example:

- an LLM-based action interpreter;
- deterministic schema matching;
- a symbolic planner;
- affordance-graph planning;
- tool-like structured calls;
- behavior trees;
- or another model not yet designed.

These alternatives should be replaceable without redesigning `Actor`, `WorldState`, `EventStore`, `DecisionProvider`, or persistence of authoritative history.

Conceptually, the implementation should preserve narrow boundaries similar to:

`DecisionProvider -> ActionProposal -> ActionPlanningPort -> ExecutionPlan -> ActionExecutionPort -> ExecutionResult -> WorldEffects -> WorldState / Events`

The names and exact interfaces are provisional. The important requirement is dependency direction and replaceability.

`ActionProposal` should preserve the semantic intent of the actor and MUST NOT declare arbitrary world effects. A planner may attach structured metadata, candidate operations, or an execution-model identifier, but its private intermediate representations must not leak into unrelated domain models.

`ExecutionPlan` is a boundary object, not a promise that all future planners will use the same internal step language. If execution-model-specific operations are persisted or exposed, they must be explicitly versioned and treated as implementation-specific data rather than universal GRASS semantics.

`ExecutionResult` / `WorldEffects` describe what the resolver determined can happen. External components, including LLMs and planners, still do not receive direct mutation access to `WorldState`.

Planning and execution are separate axes of change: GRASS should be able to replace the planner without replacing world resolution, and to change execution/resolution mechanics without changing how an actor expresses its intention.

### 5.2 Initial candidate execution model

For the initial implementation, a useful candidate is to let actors propose open-ended intentions and allow the planner/interpreter to map them to scenario-defined processes or compositions of generic interactions.

The scenario, rather than core, may define domain-specific processes such as `gather_wood`, `repair_shelter`, `write_report`, or `run_security_scan`. The core should not contain a global catalog of human actions such as `schedule_company_all_hands`, `propose_law`, or `build_sos`.

The planner may attempt to realize novel intentions by composing available scenario processes and generic interactions. An intention that cannot be interpreted coherently may be rejected, refined, delayed, or converted into a failure/no-op attempt according to scenario policy.

Candidate actor-facing interactions such as `PERFORM`, `COMMUNICATE`, `OBSERVE`, and `MOVE` are exploratory design ideas, not frozen primitives. Likewise, the exact minimal algebra of world effects remains unresolved.

Capabilities should be evaluated against world objects and context (for example access, control, presence, channel use, or resource authority) rather than against a hard-coded domain action name. Lack of authorization does not automatically imply physical or technical impossibility; preventive enforcement, actual feasibility, detection, and later consequences are distinct concerns.

LLM-generated text never directly mutates state and must not be allowed to declare outcomes such as `increase_loyalty(20)` or `make_actor_afraid`. Actors choose attempts; the world resolves consequences.

### 5.3 Persist semantic intent separately from execution details

When practical, event history should preserve the actor's semantic `ActionProposal` separately from planner-specific and resolver-specific details.

This supports:

- debugging why an action was interpreted in a particular way;
- comparing different planners against the same actor intention;
- replaying or branching from an action proposal with a different planning/execution model;
- measuring how much simulation outcomes depend on the chosen action interpretation architecture.

Planner internals are not automatically authoritative history. Persist only the portions needed for reproducibility, inspection, or deterministic replay, and version them explicitly when they are execution-model-specific.

### 5.4 Scenario-resolution entities and semantic content

GRASS models authoritative reality at the resolution chosen by the scenario, not at an imagined microscopic physical ground truth below that resolution. The engine MUST NOT require irrelevant low-level entities merely to reconstruct an outcome.

A novel action may therefore create or modify a generic scenario-level `Entity` rather than forcing the core to introduce domain-specific outcome primitives such as `VisualMarker`, `Document`, `Shelter`, or `Barricade`.

Mechanically relevant properties should remain explicit and be determined by validated world/scenario mechanics. Optional `semantic_content` may describe what an entity represents, contains, depicts, or communicates and may later be interpreted by cognition providers.

For example, an actor intending to arrange stones into an SOS signal may, after successful resolution, result in an entity conceptually similar to:

`Entity(entity_type=Artifact, properties={location: beach, material: stones, visibility: 0.72}, semantic_content="Visual representation of the letters SOS")`

Individual stones need not exist as entities unless their individual identity is itself relevant at the scenario's simulation resolution.

The actor may propose intended semantic content, but it does not directly declare authoritative success or mechanical properties. World resolution determines whether the intended object is actually realized and which mechanically relevant properties it has. Partial or failed execution may result in different realized semantic content.

Semantic content is not synonymous with world truth. A document may truthfully exist with semantic content claiming that revenue was `$10M` while the authoritative revenue state is `$4.2M`. Likewise an SOS representation can exist even if nobody actually requires rescue.

GRASS therefore keeps distinct:

- authoritative entity state and mechanical properties;
- semantic content represented by an entity;
- actor-relative observation;
- actor interpretation;
- actor belief.

World effects should operate on a formal scenario-state model using generic state operations rather than an ever-growing catalog of domain action or outcome primitives. The exact minimal state-delta algebra remains open, but it should support creating, updating, activating/deactivating entities, changing entity properties, changing entity-associated resource states, and creating/updating/removing relations without requiring core GRASS to know what those domain objects mean.

### 5.5 Ethics, illegality and enforcement

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

LLM-backed simulation is probabilistic and provider-dependent. Runs using different models may differ systematically. Provider choice should therefore be treated as an experimental variable, not hidden infrastructure.

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
6. exact action-planning and execution contracts, including how `ActionProposal`, execution-model-specific plans, and `WorldEffects` are represented and versioned;
7. degree of LLM use in action interpretation versus deterministic/schema-based interpretation;
8. minimal actor-facing interaction language and minimal world-effect algebra for the initial execution model;
9. scenario-process representation and discovery by planners;
10. belief representation;
11. memory storage and retrieval;
12. conversation granularity and long-running action semantics;
13. exact interaction between utility estimation and LLM reasoning;
14. causal-reference semantics between events;
15. durable storage/security design for client-managed credentials, if persistent BYOK is added;
16. whether and how a future local provider bridge or secured server relay should be implemented;
17. cost controls, batching, caching, and concurrency for LLM calls.

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
