# ADR-0017: Minimal GEL v1 language and execution contracts

- Status: Accepted
- Date: 2026-09-11
- Amended: 2026-10-27

## Context

Slice 10 introduces the first GRASS Expression Language implementation. ADR-0004
accepts GEL as a versioned, deterministic, resource-bounded, side-effect-free
language but deliberately leaves its concrete syntax, type system, standard
functions, numeric behavior, limits, and random-context API open.

Those choices define the meaning of canonical GEL source. They must be fixed for
language version 1 before source can be prepared or executed reproducibly.

## Decision 1: Standalone language boundary

Slice 10 implements GEL as a standalone pure-Python language runtime:

```text
GelProgram
    -> prepare_gel
    -> PreparedGelProgram
    -> execute_gel(explicit input, optional random context)
    -> typed immutable value
```

GEL does not receive SimulationState or WorldState and does not create
WorldEffects, Events, transitions, scheduler entries, or authoritative state.
WorldDefinition mechanics, run configuration, resolver/engine adapters, and
historical provenance remain outside this slice. Ordinary replay never invokes
GEL to reconstruct accepted history.

## Decision 2: Canonical and derived representations

`GelProgram` canonically retains exactly:

```text
source
language_version
input_schema
output_schema
```

Source is retained byte-for-code-point exactly as the supplied Python string; it
is not normalized. GEL language version 1 is the only supported version.

Until GRASS stable v1.0, GEL language version 1 is itself pre-stable. Incompatible
language/type/schema changes replace the current GEL-v1 contract in place rather
than creating GEL v2/v3 during pre-stable development. Repository-maintained GEL
programs, fixtures, examples, and documentation move forward with the current v1
shape. Earlier pre-release GEL-v1 material may require recreation.

GEL language-version numbering becomes a compatibility promise when stable GRASS
v1.0 freezes the then-current GEL-v1 contract.

`PreparedGelProgram` retains its canonical GelProgram and a private parsed and
statically validated representation. The AST and any later bytecode are derived,
disposable, noncanonical, and never persisted by this contract. The preparation
API is named `prepare_gel`, not compile, because Slice 10 introduces no compiler.

## Decision 3: Closed GEL v1 type and schema system

The current pre-stable GEL v1 type/schema system includes:

- boolean;
- signed bounded integer;
- bounded string;
- homogeneous bounded list;
- exact-field object;
- explicit null;
- finite enum schema/value constraints;
- optional schema values.

Floats, arbitrary maps, dynamic/Any values, and unrestricted general unions remain
outside the current language. Boolean and integer are distinct types.

The exact ENUM semantics and optional-field access/flow-narrowing rules are refined by
later amendments before implementation. NULL/OPTIONAL value semantics and their separation
from object-field presence are fixed by Decision 10.

Schemas include the existing `GelBooleanSchema`, `GelIntegerSchema(minimum, maximum)`,
`GelStringSchema(max_length)`, `GelListSchema(item_schema, max_items)`, and
`GelObjectSchema(fields)`, plus current-v1 NULL/ENUM/OPTIONAL schema forms defined
by the later amendment. Input schema is always an object schema. Integer bounds
must be ordered and inside the language integer domain. Strings and lists declare
positive-or-zero maxima no larger than the language limits. Object fields form an
exact closed set and use legal GEL identifiers. Missing and additional fields are
invalid. Both input and output are validated and recursively copied/frozen.

Integer-only GEL v1 does not constrain GRASS Resource, StateVariable, or future
GEL-version numeric models.

## Decision 4: Concrete grammar and scope

GEL v1 source uses ASCII identifiers, Unicode double-quoted strings with
JSON-style escapes, braces, commas, colons, and semicolons. It has no comments.
Keywords include `let`, `set`, `if`, `else`, `for`, `in`, `return`, `true`, `false`,
`null`, `and`, `or`, and `not`.

```text
program       := statement* return_statement EOF
statement     := let_statement | set_statement | if_statement | for_statement
let_statement := "let" IDENT "=" expression ";"
set_statement := "set" IDENT "=" expression ";"
if_statement  := "if" expression block "else" block
for_statement := "for" IDENT "in" expression block
block         := "{" statement* "}"
return_statement := "return" expression ";"
```

Exactly one return is required and it is the final top-level statement. There is
no early return, break, continue, while, user-defined function, recursion, import,
exception handling, method call, reflection, indexing, or dynamic call.

Blocks have lexical scope. A declaration cannot shadow any visible name. Inputs
and loop variables are read-only. A `set` targets an existing mutable local and
may update an outer local from a nested block. A local has one static type and
reassignment cannot change it. Block-local declarations do not escape.

Expression precedence, from lowest to highest, is `or`, `and`, equality,
ordering, additive, multiplicative, unary, then field access. Expressions support
typed literals, variable reads, exact object-field reads, list/object literals,
operators, parentheses, and direct calls to the closed safe-function vocabulary.
Object literal fields are identifier keys. List literals are homogeneous. An
empty list literal is valid only where an expected list schema supplies its item
type.

