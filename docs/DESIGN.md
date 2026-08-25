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

GRASS is not assumed to be scientifically predictive by default. Scientific claims require scenario-specific calibration, validation, uncertainty analysis, and evidence.

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

The engine therefore separates:

1. **ActionProposal / intention** — open-ended behavior proposed by a provider.
2. **Interpretation** — mapping an intention to known mechanics, parameters, targets, and possibly a composed plan.
3. **Validation** — checking physical, temporal, resource, membership, permission, and scenario constraints.
4. **Resolution** — resolving simultaneous or conflicting actions.
5. **State transition** — applying validated effects.
6. **Event emission** — recording what actually happened.

Novel intentions may be decomposed into existing mechanics. An intention that cannot be interpreted coherently may be rejected, refined, delayed, or converted into a failure/no-op event according to scenario policy.

LLM-generated text never directly mutates state.

### 5.1 Ethics, illegality and enforcement

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
6. interpret and validate proposals;
7. resolve simultaneous interactions/conflicts;
8. apply state transitions and rule/institution mechanics;
9. propagate resulting information and observations;
10. emit immutable events and derived metrics;
11. evaluate entry/exit and termination conditions;
12. continue to the next logical time.

The exact phase boundaries, handling of long-running actions, and multi-message conversations remain open design questions.

Sequentially mutating the world while querying each actor in arbitrary order should be avoided because it can create artificial ordering bias.

## 10. History, replay and branching

Simulation history is designed as a tree rather than only a linear log.

Every material authoritative state change should be representable by immutable events with logical time, branch identity, and provenance.

A branch has a parent and fork point. History before the fork is conceptually shared and immutable; continuation after the fork is independent.

Checkpoints/snapshots may accelerate reconstruction but are not the semantic source of truth.

Required future capabilities include:

- reconstruct state at historical points;
- fork from a selected point;
- change an intervention or actor decision;
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
6. degree of LLM use in action interpretation versus deterministic/schema-based interpretation;
7. belief representation;
8. memory storage and retrieval;
9. conversation granularity and long-running action semantics;
10. exact interaction between utility estimation and LLM reasoning;
11. causal-reference semantics between events;
12. UI technology;
13. cost controls, batching, caching, and concurrency for LLM calls.

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
