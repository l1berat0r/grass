# SPDX-License-Identifier: GPL-3.0-only

"""Public contracts for the standalone GEL v1 runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Protocol, TypeAlias

GEL_LANGUAGE_VERSION = 1
GEL_V1_INTEGER_MIN = -(2**63)
GEL_V1_INTEGER_MAX = 2**63 - 1


@dataclass(frozen=True, slots=True)
class GelLanguageLimits:
    """Fixed semantic resource limits for one GEL language version."""

    source_characters: int
    tokens: int
    ast_nodes: int
    ast_depth: int
    execution_operations: int
    loop_iterations: int
    collection_items: int
    string_characters: int
    structured_depth: int
    input_nodes: int
    result_nodes: int


GEL_V1_LIMITS = GelLanguageLimits(
    source_characters=16_384,
    tokens=4_096,
    ast_nodes=2_048,
    ast_depth=64,
    execution_operations=100_000,
    loop_iterations=10_000,
    collection_items=1_024,
    string_characters=16_384,
    structured_depth=32,
    input_nodes=16_384,
    result_nodes=4_096,
)


class GelError(ValueError):
    """Base class for explicit GEL language and runtime failures."""


class GelParseError(GelError):
    """GEL source is not valid version-1 syntax."""


class GelValidationError(GelError):
    """A parsed GEL program is not statically valid."""


class GelInputError(GelError):
    """Invocation input does not satisfy the program input schema."""


class GelExecutionError(GelError):
    """A statically valid GEL program failed during execution."""


class GelNumericError(GelExecutionError):
    """A GEL integer operation is undefined or outside the v1 domain."""


class GelOutputError(GelError):
    """The returned value does not satisfy the program output schema."""


class GelRandomContextError(GelExecutionError):
    """An executed random operation has no valid explicit context/result."""


class GelBudgetExceededError(GelError):
    """A fixed GEL v1 preparation or execution limit was exhausted."""


@dataclass(frozen=True, slots=True)
class GelBooleanSchema:
    """The exact GEL boolean type."""


@dataclass(frozen=True, slots=True)
class GelIntegerSchema:
    """A signed-64-bit integer constrained to explicit inclusive bounds."""

    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if type(self.minimum) is not int or type(self.maximum) is not int:
            raise TypeError("GEL integer schema bounds must be integers")
        if self.minimum < GEL_V1_INTEGER_MIN or self.maximum > GEL_V1_INTEGER_MAX:
            raise ValueError("GEL integer schema bounds must be within the v1 integer domain")
        if self.minimum > self.maximum:
            raise ValueError("GEL integer schema minimum must not exceed maximum")


@dataclass(frozen=True, slots=True)
class GelStringSchema:
    """A GEL string constrained by Unicode code-point length."""

    max_length: int

    def __post_init__(self) -> None:
        _validate_maximum(self.max_length, GEL_V1_LIMITS.string_characters, "string max_length")


@dataclass(frozen=True, slots=True)
class GelListSchema:
    """A homogeneous GEL list constrained by item count."""

    item_schema: GelSchema
    max_items: int

    def __post_init__(self) -> None:
        if not _is_schema(self.item_schema):
            raise TypeError("item_schema must be a GEL schema")
        _validate_maximum(self.max_items, GEL_V1_LIMITS.collection_items, "list max_items")


@dataclass(frozen=True, slots=True)
class GelObjectSchema:
    """A closed exact-field GEL object schema."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    fields: Mapping[str, GelSchema]

    def __post_init__(self) -> None:
        if not isinstance(self.fields, Mapping):
            raise TypeError("fields must be a mapping")
        copied: dict[str, GelSchema] = {}
        for name, schema in self.fields.items():
            if len(copied) >= GEL_V1_LIMITS.collection_items:
                raise ValueError("object fields exceed the GEL v1 collection limit")
            if type(name) is not str:
                raise ValueError("GEL object field names must be legal ASCII identifiers")
            if len(name) > GEL_V1_LIMITS.string_characters:
                raise ValueError("GEL object field name exceeds the v1 string limit")
            if not _is_identifier(name):
                raise ValueError("GEL object field names must be legal ASCII identifiers")
            if name in _KEYWORDS:
                raise ValueError("GEL object field names must not be reserved keywords")
            if not _is_schema(schema):
                raise TypeError("object fields must contain GEL schemas")
            if name in copied:
                raise ValueError("GEL object field names must be unique")
            copied[name] = schema
        object.__setattr__(self, "fields", MappingProxyType(copied))


