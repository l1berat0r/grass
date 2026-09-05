# ADR-0004: WorldDefinition, run configuration, scenario events, and GRASS Expression Language

- Status: Accepted
- Date: 2026-09-05

## Context

GRASS needs a formal scenario definition that is expressive enough to describe very different worlds without hard-coding their domain semantics into core. At the same time, experimental choices such as which decision/model providers are used, whether world resolution is deterministic or generative, and which random seed is selected should not redefine the scenario itself.

Scenario authors also need more freedom than a fixed catalog of simple models such as minimum/maximum bounds or linear rates. LLM-assisted world building should be able to generate useful mechanics programmatically, but arbitrary generated Python/host-language execution would violate the security and reproducibility boundaries of the simulator.

GRASS also needs scenario-authored future occurrences: deterministic events scheduled for a known time and stochastic events whose occurrence time is sampled from a distribution.

## Decision 1: Separate WorldDefinition from SimulationRunConfig

`WorldDefinition` defines **what the scenario is and how its world behaves**. `SimulationRunConfig` defines **how one concrete experimental run executes that scenario**.

Conceptually:

```text
WorldDefinition
    world_definition_id
    version
    schema_version

    vocabulary
        entity_types
        relation_types
        resource_types
        state_variable_types
        channel/information types?

    mechanics
        blueprints
        primitive_mechanics
        resource_mechanics
        state_variable_mechanics
        temporal_mechanics
        scenario_event_rules
        capability_evaluator_binding
        perception_mechanics
        decision_trigger_policy_binding
        validation_mechanics?

    initial_conditions
        logical_time
        entities
        actor_facets
        relations
        resources
        state_variables
        information?
        commitments?

    termination_rules?
    metadata
```

The exact DTO/schema remains provisional; the architectural boundary is accepted.

A used `WorldDefinition` version is immutable. A material change to scenario semantics creates a new version.

The following do **not** belong in `WorldDefinition`:

- runtime `WorldState`;
- committed `Event`s/history;
- Jobs, Plans, DecisionPoints, actor beliefs/memory;
- branch/checkpoint state;
- ephemeral scheduler projections/indexes such as `ScheduledResolution`;
- API/database/frontend/credential configuration;
- concrete provider/model selection for one run;
- a particular resolver mode or random seed when these are experimental run choices.

`SimulationRunConfig` conceptually contains:

```text
SimulationRunConfig
    world_definition_ref

    resolution_mode
    world_resolution_provider_binding

    decision_provider_bindings
    model_provider_bindings

    random_seed / random stream configuration
    execution_options
    reproducibility_options
```

This allows the same versioned world to be executed repeatedly under different deterministic/generative resolvers, cognition providers, models, or random seeds without redefining scenario truth.

## Decision 2: InitialConditions are declarations, not Events

`WorldDefinition.initial_conditions` describe the intended starting state of a scenario. They are not themselves historical event records because event identity, branch identity, sequence, provenance, and concrete run metadata belong to an actual run.

Starting a run performs a validated initialization/genesis transition:

```text
WorldDefinition.initial_conditions
    ↓
validation / initialization transition
    ↓
genesis Event batch
    ↓
initial authoritative WorldState
```

The exact number/type of genesis events is deferred.

Scenario-defined blueprints belong to `WorldDefinition`. Blueprints created by actors during a simulation belong to runtime authoritative state/history.

## Decision 3: Scenario event rules

`WorldDefinition` may define `ScenarioEventRule`s that describe future material occurrences.

Conceptually:

```text
ScenarioEventRule
    rule_id
    trigger
    mechanic / resolution binding
    enabled
    metadata?
```

Initial trigger families should support at least:

- `AT_TIME` — occur/reconsider at a concrete logical time;
- `AFTER_DURATION` — occur/reconsider after a configured delay from an anchor;
- `RANDOM_TIME` — sample an occurrence time from a configured probability distribution.

Later recurrence/condition-based triggers may be added without changing the architectural distinction.

