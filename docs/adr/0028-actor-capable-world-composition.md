# ADR-0028: Actor-capable world composition, scenario reactions, and perception

- Status: Draft
- Date: 2026-10-11

## Context

Slice 18 must make ordinary WorldPackages actor-capable without creating a second runtime path or weakening the existing event-sourced authority, replay, branching, scheduler, world-resolution, cognition, and provider contracts.

The current architecture already fixes several relevant boundaries:

- actors are entity-backed participants rather than a separate world-state identity system;
- `PlanStep` has exactly one primitive from the closed v0.1 set, including `OBSERVE` and `COMMUNICATE`;
- Jobs are the executable form of started PlanSteps;
- `WorldEffect` is a closed candidate algebra for authoritative world/execution consequences and is distinct from committed Events;
- `Observation` is actor-relative persistent cognition with stable identity, content, provenance, and logical time;
- `DecisionTriggerPolicy` decides whether one Observation creates a DecisionPoint;
- `ScheduledResolution` is ephemeral and rebuildable from authoritative state/history and scenario mechanics;
- ordinary replay must never regenerate historical perception, cognition, world resolution, randomness, or provider output;
- diagnostics must later explain accepted behavior from existing semantic identities, provenance, causation, correlation, and recorded domain facts rather than from a parallel diagnostics authority.

Slice 18 also needs practical authoring rules for initial actors and reusable templates, runtime actor creation, active and passive perception, scenario-defined reactions to committed world changes, future scenario reactions, and the boundary between world resolution and actor cognition.

This ADR records the decisions reached so far. It remains Draft until the remaining Slice-18 architecture topics listed at the end are resolved.

## Decision 1: Actor declarations and reusable templates

An ordinary actor-capable WorldPackage may contain separate authored actor declarations and reusable actor templates, conceptually:

```text
world-package/
├── package.json
├── world.json
├── actors/
│   ├── alice.json
│   └── bob.json
├── actor_templates/
│   ├── software-engineer.json
│   └── manager.json
└── mechanics/
    └── ...
```

`actors/*.json` declare concrete actors that exist at world bootstrap. They use stable authored actor/entity identities.

`actor_templates/*.json` declare reusable definitions. A template may be used during authoring to compose an initial actor and may also be used at runtime to instantiate a new actor when the scenario explicitly permits that operation.

A template is a definition, not a runtime actor subtype. Template instantiation always creates an ordinary actor-capable Entity; no `TemplateActor` runtime type is introduced.

Template existence alone does not authorize runtime actor creation. Scenario/world mechanics must explicitly define whether creation is allowed, from which templates, under what conditions, and by which authority. Exact spawn-policy schema remains open.

An authored actor should initially use at most zero or one template plus actor-local overrides. Template inheritance/chaining is not required for Slice 18.

Initial actor declarations are scenario declarations, not runtime state. Run bootstrap materializes them through the normal validated initialization/Event path so actor existence is reconstructable from canonical history rather than hidden package-composer mutation.

Runtime actor creation likewise produces normal actor/entity state and must be recorded in canonical history with enough identity and provenance to reconstruct the same actor during replay. Replay never reruns the actor-creation decision or randomization.

Runtime-created actor identities are engine-controlled canonical identities unless an accepted scenario mechanic explicitly supplies a stable identity under a future contract.

## Decision 2: Two perception origins and one active-perception primitive

Actor perception has two origins:

```text
1. active perception
   the actor intentionally attempts to observe something

2. passive perception
   scenario mechanics explicitly expose a perceptual consequence of a world occurrence
```

### Active perception

`OBSERVE` remains the single actor-facing v0.1 primitive for intentional perception. Core does not add separate `LOOK`, `READ`, `LISTEN`, `INSPECT`, or similar primitives.

Different observation behaviors are expressed through the `OBSERVE` PlanStep's bindings/parameters, optional Blueprint, and scenario perception mechanics, for example:

```text
OBSERVE target=document-17 mode=read
OBSERVE target=room mode=look-around
OBSERVE target=direction-east mode=listen
```

An observation attempt may succeed, partially succeed, be blocked, or fail while still revealing actor-relative information. For example, a locked rack may produce a BLOCKED resolution while still yielding content equivalent to "rack is locked".

### Passive perception

