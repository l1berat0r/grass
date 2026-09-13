# ADR-0021: Runnable WorldPackages and templates

- Status: Accepted
- Date: 2026-09-13

## Context

GRASS 0.1 should be usable by a scenario author without requiring changes to GRASS Python source code. The existing architecture already separates immutable WorldDefinition semantics, GEL, provider bindings, and trusted resolution/validation boundaries, but GEL is currently a standalone runtime and test scenarios still supply Python-specific mechanics/resolvers.

A practical authored world may also require multiple supporting files such as GEL programs, prompts, and documentation. Treating every world as one monolithic JSON document would conflate semantic identity with package delivery.

New users also need executable examples rather than starting from an empty schema.

## Decision

### Data-defined ordinary worlds

A normal local-0.1 world must be runnable without importing arbitrary user Python modules or modifying GRASS source code.

The trusted runtime-composition layer may combine:

```text
WorldDefinition
    + built-in mechanics
    + GEL mechanics
    + scenario rules
    + provider bindings
    -> existing resolution/provider/validation contracts
```

Built-in and GEL mechanics remain candidate-producing logic below the existing engine authority boundary. They never commit authoritative state directly.

Trusted installed `IMPLEMENTATION`/plugin mechanics remain a possible advanced extension point, consistent with ADR-0004, but they are not required for the ordinary v0.1 authoring workflow.

### WorldPackage

Introduce `WorldPackage` as an application/delivery concept distinct from the immutable semantic `WorldDefinition`.

Conceptually:

```text
WorldPackage
    world definition document
    referenced GEL programs
    optional prompts/supporting authored resources
    documentation/metadata
```

A package may be represented by a directory or another future container format. The exact packaging/distribution format is not frozen by this ADR.

`WorldDefinition` remains the semantic world/version consumed by the simulation contracts. `WorldPackage` describes the material authored inputs needed to construct/validate a runnable world.

### Reproducibility

Creating a run must preserve or snapshot the exact material package inputs needed for continuation and reproducibility rather than depending on later mutable files in the author's working directory.

Material GEL source, language version, schemas, and other mechanics content must therefore remain recoverable for the run where required.

### Templates

Templates are ordinary valid WorldPackages executed through the same loader, validation, composition, persistence, and runtime paths as user-authored worlds.

They do not receive hidden mechanics, privileged Event injection, or test-only runtime behavior.

The local 0.1 template set should include at least:

- a minimal actor-interaction world;
- a shared-resource conflict world;
- a small multi-actor team/social world.

Templates serve as authoring starting points, executable documentation, and end-to-end regression/acceptance worlds.

## Consequences

- users can author useful simple scenarios without becoming GRASS Python developers;
- GEL becomes integrated with actual scenario/runtime composition rather than remaining only a standalone interpreter;
- ordinary scenario files cannot silently escape the GRASS trust boundary through arbitrary Python imports;
- authored source layout can evolve independently from immutable WorldDefinition semantics;
- templates exercise exactly the same production paths as user worlds and therefore provide strong end-to-end examples.

## Deferred details

- exact WorldPackage manifest/layout/schema;
- exact built-in mechanic catalogue;
- prompt-template format and versioning;
- package dependency/version resolution;
- remote package registry/distribution/signing;
- plugin installation/trust model for advanced IMPLEMENTATION mechanics;
- UI-assisted world authoring.

## Alternatives considered

### Require Python resolver/mechanic classes for each new world

Rejected because it makes GRASS primarily a framework for programmers rather than a data-driven simulator and weakens ordinary scenario isolation.

### Put all supporting source inside one WorldDefinition JSON document

Rejected because semantic world identity and authored package delivery have different responsibilities and multi-file GEL/supporting content is likely to become natural.

### Make templates special built-in scenarios

Rejected because they would stop validating the real user authoring/runtime path and create parallel semantics.
