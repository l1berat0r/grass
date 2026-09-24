# GRASS — GRASS Roots Agentic Systems Simulator

GRASS is a general-purpose, AI-assisted simulation engine for dynamic human and social systems.

A scenario may represent a corporation, political party, state, community, expedition, or another social environment without embedding domain-specific assumptions in the core engine.

The central architectural principle is:

> **Only the simulation engine commits reality. Decision providers propose actor behavior; world-resolution providers determine candidate outcomes.**

LLMs, humans, scripts, deterministic providers, planners, and world resolvers may propose behavior or candidate outcomes. Authoritative state changes are committed only by the simulation engine as validated immutable Events.

## Project status

The initial architecture is baselined as **`design-0.1`**. Slices 0–17 are implemented on the current implementation branch, including the event-sourced/branchable core, scheduler, world resolution, perception/DecisionPoints, executable acceptance scenario, GEL, provider adapters, production runtime orchestration, durable SQLite persistence, data-defined WorldPackage composition with per-run snapshots, transport-neutral Application/Query APIs, the permanent local CLI, and reusable occurrence-only WorldPackage template infrastructure.

The next architecture activity is the post-Slice-17 **Diagnostics Architecture** checkpoint. Actor-capable ordinary WorldPackage composition and actor templates are planned for Slice 18 only after their required architecture is accepted.

Start here:

- [Architecture baseline](docs/DESIGN.md)
- [Local CLI](docs/CLI.md)
- [Local GRASS 0.1 runtime](docs/LOCAL_0_1_RUNTIME.md)
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
- ordinary local-0.1 worlds should be runnable without modifying GRASS Python source;
- authored multi-file worlds may be delivered as `WorldPackage`s while `WorldDefinition` remains the immutable semantic definition;
- actions express intention; Plan/PlanStep/Job represent intended and concrete execution; only world resolution + validation + Events commit outcomes;
- the scheduler is event-driven, has no mandatory global tick, and its `ScheduledResolution` index is ephemeral/rebuildable;
- information has provenance and is distinct from observation/belief;
- history is replayable and branchable for counterfactual experiments;
- human and model-backed decisions use the same non-authoritative proposal boundary;
- local persistence must preserve canonical history without turning derived projections/query views into competing truth;
- CLI, future HTTP APIs, and future UI are clients of Application/Query APIs and do not receive direct write authority over simulation history.

## Local 0.1 target

A representative target workflow is:

```text
grass template init occurrence-counter ./demo
grass world validate ./demo
grass run create ./demo
# Retain the generated UUID as RUN.
grass branch create RUN --from root --branch-id alternative
grass run advance RUN
grass run advance RUN --branch alternative
grass inspect state RUN
grass inspect events RUN
grass run verify RUN
```

Runs should survive process restarts through local persistence. Templates are ordinary valid WorldPackages and should exercise the same production runtime path as user-authored worlds.

## Development methodology

`design-0.1` is the first design baseline. Implementation details that preserve accepted contracts may be decided locally, while material changes to authority, persistence, replay, provider, action, scheduler, world-resolution, scenario-mechanics, or application/runtime boundaries should normally use an ADR first.

Design baselines and executable software releases are versioned separately.

After the local 0.1 milestone, the next implementation order should be chosen from evidence gathered from real runs rather than from a precommitted frontend-first sequence.

## License

GRASS is licensed under the **GNU General Public License version 3 only (GPL-3.0-only)**. See [LICENSE](LICENSE).