Passive perception occurs only when scenario mechanics explicitly define a perceptual consequence. Core does not infer a physical simulation from arbitrary world changes.

The baseline rule is:

> If an actor action is not intended to produce perception by others and scenario mechanics do not explicitly define a perceptual consequence, the action produces no passive-perception stimulus.

For example, `MOVE Bob office -> corridor` does not implicitly generate footsteps, door movement, sound, field-of-view changes, air movement, or other physical traces merely because they would exist in the real world.

A deliberately modeled action such as slamming a door, activating an alarm, firing a weapon, or triggering a trap may explicitly produce a perceptual consequence.

`COMMUNICATE` remains a separate existing primitive/path. Communication content/history is not redefined as a generic Stimulus merely to reuse passive-perception plumbing.

## Decision 3: Stimulus is transient scenario-mechanic output, not canonical state

`Stimulus` is a narrow transient concept used by passive perception.

Conceptually:

```text
committed world occurrence
    -> applicable scenario-reaction mechanic
    -> optional Stimulus
    -> perception mechanics
    -> zero or more actor-relative Observations
```

A Stimulus indicates that an accepted world occurrence has an explicitly modeled perceptual consequence for potential actors. It is not automatically inferred from arbitrary Events and is not authoritative simulation state.

Slice 18 does not introduce `StimulusId`, `StimulusCreated`, or `StimulusState` merely to support passive perception.

The default perception behavior should be as simple as practical for ordinary scenarios, for example scope/recipient rules based on same versus different location. More detailed perception may be expressed through scenario mechanics, including GEL where the usage-specific contract supplies explicit typed inputs. GRASS core does not become a general physics, acoustics, visibility, or sensor simulator.

The authoritative actor-relative result is `Observation`, not Stimulus.

## Decision 4: Scenario reactions follow committed world changes

Actor Job resolution commits only the direct accepted consequences of the attempted primitive. Scenario-defined reactions to those consequences are evaluated afterward rather than being silently folded into every primitive resolver.

Conceptually:

```text
actor/world action
    -> direct resolution
    -> authoritative transition committed
    -> scenario-reaction mechanics
    -> zero or more additional authoritative reactions
```

This allows generic primitives to remain domain-neutral. For example, `MOVE` knows how movement is attempted/resolved; a trap, alarm, institutional rule, environmental process, or other scenario mechanic separately decides whether the resulting committed state/history requires a reaction.

Immediate scenario reactions normally execute at the same `LogicalTime` as their source occurrence but as separate authoritative transitions with explicit causation. Same-time Event/transition append order does not itself establish causality.

Immediate scenario reactions stabilize before downstream passive perception and actor cognition that depend on their results. This permits chains such as:

```text
Bob enters camp
    -> committed MOVE consequence
    -> trap mechanic evaluates
    -> trap state changes / actor effects
    -> optional trap-noise Stimulus
    -> actor Observations
    -> optional DecisionPoints
```

A scenario reaction may produce three conceptually distinct kinds of result:

```text
1. immediate authoritative state/execution consequences
2. immediate perceptual consequences
3. future temporal consequences
```

The exact usage-specific mechanic schemas remain open.

## Decision 5: Future scenario reactions use rebuildable ScheduledResolution semantics

Scenario-reaction mechanics do not mutate a hidden scheduler queue and do not persist timers as scheduler state.

Instead, accepted authoritative state/history plus scenario mechanics may imply a future material reaction point. The scheduler derives an ephemeral `ScheduledResolution` for that point using the existing rebuildable scheduler contract.

When the resolution becomes due, the relevant scenario-reaction mechanic is evaluated again against current authoritative state and history. It may then produce further immediate state consequences, perceptual consequences, and/or another future material reaction point.

For example:

```text
10:00:00 unauthorized entry
    -> alarm.state = ACTIVE

scheduler derives:
    escalation due at 10:00:30

10:00:30 scheduled resolution
    -> alarm mechanic re-evaluates current state
    -> if still ACTIVE: alert police
    -> optional new Stimulus
    -> optional later escalation resolution
```

If another accepted transition changes the state before 10:00:30, for example setting the alarm to INACTIVE, scheduler rebuild/reprojection may remove the future candidate. A ScheduledResolution is a prediction from authoritative inputs, not a persisted promise.