GelSchema: TypeAlias = (
    GelBooleanSchema | GelIntegerSchema | GelStringSchema | GelListSchema | GelObjectSchema
)
GelScalar: TypeAlias = bool | int | str
GelInputValue: TypeAlias = (
    GelScalar | dict[str, "GelInputValue"] | list["GelInputValue"] | tuple["GelInputValue", ...]
)
GelValue: TypeAlias = GelScalar | Mapping[str, "GelValue"] | tuple["GelValue", ...]


@dataclass(frozen=True, slots=True)
class GelProgram:
    """Canonical GEL source and its declared typed boundary."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    source: str
    language_version: int
    input_schema: GelObjectSchema
    output_schema: GelSchema

    def __post_init__(self) -> None:
        if type(self.source) is not str:
            raise TypeError("GEL source must be a string")
        if type(self.language_version) is not int:
            raise TypeError("GEL language_version must be an integer")
        if self.language_version != GEL_LANGUAGE_VERSION:
            raise ValueError(f"unsupported GEL language_version: {self.language_version}")
        if type(self.input_schema) is not GelObjectSchema:
            raise TypeError("GEL input_schema must be a GelObjectSchema")
        if not _is_schema(self.output_schema):
            raise TypeError("GEL output_schema must be a GEL schema")


@dataclass(frozen=True, slots=True, init=False)
class PreparedGelProgram:
    """A canonical program coupled to its private disposable representation."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    program: GelProgram
    _ast: object = field(repr=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("PreparedGelProgram values are created only by prepare_gel")


class GelRandomContext(Protocol):
    """One explicit invocation-scoped source for GEL random integers."""

    def random_int(self, lower: int, upper: int, /) -> int:
        """Return one integer in the half-open interval [lower, upper)."""

        ...


def prepare_gel(program: GelProgram, /) -> PreparedGelProgram:
    """Parse and statically validate one canonical GEL program."""

    if type(program) is not GelProgram:
        raise TypeError("program must be a GelProgram")
    if len(program.source) > GEL_V1_LIMITS.source_characters:
        raise GelBudgetExceededError("GEL source character limit exceeded")

    from grass.core._gel_syntax import parse_gel
    from grass.core._gel_validation import validate_program, validate_schema_limits

    validate_schema_limits(program.input_schema, GEL_V1_LIMITS.input_nodes, "input schema")
    validate_schema_limits(program.output_schema, GEL_V1_LIMITS.result_nodes, "output schema")
    ast = parse_gel(program.source)
    validate_program(ast, program.input_schema, program.output_schema)
    return _prepared_program(program, ast)


def execute_gel(
    prepared_program: PreparedGelProgram,
    inputs: dict[str, GelInputValue],
    random_context: GelRandomContext | None = None,
    /,
) -> GelValue:
    """Execute one prepared program against explicit typed input only."""

    if type(prepared_program) is not PreparedGelProgram:
        raise TypeError("prepared_program must be a PreparedGelProgram")

    from grass.core._gel_interpreter import execute_prepared_gel

    return execute_prepared_gel(prepared_program, inputs, random_context)


def _prepared_program(program: GelProgram, ast: object) -> PreparedGelProgram:
    prepared = object.__new__(PreparedGelProgram)
    object.__setattr__(prepared, "program", program)
    object.__setattr__(prepared, "_ast", ast)
    return prepared


def _validate_maximum(value: object, upper_bound: int, field_name: str) -> None:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    if value < 0 or value > upper_bound:
        raise ValueError(f"{field_name} must be between 0 and {upper_bound}")


def _is_schema(value: object) -> bool:
    return type(value) in (
        GelBooleanSchema,
        GelIntegerSchema,
        GelStringSchema,
        GelListSchema,
        GelObjectSchema,
    )


_KEYWORDS = frozenset(
    {"let", "set", "if", "else", "for", "in", "return", "true", "false", "and", "or", "not"}
)


def _is_identifier(value: str) -> bool:
    if value == "" or not (value[0].isascii() and (value[0].isalpha() or value[0] == "_")):
        return False
    return all(
        character.isascii() and (character.isalnum() or character == "_") for character in value
    )
