# ADR-0002: Replaceable capability and feasibility evaluation

- Status: Draft
- Date: 2026-09-02

## Context

GRASS needs to evaluate constraints around concrete actor attempts without collapsing distinct concepts such as physical possibility, technical possibility, authorization, preventive enforcement, and detectability into one permission flag.

The initial implementation needs a useful feasibility model, but the project is still pre-baseline and there is not enough evidence to treat one particular capability ontology as permanent. The engine must therefore be able to evolve toward a rule-based, graph-based, probabilistic, generative, or other evaluator without requiring changes throughout actors, jobs, scheduling, event sourcing, or authoritative state transitions.

Capability evaluation also represents authoritative/current world mechanics, not actor belief. An actor may attempt something because it incorrectly believes access exists, or fail to propose something that is objectively possible because its perceived world is incomplete.

## Decision

Capability and feasibility evaluation is a replaceable architectural boundary.

Conceptually:

`CapabilityEvaluator.evaluate(context) -> CapabilityAssessment`

The evaluator describes mechanically or normatively relevant facts and constraints that can be derived from the current world context. It does not mutate authoritative state and it does not replace `WorldResolutionProvider`, which still adjudicates the concrete attempt and produces the candidate resolution outcome.

The default v0.1 evaluator MAY use a multidimensional assessment containing dimensions such as:

- `physical`;
- `technical`;
- `authorization`;
- `preventive_enforcement`;
- `detectability`.

A simple initial dimension value MAY be `SATISFIED`, `UNSATISFIED`, or `UNKNOWN`, together with structured constraint/explanation metadata where useful.

This shape is intentionally provisional. Core components MUST NOT depend on every future `CapabilityAssessment` containing exactly these five dimensions. The assessment representation and evaluator policy SHOULD be versionable and carry sufficient provenance for reproducibility when evaluator changes can affect simulation outcomes.

The initial model follows these semantics:

1. **Physical possibility** asks whether relevant physical conditions permit the attempt.
2. **Technical possibility** asks whether the required technical means, interface, control, or mechanism exists.
3. **Authorization** asks whether applicable rules or norms grant permission.
4. **Preventive enforcement** asks whether the world actually blocks an unauthorized or otherwise disallowed attempt.
5. **Detectability** asks whether the attempt or result can create traces or observations available to other actors or systems.

`unauthorized != impossible`.

An actor may be unauthorized yet still physically and technically capable of attempting an action if no preventive mechanism stops it. Detectability likewise does not itself block execution; it may instead produce traces, observations, information flow, or later institutional/social consequences.

The evaluator SHOULD derive capability dynamically from world context, potentially including:

- actor/entity state;
- relations;
- resources;
- location/presence;
- controlled entities;
- roles and memberships;
- scenario rules;
- current environmental or execution conditions.

Core GRASS SHOULD avoid static domain-action catalogs such as `actor.can_restart_server` or `actor.capabilities = ["hire_employee", ...]` as the primary capability representation.

`CapabilityAssessment` SHOULD NOT expose a mandatory universal `can_execute: bool` that collapses these distinctions back into a permission engine. `WorldResolutionProvider` interprets the assessment together with the concrete blueprint/job, resources, authoritative world state, and resolution mode.

`UNKNOWN` means that the selected evaluator cannot establish the dimension from its current mechanics. It MUST NOT silently mean either success or failure. Exact deterministic handling of unresolved/unknown feasibility remains a later resolver-policy decision.

## Replaceability constraints

To preserve future flexibility:

1. `CapabilityEvaluator` MUST remain behind a replaceable boundary.
2. `Actor`, `Job`, the scheduler, event store, and authoritative transition APIs MUST NOT embed the v0.1 five-dimension schema as their own permanent state model.
3. `WorldResolutionProvider` MUST NOT assume that all future evaluators expose exactly the same dimension set.
4. Scenario rules may provide inputs to an evaluator, but scenario definitions SHOULD NOT become coupled to one evaluator implementation when a more generic representation is practical.
5. Authoritative capability assessment remains distinct from actor perception/belief.
6. Replacing an evaluator MUST NOT change the rule that only validated events/reducers commit authoritative world state.

## Consequences

### Positive

- v0.1 can use a concrete, understandable model without turning it into permanent core ontology.
- Authorization and actual enforcement remain separate, allowing rule violations and imperfect controls to be simulated.
- Detectability can drive information flow and later reactions rather than acting as an implicit blocker.
- Different feasibility approaches can be compared experimentally without redesigning the simulation engine.
- Actor misconceptions remain possible because objective feasibility is not stored as actor knowledge.

### Costs

- Resolver integration cannot rely on one convenient universal `can_execute` flag.
- Assessment formats and evaluator provenance may require versioning.
- `UNKNOWN` requires an explicit policy at the resolver boundary rather than a convenient implicit default.
- Some scenario mechanics will need generic inputs that can be interpreted by more than one evaluator implementation.

## Deferred details

The following are intentionally not fixed by this ADR:

- the exact `CapabilityAssessment` DTO/schema;
- the final set or number of assessment dimensions;
- the exact structured constraint vocabulary;
- whether dimensions remain ternary or become richer/probabilistic;
- deterministic resolver behavior when material feasibility remains `UNKNOWN`;
- caching/invalidation strategy for capability assessments;
- whether future evaluators may use LLMs or other learned models internally.
