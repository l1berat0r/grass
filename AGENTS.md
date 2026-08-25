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
7. **`Actor` is the core abstraction.** Initial implementation may support only `IndividualActor`, but APIs and persistence schemas must not assume that every actor is an individual human.
8. **Decision providers are replaceable.** OpenAI, Ollama, local models, future providers, humans, scripts, and deterministic strategies must use the same conceptual decision interface.
9. **Model providers and decision policy are separate concepts.** Do not couple an actor directly to a specific LLM SDK.
10. **Actions are open at the intention level and constrained at the mechanics level.** Actors may propose novel intentions. The engine must interpret, validate, decompose, or reject them before execution.
11. **Rules do not imply enforcement.** Legal, organizational, or social violations can occur if physically possible. Detection, reporting, institutional response, and consequences are separate mechanics.
12. **Information is not equivalent to belief.** Receiving a message creates an observation/claim; actor belief updates are separate.
13. **Membership is dynamic.** Actors may enter, leave, be removed from, or join organizations/groups during a simulation without deleting their historical identity.
14. **Human interventions must be explicit and auditable.** Distinguish in-world interventions from direct simulation overrides.
15. **No unrestricted execution of LLM-generated Python.** Never use raw `eval`/`exec` on generated expressions or functions. Use a validated expression language, AST whitelist, sandboxed worker, or another constrained mechanism.
16. **Reproducibility matters.** Persist seeds, configuration versions, model/provider metadata, and branch ancestry when feasible.
17. **Do not store or expose private chain-of-thought.** If decisions need explainability, request and store structured decision metadata such as intent, considered options, expected effects, confidence, and cited observations.

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

- Python is the expected initial implementation language unless a later ADR changes this.
- Favor typed interfaces and explicit schemas.
- Keep pure state-transition logic separate from I/O and LLM calls.
- Make simulation components testable with deterministic fake providers.
- Use dependency inversion at provider and persistence boundaries.
- Prefer append-only event records for historical facts.
- Add tests for branch isolation, replay consistency, action validation, information provenance, and provider substitution as these modules appear.
- Do not optimize prematurely for millions of actors; preserve extension points for aggregate/collective actors and scalable schedulers.

## Scope discipline for v0.1

Implement only what is required for a small simulation of individual actors. Do not build full collective-actor or institutional decision semantics yet. Preserve extension points for them.

Do not implement sophisticated economics, psychology, law, political systems, or biological realism in core. These are scenario concerns.

## Prior art

`docs/DESIGN.md` contains a short prior-art section. It is informational only. Do not copy external project architecture, APIs, schemas, class layouts, prompts, or implementation details merely because a project is mentioned there.
