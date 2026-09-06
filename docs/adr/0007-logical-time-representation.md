# ADR-0007: Logical time representation

- Status: Accepted
- Date: 2026-09-06

## Context

The `design-0.1` baseline requires event-driven logical time that is exact, comparable, reproducible, independent from wall-clock time, and suitable for Event ordering and future scheduler projections. Slice 0 is the first implementation point where a concrete `LogicalTime` value object is required.

Leaving its representation to incidental implementation would risk freezing wall-clock, timezone, floating-point, or precision semantics into persisted history without an explicit architecture decision.

## Decision

`LogicalTime` is represented semantically as a non-negative integer number of **nanoseconds from a run-local logical origin**.

Conceptually:

```text
LogicalTime
    nanoseconds_from_origin: integer >= 0
```

The logical origin belongs to one simulation run. `LogicalTime(0)` means that run's configured initial logical origin, not Unix epoch, UTC midnight, process start time, or any other external clock reference.

### No wall-clock semantics

Core `LogicalTime` has no inherent:

- timezone;
- UTC/local-time interpretation;
- calendar/date representation;
- operating-system clock dependency;
- implicit `now()`;
- daylight-saving semantics.

A scenario/UI may later map logical positions to domain/calendar representations through explicit adapters/configuration, but that mapping is outside the core `LogicalTime` contract.

### Exact integer representation

Use an integer rather than floating point so comparisons, serialization, replay, and scheduler boundaries do not depend on floating-point rounding.

Nanoseconds define representational precision. They **do not create a simulation tick**. The scheduler remains event-driven and may jump directly between arbitrary material logical times without iterating through intermediate nanoseconds.

For example:

```text
LogicalTime(0)
    -> next material event eight hours later
LogicalTime(28_800_000_000_000)
```

No intermediate times are simulated merely because the representation uses nanoseconds.

### Slice 0 contract

The initial `LogicalTime` value object supports:

- validation of a non-negative integer value;
- equality;
- total ordering;
- hashing/immutability suitable for value-object use.

Slice 0 must not introduce:

- implicit current-time factories;
- mutable clocks;
- scheduler behavior;
- sequence/tie-break semantics;
- calendar conversion;
- `Duration` arithmetic merely for convenience.

A future `Duration` value object and arithmetic API may be introduced when an implementation slice genuinely requires them, while preserving this representation.

## Consequences

### Positive

- deterministic exact comparison and persistence;
- no floating-point drift;
- no accidental coupling to operating-system/calendar/timezone semantics;
- sufficiently fine representation for diverse scenarios without forcing fine-grained simulation execution;
- simple future serialization as an integer scalar.

### Costs

- user-facing calendar/date semantics require explicit conversion/mapping when scenarios need them;
- human-readable durations/timestamps need formatting helpers outside the core value object's minimal contract;
- nanosecond values can become numerically large, although Python's arbitrary-precision integers make this harmless for the initial implementation.

## Alternatives considered

### Floating-point seconds

Rejected because persisted/replayed comparisons and arithmetic can inherit rounding artifacts.

### `datetime` / UTC timestamps

Rejected as the core representation because many simulations do not have Earth-calendar semantics and logical time must remain independent from timezone and host-clock concerns.

### Generic integer ticks

Rejected because the word `tick` tends to imply a scenario-wide fixed simulation step. GRASS is explicitly event-driven. A fixed nanosecond unit provides an exact scalar coordinate without defining execution cadence.

### Arbitrary rational/decimal time

Deferred as unnecessary complexity for v0.1. Integer nanoseconds provide exact, simple ordering with ample precision for the intended scenarios.
