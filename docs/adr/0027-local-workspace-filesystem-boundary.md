# ADR-0027: Local workspace filesystem boundary

- Status: Accepted
- Date: 2026-10-04

## Context

The local CLI already selects `Path.cwd() / ".grass"` by default and allows `--data-dir`
to replace it, but path derivation was repeated across the composition root. Template
initialization also treated its second positional argument as a path, so a logical name
such as `test` wrote to `./test`. Bundled and rewritten template validation additionally
used the operating system temporary directory, and SQLite could select external temporary
query storage.

These behaviors made the workspace root an incomplete boundary even though Core and the
transport-neutral Application correctly had no knowledge of the CLI layout.

## Decision

One CLI-owned immutable path value derives every implicit local path from the selected
workspace root. The default root remains exactly `Path.cwd() / ".grass"`, and `--data-dir`
replaces it. Current managed children are `grass.db`, `worlds/`, `world_snapshots/`,
`runs/`, `templates/`, and `templates/worlds/`.

`template init TEMPLATE [WORLD_NAME] [--output PATH]` distinguishes logical identity from
placement. Without `--output`, the destination is `worlds/<world-name>/` beneath the
workspace; the name defaults to the template name. With `--output`, the destination is an
explicit external path. If both name and output are supplied, the output basename must
equal the name because a format-1 WorldPackage directory basename equals its
`world_definition_id`.

Explicit package inputs and output paths are not workspace-managed state and may refer
outside the root. CWD is used only to select the default root, never as a separate implicit
artifact destination.

Bundled template and rewritten pre-publication material are validated from in-memory bytes
through the same package parsing and production-composition rules used by directory
loading. Published material is still reloaded from disk. SQLite connections use
memory-backed temporary storage; database journals and other sidecars remain adjacent to
`grass.db`.

## Consequences

- all current implicit local CLI filesystem state is contained by one selected root;
- template list/show perform no filesystem writes;
- default template initialization creates only the workspace and editable-world roots;
- explicit external authoring remains available but is syntactically visible;
- Core, Event authority, replay, branching, and transport-neutral Application contracts
  remain unchanged;
- no cache, runtime, or temporary workspace directory is introduced without a concrete
  need.

## Alternatives considered

Keeping a positional destination was rejected because relative logical-looking values are
indistinguishable from accidental CWD-relative output. Moving template scratch files under
the workspace was rejected because parsing trusted byte material directly removes the
scratch write entirely. SQLite's deprecated process-global temporary-directory pragma was
rejected in favor of per-connection memory-backed temporary storage.