Scenario state determines whether a mechanic may react again. An alarm may be modeled as a short retriggerable pulse, as a latched state that remains active until explicitly reset, or with another scenario-defined lifecycle. These behaviors are scenario semantics rather than core alarm behavior.

## Decision 6: Scenario reactions have canonical consumption identity

Scenario reactions must remain replayable/rebuildable even when evaluating a source occurrence produces no world effect and no perceptual consequence.

Use the same architectural pattern already established for one-shot scenario occurrences: a concrete reaction has a stable reference and successful evaluation records canonical consumption.

Conceptually:

```text
ScenarioReactionRef
    mechanic/rule identity
    source occurrence/Event identity
    additional reaction key only where the mechanic requires it
```

and:

```text
ScenarioReactionResolved
    reaction_ref
```

The exact v1 fields and identity vocabulary remain to be fixed during implementation design, but the semantic requirements are:

- one concrete source-triggered reaction can be recognized across runtime reconstruction;
- an accepted evaluation records consumption even when it is a valid no-op;
- a consumed reaction is not evaluated again on ordinary replay/reopen;
- a fork before the reaction may evaluate it independently;
- a fork after the reaction inherits the recorded consumption;
- future scheduled evaluations are separate reaction occurrences/references rather than implicit reuse of a consumed source-triggered reaction;
- replay never executes the mechanic to reconstruct historical reaction results.

`ScenarioReactionResolved` is a historical/semantic Event and need not mutate WorldState directly. It commits atomically with any state/execution Events produced by that reaction.

## Decision 7: OBSERVE resolution produces ObservationContent beside WorldEffects

`OBSERVE` remains a normal executable `PlanStep -> Job` primitive and uses the normal scheduling/resolution path.

Its resolution may produce actor-relative `ObservationContent` in addition to the normal Job resolution outcome and any allowed world/execution candidate results.

`ObservationContent` is not a `WorldEffect` and is not itself an authoritative `Observation`.

Conceptually:

```text
ResolutionProposal
    outcomes
    world_effects
    observation_content?   # only where permitted by the resolved OBSERVE Job
```

The exact integration shape may use a dedicated OBSERVE resolution result rather than literally changing every existing `ResolutionProposal`; the architectural requirement is that cognition content exists beside, not inside, the closed WorldEffect algebra.

`ObservationContent` is immutable structured actor-relative semantic data. It contains the perceived result only. It does not contain authoritative envelope fields such as:

```text
ObservationId
actor_id
EventId
TransitionId
logical_time
provenance
```

Those values are supplied or derived by trusted GRASS code.

The actor identity is derived from the exact source Job -> PlanStepRef -> Plan actor relationship. Untrusted mechanic/provider output does not choose the Observation actor or allocate GRASS identities.

A scenario perception mechanic determines the content visible to the actor from explicitly supplied authorized inputs. It does not receive unrestricted WorldState merely for convenience.

Examples of structured content include:

```text
{
  "kind": "document_content",
  "target": "document-17",
  "text": "..."
}
```

or:

```text
{
  "kind": "access_state",
  "target": "rack-1",
  "state": "locked"
}
```

One OBSERVE attempt may produce structured content containing several related visible facts. Slice 18 does not require splitting every perceived fact into a separate Observation.

### OBSERVE validation

ObservationContent produced through this active-perception resolution path is valid only for a source Job whose exact PlanStep primitive is `OBSERVE`.

Ordinary primitives such as `MOVE` must not smuggle passive perception through hidden observation content in their resolver output. Passive perception from world consequences uses the separate scenario-reaction -> Stimulus -> perception path.

By default, `OBSERVE` means acquiring actor-relative information rather than mutating the observed world. If observation requires a world-changing prerequisite such as opening a container, that prerequisite should normally be represented by the appropriate primitive (for example `MODIFY`) before `OBSERVE`. Scenario reactions may still respond to the fact that an observation attempt occurred when the scenario explicitly models such consequences.

## Decision 8: Trusted materialization persists ObservationContent inside Observation

Before commit, `ObservationContent` is a transient candidate value. After trusted validation and materialization, the same accepted semantic value becomes `Observation.content` in the existing canonical Observation model.

Conceptually:

```text
OBSERVE Job
    -> perception mechanic
    -> ObservationContent
    -> trusted validation/materialization
    -> ObservationCreated
         observation_id
         actor_id
         content = accepted ObservationContent
```

