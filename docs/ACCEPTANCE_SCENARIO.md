# GRASS design-0.1 acceptance scenario

This walkthrough is the integration target for the `design-0.1` architecture baseline. It is not a domain specification. Its purpose is to prove that core contracts compose coherently before richer scenarios are implemented.

## 1. Scenario setup

A minimal corporate scenario contains:

- `Alice`, `Bob`: `Person` entities with ActorFacet;
- `Acme`: `Organization`;
- `Office`: `Location`;
- `TestEnvironment`: scenario entity/resource context;
- `Alice employed_by Acme` and `Bob employed_by Acme` Relations;
- `TestEnvironment.capacity = 1` Resource;
- actor stress StateVariables;
- one scenario-defined Blueprint for report work;
- one `RANDOM_TIME` network-outage ScenarioEventRule;
- one GEL stress/interruption mechanic;
- one meeting Commitment due later in the run.

`SimulationRunConfig` selects deterministic world resolution, scripted/fake DecisionProviders for acceptance tests, and a known run seed.

## 2. Genesis

`WorldDefinition.initial_conditions` are validated and materialized through an atomic genesis transition.

Expected properties:

- initial conditions are declarations, not historical Events;
- genesis produces semantic generic Events such as EntityCreated, RelationCreated, ResourceChanged, and StateVariableChanged;
- all Events in one genesis transition share one `transition_id` and commit atomically;
- the resulting `SimulationState` contains consistent WorldState/ExecutionState/CognitionState projections;
- no provider call is required to replay genesis.

## 3. Initial actor decision and Plan

Alice has no sufficient Plan, so the engine creates a `PLAN_REQUIRED` DecisionPoint with `FULL` scope.

A scripted DecisionProvider decides that Alice will move to the office and then modify/write a report. Planning materializes an immutable Plan version with two PlanSteps:

1. `MOVE Alice -> Office`;
2. report work (`MODIFY` or `CREATE`, depending on the modeled report object), dependent on step 1 `SUCCESS`.

Expected properties:

- DecisionPoint/decision/Plan are reconstructable from Event history;
- the planner may operationalize Alice's intent but may not invent an unrelated psychological goal;
- PlanStep declares one primitive;
- a Blueprint is optional and, if referenced, must match the PlanStep primitive.

## 4. Job start and direct time jump

The first ready PlanStep starts exactly one Job. World/temporal mechanics project arrival at 08:30 and the scheduler derives an ephemeral `JOB_EXPECTED_COMPLETION` ScheduledResolution.

Nothing else can affect the run before 08:30, so the clock advances directly from 08:00 to 08:30.

Expected properties:

- no per-minute ticks/events are produced;
- ScheduledResolution is not persisted as authoritative history;
- elapsed-time progress is resolved at the material boundary;
- completion commits through Events;
- the next already-planned step may start without another cognition call.

## 5. Observation and bounded interaction

Bob observes Alice entering the office through scenario perception mechanics. His DecisionTriggerPolicy creates a material DecisionPoint and Bob decides to ask Alice whether she has a moment.

The communication travels through the normal ActionProposal -> PlanStep -> Job -> resolution -> Event path. Alice receives an actor-relative Observation and a bounded `INTERACTION_REQUEST` DecisionPoint.

Alice responds: "Yes, but only for five minutes."

Expected properties:

- Observation != DecisionPoint;
- the same Event may create different actor-relative effects for different actors;
- bounded cognition does not automatically replace Alice's main Plan;
- any world-affecting bounded reaction still uses the normal execution/resolution path;
- no `DecisionOutcome -> WorldState` shortcut exists.

## 6. Scenario event and GEL

The run's deterministic random stream places a network outage at 09:12 from a `RANDOM_TIME` ScenarioEventRule.

At 09:12 the scheduler resolves the due scenario occurrence. The resulting world change becomes normal semantic Events.

A GEL mechanic computes Alice's new stress from explicit typed inputs such as current stress, interruption severity, and workload.

Expected properties:

- the distribution is scenario semantics while the seed/random stream is run configuration;
- replay does not resample the outage time;
- GEL has no direct access to mutable WorldState or host capabilities;
- GEL returns a typed calculation only;
- a normal candidate `SET_STATE_VARIABLE`/equivalent world effect and Event commit the state change;
- GEL failure/budget violation is an explicit mechanic error, never permission to guess.

