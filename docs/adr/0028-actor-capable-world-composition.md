# ADR-0028: Actor-capable world composition, scenario reactions, and perception

- Status: Draft
- Date: 2026-10-11

## Context

Slice 18 must make ordinary WorldPackages actor-capable without creating a second runtime path or weakening the existing event-sourced authority, replay, branching, scheduler, world-resolution, cognition, and provider contracts.

The current architecture already fixes several relevant boundaries:

- actors are Entity-backed participants rather than a separate world-state identity system;
- `PlanStep` has exactly one primitive from the closed v0.1 set, including `OBSERVE` and `COMMUNICATE`;
- Jobs are the executable form of started PlanSteps;
- `WorldEffect` is a closed candidate algebra for authoritative world/execution consequences and is distinct from committed Events;
- `Observation` is actor-relative persistent cognition with stable identity, content, provenance, and logical time;
- `DecisionTriggerPolicy` decides whether one Observation creates a DecisionPoint;
- `ScheduledResolution` is ephemeral and rebuildable from authoritative state/history and scenario mechanics;
- ordinary replay never regenerates historical perception, cognition, world resolution, randomness, or provider output;
- diagnostics must later explain accepted behavior from existing semantic identities, provenance, causation, correlation, and recorded domain facts rather than from a parallel diagnostics authority.

This ADR records the Slice-18 architecture decisions reached so far. It remains Draft until the remaining topics listed at the end are resolved.

## Decision 1: Actor declarations and reusable templates

An actor-capable WorldPackage may contain separate authored actor declarations and reusable actor templates, conceptually:

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

`actors/*.json` declare concrete actors that exist at world bootstrap and use stable authored actor/entity identities.

`actor_templates/*.json` declare reusable definitions. A template may be used while authoring an initial actor and may also be used at runtime to instantiate a new actor when scenario semantics explicitly authorize that operation.

A template is a definition, not a runtime actor subtype. Instantiation always creates an ordinary actor-capable Entity; no `TemplateActor` runtime type is introduced.

Template existence does not itself authorize runtime actor creation. Scenario/world mechanics must explicitly govern whether creation is allowed, from which templates, and under what authority. Exact spawn-policy schema remains open.

An authored actor should initially use at most zero or one template plus actor-local overrides. Template inheritance/chaining is not required for Slice 18.

Initial actor declarations are scenario declarations, not runtime state. Run bootstrap materializes them through the normal validated initialization/Event path. Runtime actor creation likewise produces canonical Entity/actor history. Replay never reruns actor-creation decisions or randomization.

Runtime-created identities are engine-controlled canonical identities unless an accepted future mechanic contract explicitly supplies a stable identity.

## Decision 2: Two perception origins and one active-perception primitive

Actor perception has two origins:

```text
1. active perception
   the actor intentionally attempts to observe something

2. passive perception
   scenario mechanics explicitly expose a perceptual consequence of a world occurrence
```

### Active perception

`OBSERVE` remains the single actor-facing v0.1 primitive for intentional perception. Core does not add `LOOK`, `READ`, `LISTEN`, `INSPECT`, or similar primitives.

Different observation behaviors are expressed through `OBSERVE` PlanStep bindings/parameters, optional Blueprints, and scenario perception mechanics, for example:

```text
OBSERVE target=document-17 mode=read
OBSERVE target=room mode=look-around
OBSERVE target=direction-east mode=listen
```

An observation attempt may succeed, partially succeed, be blocked, or fail while still revealing actor-relative information. A locked rack may therefore yield a blocked Job outcome while still producing content equivalent to `rack is locked`.

### Passive perception

Passive perception occurs only when scenario mechanics explicitly define a perceptual consequence. Core does not infer a physical simulation from arbitrary world changes.

> If an actor action is not intended to produce perception by others and scenario mechanics do not explicitly define a perceptual consequence, the action produces no passive-perception stimulus.

