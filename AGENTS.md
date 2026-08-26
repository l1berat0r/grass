# AGENTS.md

# GRASS — Coding Agent Instructions

This repository is currently architecture-first. Read `docs/DESIGN.md` completely before changing core structures.

## Mission

Build GRASS (GRASS Roots Agentic Systems Simulator), a general-purpose simulator of dynamic human systems. The same core engine must be capable of hosting scenarios such as a corporation, state, political party, community, or other social system without hard-coding those domains into core modules.

## Non-negotiable architectural rules

1. **The engine owns reality.** LLMs, humans, and other decision providers may propose actions but must never mutate authoritative world state directly.
2. **Actors do not receive omniscient state.** Decision providers operate on `PerceivedWorld` / observations, memories, beliefs, drives, plans, and actor-local state.
3. **Every authoritative state-changing operation produces events.** Do not introduce hidden mutations of simulated reality.
4. **History is branchable.** New persistence decisions must preserve the ability to fork from any persisted checkpoint/event position and continue independently.
5. **Provenance is mandatory.** Events and interventions must record their origin: AI actor, human-controlled actor, world rule, institution, scenario event, operator intervention, or explicit override.
6. **Do not hard-code corporate, governmental, political, or other scenario-specific semantics in the core engine.** Domain mechanics belong in scenario definitions, plugins, rules, schemas, and functions.
7. **`Entity` is the persistent world identity anchor; actors are entity-backed.** Initial implementation may focus on actor-capable `Person` entities, but APIs and persistence schemas must remain extensible to future collective and institutional actors.
8. **Decision providers are replaceable.** OpenAI, Ollama, local models, future providers, humans, scripts, and deterministic strategies must use the same conceptual decision interface.
9. **Model providers and decision policy are separate concepts.** Do not couple an actor directly to a specific LLM SDK.
10. **Actions are open at the intention level and constrained at the mechanics level.** Actors may propose novel intentions. The engine must interpret, validate, decompose, or reject them before execution.
11. **Action planning and execution are replaceable boundaries.** Do not couple `Actor`, `WorldState`, `EventStore`, or provider contracts to the current candidate interpreter/process/operation model. Treat planner-specific intermediate structures and execution-model-specific operations as private or explicitly versioned implementation details.
12. **Rules do not imply enforcement.** Legal, organizational, or social violations can occur if physically possible. Detection, reporting, institutional response, and consequences are separate mechanics.
13. **Information is not equivalent to belief.** Receiving a message creates an observation/claim; actor belief updates are separate.
14. **Membership is dynamic.** Actors may enter, leave, be removed from, or join organizations/groups during a simulation without deleting their historical identity.
15. **Human interventions must be explicit and auditable.** Distinguish in-world interventions from direct simulation overrides.
16. **No unrestricted execution of LLM-generated Python.** Never use raw `eval`/`exec` on generated expressions or functions. Use a validated expression language, AST whitelist, sandboxed worker, or another constrained mechanism.
17. **Reproducibility matters.** Persist seeds, configuration versions, model/provider metadata, and branch ancestry when feasible.
18. **Do not store or expose private chain-of-thought.** If decisions need explainability, request and store structured decision metadata such as intent, considered options, expected effects, confidence, and cited observations.
19. **Provider execution location is explicit.** Server-managed and client-managed providers share a logical provider contract without sharing credential handling. Client-managed credentials must not be sent to the backend; server-managed credentials must not be sent to the frontend.
20. **Authoritative history is event-sourced.** `WorldEffect` is a proposed transition; `Event` is an immutable historical fact. Only accepted events applied through deterministic state-transition logic may mutate `WorldState`.
21. **Replay does not regenerate cognition.** Reconstruct recorded branches from persisted history without re-calling LLMs or other decision providers. New provider calls create new history, for example during branch continuation.
22. **Model at scenario resolution.** Do not introduce lower-level entities only to reconstruct irrelevant physical detail. Scenario-level entities may carry explicit mechanical properties and optional semantic content, while actor-relative perception, interpretation, and belief remain separate.
23. **Entity is the persistent world identity anchor.** Scenario-relevant things use stable entity identity; actors are entity-backed cognition/decision participants rather than a separate parallel identity system. `active` deactivates an entity without deleting its history.
24. **Entity types are extensible vocabulary, not domain classes.** Preserve a small built-in set of generic types (initially `Person`, `Organization`, `Group`, `Location`, `Artifact`) and allow scenarios to extend it. Do not attach domain-specific core mechanics merely because a scenario defines a new type.
25. **Resources are entity-associated quantities.** Every authoritative resource quantity belongs to an entity context. Do not create detached global resource balances or microscopic entities for fungible resource units.
26. **Primary intentions are simultaneous at turn start.** All eligible actors form primary intentions from the same start-of-turn authoritative snapshot. Never let provider iteration order leak newly generated intentions or state changes into later actors' decision contexts.
27. **Conflicts are jointly resolved.** Do not implement the scheduler as a naive `for actor/action` mutation loop or recursively resolve cyclic dependencies actor-by-actor. Detect interacting/conflicting plan components and resolve each component coherently.
28. **Reaction is bounded, not recursive cognition.** An actor may respond to already-discovered participation requests/conflicts by accepting, refusing, deferring, prioritizing, or modifying participation, but the reaction phase must not become an unbounded new primary-decision loop.
29. **Revalidate at execution time.** A scheduled action may become infeasible after earlier same-turn events. Re-check relevant preconditions/capabilities immediately before authoritative resolution and emit explicit failure/cancellation events when conditions changed.
30. **True simultaneity is representable.** Do not force arbitrary ordering where several actions require one joint resolution outcome. Support simultaneous-resolution groups when scenario mechanics require them.