`and` and `or` short-circuit from left to right. Equality and inequality accept
same-type scalar operands only. Ordering accepts integers only. Object/list
equality, general indexing, string concatenation, and methods are absent.

## Decision 5: Signed 64-bit arithmetic

The GEL v1 integer domain is exactly `-2^63` through `2^63 - 1`. Decimal integer
literals and every intermediate/result value are checked against that domain.
The minimum signed literal is representable as unary minus applied directly to
`2^63`; that positive magnitude is otherwise invalid.

Arithmetic is unary minus, addition, subtraction, multiplication, floor division,
and modulo. Floor division and modulo use Python-style mathematical floor
semantics. Division/modulo by zero is an explicit numeric execution error.
Overflow is an explicit numeric error; host arbitrary-precision integers never
leak into GEL semantics. There is no floating division or exponentiation.

## Decision 6: Closed standard functions

GEL v1 exposes only:

```text
abs(integer) -> integer
min(integer, integer) -> integer
max(integer, integer) -> integer
clamp(integer, integer, integer) -> integer
length(string | list) -> integer
random_int(integer, integer) -> integer
```

`clamp` requires `lower <= upper`. Function names, arity, and argument types are
statically validated. No host math/scientific library or callable GEL value is
exposed.

## Decision 7: Explicit invocation-scoped randomness

`random_int(lower, upper)` requires `lower < upper` and returns an exact integer
such that `lower <= result < upper`. It calls only an explicitly supplied
invocation-scoped `GelRandomContext.random_int(lower, upper)` protocol. The
interpreter validates the returned host value and translates context failures to
a GEL random-context error.

A program that does not execute `random_int` needs no context. Short-circuited or
otherwise unexecuted calls consume no draw. Slice 10 supplies no production PRNG,
seed, stream key, distribution, run configuration, or random provenance.

## Decision 8: Fixed GEL v1 budgets

GEL v1 has fixed, non-configurable semantic limits:

| Limit | Value |
|---|---:|
| source Unicode code points | 16,384 |
| tokens, excluding EOF | 4,096 |
| AST nodes | 2,048 |
| parser/AST depth | 64 |
| executed operations | 100,000 |
| aggregate loop iterations | 10,000 |
| items in one list/object | 1,024 |
| string Unicode code points | 16,384 |
| structured value/schema depth | 32 |
| structured input nodes | 16,384 |
| structured result nodes | 4,096 |
| integer domain | signed 64-bit |

One node is counted for each scalar or collection value; object keys are not
additional value nodes. Schema traversal uses the corresponding input/output node,
depth, and collection limits. Every executed statement or expression AST node
costs one operation, and each entered loop iteration costs one additional
operation and one aggregate iteration. Short-circuited and untaken nodes cost no
execution operations.

Budgets are checked before exceeding the limit. There is no wall-clock timeout in
language semantics.

## Decision 9: Errors and security

GEL exposes distinct parse, static validation, input, execution, numeric, output,
random-context, and budget errors. Failure returns no partial result. Translation
of a future deterministic mechanic failure to a scenario/resolution integrity
error belongs to the future adapter, not GEL.

The closed grammar and interpreter provide no filesystem, network, process,
environment, database, import/module, reflection, dynamic-evaluation, host method,
or hidden-global-state capability. Inputs accept only exact GEL host value shapes,
not custom mappings, sequences, scalar subclasses, callables, or arbitrary
objects. GEL source is never passed to host `eval`, `exec`, or `compile`.


## Decision 10: NULL, OPTIONAL(T), and object-field presence are distinct semantics

GEL v1 has one explicit `null` literal and a corresponding null value/schema.

`OPTIONAL(T)` means that a present GEL value may be either a value satisfying `T` or
`null`:

```text
OPTIONAL(T) = T | NULL
```

OPTIONAL does not mean that an object field may be absent.

Object-field presence is modeled separately. GelObjectSchema fields use a field descriptor:

```text
GelObjectField
    schema: GelSchema
    required: bool

GelObjectSchema
    fields: Mapping[str, GelObjectField]
```

The four combinations are therefore semantically distinct:

```text
required = true
schema = STRING

"value" -> valid
null    -> invalid
absent  -> invalid
```

```text
required = true
schema = OPTIONAL(STRING)

"value" -> valid
null    -> valid
absent  -> invalid
```

```text
required = false
schema = STRING

"value" -> valid
null    -> invalid
absent  -> valid
```

```text
required = false
schema = OPTIONAL(STRING)

"value" -> valid
null    -> valid
absent  -> valid
```

This preserves three different states where a contract needs them:

```text
field absent
field present with null
field present with T
```

Validation never silently rewrites one state into another.

For object schemas, an absent non-required field is omitted from the immutable GEL object;
it is not materialized as `null`.

Nested redundant optional schemas are invalid:

```text
OPTIONAL(OPTIONAL(T)) -> invalid
OPTIONAL(NULL)        -> invalid
```

because they add no semantic state beyond OPTIONAL(T) and would create multiple canonical
schema representations for the same value set.

