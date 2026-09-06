# ADR-0008: Minimal Event commit and ordering semantics

- Status: Accepted
- Date: 2026-09-06

## Context

ADR-0001 establishes event-sourced, branchable history. ADR-0005 defines the semantic Event envelope and `transition_id` as the atomic authoritative commit boundary. ADR-0006 requires externally visible replay/fork positions to correspond to complete committed transitions, and ADR-0007 defines `LogicalTime`.

The first EventStore implementation now needs several lower-level rules that affect durable history semantics rather than only local code structure:

- how branch-local `sequence` values are assigned;
- the scope of transition identity;
- how logical time relates to an atomic transition;
- whether empty transitions are valid history;
- what payload representation may be used before concrete semantic Event payload schemas exist.

These rules must be explicit before later replay, projections, branch ancestry, persistence adapters, or APIs depend on accidental implementation behavior.

This ADR defines the minimum persistent-history semantics only. It does not standardize Python class names, a database schema, serialization format, EventStore protocol, ID generation strategy, or concrete domain Event payloads.

## Decision

### 1. Event sequence is branch-local and contiguous

For Events originating on a branch, the EventStore assigns monotonically increasing contiguous `sequence` values beginning at `1`.

Within one accepted transition, Events receive sequence values in their submitted order.

Conceptually:

```text
branch A
    T1: E1 sequence=1
        E2 sequence=2
    T2: E3 sequence=3

branch B
    T9: E4 sequence=1
```

A rejected transition consumes no sequence values.

`sequence` is technical deterministic replay/storage order only. It does not establish causal truth, priority, or semantic ordering among Events that share a logical time.

Future branch ancestry/shared-prefix traversal must preserve the original Events and their original branch-local sequences. Inherited parent Events are not renumbered into a synthetic child-branch sequence.

### 2. Transition identity is branch-qualified and single-use

The durable identity of a transition is the pair:

```text
TransitionRef(branch_id, transition_id)
```

A given `TransitionRef` may be committed at most once.

The same raw `TransitionId` value may be used on another branch because `transition_id` is not defined as globally unique across the simulation history.

A repeated commit attempt using an already committed `TransitionRef` fails. The EventStore must not silently interpret such a call as an idempotent retry.

Request/API idempotency, retry tokens, or orchestration-level idempotency keys are separate concerns and remain deferred.

### 3. One authoritative transition has exactly one LogicalTime

An atomic transition has one `LogicalTime`, and every Event committed as part of that transition carries that same value.

The transition-level time is therefore authoritative for the whole Event batch; individual candidate Event records must not independently select different logical times within one transition.

Committed transition times must be nondecreasing among transitions originating on the same branch.

Valid:

```text
10
10
10
15
20
```

Invalid:

```text
10
20
15
```

Equal logical times are explicitly valid. Their technical append/sequence order does not by itself imply causality between the transitions or their Events.

Until branch ancestry exists, the minimal EventStore enforces only branch-local nondecreasing time. A future branch implementation must additionally ensure that child continuation does not commit before the selected fork position's logical time.

### 4. Empty authoritative transitions are invalid

A transition must contain at least one Event.

An empty transition would create an authoritative commit boundary without recording any historical fact and would complicate replay/fork semantics without providing useful information.

Rejecting an empty transition must not consume:

- its `TransitionRef`;
- Event sequence values;
- Event IDs;
- any other EventStore state.

If a semantically meaningful no-op or occurrence must be recorded in the future, it must be represented by an explicit semantic Event rather than an empty transition.

### 5. Event IDs remain globally unique

ADR-0005 defines `event_id` as globally unique opaque Event identity. The EventStore therefore rejects reuse of an Event ID anywhere in the history it manages, including:

- duplicate Event IDs inside one candidate transition;
- reuse in a later transition on the same branch;
- reuse on another branch.

ID generation remains outside this ADR. The core must not infer ordering, timestamps, branch identity, or scenario semantics from Event ID representation.

### 6. Commit validation and publication are atomic

Before making a transition visible, the EventStore validates all structural commit invariants needed by this ADR and constructs the complete immutable committed transition.

The publication boundary is all-or-nothing:

```text
validate complete candidate
    -> allocate branch-local sequences
    -> construct complete committed Events
    -> publish complete transition atomically
```

If validation or construction fails, no part of the candidate transition becomes visible and no sequence or identity is consumed.

Readers must observe either the state before the transition or the complete committed transition, never a partially published Event prefix.

This ADR concerns structural Event-history validation only. World, scenario, reducer, capability, resolver, and other domain validation remain outside the EventStore boundary.

### 7. Read results are immutable history snapshots

An EventStore read of committed transitions must not expose mutable internal storage whose later mutation could rewrite history.

