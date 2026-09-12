# ADR-0018: Minimal provider adapter contracts

- Status: Accepted
- Date: 2026-09-12

## Context

Slice 11 introduces asynchronous acquisition of actor decisions from model-backed
providers while retaining the cognition, atomic-transition, provenance, replay,
and security boundaries accepted by ADR-0004, ADR-0005, ADR-0007, ADR-0008,
ADR-0010, ADR-0012, and ADR-0015.

ADR-0015 deliberately defines a synchronous semantic policy boundary and leaves
production invocation, model transport, credentials, routing, raw-model
identifier allocation, and concurrency open. Network and human response latency
must not be confused with simulation logical time, and model transport must not
gain authority to prepare or commit a decision transition.

## Decision 1: Preserve DecisionProvider and add DecisionInvoker

The existing synchronous semantic policy boundary is unchanged:

```text
DecisionProvider.decide(DecisionRequest) -> DecisionProposal
```

Scripted, deterministic, and other in-process policies may continue to implement
that boundary directly. Slice 11 adds a separate asynchronous orchestration
boundary:

```text
await DecisionInvoker.invoke(DecisionRequest)
    -> DecisionInvocationResult
        proposal
        receipt
```

Trusted orchestration separately captures the exact immutable ADR-0015
`DecisionRequest`, the already-resolved non-secret binding, history position, and
logical time as an ephemeral `DecisionInvocationContext`. The invoker acquires
untrusted cognition from the DecisionRequest; it does not prepare Events, mutate
SimulationState, advance logical time, or commit.

Invocation and transition preparation are separate operations. A successful
invocation result is passed to the existing trusted decision-preparation path,
which remains responsible for complete Decision/Plan validation, authoritative
Event identities, provenance construction, expected-head validation, and atomic
commit through the EventStore.

## Decision 2: Generic asynchronous structured ModelProvider

Model transport is below decision policy and has no GRASS decision semantics:

```text
await ModelProvider.invoke(ModelRequest) -> ModelResponse
```

`ModelRequest` identifies the selected model and contains adapter-rendered input,
generation parameters, and an exact structured-output schema. `ModelResponse`
contains the returned structured value and transport metadata needed to construct
an invocation receipt. It does not contain a DecisionProposal, Events,
WorldEffects, or replacement state.

A model-backed DecisionInvoker translates the actor-relative invocation request
to a generic ModelRequest, requires schema-conforming structured output, and
translates that output to a typed DecisionProposal. Provider-native payloads,
SDK objects, tool calls, and transport errors do not cross the ModelProvider
boundary as authoritative domain values.

The initial production transports are the OpenAI Responses API and a deliberately
limited structured-output Chat Completions contract for explicitly installed or
operator-trusted OpenAI-compatible endpoints, including Ollama's compatible API.
Endpoint origins are deployment configuration, not model output or arbitrary
per-run URLs. This is not an unrestricted provider proxy, and native Ollama,
tool-execution, or arbitrary OpenAI-compatible surface support is not implied.

## Decision 3: Non-secret deterministic routing

One run may declare immutable, non-secret decision routing configuration with:

- one run-default binding when provider routing is configured;
- named routing-group bindings;
- at most one routing-group assignment for each actor;
- optional actor-specific bindings.

Binding precedence is exactly:

```text
actor-specific binding
    > the actor's one routing-group binding
    > run-default binding
```

The first present binding is the complete selected route. A missing route,
unknown binding, unavailable adapter, or invalid provider/model configuration is
an explicit failure. There is no implicit provider, model, route, retry, or
fallback. A configured failure never falls through to the next precedence level.

Bindings and receipts may identify providers, adapters, models, and routing
groups, but contain no API keys, bearer tokens, cookies, credential references
that reveal a secret, or secret-bearing headers. Credentials are supplied to the
adapter by its execution environment and are never part of SimulationRunConfig,
DecisionRequest, model input, or Event provenance.

## Decision 4: GRASS owns identities

Raw model output does not allocate or choose GRASS identifiers. Existing actor,
Observation, DecisionPoint, subject-Plan, and other references are supplied from
the exact DecisionRequest. When model output requires a new Plan or PlanSteps,
the trusted decision adapter assigns the required nominal GRASS `PlanId` and
`PlanStepId` values through an explicit ID source while preserving ADR-0012 and
ADR-0015 version/revision/replacement rules.

The trusted preparation caller continues to assign `EventId` and `TransitionId`.
An external provider response identifier is transport metadata and is never used
as a GRASS domain identity. Model-generated prose that resembles an identifier
has no reference authority.

## Decision 5: Actor-relative extensible invocation context

The exact ADR-0015 DecisionRequest remains the stable semantic request. An
invocation may additionally receive a versioned, immutable structured context
assembled by trusted code. Extensions must be explicitly named and actor-relative
and may contain only information the actor is permitted to use for that decision.

The context is not unrestricted SimulationState or WorldState, cannot expose
other actors' private cognition or hidden simulator state, and cannot grant
authority to references or outcomes. Unknown context extensions are rejected or
ignored only according to the selected adapter's explicit versioned contract;
they are never silently interpreted as world truth. Belief, memory/retrieval,
prompt compaction, and scenario-specific context construction remain separate
policies.