For example, `MOVE Bob office -> corridor` does not implicitly generate footsteps, door movement, sound, field-of-view changes, or similar physical traces.

`COMMUNICATE` remains a separate primitive/path. Communication content/history is not redefined as a generic Stimulus merely to reuse passive-perception plumbing.

## Decision 3: Stimulus is transient scenario-mechanic output

`Stimulus` is a narrow transient concept used by passive perception:

```text
committed world occurrence
    -> applicable scenario-reaction mechanic
    -> optional Stimulus
    -> perception mechanics
    -> zero or more actor-relative Observations
```

A Stimulus indicates that an accepted world occurrence has an explicitly modeled perceptual consequence. It is not automatically inferred from arbitrary Events and is not authoritative simulation state.

Slice 18 does not introduce `StimulusId`, `StimulusCreated`, or `StimulusState` merely to support passive perception.

Default perception behavior should remain simple for ordinary scenarios, for example location-based recipient rules. Richer perception may be modeled by scenario mechanics, including GEL where a usage-specific contract supplies explicit typed inputs. GRASS core does not become a general physics, acoustics, visibility, or sensor simulator.

The authoritative actor-relative result is `Observation`, not Stimulus.

## Decision 4: Scenario reactions follow committed world changes

Actor Job resolution commits only the direct accepted consequences of the attempted primitive. Scenario-defined secondary consequences are evaluated afterward rather than being silently folded into primitive resolvers.

```text
actor/world action
    -> direct resolution
    -> authoritative transition committed
    -> scenario-reaction mechanics
    -> zero or more additional authoritative reactions
```

Generic primitives therefore remain domain-neutral. `MOVE` resolves movement; traps, alarms, institutions, environmental rules, and similar scenario behavior react separately to committed state/history.

Immediate scenario reactions normally execute at the same `LogicalTime` as their source occurrence but as separate authoritative transitions with explicit causation. Same-time append order is replay/storage order, not causality.

Immediate scenario reactions stabilize before downstream passive perception and actor cognition that depend on their results.

A scenario reaction may produce conceptually distinct result classes:

```text
1. immediate authoritative state/execution consequences
2. immediate perceptual consequences
3. future temporal continuations
```

## Decision 5: Future scenario reactions use rebuildable ScheduledResolution semantics

Scenario-reaction mechanics do not mutate a hidden scheduler queue and do not persist timers as scheduler state.

Accepted reaction semantics may produce zero or more future `TemporalContinuation`s. Each continuation represents a future material reaction point. The scheduler derives an ephemeral `ScheduledResolution` from canonical reaction history plus the accepted continuation semantics.

A continuation is not a precomputed future effect. When it becomes due, the target scenario reaction is evaluated again using current explicitly declared inputs and may produce ordinary consequences or a valid no-op.

Example:

```text
10:00:00 unauthorized entry
    -> alarm becomes ACTIVE
    -> accepted reaction result implies continuation +30s

scheduler derives:
    escalation reconsideration at 10:00:30

10:00:30
    -> target reaction mechanic evaluates current declared inputs
    -> may alert police
    -> or may validly produce no-op
```

Changing ordinary world state after the continuation was created does not implicitly issue a scheduler cancellation command. The future material point remains derived from its canonical anchor and continuation semantics; current state is considered when the due mechanic executes.

If a deadline/time is itself meaningful modeled world state, that temporal fact may be persisted through ordinary world semantics. Otherwise due time remains derivable from canonical history and the continuation definition.

A `ScheduledResolution` remains derived runtime data rather than authoritative timer state.

## Decision 6: Scenario reactions have canonical consumption identity

Scenario reactions must remain replayable/rebuildable even when evaluation produces no world effect and no perceptual consequence.

A concrete reaction has a stable reference and successful evaluation records canonical consumption.

Conceptually:

```text
ScenarioReactionRef
    rule/mechanic identity
    source occurrence/Event identity
    additional reaction key only where required
```

