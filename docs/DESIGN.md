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

### 3.3 Actor

`Actor` is the common participant abstraction. Actor identity must remain stable across the history of a simulation even if the actor becomes inactive or leaves a modeled organization.

The first implementation will focus on `IndividualActor`, while persistence, action, event, relationship, membership, information, and provider boundaries MUST remain extensible to future `CollectiveActor` and `InstitutionActor` types.

Future collective actors may represent aggregate populations rather than one LLM call per represented human. Future institutional actors may expose actor-like behavior externally while deriving decisions internally from procedures, roles, votes, or other actors.

### 3.4 StateVariable and Resource

State variables are scenario-defined rather than hard-coded. Examples include energy, stress, fulfillment, security, influence, health, or public support.

A state variable may define range, initialization, thresholds, visibility, decay/recovery behavior, and transition rules.

Resources represent quantities that may be owned, transferred, consumed, created, reserved, or competed over. Examples include money, food, budget, attention, or time allocations.

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

Decision policy and model transport are separate concepts. An actor must not be coupled directly to a specific LLM SDK.

### 4.3 Explainability metadata

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

### 5.4 Ethics, illegality and enforcement

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

A conceptual turn is:

1. advance/establish logical time;
2. derive observations for each relevant actor;
3. update bounded cognition context, memory, and beliefs where appropriate;
4. request action proposals from eligible decision providers;
5. collect proposals before authoritative resolution;
6. plan/interpret proposals through the selected action-planning model;
7. validate capabilities and feasibility;
8. resolve simultaneous interactions/conflicts through the selected execution model;
9. apply accepted world effects and rule/institution mechanics;
10. propagate resulting information and observations;
11. emit immutable events and derived metrics;
12. evaluate entry/exit and termination conditions;
13. continue to the next logical time.

The exact phase boundaries, handling of long-running actions, multi-message conversations, and the concrete planning/execution contracts remain open design questions.

Sequentially mutating the world while querying each actor in arbitrary order should be avoided because it can create artificial ordering bias.

## 10. History, replay and branching

Simulation history is designed as a tree rather than only a linear log.

Every material occurrence, attempted action, authoritative decision, and state change should be representable by immutable events when it matters for replay, observability, or analysis. In particular, failed attempts, refusals, or deliberate non-actions may be historically meaningful even when they cause no immediate state mutation.

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

The exact event store, serialization format, checkpoint cadence, and physical representation of shared history are not decided yet.

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
15. UI technology;
16. cost controls, batching, caching, and concurrency for LLM calls.

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