The source-language behavior for absent-field reads is defined by Decision 11: GEL adds no
presence-test or flow-narrowing syntax; an absent-field read is a GelExecutionError, with
conservative pre-run composition validation used to reject unsafe configured mechanics.

Invariant:

> OPTIONAL(T) is nullable-value semantics, not field-presence semantics. Object field
> requiredness independently controls whether the field may be absent, so GEL can preserve
> absent, explicit null, and ordinary values as distinct states.


## Decision 11: Absent object-field reads fail at runtime; composition validates conservatively

GEL v1 does not add presence-test syntax, optional chaining, pattern matching, or
presence-based flow narrowing.

Reading an object field keeps one simple runtime rule:

```text
read present field
    -> field value

read absent non-required field
    -> GelExecutionError
```

A field declared `required: false` may therefore be omitted from a valid GEL object, but
source that dereferences that field assumes responsibility for its presence at execution
time.

GRASS minimizes unexpected runtime failures through composition validation before a
WorldDefinition is accepted for execution.

Prepared GEL exposes or permits deterministic extraction of statically referenced input
object fields. For one concrete mechanic configuration, composition validation compares
those references with the semantic contract and concrete ValueBindings.

Conceptually:

```text
prepared GEL field references
    + semantic input contract
    + concrete input_bindings
    -> composition validation
```

For example:

```text
GEL references input.mode
+
MovementContract.mode.required = false
+
MovementRule.input_bindings.mode.optional = true
    -> invalid mechanic composition
```

because that concrete rule cannot guarantee that `input.mode` exists when GEL dereferences
it.

By contrast:

```text
GEL references input.mode
+
MovementContract.mode.required = false
+
MovementRule.input_bindings.mode.optional = false
    -> valid composition
```

because this rule guarantees that the field is supplied.

The initial dependency analysis is deliberately conservative:

> Every statically referenced object field is treated as required by the GEL program,
> regardless of control-flow reachability.

Therefore a reference inside an `if` branch still counts as a dependency even if that branch
may not execute for some inputs. GEL v1 does not initially perform path-sensitive presence
analysis.

This static validation is a composition safeguard rather than a change to GEL runtime
semantics. If an absent field nevertheless reaches a field-read operation at runtime,
`GelExecutionError` remains the final deterministic failure mode.

The same extracted field-reference information may later support dependency tracking or
invalidation, but no scheduler/invalidation semantics are implied by this decision.

Invariant:

> GEL field access stays simple: absent-field reads are execution errors. GRASS composition
> validation conservatively rejects a configured GEL mechanic when any statically referenced
> input field is not guaranteed present by that concrete configuration.


## Decision 12: ENUM is a finite constrained string schema

GEL v1 adds enum constraints without adding a separate enum literal syntax or a new runtime
scalar representation.

Conceptually:

```text
GelEnumSchema
    values: finite non-empty ordered collection of strings
```

Each value must be an exact GEL string, unique within the enum, and within the normal GEL v1
string-size limit.

At runtime, a value satisfying GelEnumSchema is still an ordinary GEL string. The schema
constrains which strings are accepted.

For example:

```text
ENUM("SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "INTERRUPTED")
```

uses ordinary GEL string syntax:

```text
return {
    outcome: "SUCCESS",
    resolved_destination: null
};
```

GEL adds no separate source syntax such as `ResolutionOutcome.SUCCESS`, a bare `SUCCESS`,
or an `enum { ... }` declaration. String equality remains the normal comparison operation
for enum-constrained values.

When an enum-incompatible string literal appears directly in a statically expected enum
position, preparation/type validation rejects it where the expected schema is available.
When membership cannot be proven statically, normal input/output schema validation enforces
the finite allowed-value set at the boundary.

`OPTIONAL(ENUM(...))` is valid.

GelEnumSchema is a constrained string schema, not a nominal GRASS domain type. Trusted
mechanic adapters map an accepted enum string to the corresponding semantic GRASS enum such
as ResolutionOutcome.

Invariant:

> GelEnumSchema constrains ordinary GEL strings to one value from a finite declared set.
> GEL v1 adds no separate enum literal syntax or runtime enum object.

## Consequences

- GEL v1 source has deterministic, testable semantics independent of simulation
  authority and host capabilities.
- The intentionally bounded language can express typed structured results including
  explicit null/optional and finite enum-valued contracts without deciding future
  scientific numeric behavior.
- Fixed limits make success/failure reproducible for one language version.
- Future integration can consume typed GEL results below existing authoritative
  validation without making the AST or interpreter canonical.

## Deferred details

- WorldDefinition mechanic schemas/registries/bindings and source hashes;
- SimulationRunConfig GEL/random settings or budget profiles;
- production random streams, key derivation, distributions, and RANDOM_TIME;
- scheduler, resolver, WorldEffect, Event, provenance, and engine integration;
- dependency extraction and invalidation tracking;
- floats or another precisely specified non-integer numeric type;
- unrestricted general unions, arbitrary maps, and general indexing;
- scientific functions, user functions, recursion, plugins, and compilation;
- AST/bytecode persistence or caching contracts;
- provider/LLM generation and repair, backend, and frontend.