## Decision 6: Safe concurrent acquisition and stale-result rejection

External decision acquisition may run concurrently, but concurrency is an I/O
optimization rather than simulation semantics. Candidates enter acquisition in
canonical lexicographic `(actor_id, decision_point_id)` order, and returned
results preserve that order. Completion order has no causal or Event-order
meaning.

After an invocation completes and before its proposal is prepared, trusted code
rebuilds the DecisionRequest from the current branch-visible SimulationState. The
rebuilt request must be semantically equal in every field to the exact request
used for invocation, and the DecisionPoint must still be pending. Missing,
resolved, replaced, or otherwise changed requests fail explicitly as stale and
commit nothing.

Preparation then validates the proposal under ADR-0015 and captures the current
exact expected history head. A head race after semantic revalidation is rejected
by the existing commit boundary. Stale failure does not automatically reinvoke,
retry, or select another route.

Wall-clock provider latency, acquisition order, concurrency, timeout, retry, and
human response delay do not advance `LogicalTime` or choose the logical timestamp
of an Event. Simulation time remains governed by existing engine and scheduler
contracts.

## Decision 7: Post-invocation receipt uses existing provenance

A successful invocation produces an immutable receipt only after provider work
has completed. It identifies the resolved non-secret binding and invoker,
adapter/provider/model, optional external response identifier, and
available structured completion/usage metadata. It contains no credential,
private chain-of-thought, hidden reasoning, or authority-bearing copy of state.
Raw prompts and responses are not required receipt fields.

When the proposal is accepted, the trusted preparer records the receipt as
structured metadata in the existing Event provenance for `DecisionRecorded` and
any Plan Event in the same transition. The Events share the receipt for that
invocation. This changes neither their version-1 payloads nor their projection
semantics and introduces no provider-invocation Event type.

Provider failure or stale/invalid output creates no authoritative decision Event.
Operational records for unsuccessful attempts are outside canonical simulation
history unless a future ADR defines otherwise. Ordinary replay reads accepted
Decision and Plan Events and never repeats invocation.

## Decision 8: Failures are explicit and non-authoritative

Routing/configuration, credential, transport, timeout, provider refusal,
incomplete response, malformed structured output, schema, translation, ID
allocation, stale request, and Decision/Plan validation failures remain
distinguishable explicit failures. No such failure returns a partial proposal or
commits a partial transition. Error details must not expose secrets.

Model output and human input remain untrusted cognition even when transport and
authentication succeeded. Neither ModelProvider nor DecisionInvoker can bypass
the same identity, reference, proposal, Event, provenance, and atomic-commit
validation used for synchronous DecisionProviders.

## Decision 9: Human providers use the asynchronous boundary

`HumanDecisionInvoker` uses DecisionInvoker's asynchronous acquisition boundary
and returns the same typed proposal and post-invocation receipt. A human
may take wall-clock time to respond, but receives actor-relative context and gains
no additional simulation authority. A human provider does not require or
masquerade as a ModelProvider.

Slice 11 fixes this core boundary but does not define human session transport,
operator possession workflow, browser/backend coordination, disconnect/resume,
or authentication behavior.

## Consequences

- Existing deterministic DecisionProviders and ADR-0015 Decision/Plan contracts
  remain valid.
- Slow I/O is awaitable without making the core semantic policy or preparation
  boundary asynchronous.
- Model transports remain replaceable and unaware of authoritative simulation
  state.
- Routing is reproducible, inspectable, non-secret, and incapable of silent
  fallback.
- Concurrent calls may improve throughput without making wall-clock completion
  order or latency part of simulated causality.
- Accepted provider metadata is available through existing Event provenance
  without adding canonical invocation state or a new Event type.

## Deferred details

- Slice 12 backend/API, WebSocket, frontend, and interactive session behavior;
- client-managed provider execution and credential handoff/storage;
- HumanDecisionProvider transport, operator possession, cancellation,
  disconnect/resume, and authentication;
- durable provider registries, secret stores, configuration APIs, and deployment
  policy for trusted compatible endpoints;
- automatic retry, explicit fallback graphs, rate-limit scheduling, circuit
  breakers, budgets, quotas, and cost policy;
- prompt templates/versioning, context selection, memory/retrieval/compaction,
  transcript retention, redaction, and content policy;
- streaming, tool calls, multimodal input, native Ollama adapters, broader
  provider-specific features, and generative world resolution;
- operational persistence for failed/abandoned invocations and invocation
  receipts not attached to an accepted transition.

## Alternatives considered

### Make DecisionProvider asynchronous

Rejected because it would mix semantic policy with I/O and needlessly invalidate
the simple deterministic boundary already accepted by ADR-0015.

### Let ModelProvider return DecisionProposal directly

Rejected because transport would become coupled to GRASS cognition contracts and
could allocate identities or imply domain authority.

### Persist every invocation as a new Event

Rejected for Slice 11 because failed transport attempts are not accepted actor
facts, while successful invocation metadata fits the existing provenance model.

### Fall back automatically after provider failure

Rejected because it obscures which policy/model produced behavior and damages
experimental reproducibility.

### Accept arbitrary compatible endpoint URLs from run input

Rejected because it creates proxy/SSRF and trust-boundary risks outside the
minimal provider adapter contract.
