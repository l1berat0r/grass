# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for GRASS.

The first architecture baseline is **`design-0.1`**. `docs/DESIGN.md` describes the current baseline architecture; accepted ADRs preserve the rationale behind significant decisions.

After the baseline, material changes to core architectural contracts should normally be proposed through a new ADR before implementation and reflected in `docs/DESIGN.md` after acceptance.

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
- ADR-0015 — minimal perception and DecisionPoint contracts.
- ADR-0016 — minimal one-shot AT_TIME scenario-occurrence contracts.

ADR-0002 remains Draft and documents the current replaceable capability-evaluation direction; its exact default dimensions are intentionally not frozen by the baseline.

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
