# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for GRASS.

During the current pre-baseline design phase, ADRs may be created as **Draft** records to capture candidate architectural decisions, but the core design may still be edited directly while the architecture is being shaped. A draft ADR is not binding.

After the first design baseline is declared, material changes to core architectural contracts should normally be introduced through a new ADR and reflected in `docs/DESIGN.md` after acceptance.

## Status values

- `Draft` — under discussion; not binding.
- `Accepted` — current architectural decision.
- `Rejected` — considered and deliberately not adopted.
- `Superseded` — replaced by a later ADR.

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