No separate `ObservationContentId`, `ObservationContentCreated`, or independent ObservationContent persistence model is introduced.

Persistence is required primarily because the Observation is part of the historical actor cognition on which later decisions may depend. Replay must restore what the actor actually observed rather than rerun the perception mechanic against a later or differently configured world. The same canonical content will also be useful to future Diagnostics.

Diagnostics must consume the canonical Observation and its semantic links rather than duplicate the content into a diagnostics-only store. Existing Observation identity, DecisionPoint references, provenance, explicit causation, Job/Plan lineage, and relevant mechanic identity/version should be preserved where they naturally exist. Slice 18 does not persist raw GEL execution traces, intermediate calculations, private chain-of-thought, or other transient implementation details solely for possible future diagnostics.

## Decision 9: OBSERVE resolution, Observation, and trigger evaluation are atomic

An OBSERVE Job must not be committed as completed while the corresponding accepted Observation is left to a later transition that might never occur.

Trusted resolution therefore validates/materializes the Job result and Observation together. It also applies the existing `DecisionTriggerPolicy` before publication so that the accepted cognition boundary remains coherent.

Conceptually:

```text
OBSERVE Job resolution
    -> ObservationContent
    -> trusted candidate Observation
    -> DecisionTriggerPolicy
    -> CONTINUE | DecisionPointProposal
    -> one atomic authoritative transition
```

A typical accepted transition may therefore contain:

```text
ResolutionOutcomeRecorded
Job progress/lifecycle Event(s)
ObservationCreated
optional DecisionPointCreated
```

The existing ADR-0015 rule remains: Observation and an optional DecisionPoint may be created in one cognition transition, while provider-generated Decision/Plan materialization happens later.

A failed or blocked OBSERVE attempt may still produce ObservationContent when the failure itself reveals actor-relative information. Job outcome and acquired information are orthogonal and must not be collapsed into `SUCCESS => Observation, otherwise none`.

## Decision 10: Passive perception remains separate from active OBSERVE resolution

The two perception origins converge at canonical Observation but have distinct upstream semantics:

```text
ACTIVE
Actor decision
    -> OBSERVE PlanStep/Job
    -> perception mechanic
    -> ObservationContent
    -> ObservationCreated

PASSIVE
Committed occurrence
    -> scenario reaction
    -> optional transient Stimulus
    -> perception mechanic
    -> ObservationCreated
```

Both produce ordinary actor-relative Observations and then use the same DecisionTriggerPolicy/DecisionPoint contracts.

This distinction prevents normal world resolvers from silently exposing arbitrary world state to actors and prevents passive perception from becoming hidden side output of unrelated primitives.

## Decision 11: Full actor memory remains deferred

Slice 18 fixes perception acquisition and canonical Observation persistence, not the final long-term actor memory architecture.

The following distinction remains explicit:

```text
world truth
!= Observation
!= interpretation
!= belief
!= memory
```

Observation history must remain first-class, actor-relative, replayable, and provenance-aware so a later memory policy can build episodic/semantic/retrieval/compaction behavior without redesigning perception.

Slice 18 must not prematurely freeze embedding retrieval, automatic summarization, forgetting, consolidation, short-term/long-term stores, or belief-update rules. Evidence from actor-capable runs and the post-Slice-18 Diagnostics Architecture checkpoint should inform the dedicated memory/cognition design.

## Decision 12: Passive-perception fan-out uses one cognition transition per actor

When one passive-perception source reaches multiple actors, GRASS does not commit all recipients as one large multi-actor cognition transition. Each recipient is materialized independently in one actor-scoped cognition transition.

Conceptually:

```text
one settled passive-perception source
    -> Alice Observation transition
    -> Bob Observation transition
    -> Carol Observation transition
    -> ...
```

Each such transition may atomically contain:

```text
ObservationCreated(actor)
optional DecisionPointCreated(actor)
```

All Observations caused by the same settled world/reaction frontier use the applicable common `LogicalTime`. Their branch Event `sequence` values exist for deterministic append/replay order only and do not mean that Alice perceived the occurrence before Bob merely because Alice's Event was appended first.

