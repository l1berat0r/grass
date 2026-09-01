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
5. **Provenance is mandatory.** Events and interventions must record their origin.
6. **Do not hard-code scenario domains in core.** Corporate, governmental, political, survival, or other domain mechanics belong in scenario definitions/plugins/rules/schemas rather than core abstractions.
7. **`Entity` is the persistent world identity anchor; actors are entity-backed.**
8. **Decision providers are replaceable.** OpenAI, Ollama, local models, humans, scripts, deterministic strategies, and future providers share the conceptual decision boundary.
9. **Model providers and decision policy are separate concepts.**
10. **Actions are open at the intention level and constrained at the mechanics level.**
11. **Action planning and world resolution are replaceable boundaries.** Do not couple authoritative state/history or provider contracts to one planner or resolver implementation.
12. **Rules do not imply enforcement.** Legality, authorization, possibility, detection, and consequence are distinct.
13. **Information is not equivalent to belief.**
14. **Membership and relation state are dynamic; historical identity is preserved.**
15. **Human interventions must be explicit and auditable.**
16. **No unrestricted execution of LLM-generated Python.**
17. **Reproducibility matters.** Persist seeds, configuration versions, provider/model metadata, resolution mode, and branch ancestry when feasible.
18. **Do not store or expose private chain-of-thought.** Use structured decision metadata instead.
19. **Provider execution location is explicit.** Server-managed and client-managed provider credentials follow distinct security boundaries.
20. **Authoritative history is event-sourced.** `WorldEffect` is a candidate transition; `Event` is an immutable historical fact. Only accepted events applied through deterministic transition logic mutate projected `WorldState`.
21. **Replay does not regenerate cognition or world resolution.** Reconstruct recorded branches from persisted history; new provider/resolver calls create new history.
22. **Model at scenario resolution.** Do not introduce microscopic entities merely to reconstruct irrelevant physical detail.
23. **Entity deactivation preserves identity/history.**
24. **Entity types are extensible vocabulary, not domain classes.** Initial generic vocabulary includes `Person`, `Organization`, `Group`, `Location`, `Artifact`, and `Commitment`.
25. **Resources are entity-associated and scenario-defined.**
26. **Primary intentions are simultaneous at turn start.** All eligible actors decide from the same authoritative start snapshot.
27. **Conflicts are jointly resolved.** Do not use a naive sequential mutation loop or recursive actor-by-actor conflict handling.
28. **Reaction is bounded, not recursive cognition.**
29. **Revalidate at execution time.** Earlier same-turn events may invalidate later attempts.
30. **True simultaneity is representable.**
31. **World resolution is replaceable, committing reality is not.** Deterministic or generative resolvers propose outcomes; only the authoritative transition layer commits events/state.
32. **Resolution mode is explicit experimental configuration.** Initial identifiers are `DETERMINISTIC` and `GENERATIVE`; UI may label the latter `Generative / LLM Crazy`.
33. **Generative resolution is semantically permissive, not structurally privileged.** It may invent surprising outcomes but cannot bypass state/event schemas, identity/reference validity, event sourcing, atomicity, or branch isolation.
34. **Blueprints are hypotheses, not feasibility certificates.** Feasibility is contextual and discovered through concrete `Job` execution.
35. **One blueprint = one primitive; one job = one blueprint execution.** Multi-primitive composition belongs to `Plan`.

## Action-system guardrails