A scenario event rule is **not** a committed Event. The scheduler may derive an ephemeral `ScheduledResolution` from it; when due, the normal temporal/world-resolution path determines candidate effects and commits actual Events.

```text
ScenarioEventRule
    ↓
derived ScheduledResolution
    ↓
resolution/mechanic
    ↓
ResolutionProposal / WorldEffects
    ↓
authoritative validation
    ↓
Event(s)
```

The configured distribution belongs to `WorldDefinition`; random seeds/stream configuration belong to `SimulationRunConfig`.

Material random choices must be reproducible. A run should avoid one accidental process-global random stream whose call ordering causes unrelated mechanics to perturb one another. The exact design is deferred, but keyed/sub-stream RNG based on run seed + mechanic/rule identity + occurrence identity is a preferred direction. Alternatively, material sampled outcomes may be recorded with sufficient provenance to support replay and analysis.

Ordinary replay never resamples already-committed history.

## Decision 4: Mechanic bindings are extensible

Built-in formulas are convenience models, not the expressiveness boundary of GRASS.

Scenario mechanics should use a common conceptual binding that can select at least:

```text
MechanicBinding
    BUILTIN
    GEL
    IMPLEMENTATION
```

### BUILTIN

Core/library-provided, well-known mechanics for common cases, such as bounded linear evolution, constant rates, threshold rules, simple decay, or common distributions.

### GEL

A restricted interpreted scenario function written in **GRASS Expression Language (GEL)**. GEL is specifically designed to be safely generated by LLMs or humans and validated before use.

### IMPLEMENTATION

An explicitly trusted, installed scenario/plugin implementation written in normal host-language code. This is available for advanced models that cannot reasonably be represented by built-ins or GEL. Such code is trusted by explicit installation/authorization, not because an LLM generated it.

All three forms remain below the same world-resolution, validation, Event, reducer, and branch-authority boundaries. Selecting a more expressive mechanic never grants authority to mutate committed reality directly.

## Decision 5: GEL execution model

GEL is a versioned, deterministic DSL/interpreter boundary.

Conceptually:

```text
LLM/human generates GEL source
        ↓
parser
        ↓
AST
        ↓
static validation/type checking
        ↓
bounded safe interpreter
        ↓
typed result
```

Never:

```text
LLM output -> eval/exec host language
```

A GEL mechanic declares typed inputs and typed output. Canonical scenario data should preserve at least:

```text
GELMechanic
    language = GEL
    language_version
    input_schema
    output_schema
    source
    source_hash?
```

The parsed AST/interpreter bytecode may be cached as derived data but is not the canonical scenario definition.

### Explicit input capability

GEL may access only variables and read-only views explicitly supplied to the mechanic. It does not receive an unrestricted `WorldState` handle.

Examples of allowed explicit inputs might include:

```text
current_value
elapsed_time
actor
participants
resources
environment
target
```

but only fields exposed by the corresponding typed input contract are readable.

GEL has no ambient capability to access:

- filesystem;
- network;
- subprocess/process execution;
- environment variables;
- host database;
- imports/modules;
- reflection/introspection of the host runtime;
- dynamic code evaluation;
- arbitrary memory allocation;
- hidden global state.

This explicit-input design should also preserve the possibility of later dependency tracking: if a mechanic can read only declared fields, the scheduler/engine can eventually determine which state changes could invalidate a projection without requiring such dependency tracking in v0.1.

### Language features

The initial language may support:

- numbers, booleans, strings/enums where appropriate;
- typed objects/lists with bounded sizes;
- local variables;
- arithmetic;
- comparisons;
- boolean logic;
- `if` / `else`;
- safe built-in functions such as `min`, `max`, `clamp`, `abs`, and selected mathematical functions;
- bounded `for` iteration over supplied collections and/or bounded integer ranges;
- explicit return of a typed scalar or structured result.

The initial GEL SHOULD NOT support unrestricted `while`, recursion, imports, reflection, exceptions as arbitrary control-flow, concurrency, or dynamic code generation.

A later bounded-loop construct may be added if needed, but all control flow must remain statically/runtime bounded.

