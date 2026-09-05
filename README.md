# GRASS — GRASS Roots Agentic Systems Simulator

GRASS is a general-purpose, AI-assisted simulation engine for dynamic human and social systems.

A scenario may represent a corporation, political party, state, community, expedition, or another social environment without embedding domain-specific assumptions in the core engine.

The central architectural principle is:

> **Only the simulation engine commits reality. Decision providers propose actor behavior; world-resolution providers determine candidate outcomes.**

LLMs, humans, scripts, deterministic providers, planners, and world resolvers may propose behavior or candidate outcomes. Authoritative state changes are committed only by the simulation engine as validated immutable Events.

## Project status

The initial architecture is baselined as **`design-0.1`**. Implementation may now proceed in bounded vertical slices. Material changes to core architectural contracts should normally be proposed through ADRs and reflected in the current design document.

Start here:

- [Architecture baseline](docs/DESIGN.md)
- [Acceptance scenario](docs/ACCEPTANCE_SCENARIO.md)
- [Coding-agent instructions](AGENTS.md)
- [Roadmap](ROADMAP.md)
- [Architecture Decision Records](docs/adr/README.md)

## Core ideas

- committed Event history is the canonical source of truth;
- `SimulationState` is reconstructed as distinct `WorldState`, `ExecutionState`, and `CognitionState` projections;
- `Entity` is the persistent identity anchor; actor capability is entity-backed composition;
- actors perceive only actor-relative information, never unrestricted world truth;
- state variables, resources, event rules, and world mechanics are scenario-defined;
- `WorldDefinition` is separate from experimental `SimulationRunConfig`;
- simple mechanics may use built-ins, LLM-generated safe mechanics may use GEL, and advanced trusted models may use installed implementations/plugins;
- actions express intention; Plan/PlanStep/Job represent intended and concrete execution; only world resolution + validation + Events commit outcomes;
- the scheduler is event-driven, has no mandatory global tick, and its `ScheduledResolution` index is ephemeral/rebuildable;
- information has provenance and is distinct from observation/belief;
- history is replayable and branchable for counterfactual experiments;
- human operators may observe, intervene in-world, explicitly override simulation state, or temporarily possess actors;
- deterministic and generative world resolution share the same structural authority boundaries.

## Development methodology

`design-0.1` is the first design baseline. From this point, implementation details that preserve the baseline may be decided locally, while material changes to authority, persistence, replay, provider, action, scheduler, world-resolution, or scenario-mechanics contracts should normally use an ADR first.

Design baselines and executable software releases are versioned separately.

## License

GRASS is licensed under the **GNU General Public License version 3 only (GPL-3.0-only)**. See [LICENSE](LICENSE).