- Model v0.1 `ActionProposal` as a discriminated union: common envelope (`proposal_id`, `actor_id`, `primitive`, `intent_description`, optional `content`, optional `time_budget`, optional `job_id`) plus typed primitive-specific payload.
- Keep `intent_description` separate from `content`; neither declares authoritative outcome.
- Treat `time_budget` as intended/requested actor time, never guaranteed duration.
- Treat `job_id` as continuation of an existing execution.
- Do not put generic `targets[]` in the common proposal envelope; use semantic references within each primitive payload.
- Support common world references for concrete `ENTITY`, `RELATION`, or `BLUEPRINT` identities and unresolved semantic descriptions for planner resolution against perceived world.
- Keep calculated resource claims, required participants, dependencies, resolved preconditions, completion, and world deltas out of `ActionProposal`.
- Current v0.1 actor-facing primitives are `CREATE`, `MODIFY`, `RELATE`, `TRANSFER`, `MOVE`, `COMMUNICATE`, `OBSERVE`, `WAIT`, and `REST`.
- Do not introduce `PERFORM` for ordinary work; use `CREATE` or `MODIFY`, with `Job` continuation for multi-turn execution.
- Do not introduce `DESTROY`; destructive intent uses `MODIFY` and deactivation/remnant effects at scenario resolution.
- Do not introduce `SCHEDULE`; future social coordination is represented by creating a `Commitment` entity and relations to its parties.
- Do not introduce `GRANT_ACCESS`; access may be a scenario-defined resource handled through `TRANSFER` with delegation/sharing semantics.
- Use `RELATE` to establish scenario-defined relations and `MODIFY` to change/deactivate existing relations.
- Resource types/granularity belong to the scenario. `TRANSFER` modes may include ordinary transfer, `GATHER`, `CONSUME`, and scenario-defined delegation/sharing.
- Keep every resource operation anchored to entity-associated resource state.
- A blueprint is a process hypothesis/recipe, not proof of feasibility. The same blueprint may succeed in one context and fail in another.
- Do not require global blueprint `EXECUTABLE`/`REJECTED` feasibility status before an attempt.
- Blueprints may carry semantic `assumptions`; do not prematurely convert all assumptions into an executable condition DSL.
- Keep blueprint lifecycle orthogonal to feasibility: active/inactive plus immutable versioning is sufficient initially.
- Bind each blueprint to exactly one primitive. Do not put steps, nested actions, workflows, or multiple primitives in a blueprint.
- Compose multi-primitive intentions in `Plan`; each plan step may select one primitive + blueprint and declare dependencies.
- Scenario-defined and actor-created/LLM-generated blueprints may both be attempted. Actor-created blueprints are untrusted hypotheses and cannot bypass resource/capability/transition boundaries.
- Multi-party blueprint execution never implies automatic participation; consent/participation is resolved through bounded reaction and scheduling.
- Always create a `Job` for blueprint-backed execution, even when it completes in the same atomic transition.
- Use initial job statuses `PENDING`, `ACTIVE`, `PAUSED`, `COMPLETED`, `FAILED`, and `CANCELLED`; the last three are terminal.
- Do not assume universal percentage completion. Support at least simple `LINEAR` and `BINARY` structured progress models in v0.1.
- Allow world resolution to invalidate blueprint assumptions or discover additional constraints/resources during execution.
- One `Job` executes one blueprint and therefore one primitive; retries after terminal failure/cancellation create a new job.
- Do not confuse blueprint scope with effect scope: one job resolution may produce multiple `WorldEffects` and events atomically.
- Keep responsibility split explicit: `Plan` composes steps, `Blueprint` describes one primitive attempt, `Job` tracks one concrete execution, and `WorldEffects` describe candidate authoritative changes.
- Capability checks should target world objects/context rather than hard-coded domain action names.
- Keep planning and world resolution independently replaceable.
- Never persist private planner intermediates merely for convenience; persist only what replay/observability/reproducibility requires and version implementation-specific data.
- Candidate plans should expose enough mechanical requirements for scheduling/conflict discovery without embedding narrative domain action semantics.
- Resolver may determine compatibility, ordering, timing, grouping, and mechanics, but MUST NOT invent an actor's psychological preference when the actor must choose.
- Treat cyclic plan dependencies as joint-resolution components, not recursion errors.

## World-resolution guardrails

- Keep `WorldResolutionProvider` (exact interface/name provisional) behind a narrow boundary so deterministic and generative resolution can be replaced without changing event/state authority.
- `DETERMINISTIC` derives outcomes from explicit scenario mechanics/current state.
- `GENERATIVE` may use an LLM/model as a creative adjudicator and intentionally sacrifice strict realism/repeatability.
- Never let a world-resolution model return an authoritative replacement `WorldState`; it proposes structured effects/outcomes that pass through validation/events/reducers.
- Treat generative resolver output as untrusted structured input.
- Structural invariants are mode-independent: preserve event sourcing, append-only history, branch isolation, reducer authority, identity/reference integrity, schema validation, and atomicity.
- Replay uses recorded events only. Re-invoking a resolver from the same checkpoint is regeneration/branch continuation and may produce different history.
- Persist resolution mode and relevant resolver/model/version metadata as experimental/provenance data.
- Do not introduce hybrid deterministic-to-generative fallback implicitly; any future hybrid policy must be explicit, auditable, and recorded.

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
- Treat built-in entity types as a small semantic vocabulary including `Commitment`. Scenario-defined types may extend them, optionally identifying a generic base type, without forcing new core classes.
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

An LLM may serve as actor cognition or, in `GENERATIVE` mode, as an untrusted world-adjudication component. It is never the database, authoritative event/state transition layer, or source of committed truth.

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