### Execution budgets

The interpreter must enforce hard limits such as:

- maximum source/AST size;
- maximum operations/execution steps;
- maximum loop iterations;
- maximum collection sizes;
- recursion depth (initially zero/no recursion);
- numeric bounds/NaN/overflow policy;
- wall-clock timeout or equivalent operation budget;
- maximum result size.

A parse/type/budget/runtime failure produces a mechanic execution error. The engine does not silently guess a result merely to keep the simulation moving.

In deterministic resolution, a deterministic GEL mechanic failure that prevents valid resolution is an implementation/scenario integrity failure consistent with the existing fatal-invalid-resolution policy. Generative repair behavior applies only where an explicit generative boundary is responsible for producing a candidate, not as an excuse to reinterpret broken deterministic mechanics.

## Decision 6: GEL is side-effect free with respect to authoritative state

GEL computes values; it does not own reality.

A GEL expression may return, for example:

- a new calculated value;
- a duration or next threshold time;
- a probability;
- a boolean/enum capability result;
- a structured result consumed by a scenario mechanic/resolver adapter;
- data from which a normal `ResolutionProposal` can be built.

GEL MUST NOT directly:

- mutate `WorldState`;
- append Events;
- alter Jobs/Plans outside normal transitions;
- write scheduler history;
- issue arbitrary scenario-defined mutation opcodes;
- bypass the closed core `WorldEffect` algebra or authoritative validator.

World-affecting output therefore remains:

```text
GEL result
    ↓
scenario mechanic / resolver adapter
    ↓
ResolutionProposal
    ↓
authoritative validation
    ↓
Events / reducers
```

## Decision 7: Randomness in GEL

If a GEL mechanic needs randomness, it receives an explicit deterministic random context/stream. GEL never reads a hidden process-global RNG.

The language may later expose controlled operations such as conceptually:

```text
random.uniform(...)
random.normal(...)
random.chance(...)
```

but their values must come from the run's reproducible random-stream architecture and be attributable to the mechanic invocation.

## Decision 8: GEL is reusable across scenario subsystems

The same GEL boundary may be used wherever a scenario needs a function rather than inventing a separate mini-language for every subsystem, including potentially:

- resource constraints/evolution/accessibility;
- state-variable evolution and thresholds;
- temporal projection and elapsed-time mechanics;
- scenario-event timing/conditions/resolution parameters;
- perception calculations;
- capability assessment;
- utility or scenario metrics;
- validation rules that are appropriate for scenario semantics.

Each usage provides its own typed input/output contract. GEL itself remains domain-neutral.

## Consequences

### Positive

- LLM-assisted world building can generate genuinely programmable scenario mechanics without host-code execution.
- Simple scenarios stay concise through built-ins while advanced scenarios retain an escape hatch through trusted plugins.
- The same world can be run under multiple provider/resolver/random configurations without versioning scenario semantics unnecessarily.
- Scenario events support both authored schedules and stochastic processes.
- GEL mechanics are inspectable, versioned, type-checkable, resource-bounded, and reproducible.
- Explicit inputs reduce security exposure and create a future path toward dependency-aware scheduler reprojection.

### Costs

- GEL requires a real parser, AST, validator/type checker, interpreter, versioning strategy, test suite, and security review.
- The language must remain intentionally smaller than a general-purpose programming language.
- Complex numerical/scientific models may require trusted plugins instead of GEL.
- Reproducible random streams need careful design so concurrency/order does not perturb unrelated stochastic mechanisms.

## Deferred details

This ADR intentionally does not freeze:

- final JSON/YAML schema of `WorldDefinition` and `SimulationRunConfig`;
- exact GEL textual syntax;
- exact GEL primitive types and standard-library functions;
- expression-vs-statement grammar details;
- exact AST representation;
- static dependency extraction algorithm;
- random-stream/key derivation algorithm;
- exact scenario-event recurrence/condition vocabulary;
- plugin packaging/sandboxing/distribution model;
- complete safe numeric policy;
- whether a future GEL compiler is added in addition to the interpreter.