and:

```text
ScenarioReactionResolved
    reaction_ref
```

Requirements:

- one concrete source-triggered reaction can be recognized across runtime reconstruction;
- accepted evaluation records consumption even for a valid no-op;
- a consumed reaction is not reevaluated on ordinary replay/reopen;
- a fork before the reaction may evaluate independently;
- a fork after the reaction inherits consumption;
- a future scheduled evaluation is a separate reaction occurrence/reference;
- replay never executes a mechanic to reconstruct historical reaction results.

`ScenarioReactionResolved` is a semantic historical Event and commits atomically with any authoritative Events produced by that reaction.

## Decision 7: OBSERVE resolution produces ObservationContent beside WorldEffects

`OBSERVE` remains a normal executable `PlanStep -> Job` primitive using the normal scheduling/resolution path.

Its resolution may produce actor-relative `ObservationContent` in addition to the normal Job outcome and allowed world/execution candidate results.

`ObservationContent` is neither a `WorldEffect` nor an authoritative `Observation`.

Conceptually:

```text
ResolutionProposal
    outcomes
    world_effects
    observation_content?   # permitted for resolved OBSERVE work
```

The exact DTO may use a dedicated OBSERVE result rather than literally changing every `ResolutionProposal`. The architectural requirement is that cognition content exists beside, not inside, the closed WorldEffect algebra.

`ObservationContent` is immutable structured actor-relative semantic data and does not contain authoritative envelope fields such as:

```text
ObservationId
actor_id
EventId
TransitionId
logical_time
provenance
```

Trusted GRASS code supplies or derives those values.

The Observation actor is derived from the exact source Job -> PlanStepRef -> Plan actor relationship. Untrusted mechanics/providers do not choose the actor or allocate GRASS identities.

A scenario perception mechanic receives explicit authorized inputs rather than unrestricted WorldState.

One OBSERVE attempt may produce structured content containing several related visible facts; Slice 18 does not require one Observation per fact.

ObservationContent on this active-perception path is valid only for a source Job whose exact PlanStep primitive is `OBSERVE`. Other primitives must not smuggle passive perception through hidden observation output.

By default, OBSERVE acquires information rather than mutating the observed world. A physical prerequisite such as opening a container should normally use an appropriate world-changing primitive first.

## Decision 8: Trusted materialization persists ObservationContent inside Observation

Before commit, `ObservationContent` is transient candidate data. After trusted validation/materialization, the same accepted semantic value becomes canonical `Observation.content`.

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

Persistence exists because Observation is historical actor cognition required for replay, branch continuation, and later decisions. Replay restores what the actor observed rather than rerunning perception.

Diagnostics consumes canonical Observation content and semantic lineage rather than a duplicate diagnostics store. Raw GEL traces, intermediate calculations, private chain-of-thought, and similar transient details are not persisted solely for Diagnostics.

## Decision 9: OBSERVE resolution, Observation, and trigger evaluation are atomic

An OBSERVE Job must not be historically committed as completed while its accepted Observation is left to a later transition that might never occur.

Trusted resolution validates/materializes the Job result and Observation together and applies the existing `DecisionTriggerPolicy` before publication:

```text
OBSERVE Job resolution
    -> ObservationContent
    -> trusted candidate Observation
    -> DecisionTriggerPolicy
    -> CONTINUE | DecisionPointProposal
    -> one atomic authoritative transition
```

A typical transition may contain:

```text
ResolutionOutcomeRecorded
Job progress/lifecycle Event(s)
ObservationCreated
optional DecisionPointCreated
```

Provider-generated Decision/Plan materialization still happens later.

A failed or blocked OBSERVE attempt may still produce ObservationContent when failure itself reveals actor-relative information. Job outcome and acquired information remain orthogonal.

## Decision 10: Passive perception remains separate from active OBSERVE resolution

The two perception origins converge at canonical Observation but retain distinct upstream semantics:

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