A previously returned read snapshot remains semantically unchanged when later transitions are committed.

The exact collection type, pagination model, cursor API, subscription model, and database transaction mechanism remain implementation choices.

### 8. Slice-1 payloads use open, immutable structured data

Before concrete semantic Event payload schemas are introduced, an Event is identified by:

- a non-empty open `event_type` token;
- a positive integer `event_version`;
- a recursively immutable structured mapping payload.

The initial structured payload value domain may contain JSON-like deterministic data:

```text
string
integer
finite floating-point number
boolean
null
mapping<string, value>
sequence<value>
```

Candidate input must be copied/frozen deeply enough that mutating caller-owned input after commit cannot alter committed history.

This representation does **not** define the final serialization format and does not authorize arbitrary opaque objects in Event payloads.

Concrete payload types such as `EntityCreated`, `ResourceChanged`, `PlanCreated`, or `ObservationCreated`, along with their validation/projection contracts, remain deferred until the corresponding implementation slices.

Do not introduce an Event registry, payload registry, upcasting framework, or generic plugin payload mechanism merely to implement this minimal contract.

### 9. Cause references remain explicit and syntactic

A cause reference is an explicit immutable reference supplied as part of Event history. The EventStore does not infer causality from adjacency, `sequence`, or equal/different logical times.

At this stage cause references are structurally validated only. Referential existence rules, causal graph constraints, and branch-visible cause validation remain deferred until the relevant history/branch semantics require them.

### 10. Committed transitions are complete non-empty Event groups

A committed transition represents the complete immutable Event group for one atomic authoritative commit.

Branch identity, transition identity, and logical time are necessarily identical across every Event in the group.

Implementations should avoid creating independent conflicting sources for these values. They may derive transition-level accessors from the non-empty Event collection or otherwise guarantee consistency constructionally.

This ADR does not require a particular `CommittedTransition` DTO shape.

## Invariants

```text
Event history is append-only
Event IDs are globally unique
Transition identity is (branch_id, transition_id)
A TransitionRef is single-use
A transition contains at least one Event
One transition has exactly one LogicalTime
All Events in a transition share branch_id, transition_id, and logical_time
Branch-origin Event sequences begin at 1 and are contiguous
Rejected commits consume no sequence or identity state
Branch-local transition time is nondecreasing
Equal logical times are valid
sequence does not imply causality
commit publication is atomic
caller mutation cannot alter committed Event payload/provenance history
EventStore performs structural history validation, not world semantics
```

## Consequences

### Positive

- Replay has an explicit deterministic branch-local append order.
- Failed commit attempts cannot create gaps or hidden history positions.
- Atomic transitions have one coherent temporal coordinate.
- EventStore behavior is deterministic without inventing causal semantics.
- Branch-qualified transitions avoid prematurely requiring global transition IDs.
- Payload immutability protects event-sourced history from aliasing/mutation bugs.
- Concrete semantic Event payloads can be introduced incrementally in later slices without requiring a premature registry framework.

### Costs and constraints

- EventStore commit operations need atomic synchronization/transaction semantics when concurrent writers exist.
- A future persistent database adapter must preserve these invariants transactionally.
- Retries cannot simply resubmit the same committed TransitionRef; an explicit orchestration idempotency mechanism will be needed where retry-safe external APIs are required.
- Future branch traversal must preserve original branch-local Event sequences rather than flattening/renumbering shared ancestry.

## Alternatives considered

### Globally increasing Event sequence

Rejected because branch histories are independent continuations and a global counter would couple unrelated branches, complicate concurrency, and imply a cross-branch ordering with no simulation meaning.

### Sequence allocated before validation

Rejected because failed commits would consume numbers and make sequence reflect failed implementation attempts rather than accepted history.

### Globally unique transition_id

Not required. `TransitionRef(branch_id, transition_id)` already provides unambiguous identity without freezing a global transition-ID generation policy.

### Idempotent duplicate TransitionRef commit

Rejected for the core EventStore because equality of retry intent/payload cannot be safely inferred from identity alone. External idempotency should be explicit at an orchestration/API boundary.

### Event-specific logical time inside one transition

Rejected because `transition_id` is the atomic authoritative state boundary. Allowing several logical times inside one atomic transition would make its externally visible state position temporally ambiguous.

### Empty transitions

Rejected because they create history/fork positions without historical facts. Meaningful no-op occurrences should use explicit Events.

### Concrete payload registry in Slice 1

Rejected as premature. Concrete semantic payload contracts should appear when their corresponding projection/domain slices are implemented.

### Arbitrary `dict[str, Any]` payload

Rejected because mutable or opaque runtime objects could make committed history nondeterministic, nonportable, or retrospectively mutable.
