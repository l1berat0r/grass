# GRASS — GRASS Roots Agentic Systems Simulator

GRASS is a general-purpose, AI-assisted simulation engine for dynamic human and social systems.

A scenario may represent a corporation, political party, state, community, expedition, or another social environment without embedding domain-specific assumptions in the core engine.

The central architectural principle is:

> **The simulation engine owns reality; cognition providers propose behavior.**

LLMs, humans, scripts, or deterministic decision providers may propose intentions, interpret observations, communicate, form beliefs, and choose strategies. Only the simulation engine may validate actions, resolve conflicts, mutate authoritative world state, and emit historical events.

## Project status

GRASS is currently in the **design phase**. The first implementation has not started yet.

The initial architecture is being designed around these principles:

- `Actor` is the fundamental participant abstraction.
- The first implementation focuses on individual actors while preserving extension points for future collective and institutional actors.
- World state is authoritative; actors perceive only a subset of it.
- State variables and dynamics are scenario-defined rather than hard-coded into the core.
- Actor cognition is provider-independent and may use hosted LLM APIs, local models such as Ollama, humans, scripts, or deterministic strategies.
- Actions may be creatively proposed, but only validated simulation mechanics may change the world.
- Information has provenance and is distinct from belief.
- History is event-sourced, replayable, and branchable for counterfactual experiments.
- Human operators may observe, intervene in-world, explicitly override simulation state, or temporarily control actors.
- Ethics and legality belong to the modeled world and actor preferences rather than a hard-coded moral policy in the simulation core.

## License

GRASS is intended to be released under the **GNU General Public License v3.0 only (GPL-3.0-only)**.

A full `LICENSE` file and the initial architecture documents will be added as the design baseline is committed.