Both then use the existing DecisionTriggerPolicy/DecisionPoint contracts.

This prevents ordinary world resolvers from silently exposing arbitrary world state and prevents passive perception from becoming hidden side output of unrelated primitives.

## Decision 11: Full actor memory remains deferred

Slice 18 fixes perception acquisition and canonical Observation persistence, not the final long-term actor memory architecture.

```text
world truth
!= Observation
!= interpretation
!= belief
!= memory
```

Observation history remains first-class, actor-relative, replayable, and provenance-aware. Slice 18 does not prematurely freeze embeddings, retrieval, summarization, forgetting, consolidation, short-term/long-term stores, or belief-update rules.

Evidence from actor-capable runs and the post-Slice-18 Diagnostics Architecture checkpoint should inform the dedicated cognition/memory design.

## Decision 12: Passive-perception fan-out uses one cognition transition per actor

When one passive-perception source reaches multiple actors, each recipient is materialized independently in one actor-scoped cognition transition rather than one large multi-actor transaction.

```text
one settled passive-perception source
    -> Alice Observation transition
    -> Bob Observation transition
    -> Carol Observation transition
    -> ...
```

Each transition may atomically contain:

```text
ObservationCreated(actor)
optional DecisionPointCreated(actor)
```

All Observations caused by the same settled world/reaction frontier use the applicable common `LogicalTime`. Event sequence gives deterministic append/replay order only; it does not imply that Alice perceived the occurrence before Bob.

Actor-relative perception remains independent. Recipients may receive different content or no Observation according to scenario perception mechanics.

A passive-perception wave has a cognition barrier: resulting DecisionPoints may be created with their Observations, but no resulting decision/provider invocation is serviced until all outstanding passive perceptions at that current frontier have been drained.

No persisted fan-out cursor is introduced. Outstanding recipient work is rebuildable from canonical source/reaction history, immutable run/world inputs, and existing Observation causation/provenance. Reconstruction does not rerun an already consumed scenario reaction or repeat its state consequences.

## Decision 13: Runtime frontier prioritizes world stabilization before perception and cognition

ADR-0022's frontier principle is retained and refined.

At one current `LogicalTime`, priority is:

```text
1. outstanding immediate scenario reactions
2. outstanding passive perception
3. pending DecisionPoints / decision work
4. ready PlanStep / Job starts
5. scheduler work, including due Job/scenario work and
   future scenario-reaction ScheduledResolutions
```

After every committed transition, the engine restarts frontier evaluation from priority 1.

Immediate scenario reactions therefore stabilize the authoritative world frontier before downstream passive perception and cognition. Actors cannot act in the middle of a zero-time immediate reaction cascade.

If a scenario intentionally allows reaction time between two consequences, the later consequence must be temporal rather than immediate.

A future `ScheduledResolution` does not preempt unresolved current-time work. When scheduler work commits, the engine again restarts from priority 1.

The same restart rule applies after active OBSERVE resolution: a newly created DecisionPoint is not serviced ahead of any immediate scenario reactions caused by the committed attempt/history.

The existing runtime work/step budget protects against pathological mechanics that continually create new reaction identities and never allow the frontier to quiesce.

## Decision 14: ActorFacet is canonical and PLAN_REQUIRED is runtime-derived

Actor membership must not be inferred from incidental Plans, Observations, or DecisionPoints.

Actor identity remains Entity-backed. An actor uses the same identifier as its world Entity, and explicit canonical `ActorFacet` state marks that the Entity participates in actor cognition/execution.

Conceptually:

```text
Entity
    entity_id = alice

ActorFacet
    actor_id = alice
```

Slice 18 does not introduce a separate Actor identity/aggregate.

The minimal canonical Event is conceptually:

```text
ActorFacetCreated
    actor_id
```

Exact payload/projection placement is finalized with remaining Event/DTO work, but actor membership must be reconstructable from canonical history. Query surfaces should no longer infer actors from the union of Plan, Observation, and DecisionPoint references.