## 7. Same-time resource conflict

At 10:00 Alice and Bob each have an active Job requiring the only available `TestEnvironment.capacity = 1` resource.

The scheduler gathers all due items at 10:00 before resolution. Because both Jobs interact through the same constrained resource, they form one conflict component and are resolved coherently.

Expected properties:

- heap/queue ordering does not decide the winner;
- same-time provider/order implementation details create no world causality;
- resolver may produce BLOCKED/PAUSED or another scenario-valid outcome;
- interacting Jobs may produce one joint atomic transition;
- resulting Event sequence is replay order, not evidence of causality;
- both actors may receive DecisionPoints if a new choice is required.

## 8. Commitment due

A meeting Commitment becomes due at 11:00 and causes a material scheduler resolution/Observation.

Expected properties:

- Commitment can project a future due point;
- due Commitment does not force attendance;
- actor may comply, revise Plan, refuse, or violate the Commitment;
- social/legal/normative rule does not imply mechanical enforcement.

## 9. Failure after world change

Alice's report-work Blueprint assumed database access. Access is revoked before the Job's next material checkpoint.

Execution-time capability evaluation discovers that the relevant authorization/mechanical requirement is no longer satisfied. The Job fails or pauses according to scenario mechanics.

Expected properties:

- feasibility is contextual, not certified globally by Blueprint;
- capability is re-evaluated at execution time;
- normal infeasibility is a valid world outcome, not an integrity error;
- `JobFailed`/`JobPaused` is persisted;
- DecisionTriggerPolicy may create `JOB_FAILED`/`JOB_PAUSED` DecisionPoint;
- retry after a terminal Job uses a new PlanStep/new Job, normally under a new Plan revision.

## 10. Replay

All external providers/resolvers/random samplers/GEL execution are disabled and the recorded branch is reconstructed solely from Event history and deterministic projections.

Expected properties:

- materially equivalent WorldState, ExecutionState, and CognitionState are reconstructed;
- recorded Observations, DecisionPoints, Decisions, Plans, and Jobs are restored without calling providers;
- replay never calls LLMs, humans, planners, world resolvers, GEL, or random samplers to rediscover history;
- snapshots, if present, are only optimization.

## 11. Branching before a decision

Fork the branch at the committed transition boundary immediately before Alice answers Bob.

In the new branch Alice's DecisionProvider is invoked when the pending DecisionPoint is reached and returns a different response: she refuses and continues the report work.

Expected properties:

- shared prefix is immutable;
- new Events belong only to the new branch continuation;
- original branch is unchanged;
- provider may be called again because the fork occurred before the recorded decision;
- no partial state inside one atomic `transition_id` is exposed as a valid fork point.

## 12. Branching after a decision

Fork immediately after Alice's recorded acceptance decision.

Expected properties:

- the branch inherits the already-recorded decision and Plan state;
- ordinary continuation does not ask the provider to decide the historical answer again;
- changing that answer requires an earlier fork or explicit intervention/regeneration that creates new history.

## 13. Scheduler rebuild equivalence

Run the deterministic acceptance scenario twice:

- once with incremental scheduler-index maintenance;
- once rebuilding the entire ScheduledResolution index after every committed transition.

Expected property:

```text
same inputs + deterministic providers/mechanics
=> same authoritative Event history
```

This test detects hidden scheduler authority.

## 14. Acceptance criteria for the first vertical slice

A minimal implementation passes the architectural acceptance scenario when it can demonstrate:

- atomic semantic Event commits;
- deterministic projection/replay;
- branch isolation/fork reconstruction;
- Entity/Relation/Resource/StateVariable mutation through Events only;
- PlanStep -> exactly one Job once started;
- event-driven clock jumps without hidden ticks;
- ephemeral/rebuildable scheduler index;
- same-time conflict grouping;
- actor-relative Observation and DecisionPoint behavior;
- no historical provider regeneration during replay;
- GEL side-effect isolation once GEL is implemented.

Not every rich domain detail is required in the first executable slice; the architecture/invariants are the acceptance target.
