# ADR-0025: Local CLI and JSON presentation contract v1

- Status: Accepted
- Date: 2026-09-20

## Context

ADR-0019 established the transport-neutral Application/Query boundary, and
ADR-0024 supplied the local lifecycle, query, branching, and verification APIs.
Slice 16 needs a permanent local interface without creating another execution
path, exposing write-capable persistence, or freezing future HTTP and UI
contracts.

The CLI also needs deterministic machine output, explicit behavior for the
recoverable registered-but-uninitialized lifecycle state, and a terminal
implementation of the existing human decision source. The production runtime
composition remains the occurrence-only subset accepted by ADR-0023.

## Decision

### Authority and composition

The CLI is an `argparse` client of `LocalSimulationApplication` and
`LocalSimulationQueries`. It never receives an EventStore, commits Events,
mutates projections, or owns scheduler state. Commands that may change history
use `create_run`, `open_run`, or `OpenedRun`; inspection uses Query APIs.

The production composition root uses `OccurrenceRuntimeComposer`, SQLite at
`<data-root>/grass.db`, and package snapshots at
`<data-root>/world_snapshots/`. The default data root is exactly
`Path.cwd() / ".grass"`; `--data-dir` replaces it. RunIds remain
Application-generated canonical UUID strings, and Slice 16 adds no aliases.

`world validate` loads the complete WorldPackage, creates the default
`SimulationRunConfig`, and invokes the production composer's side-effect-free
`validate` method. `run create` uses that same default configuration and does
not synthesize provider bindings.

### Command and lifecycle behavior

The v1 command surface covers world validation, run create/list/status/step/
advance/verify, branch list/create, state and Event inspection, Job and Decision
inspection, actor-focused inspection, and persisted non-secret configuration
and provider-binding inspection. `advance` exposes target logical time and a
step budget, not an `--until-idle` mode.

Status remains read-only. A valid registered run with an empty parentless root
is reported as requiring recovery and is not opened. Step and advance may open
the run and therefore perform the ADR-0024 idempotent genesis recovery.

The run catalog processes durable registrations independently. `OK`,
`RECOVERABLE`, and `INVALID` are CLI presentation values, not persisted state
or additions to `RunStatus`. The Query API exposes registration records and a
typed empty-root condition so the CLI does not inspect persistence or match
exception text.

Branch creation first queries the parent once, retains that exact
`HistoryPosition`, opens the run, and creates the child at the captured
position. It is never a symbolic fork-at-current-head operation.

### JSON presentation contract

JSON v1 uses exactly one stdout document:

```text
{"schema_version":1,"command":"...","data":{...}}
{"schema_version":1,"command":"...","error":{"code":"...","message":"..."}}
```

Serializers are explicit and independent of private persistence codecs.
Identifiers are strings, logical times are integer nanoseconds, maps and sets
have deterministic ordering, and complete atomic transitions remain grouped.
Positions distinguish the viewed branch from the origin branch of the exact
transition reference. Event output includes complete provenance, explicit
causation references, and correlation identity.

Operational datetimes are normalized to UTC and emitted as
`YYYY-MM-DDTHH:MM:SS`, without microseconds or a suffix. JSON schema version 1
belongs to this CLI only and does not pre-decide a future HTTP wire format.

Prompts and warnings use stderr. Exit 0 represents valid results, including
normal runtime stop reasons; exit 1 represents handled execution, integrity,
or storage failures; exit 2 represents usage failures; and exit 130 represents
interruption. Stable error codes, rather than Python exception class names, are
the machine contract.

### Human decisions and provider inspection

`CliHumanDecisionSource` displays only an actor-relative `DecisionRequest` and
accepts one strict structured decision document from stdin. Plan drafts use
local step keys. Trusted CLI code allocates Plan and PlanStep identities after
validation, so users never invent authoritative identities. Acquisition still
passes through `HumanDecisionInvoker`, runtime validation, provenance, and the
normal engine commit path.

The terminal source is testable with an installed trusted actor-capable
composer, but ordinary Slice-16 package runs remain occurrence-only. Provider
inspection exposes only persisted routing and binding metadata. It never shows
credentials, environment secrets, invoker objects, probes, or account status.

## Consequences

- local users and scripts gain one stable interface over the existing runtime;
- CLI execution cannot bypass engine authority or replay semantics;
- interrupted creation is visible without making status a write operation;
- exact branch positions and atomic transition boundaries survive presentation;
- JSON changes now require deliberate CLI schema versioning;
- catalog verification may be relatively expensive, but it is correct for the
  bounded local baseline and can later be optimized behind Query APIs;
- the human terminal adapter exists before ordinary packages can configure an
  actor-capable runtime composition.

## Deferred details

- friendly run aliases and authored SimulationRunConfig files;
- provider profiles, credentials, connectivity probes, and client-managed
  decision submission;
- actor bootstrap and actor-capable ordinary WorldPackages;
- templates and examples from Slice 17;
- historical-position selectors, pagination, filtering, and derived indexes;
- branch rename, delete, merge, and rebase;
- Diagnostics and low-level Debug APIs;
- XDG/global configuration, shell completion, colors, and a TUI;
- HTTP, FastAPI, WebSocket, and frontend interfaces.

## Alternatives considered

### Let the CLI read or write EventStore directly

Rejected because it would create a second authority path and expose arbitrary
Event commit capability.

### Recover genesis while inspecting status

Rejected because a read command must not change canonical history.

### Serialize dataclasses or reuse persistence codecs

Rejected because private storage representation and Python implementation
details are not a stable public wire contract.

### Add aliases or global configuration in v1

Rejected because UUID RunIds and one explicit local data root are sufficient to
prove the interface without introducing mutable naming or configuration rules.

### Expand production world composition for terminal decisions

Rejected because actor bootstrap and actor-capable authored worlds require a
later architecture decision, not a CLI convenience exception.