### Authored and runtime-created actors

For an authored actor, bootstrap atomically materializes the concrete Entity and ActorFacet in the same genesis transition:

```text
genesis
    -> EntityCreated(alice)
    -> ActorFacetCreated(alice)
```

There is no externally visible historical position where an authored actor's Entity exists but the declared ActorFacet does not.

Runtime actor creation follows the same principle: accepted creation atomically materializes required world state plus ActorFacet. Replay restores the accepted actor rather than rerunning template instantiation.

Authored profile/background/traits/drives/beliefs/future memory configuration are not encoded as historical `ObservationCreated` merely because they are initially available to the actor. Initial profile/cognition and Observation history remain distinct concepts.

### PLAN_REQUIRED is produced by runtime readiness

Genesis establishes actor existence and initial declarations. It does not preemptively record a cognition decision merely because an actor will need a Plan.

`PLAN_REQUIRED` is a subjectless `FULL` DecisionPoint derived by normal runtime readiness. It is not limited to bootstrap. It is the fallback when an active actor requires planning, has no pending DecisionPoint, has no applicable Plan lineage governing further actor work, and no more specific accepted DecisionPoint reason applies.

```text
active Entity
    + ActorFacet
    + actor currently requires planning
    + no pending DecisionPoint
    + no applicable Plan lineage for further work
    + no more specific reason applies
        -> PLAN_REQUIRED / FULL / subject_plan_ref = null
```

This covers both a new actor starting without a Plan and an existing actor that later becomes planless for another reason.

`PLAN_REQUIRED` must not erase more precise semantics. Where the runtime knows an exact Plan/Job reason, specific reasons such as `PLAN_EXHAUSTED`, `PLAN_BLOCKED`, `JOB_FAILED`, or `JOB_PAUSED` remain preferred.

The runtime must not implement readiness by inventing an implicit global/current Plan. It derives need from explicit branch-visible execution/cognition relationships and accepted Plan semantics.

When multiple actors at the same current `LogicalTime` require subjectless `PLAN_REQUIRED`, each receives its own cognition transition. All currently required points are materialized before provider acquisition for any newly created point begins.

Conceptually, decision work has internal ordering:

```text
3a. materialize currently required DecisionPoints
3b. service pending DecisionPoints / acquire decisions
```

After each committed DecisionPoint transition, full frontier evaluation still restarts at priority 1.

## Decision 15: ScenarioReactionRule, ReactionContract, and mechanic bindings

Scenario reaction authoring separates candidate discovery, semantic result definition, mechanic implementation, and trusted consequence materialization.

Conceptually:

```text
ScenarioReactionRule
    rule_id
    trigger
    input_bindings
    reaction_contract_ref
    mechanic_binding
```

The trigger is a typed declarative selector over committed semantic Events. It decides whether a rule is a candidate for evaluation; it does not implement full scenario condition/effect semantics.

```text
committed semantic Event
    -> typed trigger selector
    -> ScenarioReactionRef
    -> declared input resolution
    -> mechanic evaluation
```

Rules react to accepted canonical history, not transient pre-validation WorldEffects. Trigger selectors operate on semantic Event contracts rather than arbitrary JSON paths over serialized payloads.

The mechanic receives only explicitly declared typed inputs. It does not receive unrestricted `WorldState`, `SimulationState`, `EventStore`, scheduler, engine, or commit handles. A matched rule may validly evaluate to a no-op; `ScenarioReactionResolved` still records accepted consumption.

### ReactionContract defines result meaning

The shape and meaning of `ReactionResult` are defined by a world-level `ReactionContract`, not by hard-coded domain classes in GRASS core.

Conceptually:

```text
ReactionContract
    contract_id
    input_schema
    result_schema
    consequence_mapping
    temporal_continuations?
```

The mechanic computes only a typed semantic result:

```text
ReactionInput
    -> BUILTIN | GEL | IMPLEMENTATION
    -> ReactionResult
```

Trusted GRASS adaptation interprets that result using the world-defined contract:

```text
ReactionResult
    + ReactionContract
    -> trusted generic adaptation
    -> permitted candidate consequences
    -> authoritative validation
    -> canonical Events
```

The world defines what result fields mean and how they map to permitted state/execution/perceptual/temporal candidate consequences. GRASS core/run policy still defines the authority boundary: a contract cannot emit arbitrary Events, mutate arbitrary state, write to EventStore, or bypass the closed validated consequence model.

```text
WorldDefinition defines semantic consequence meaning.
GRASS core/run policy defines which authoritative consequence classes are legal.
```

An actor/provider/LLM therefore proposes semantics within allowed contracts; it never receives direct arbitrary world-mutation authority.

### BUILTIN, GEL, and IMPLEMENTATION use the same semantic contract

`BUILTIN`, `GEL`, and `IMPLEMENTATION` are alternate ways to compute the same world-defined typed `ReactionResult`. A more expressive implementation does not gain more simulation authority.

GEL remains sandboxed and side-effect-free under its accepted explicit-input contract.

`IMPLEMENTATION` is the future trusted plugin extension point for mechanics impractical in GEL. A plugin may use normal host-language code and libraries internally, but its simulation-facing boundary remains:

```text
typed ReactionInput
    -> installed implementation mechanic
    -> typed ReactionResult
```

A plugin does not receive EventStore, mutable SimulationState, SimulationEngine, scheduler, or commit authority merely because it is installed/trusted.

Continuation of a run may require the exact installed mechanic identity and a compatible version/content identity. Ordinary historical replay does not invoke the plugin to reconstruct accepted history.

### Dynamic rules/contracts remain future capabilities

Slice 18 may initially load reaction rules from immutable WorldDefinition material, but the architecture must not assume that the ruleset is permanently static.

Future authorized runtime semantics may allow `ScenarioReactionRule`s to appear or cease to exist during a run. Exact lifecycle semantics are deliberately deferred; Slice 18 does not define a generic mutable `enabled` flag, in-place rule mutation, or rule replacement/versioning model.

Future modes may allow actors/LLMs to propose new rules and actor-authored GEL, subject to explicit authorization, validation, and run/world policy. Accepted runtime changes must become canonical/replayable history rather than hidden process configuration.

Dynamic `ReactionContract` creation is a separate and substantially more powerful future capability and must be independently authorizable/configurable. Even an actor-created contract may compose only consequence classes permitted by the GRASS authority model and applicable run/world policy.

The exact policy representation is deferred; the architecture intentionally leaves room for separately controlled capabilities such as actor-defined rules, actor-defined GEL, and actor-defined ReactionContracts.

## Decision 16: TemporalContinuation is semantic future reaction work, not scheduler control

A reaction may derive zero or more `TemporalContinuation`s according to its world-defined `ReactionContract` and accepted `ReactionResult`.

Conceptually:

```text
TemporalContinuation
    continuation_id
    due
    target_rule_ref?   # absent => originating ScenarioReactionRule
```

The exact v1 DTO remains open, but the semantic rules are fixed.

A continuation identifies a future material reaction point. By default it targets the same `ScenarioReactionRule` that produced it. A contract may explicitly target another rule where scenario semantics require a hand-off.

Which continuations are created is itself part of world-defined result interpretation. A `ReactionContract` may define several possible continuation mappings and an accepted `ReactionResult` may select zero, one, or many of them.

Example:

```text
ReactionResult
    notify_security = true
    notify_police = false

ReactionContract mapping
    notify_security -> continuation +30s using security-response
    notify_police   -> continuation +5m using police-response

accepted continuations
    security-response only
```

No separate generic `applicability` or cancellation model is introduced.