Actor-relative perception remains independent. Different recipients may receive different ObservationContent or no Observation at all according to the scenario perception mechanic. Failure to derive or materialize one recipient's candidate therefore does not require rolling back already valid cognition transitions for unrelated actors; normal runtime failure/validation policy still applies to the failed work item.

A passive-perception wave has a cognition barrier: resulting DecisionPoints may be created with their Observations, but no resulting actor decision/provider invocation is serviced until all outstanding passive perceptions at that current frontier have been drained.

This preserves same-time semantics without requiring a large all-recipient database transaction:

```text
passive-perception source
    -> all applicable actor Observation transitions
    -> passive-perception frontier quiescent
    -> pending decisions may run
```

No persisted fan-out cursor is introduced. Outstanding recipient work is rebuildable from canonical source/reaction history, immutable scenario mechanics, actor applicability, and existing `ObservationCreated` causation/provenance. If a process stops after Alice and Bob were recorded but before Carol, reopen/rebuild recognizes Alice and Bob as already consumed for that source and continues only the missing actor-relative perception work.

Reconstruction of outstanding perception does not rerun an already consumed scenario reaction or repeat its state consequences. It only rederives the still-outstanding passive-perception candidates from canonical history plus the immutable run/world inputs.

## Decision 13: Runtime frontier prioritizes world stabilization before perception and cognition

ADR-0022's runtime-frontier principle is retained and refined for the new Slice-18 work classes.

At one current `LogicalTime`, the runtime priority is:

```text
1. outstanding immediate scenario reactions
2. outstanding passive perception
3. pending DecisionPoints / decision acquisition
4. ready PlanStep / Job starts
5. scheduler work, including due Job/scenario resolution work and
   future scenario-reaction ScheduledResolutions
```

After every committed transition, the engine restarts frontier evaluation from priority 1 rather than continuing blindly through a lower-priority queue.

Immediate scenario reactions therefore stabilize the authoritative world frontier before downstream passive perception and cognition are allowed to react to it. For example:

```text
Bob enters camp
    -> trap reacts
    -> alarm becomes active
    -> automatic lockdown reacts
    -> immediate world frontier is stable
    -> alarm/lockdown passive perception is drained
    -> resulting actor decisions may run
```

This ordering does not mean actors can perceive only a collapsed final state. Individual scenario reactions may produce distinct perceptual consequences, and those consequences can become distinct actor-relative Observations. The rule only prevents actor cognition from acting in the middle of a zero-time immediate world-reaction cascade.

If a scenario intentionally allows reaction time between two consequences, the later consequence must be temporal rather than immediate, for example through a future `ScheduledResolution`.

A future `ScheduledResolution` does not preempt unresolved work at the current logical time. Logical time may advance to that future point only when the current frontier has no higher-priority immediate reactions, passive perception, pending decisions, or ready starts that must be serviced first under the accepted scheduler/runtime contracts.

When scheduler work commits a due future scenario reaction, Job resolution, or scenario occurrence, the engine again restarts at priority 1 so any new immediate scenario reactions and passive perceptions settle before decisions or further lower-priority work.

The same restart rule applies to active perception. An `OBSERVE` resolution may atomically create an Observation and DecisionPoint, but if that committed observation attempt or its accompanying world/execution history makes an immediate scenario reaction outstanding, that reaction is processed before the actor's new DecisionPoint is serviced.

The existing runtime work/step budget remains the protection against pathological mechanics that continually create new reaction identities and never allow a frontier to quiesce. `ScenarioReactionRef` consumption prevents the same concrete reaction from being processed repeatedly, but it does not make arbitrary self-generating scenario logic impossible; exceeding the configured bounded-work policy is a runtime stop/failure condition rather than permission for an infinite loop.

## Consequences

### Positive

- actor templates support both authored bootstrap and explicitly authorized runtime creation without creating a second Actor type;
- actor identity and runtime actor creation remain replayable and branch-safe;
- active perception reuses the existing `OBSERVE` primitive rather than expanding the core verb set;
- passive perception is explicit and scenario-selected rather than an implicit physics engine;
- `Stimulus` remains disposable mechanic output instead of creating another authoritative projection;
- domain-neutral primitives stay small because traps, alarms, institutions, and similar reactions live in scenario mechanics;
- immediate and delayed scenario reactions share the existing Event/scheduler authority boundaries;
- no-op scenario reactions remain reconstructable and are not accidentally re-executed after reopen;
- `ObservationContent` keeps cognition output outside the WorldEffect algebra while reusing the existing canonical Observation contract;
- an OBSERVE Job cannot complete historically without its accepted perceived result;
- multi-actor passive perception preserves common logical-time semantics without requiring one large all-recipient transition;
- actors cannot react before the same-frontier passive-perception wave has been drained;
- immediate scenario mechanics stabilize the world before downstream actor cognition while still allowing explicitly delayed consequences through ScheduledResolution;
- Diagnostics can later explain decisions from canonical Observation content and explicit semantic lineage without a duplicate diagnostics data model;
- the eventual actor memory model remains free to evolve from real run evidence.

