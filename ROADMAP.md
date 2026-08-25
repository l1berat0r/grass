# GRASS Roadmap

This roadmap is intentionally coarse. It identifies design and implementation milestones without turning unresolved architecture into premature implementation tasks.

## Design track

### Initial conceptual architecture draft

**Status: in refinement**

Defines the project's current core thesis and concepts: `Actor`, world/perceived-state separation, configurable dynamics, provider independence, open intentions with validated mechanics, information provenance, human intervention and actor possession, event-sourced history, branching, and analyst/observer surfaces.

### Before the first design baseline

Refine the conceptual architecture directly where needed. Use draft ADRs to capture candidate decisions when useful, but do not treat the architecture as frozen yet.

Key topics to resolve or sharpen:

1. Formal `Actor` and common entity schemas.
2. `WorldDefinition` serialization and validation model.
3. Exact simulation lifecycle and phase boundaries.
4. Event schema, event-store contract, checkpoints, and branch restoration semantics.
5. Action proposal/interpreter/resolver contracts.
6. Information, claim, observation, and belief representation.
7. Safe scenario-defined dynamics/runtime.
8. DecisionProvider / ModelProvider contracts.
9. Memory representation and retrieval boundaries.
10. Conversation duration and long-running action semantics.
11. Developer-facing CLI/observer API and later UI technology.

## Implementation track

Implementation begins after enough of the design track is stable to define bounded contracts.

### Engine 0.1 — deterministic minimal core

- typed world and actor identities;
- logical clock;
- deterministic scripted/random decision provider;
- minimal action proposal and resolution path;
- configurable scalar state variables;
- immutable events;
- tests for core invariants.

### Engine 0.2 — history and replay

- EventStore interface;
- deterministic replay;
- checkpoints;
- state reconstruction tests.

### Engine 0.3 — branching

- branch ancestry and fork points;
- branch-local continuation;
- branch isolation tests;
- basic branch comparison metadata.

### Engine 0.4 — scenarios

- formal WorldDefinition loader/validator;
- scenario-defined state/resources/rules;
- safe dynamics mechanism selected by ADR.

### Engine 0.5 — cognition providers

- DecisionProvider abstraction;
- fake/scripted provider;
- HumanDecisionProvider boundary;
- remote LLM adapter;
- local/Ollama or OpenAI-compatible adapter;
- provider metadata capture.

### Engine 0.6 — information and social interaction

- observations, claims, messages, channels;
- one-to-one and one-to-many delivery;
- information provenance and retransmission;
- basic belief-update boundary.

### Engine 0.7 — operator controls

- in-world interventions;
- explicit simulation overrides;
- actor possession;
- provenance for all operator actions.

### Engine 0.8 — observer and analyst foundations

- step/run/pause developer interface;
- event and actor inspection;
- bounded/hierarchical simulation summaries;
- analyst references back to source events.

## Explicitly later

- `CollectiveActor` behavior;
- autonomous `InstitutionActor` behavior;
- distributed society-scale execution;
- dynamic population resolution;
- rich graphical UI and animated relationship graphs;
- calibrated domain models and scientific validation tooling.