When a continuation becomes due, its target rule/mechanic is evaluated using current explicitly declared inputs:

```text
ScheduledResolution
    -> target ScenarioReactionRule
    -> current declared inputs
    -> BUILTIN | GEL | IMPLEMENTATION
    -> ReactionResult
    -> normal trusted consequence adaptation
```

The due evaluation may produce normal consequences or a valid no-op. This allows current state to decide whether one due continuation has an effect while another does not, without adding a second applicability language or scheduler cancellation API.

A mechanic never returns an imperative scheduler command such as `schedule()` or `cancel()`. The scheduler only derives `ScheduledResolution` values from canonical anchors plus accepted temporal-continuation semantics.

Continuation due time may be fixed by the contract, derived deterministically from accepted typed result data, or use another future typed temporal calculation contract. GEL may participate in an explicitly typed calculation, but it never receives scheduler authority.

If a time/deadline is itself modeled world semantics, that fact may be persisted as ordinary world state. Otherwise the future point remains derivable from canonical reaction history and continuation semantics.

The exact behavior of an already-created continuation whose target rule later ceases to exist under a future dynamic-rules model is deliberately deferred. Slice 18 does not need that lifecycle decision.

## Consequences

### Positive

- actor templates support authored bootstrap and explicitly authorized runtime creation without a second Actor type;
- ActorFacet makes actor membership explicit canonical history;
- `PLAN_REQUIRED` naturally covers both initial and later planless actors;
- active perception reuses `OBSERVE` rather than expanding the primitive set;
- passive perception is explicit and scenario-selected rather than implicit physics;
- Stimulus remains transient while Observation is canonical cognition;
- primitive resolvers remain domain-neutral because secondary behavior lives in scenario reactions;
- immediate reactions stabilize before passive perception and decisions;
- passive-perception fan-out preserves common logical-time semantics without a large multi-actor transaction;
- scenario-reaction no-ops remain canonically consumed and replay-safe;
- ReactionContract keeps semantic result/consequence meaning in the world rather than hard-coding alarms/traps/etc. in core;
- BUILTIN, GEL, and IMPLEMENTATION share one authority-preserving semantic boundary;
- future actor/LLM-authored rules and contracts remain possible without granting direct world mutation;
- temporal continuations support multiple selective future reaction points without authoritative scheduler timers;
- current state can naturally cause a due mechanic to produce a no-op without a separate applicability/cancellation subsystem;
- Diagnostics can later explain decisions from canonical Observation and semantic lineage;
- the eventual memory model remains free to evolve from actor-capable run evidence.

### Costs and constraints

- runtime frontier orchestration must deterministically drain immediate reactions and passive-perception work;
- scenario-reaction and continuation identities must be deterministic/rebuildable without hidden cursors or timers;
- passive-perception recipient consumption must be rebuildable without a persisted fan-out cursor;
- runtime readiness must derive planning need without inventing an implicit current Plan;
- bootstrap/runtime actor creation must atomically materialize ActorFacet with actor Entity state;
- trusted reaction adaptation must validate world-defined consequence mappings against core/run-authorized consequence classes;
- future dynamic rule/contract lifecycle requires canonical history and explicit authorization rather than process-local mutation;
- plugin continuation may require exact implementation identity/version compatibility;
- resolution materialization must atomically validate cross-projection Events;
- passive-perception fan-out may create substantial Observation/Event volume;
- scenario authors who require rich physical perception must model it explicitly.

## Alternatives considered

### Infer passive perception from every world Event

Rejected because it would push GRASS toward a universal physics/visibility/acoustics model and create accidental perception from irrelevant scenario details.

### Put traps, alarms, and other secondary consequences inside primitive resolvers

Rejected because generic primitives would accumulate scenario-specific behavior and direct action resolution would become inseparable from arbitrary downstream rules.

### Persist scheduler timers created by scenario mechanics

