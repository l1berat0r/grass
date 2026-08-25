# ADR-0001: Event-sourced, branchable simulation history

- Status: Draft
- Date: 2026-08-25

## Context

GRASS is intended not only to run simulations but also to explain and compare them. The operator must be able to inspect the history of actors and information, identify interventions, replay deterministic runs, fork a past state, change a decision or condition, and continue an alternative timeline.

A mutable database containing only the latest state would make historical inspection, causality/provenance analysis, replay, and counterfactual branching much harder and would encourage hidden state changes.

## Decision

The canonical simulation history is event-sourced and branch-aware.

1. Every material authoritative state change MUST be represented by one or more immutable events.
2. Events MUST identify their simulation branch and logical time and MUST carry provenance sufficient to distinguish actor decisions, world mechanics, scenario events, institutions, human interventions, and explicit overrides.
3. A branch references its parent branch and a fork point in the parent's history. History before the fork is shared conceptually and MUST NOT be rewritten by descendants.
4. Events after a fork belong to the child branch and MUST NOT mutate the parent branch.
5. Checkpoints/snapshots MAY be stored to accelerate restoration, but they are an optimization rather than the canonical historical record.
6. Restoring a branch state MUST be conceptually equivalent to loading an applicable checkpoint and applying the subsequent branch-visible events in order.
7. Derived indexes, caches, metrics, and summaries MAY be rebuilt and do not themselves need to be canonical events when they do not alter simulated reality.
8. Deterministic tests MUST verify replay consistency and branch isolation.

The exact storage technology, checkpoint cadence, event serialization format, and physical representation of shared branch history remain separate decisions.

## Consequences

### Positive

- Branching and counterfactual experiments are native rather than retrofitted.
- Operator interventions and overrides remain auditable.
- Actor and information timelines can be reconstructed.
- Deterministic replay becomes testable.
- Simulation analysis can cite concrete historical events.

### Costs

- Event schemas require versioning discipline.
- State restoration and migrations are more complex than simple mutable-row persistence.
- Event payloads must avoid accidentally depending on transient implementation details.
- Large histories will require indexing, checkpointing, and retention/performance strategies.

## Alternatives considered

### Mutable current-state database plus audit log

Rejected as the canonical model because an audit log can diverge from actual mutations and does not guarantee replayable state transitions or clean branch semantics.

### Full world snapshot after every turn

Rejected as the canonical model because it is storage-heavy and obscures the semantic history of what changed and why. Snapshots remain useful as checkpoints.

### Copy the complete history/state when forking

Rejected as the conceptual model because it duplicates immutable history and weakens explicit ancestry. Implementations may materialize data for performance, but branch semantics remain parent + fork point + independent continuation.
