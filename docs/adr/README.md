# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for GRASS.

The first architecture baseline is **`design-0.1`**. `docs/DESIGN.md` describes the baseline/core architecture; accepted ADRs preserve the rationale behind significant decisions. The local executable 0.1 milestone and its application/runtime boundaries are additionally summarized in `docs/LOCAL_0_1_RUNTIME.md`.

After the baseline, material changes to core architectural contracts should normally be proposed through a new ADR before implementation and reflected in the relevant current architecture documentation after acceptance.

## Status values

- `Draft` — under discussion; not binding.
- `Accepted` — current architectural decision.
- `Rejected` — considered and deliberately not adopted.
- `Superseded` — replaced by a later ADR.

## Current accepted architecture records

- ADR-0001 — event-sourced branching;
- ADR-0003 — ephemeral ScheduledResolution index;
- ADR-0004 — WorldDefinition, run configuration, scenario events, and GEL;
- ADR-0005 — semantic Event types and atomic transition boundary;
- ADR-0006 — authoritative SimulationState projections;
- ADR-0007 — logical time representation;
- ADR-0008 — minimal Event commit and ordering semantics;
- ADR-0009 — SimulationState projection and initial world-state contracts;
- ADR-0010 — branch history positions and reconstruction;
- ADR-0011 — minimal WorldDefinition and genesis contracts;
- ADR-0012 — minimal Plan, PlanStep, and Job contracts;
- ADR-0013 — minimal event-driven scheduler contracts;
- ADR-0014 — minimal deterministic world-resolution contracts;
- ADR-0015 — minimal perception and DecisionPoint contracts;
- ADR-0016 — minimal one-shot AT_TIME scenario-occurrence contracts;
- ADR-0017 — minimal GEL v1 language and execution contracts;
- ADR-0018 — minimal provider adapter contracts;
- ADR-0019 — local runtime and Application/Query API boundary;
- ADR-0020 — SQLite local persistence baseline;
- ADR-0021 — runnable WorldPackages and templates.

ADR-0002 remains Draft and documents the current replaceable capability-evaluation direction; its exact default dimensions are intentionally not frozen by the baseline.

## Current implementation planning

Slices 0–11 are implemented on the implementation branch. Slices 12–17 target a locally runnable GRASS 0.1: runtime orchestration, durable local persistence, runnable world composition, Application/Query APIs, CLI, and reusable templates. The post-Slice-17 sequence is intentionally left open until real runs provide evidence about actor memory, persistence/read models, observer needs, provider context/cost behavior, and whether backend/frontend should be next.

Earlier ADRs may mention future slice numbers in their deferred sections. Those references record what was deferred at the time of the ADR; `ROADMAP.md` is authoritative for current implementation sequencing and does not change the accepted semantic decisions of those ADRs.

## Template

```markdown
# ADR-NNNN: Short decision title

- Status: Draft
- Date: YYYY-MM-DD

## Context

What problem or architectural tension requires a decision?

## Decision

What is being decided?

## Consequences

What becomes easier, harder, constrained, or enabled?

## Alternatives considered

What credible alternatives were considered and why were they not selected?
```
