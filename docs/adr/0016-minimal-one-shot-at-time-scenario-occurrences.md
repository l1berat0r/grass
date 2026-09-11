# ADR-0016: Minimal one-shot AT_TIME scenario occurrences

- Status: Accepted
- Date: 2026-09-11

## Context

Slice 9 must exercise a genuine scenario event while preserving the accepted
WorldDefinition, scheduler, resolution, replay, and branch boundaries. The rich
acceptance walkthrough uses RANDOM_TIME, but random streams, sampling, recurrence,
GEL, and the complete engine loop remain later work.

The executable slice needs only one-shot deterministic occurrences at exact
LogicalTime values. It must also record occurrence consumption in canonical
history so rebuilding the disposable scheduler index cannot fire one twice.

## Decision 1: Minimal identity

`ScenarioEventRuleId` is opaque and identifies a rule within one exact immutable
WorldDefinition version. Stable references are:

```text
ScenarioEventRuleRef
    world_definition_ref
    rule_id

ScenarioOccurrenceRef
    scenario_event_rule_ref
```

One AT_TIME rule has exactly one occurrence, so Slice 9 adds no occurrence index,
runtime occurrence-ID allocation, process hierarchy, branch identity, or time to
the occurrence reference. Rule and occurrence references are nominally distinct.
The same occurrence may resolve independently on branches forked before it.

## Decision 2: WorldDefinition schema version 2

Schema version 2 adds exactly one required root field to version 1:

```text
scenario_event_rules[]
    rule_id
    trigger
        kind = AT_TIME
        logical_time
```

The collection may be empty. Rule IDs are unique within the WorldDefinition
version. Logical time is exact and cannot precede initial-conditions logical time.
There is no enabled flag, metadata, mechanic binding, recurrence, condition,
duration, probability distribution, or sampling configuration.

Version-1 documents remain readable with their exact original field set and an
empty runtime rule collection. Version-1 documents reject version-2 fields.
Genesis records schema version 2 in `SimulationInitialized`, but rules remain
declarations and do not become genesis Events.

## Decision 3: ScenarioOccurrenceResolved Event

Resolving an occurrence emits one strict version-1 non-mutating Event:

```text
ScenarioOccurrenceResolved
    occurrence_ref
```

Its Event envelope supplies actual logical time, transition identity, branch,
Event identity, and provenance. It means the one-shot occurrence was consumed by
an accepted resolution. It is emitted even when no WorldEffects are proposed and
commits atomically with all effect-derived Events. Provider failure or invalid
output commits nothing and leaves the occurrence unresolved.

Preparation and history-derived scheduling reject a second resolution of the same
occurrence in one branch-visible history. Projection validates duplicate writes
within one transition. Cross-transition occurrence lifecycle validation uses full
branch-visible canonical history rather than adding scheduler or scenario cache
data to SimulationState.

## Decision 4: History-aware occurrence scheduling

A separate pure projector receives the exact WorldDefinition, explicit current
LogicalTime, and complete branch-visible committed history. It verifies the
history's `SimulationInitialized` definition reference, derives resolved
occurrences from `ScenarioOccurrenceResolved`, and emits one
`ScheduledResolution[ScenarioOccurrenceRef]` with kind `SCENARIO_EVENT` for each
unresolved rule.

An unresolved occurrence before current time is an integrity error. A candidate
at current time is valid. ScheduledResolution and all index details remain
ephemeral and unpersisted. The existing Job-oriented `ScheduleProjector` protocol
is unchanged. Checkpoint-assisted state replay does not replace full visible
history when rebuilding scenario scheduling.

## Decision 5: Separate deterministic resolution boundary

Scenario occurrences do not use ADR-0014's Job-oriented request. Slice 9 adds:

```text
ScenarioOccurrenceResolutionProvider.resolve(request)
    -> ScenarioOccurrenceResolutionProposal
```

One request identifies one exact occurrence, rule, due candidate, base
HistoryPosition, target LogicalTime, elapsed LogicalDuration, and immutable
SimulationState. A proposal contains only the existing closed WorldEffect union.
The provider creates no Events, identities, provenance, state replacement, or
commits.

The trusted preparation boundary reads the exact ancestry-visible history through
a branch-history reader and validates definition/rule identity, due time, prior
consumption, effect vocabulary, references, complete atomic
projection, and exact caller-supplied Event IDs. It creates WORLD_RESOLVER
provenance from trusted inputs and returns a prepared transition with expected-head
protection. The Job resolution public contracts remain unchanged.

## Decision 6: Same-time limits

Slice 9 resolves one occurrence per scenario request and exercises one interacting
same-time Job conflict component. It does not split mixed Job/occurrence conflict
components or sequentially publish independent same-time components as if append
order had world semantics. The acceptance fixture avoids those unsupported cases.

## Decision 7: Replay and branching

Ordinary replay recognizes the recorded occurrence Event and applies effect Events
without invoking scheduling or resolution. A fork before occurrence resolution may
resolve it independently. A fork after resolution inherits consumption and omits
the occurrence on scheduler rebuild.

## Consequences

- Slice 9 has genuine scenario-event scheduling and resolution without making the
  scheduler authoritative.
- Version-1 WorldDefinition history remains readable.
- Scenario and Job resolution share WorldEffect materialization but not request
  subject semantics.
- Full visible history is required when rebuilding scenario occurrence scheduling.

## Deferred details

- RANDOM_TIME, AFTER_DURATION, conditions, recurrence, distributions, sampling,
  random streams, and seeds;
- GEL and general scenario mechanics/bindings;
- multiple occurrences per rule and independent occurrence identity allocation;
- mixed-source conflict resolution and multiple-independent-component publication;
- Commitments, ActionProposal, Plan readiness, automatic Job creation, automatic
  perception, capability evaluation, generative resolution, and a full engine loop;
- durable persistence, APIs, frontend, provider adapters, and production identity
  generation.
