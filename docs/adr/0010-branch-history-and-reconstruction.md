# ADR-0010: Branch history positions and reconstruction

- Status: Accepted
- Date: 2026-09-06

## Context

ADR-0001 requires parent-linked branch ancestry with immutable shared prefixes. ADR-0005 and ADR-0006 require forks and externally visible state positions to occur only at complete committed-transition boundaries. ADR-0008 preserves origin-local Event sequences and requires child continuation not to predate its fork. ADR-0009 deliberately limits `ProjectionPosition` to one branch's originating transitions.

Slice 3 needs a concrete branch topology and ancestry-aware reconstruction contract without introducing durable storage, run configuration, genesis, or later simulation behavior.

## Decision 1: Branch topology is explicit history metadata

Branches are registered explicitly before Events may be committed to them. A root branch has no fork position. A child branch stores the exact position in its direct parent's visible history from which it continues.

```text
Branch
    branch_id
    fork_position?

fork_position.branch_id = direct parent branch
```

Branch creation changes history topology, not simulated world reality. It is canonical EventStore metadata rather than a world Event or a `SimulationState` mutation.

The initial in-memory store may contain more than one explicitly registered root. Run ownership and durable physical storage remain deferred.

## Decision 2: HistoryPosition is ancestry-aware

`HistoryPosition` is distinct from branch-origin `ProjectionPosition`:

```text
HistoryPosition
    branch_id
    transition_ref?
```

`branch_id` identifies the branch whose visible history is being viewed. `transition_ref` identifies the last visible complete transition and may originate on that branch or an ancestor.

A non-empty position means state **after** the referenced complete transition. It can never identify an Event inside a transition. Logical time and Event sequence are derived from canonical history and are not duplicated in this value.

An absent transition reference denotes the empty position before a root branch's first transition. Child forks require a non-empty position.

## Decision 3: Fork points must be visible through the parent

Creating a child requires an explicit `HistoryPosition` on an existing parent branch. The referenced transition must exist and be visible in that parent's ancestry at creation time.

A child may fork at a transition that originated on any ancestor but is visible through its direct parent. A transition that exists globally but is not visible from that parent is invalid as its fork point.

Fork creation captures that exact immutable prefix. Later parent commits do not become visible to the child.

## Decision 4: Origin and visible history remain distinct

Origin-history reads return only transitions committed directly to the requested branch. Ancestry-visible reads return the immutable root-to-position sequence of original `CommittedTransition` values.

Inherited Events and transitions are never copied, rewritten, or renumbered. Their original Event IDs, branch IDs, origin-local sequences, logical times, transition IDs, and provenance remain unchanged.

Child-origin Event sequences begin at `1`. The first child-origin transition must have logical time greater than or equal to the fork transition's logical time. Later local transitions retain the existing nondecreasing-time rule.

## Decision 5: Reconstruction composes origin-local projection

Ancestry replay traverses original committed transitions from the root prefix through the target position. Existing strict origin-local projection remains unchanged.

At each branch-origin boundary, replay carries the immutable world, execution, and cognition projections into a new `SimulationState` whose `ProjectionPosition` is empty for the next origin branch. It then applies that branch's local transitions normally.

The returned state's `ProjectionPosition` continues to describe only transitions originating on the viewed branch. The requested `HistoryPosition` remains the ancestry-aware coordinate.

## Decision 6: Checkpoints are optional trusted derived inputs

Slice 3 defines an immutable checkpoint containing a `HistoryPosition` and complete `SimulationState`, plus a loader protocol that may return an applicable checkpoint for a requested target.

Replay validates that checkpoint history is a prefix of target-visible canonical history and that its branch-origin projection metadata is coherent. It applies all subsequent canonical transitions normally.

Checkpoint state is trusted derived infrastructure, not a new authority source. Replay without a checkpoint remains mandatory and canonical. Checkpoint storage, selection strategy, cadence, serialization, integrity hashes, schema migration, and corruption recovery are deferred.

## Consequences

### Positive

- Shared prefixes remain physically and semantically immutable.
- Parent, child, and sibling continuations are isolated.
- Forks cannot expose partial atomic transitions.
- Origin-local Event sequence meaning remains unchanged.
- Nested ancestry and inherited fork targets are reconstructable.
- Checkpoints can accelerate replay without becoming canonical history.

### Costs

- Branches must be registered before commit.
- Unknown and known-empty branches are now distinct.
- Ancestry traversal must validate visibility rather than global transition existence alone.
- `SimulationState` and its ancestry-aware `HistoryPosition` must remain conceptually paired during reconstruction.

## Deferred details

- durable database schemas and branch-prefix physical representation;
- branch deletion, merge, rebase, rename, and history rewriting;
- symbolic concurrent “fork current head” operations;
- Event-level and partial-transition forks;
- checkpoint persistence, save APIs, cadence, hashes, migration, and untrusted checkpoint validation;
- branch comparison and analysis APIs;
- run ownership, WorldDefinition, SimulationRunConfig, and genesis;
- cause-reference visibility and causal-graph validation;
- pagination, subscriptions, retention, and distributed/concurrent persistent writers.