### Costs and constraints

- runtime frontier orchestration must discover and deterministically drain immediate scenario reactions and actor-relative passive-perception work before lower-priority cognition/execution work;
- scenario-reaction identity and scheduling must be deterministic/rebuildable without hidden cursors or timer state;
- passive-perception recipient consumption must be rebuildable without a persisted fan-out cursor;
- world composition needs explicit scenario reaction and perception mechanic authoring contracts;
- resolution materialization must atomically validate Events across ExecutionState and CognitionState;
- passive-perception fan-out may produce significant Observation/Event volume in large worlds even though each actor transition stays small;
- scenario authors who need rich physical perception must model that detail explicitly rather than receiving it automatically from core.

## Alternatives considered

### Infer passive perception from every world Event

Rejected because it would pressure GRASS toward a universal physics/visibility/acoustics model and would create large amounts of accidental perception from scenario details that were never intended to matter.

### Put traps, alarms, and other secondary consequences directly inside primitive resolvers

Rejected because generic primitives such as MOVE would accumulate scenario-specific behavior and direct action resolution would become inseparable from arbitrary downstream world rules.

### Persist scheduler timers created by scenario mechanics

Rejected because it would make scheduler state authoritative and violate the existing rebuild-equivalence contract. Future reaction points remain derived ScheduledResolutions.

### Treat Stimulus as a canonical Event/state object by default

Rejected because the actor-relative Observation is the material cognition fact. Persisting every intermediate stimulus would add history/state without current replay need.

### Add CreateObservationEffect to WorldEffect

Rejected because it would broaden WorldEffect from world/execution candidate consequences into a generic mutation algebra for all SimulationState projections. Observation belongs to cognition and already has its own canonical Event contract.

### Use ObservationProposal instead of ObservationContent

Rejected because the perception mechanic supplies semantic perceived content, not authority to propose an Observation identity/actor/time/provenance object. Trusted GRASS code constructs the Observation.

### Persist ObservationContent separately for Diagnostics

Rejected because accepted content is already canonical as `Observation.content`. Diagnostics must derive explanations from domain history rather than create a second persistence authority.

### Commit one multi-actor cognition transition for a passive-perception fan-out

Rejected because actor-relative perception is independently derived, may legitimately differ by actor, may fail independently, and can fan out to large populations. Common `LogicalTime` plus a runtime perception barrier preserves semantic simultaneity without coupling every recipient to one atomic commit.

### Allow decisions to run while same-frontier passive perception or immediate reactions remain outstanding

Rejected because actor behavior would then depend on engine iteration order and could react to a partially settled world/perception wave. Immediate scenario reactions stabilize first, then passive perception drains, then pending cognition is serviced.

## Remaining open Slice-18 decisions

This ADR remains Draft. The following topics still need explicit resolution before Slice 18 implementation begins:

- exact scenario-reaction and perception mechanic authoring schemas, including built-in versus GEL usage-specific contracts;
- initial actor cognition/bootstrap and `PLAN_REQUIRED` creation semantics;
- provider/run-config ownership and authoring for actor-capable packages;
- the remaining Decision -> Plan -> PlanStep -> Job materialization path where current bounded reactions become executable behavior;
- actor-to-actor communication semantics beyond the already accepted `COMMUNICATE` primitive and Query-versus-Diagnostics boundary;
- resource interaction/conflict semantics required by actor-oriented acceptance worlds;
- final WorldPackage schema/layout and validation for actors, templates, reaction mechanics, perception mechanics, and actor-capable starter templates;
- exact Event payload/reference shapes for ScenarioReactionRef/ScenarioReactionResolved and any required changes to current resolution DTOs.