Rejected because scheduler state would become authoritative and violate rebuild equivalence. Future work remains derived through `TemporalContinuation` -> `ScheduledResolution`.

### Treat Stimulus as canonical Event/state by default

Rejected because actor-relative Observation is the material cognition fact. Canonicalizing every intermediate stimulus would add state/history without current need.

### Add CreateObservationEffect to WorldEffect

Rejected because it would broaden WorldEffect into a generic mutation algebra for all SimulationState projections. Observation belongs to cognition and has its own canonical Event contract.

### Use ObservationProposal instead of ObservationContent

Rejected because perception mechanics supply semantic perceived content, not authority to propose Observation identity/actor/time/provenance.

### Persist ObservationContent separately for Diagnostics

Rejected because accepted content is already canonical as `Observation.content`.

### Commit one multi-actor cognition transition for passive-perception fan-out

Rejected because actor-relative perception is independently derived, may differ by actor, may fail independently, and may fan out broadly. Common LogicalTime plus a perception barrier preserves semantic simultaneity.

### Allow decisions while same-frontier immediate reactions or passive perception remain outstanding

Rejected because actor behavior would depend on engine iteration order and could react to a partially settled world/perception wave.

### Infer actor membership from Plans, Observations, or DecisionPoints

Rejected because those are incidental runtime records. An actor remains an actor while Plans or DecisionPoints are absent.

### Put initial PLAN_REQUIRED inside genesis

Rejected because genesis establishes declared simulation state while `PLAN_REQUIRED` expresses a runtime cognition need. Runtime derivation also naturally handles later planless actors.

### Restrict PLAN_REQUIRED to bootstrap

Rejected because the same subjectless planning condition may legitimately arise later in a run. More specific exact Plan/Job reasons remain preferred where available.

### Hard-code domain-specific ReactionResult/adapter classes in core

Rejected because core would accumulate scenario vocabulary such as alarms, traps, fires, and institutions. `ReactionContract` keeps result meaning and consequence mapping in world semantics.

### Let GEL or IMPLEMENTATION return arbitrary WorldEffects or Events

Rejected because extensibility would become a mutation escape hatch. Mechanics return typed semantic results; trusted adaptation applies world-defined mappings within the authorized consequence vocabulary.

### Treat reaction rules as permanently immutable run configuration

Rejected as a long-term architectural invariant because future generative modes may authorize runtime appearance/removal of rules and actor-authored GEL. Exact lifecycle semantics remain deferred.

### Add generic rule.enabled, in-place rule mutation, or replacement semantics now

Rejected/deferred because those semantics were not required to express accepted Slice-18 behavior and would prematurely constrain future dynamic-rules design.

### Add separate TemporalContinuation applicability/cancellation logic

Rejected because the target mechanic can evaluate current declared inputs at due time and return an ordinary no-op. A second applicability language would duplicate mechanic semantics and complicate selective continuation behavior.

### Let mechanics issue scheduler commands

Rejected because `schedule()`/`cancel()` style APIs would make scheduler state authoritative. Temporal continuations describe scenario semantics; scheduler work remains derived.

## Remaining open Slice-18 decisions

This ADR remains Draft. The following topics still need explicit resolution before Slice 18 implementation begins:

- exact perception mechanic authoring schemas and contracts;
- provider/run-config ownership and authoring for actor-capable packages;
- remaining Decision -> Plan -> PlanStep -> Job materialization where bounded reactions become executable behavior;
- actor-to-actor communication semantics beyond the accepted `COMMUNICATE` primitive and Query-versus-Diagnostics boundary;
- resource interaction/conflict semantics required by actor-oriented acceptance worlds;
- final WorldPackage schema/layout and validation for actors, templates, reaction contracts/rules, perception mechanics, and actor-capable starter templates;
- exact Event payload/reference shapes for ActorFacet, ScenarioReactionRef/ScenarioReactionResolved, dynamic-rule-ready provenance, TemporalContinuation references, and required resolution DTO changes.