## Action-system guardrails

- Preserve the actor's semantic `ActionProposal` separately from planner-specific representation when practical.
- Do not let an `ActionProposal` directly declare authoritative world effects.
- Do not assume a permanent primitive list such as `PERFORM`, `COMMUNICATE`, `OBSERVE`, or `MOVE`; these are current design candidates only.
- Do not place domain action names such as `schedule_company_all_hands`, `propose_law`, or `build_sos` in core APIs.
- Scenario-defined processes may be used by the first implementation, but their schema and discovery mechanism are still open design questions.
- Capability checks should target world objects and context (access, control, presence, authorization, technical/physical feasibility) rather than hard-coded domain action names.
- Keep planning and execution separate enough that either can be replaced independently.
- Never persist a planner's private intermediate object merely because it is convenient for v1. Persist only what is needed for replay, observability, or reproducibility, and version execution-model-specific data explicitly.
- Candidate plans should expose enough mechanical requirements for the scheduler to discover conflicts/dependencies without understanding scenario-specific narrative action names. Examples include required participants, duration/attention claims, resource claims, targets, dependencies, and relevant preconditions.
- The resolver may determine compatibility, ordering, timing, simultaneous grouping, and mechanical feasibility, but MUST NOT invent an actor's psychological preference when conflicting alternatives require that actor's choice.
- Treat cyclic plan dependencies as joint-resolution components, not recursion errors.

## Provider security guardrails

- Treat `SERVER_MANAGED` and `CLIENT_MANAGED` as distinct execution/security modes behind the same logical provider abstraction.
- Never expose a server-managed provider secret to frontend code.
- Never require a client-managed provider credential to pass through the backend. In the initial browser implementation, keep it in memory only; do not place it in `localStorage` or `sessionStorage`.
- Treat a client-returned model response as untrusted cognition output. It may produce an `ActionProposal` through the normal provider/decision path but may not directly supply authoritative world mutations.
- Do not implement an unrestricted backend URL proxy for user-selected providers. Any future server-side relay requires an explicit security design covering SSRF, egress restrictions, destination validation, redirects, response limits, timeouts, and secret storage.
- Do not silently switch providers after a failure. Fallback must be explicitly configured and provider/model changes affecting a run must be recorded for reproducibility.
- Direct client-managed provider calls may fail because of CORS or local-network/browser restrictions. Surface that clearly rather than routing through an unsafe transparent proxy.

## Event and world-state guardrails

- Do not mutate authoritative `WorldState` from actors, providers, planners, executors, API handlers, or frontend code.
- Executors/resolvers may propose `WorldEffects`; the authoritative transition layer validates them, emits accepted events, and applies those events through deterministic reducers/state-transition logic.
- Treat checkpoints and snapshots as replay optimizations, not an alternative canonical history.
- Preserve atomicity when one authoritative transition yields multiple events.
- Event sequence is deterministic replay ordering; do not assume it proves causality between simultaneous outcomes.
- Material failed attempts, refusals, provider changes, and deliberate non-actions may be events even when no reducer changes `WorldState`.
- Do not call cognition providers during ordinary replay of already-recorded history.
- Model outcomes at the scenario's chosen resolution. Do not create microscopic entities merely to reconstruct irrelevant physical detail.
- Keep authoritative entity state, represented semantic content, actor observation, interpretation, and belief as distinct layers.
- Keep `active` in authoritative `Entity` state and deactivate rather than delete entities whose identity/history remains relevant.
- Prefer an entity-backed actor component/facet over a parallel actor identity space or a deep domain inheritance hierarchy.
- Keep actor cognition state separate from ordinary entity properties even though both must be reproducible and branchable.
- Treat built-in entity types as a small semantic vocabulary. Scenario-defined types may extend them, optionally identifying a generic base type, without forcing new core classes.
- Associate every resource balance with an `entity_id`. Examples include `Company.budget` and `GardenBed.food`; access/control semantics can then be evaluated against the owning/context entity.
- Keep fungible quantities as resources. Promote a concrete object to an `Entity` only when its individual identity is relevant at the scenario's simulation resolution.

## Change methodology

- The repository is currently **pre-baseline**. `docs/DESIGN.md` is a working draft, so maintainers may still revise fundamental assumptions directly while shaping the initial architecture.
- ADRs marked `Draft` are informative and non-binding. Do not treat them as architectural constraints until their status becomes `Accepted`.
- After the first design baseline is declared, material changes to core architectural contracts should normally be proposed through a new ADR before implementation.
- Treat `docs/DESIGN.md` and accepted ADRs in `docs/adr/` as the architectural source of truth.
- Do not silently resolve a question listed as unresolved in the design. If implementation requires such a decision, propose an ADR first.
- Small implementation details that do not change public concepts, persistence semantics, simulation invariants, or provider boundaries may be decided locally.
- Keep changes small and reviewable. A coding task should implement a bounded contract rather than "the whole simulator".
- Preserve backward-readable historical data once persistence formats are introduced unless an accepted ADR explicitly allows a migration.

## Design philosophy

Prefer simple, composable mechanics that can produce complex emergent behavior. Avoid adding parameters merely because they sound realistic. Every core concept should justify its existence through a clear simulation need.

The LLM is an actor cognition component, not the physics engine, database, scheduler, or source of truth.

## Coding expectations

- Implement GRASS core in Python.
- Implement the backend/API with FastAPI while keeping GRASS core independent from FastAPI.
- Implement the frontend with React while keeping simulation-domain rules out of frontend code.
- Use REST for ordinary API operations and WebSocket for interactive simulation/session traffic in the initial web architecture.
- Favor typed interfaces and explicit schemas.
- Keep pure state-transition logic separate from I/O and LLM calls.
- Make simulation components testable with deterministic fake providers.
- Use dependency inversion at provider, planning/execution, and persistence boundaries.
- Prefer append-only event records for historical facts.
- Add tests for branch isolation, replay consistency, action validation, information provenance, and provider substitution as these modules appear.
- Do not optimize prematurely for millions of actors; preserve extension points for aggregate/collective actors and scalable schedulers.

## Scope discipline for v0.1

Implement only what is required for a small simulation of individual actors. Do not build full collective-actor or institutional decision semantics yet. Preserve extension points for them.

Do not implement sophisticated economics, psychology, law, political systems, or biological realism in core. These are scenario concerns.

## Prior art

`docs/DESIGN.md` contains a short prior-art section. It is informational only. Do not copy external project architecture, APIs, schemas, class layouts, prompts, or implementation details merely because a project is mentioned there.
