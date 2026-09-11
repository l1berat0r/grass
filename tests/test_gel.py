# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from types import MappingProxyType

import pytest

from grass.core import (
    GEL_LANGUAGE_VERSION,
    GEL_V1_INTEGER_MAX,
    GEL_V1_INTEGER_MIN,
    GelBooleanSchema,
    GelInputError,
    GelInputValue,
    GelIntegerSchema,
    GelListSchema,
    GelNumericError,
    GelObjectSchema,
    GelOutputError,
    GelParseError,
    GelProgram,
    GelRandomContextError,
    GelSchema,
    GelStringSchema,
    GelValidationError,
    GelValue,
    PreparedGelProgram,
    execute_gel,
    prepare_gel,
)

INTEGER = GelIntegerSchema(GEL_V1_INTEGER_MIN, GEL_V1_INTEGER_MAX)
BOOLEAN = GelBooleanSchema()
STRING = GelStringSchema(100)
NO_INPUT = GelObjectSchema({})


def prepared(
    source: str,
    output_schema: GelSchema = INTEGER,
    input_schema: GelObjectSchema = NO_INPUT,
) -> PreparedGelProgram:
    return prepare_gel(GelProgram(source, GEL_LANGUAGE_VERSION, input_schema, output_schema))


def run(
    source: str,
    output_schema: GelSchema = INTEGER,
    inputs: dict[str, GelInputValue] | None = None,
    input_schema: GelObjectSchema = NO_INPUT,
) -> GelValue:
    program = prepared(source, output_schema, input_schema)
    return execute_gel(program, {} if inputs is None else inputs)


def test_program_retains_exact_source_and_freezes_schemas() -> None:
    fields = {"value": INTEGER}
    input_schema = GelObjectSchema(fields)
    source = "\nreturn value;\n"
    program = GelProgram(source, 1, input_schema, INTEGER)
    fields["other"] = INTEGER

    assert program.source == source
    assert tuple(program.input_schema.fields) == ("value",)
    assert isinstance(program.input_schema.fields, MappingProxyType)
    with pytest.raises(FrozenInstanceError):
        program.source = "return 0;"  # type: ignore[misc]
    with pytest.raises(TypeError):
        hash(program)

    result = prepare_gel(program)
    assert result.program is program
    assert "ProgramNode" not in repr(result)
    with pytest.raises(TypeError, match="prepare_gel"):
        PreparedGelProgram(program, object())


@pytest.mark.parametrize(
    ("factory", "error_type"),
    [
        (lambda: GelIntegerSchema(True, 1), TypeError),
        (lambda: GelIntegerSchema(2, 1), ValueError),
        (lambda: GelIntegerSchema(GEL_V1_INTEGER_MIN - 1, 0), ValueError),
        (lambda: GelStringSchema(-1), ValueError),
        (lambda: GelListSchema(INTEGER, -1), ValueError),
        (lambda: GelObjectSchema({"not-valid!": INTEGER}), ValueError),
        (lambda: GelObjectSchema({"return": INTEGER}), ValueError),
    ],
)
def test_schema_contracts_are_strict(
    factory: Callable[[], object], error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        factory()


def test_program_rejects_unsupported_language_and_non_object_input() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        GelProgram("return 1;", 2, NO_INPUT, INTEGER)
    with pytest.raises(TypeError, match="input_schema"):
        GelProgram("return 1;", 1, INTEGER, INTEGER)  # type: ignore[arg-type]


def test_integer_arithmetic_precedence_flooring_and_bounds() -> None:
    assert run("return 2 + 3 * 4;") == 14
    assert run("return -7 // 3;") == -3
    assert run("return -7 % 3;") == 2
    assert run(f"return {GEL_V1_INTEGER_MAX};") == GEL_V1_INTEGER_MAX
    assert run(f"return {GEL_V1_INTEGER_MIN};") == GEL_V1_INTEGER_MIN

    with pytest.raises(GelNumericError, match="overflowed"):
        run(f"return {GEL_V1_INTEGER_MAX} + 1;")
    with pytest.raises(GelNumericError, match="overflowed"):
        run(f"return abs({GEL_V1_INTEGER_MIN});")
    with pytest.raises(GelNumericError, match="zero"):
        run("return 1 // 0;")
    with pytest.raises(GelNumericError, match="zero"):
        run("return 1 % 0;")


def test_control_flow_objects_lists_fields_and_safe_functions() -> None:
    input_schema = GelObjectSchema(
        {
            "current": GelIntegerSchema(0, 100),
            "interrupted": BOOLEAN,
            "workloads": GelListSchema(GelIntegerSchema(0, 20), 10),
            "actor": GelObjectSchema({"name": STRING}),
        }
    )
    output_schema = GelObjectSchema(
        {
            "stress": GelIntegerSchema(0, 100),
            "label_length": GelIntegerSchema(0, 100),
        }
    )
    source = """
let total = current;
for workload in workloads {
    set total = total + workload;
}
if interrupted {
    set total = clamp(total + max(2, min(4, 3)), 0, 100);
} else {
}
return {stress: total, label_length: length(actor.name)};
"""
    result = execute_gel(
        prepared(source, output_schema, input_schema),
        {
            "current": 10,
            "interrupted": True,
            "workloads": [5, 7],
            "actor": {"name": "Alice"},
        },
    )

    assert result == {"stress": 25, "label_length": 5}
    assert isinstance(result, MappingProxyType)


def test_lexical_scope_reassignment_and_no_shadowing() -> None:
    assert (
        run(
            """
let value = 1;
if true {
    let increment = 2;
    set value = value + increment;
} else {
}
return value;
"""
        )
        == 3
    )
    with pytest.raises(GelValidationError, match="shadow"):
        prepared("let value = 1; if true { let value = 2; } else {} return value;")
    with pytest.raises(GelValidationError, match="unknown variable"):
        prepared("if true { let local = 1; } else {} return local;")
    with pytest.raises(GelValidationError, match="read-only"):
        prepared(
            "set value = 2; return value;",
            input_schema=GelObjectSchema({"value": INTEGER}),
        )


@pytest.mark.parametrize(
    "source",
    [
        "return unknown;",
        "return true + 1;",
        "return 1 == true;",
        'return "a" < "b";',
        "return [1] == [1];",
        "return missing_function(1);",
        "return min(1);",
        "let value = 1; set value = false; return value;",
        "for item in 1 {} return 0;",
    ],
)
def test_static_validation_rejects_invalid_programs(source: str) -> None:
    with pytest.raises(GelValidationError):
        prepared(source)


def test_empty_list_requires_an_expected_type() -> None:
    schema = GelListSchema(INTEGER, 5)
    assert run("return [];", schema) == ()
    with pytest.raises(GelValidationError, match="empty list"):
        prepared("let values = []; return 0;")
    with pytest.raises(GelValidationError, match="string or list"):
        prepared("return length([]);")
    with pytest.raises(GelValidationError, match="empty list"):
        prepared("let value = {items: []}; return 0;")
    with pytest.raises(GelValidationError, match="empty list"):
        prepared("let value = [[]]; return 0;")
    with pytest.raises(GelValidationError, match="empty list"):
        prepared("return {items: [], value: 1}.value;")


def test_input_is_exact_validated_and_isolated_from_caller_mutation() -> None:
    input_schema = GelObjectSchema({"values": GelListSchema(INTEGER, 3)})
    program = prepared("return values;", GelListSchema(INTEGER, 3), input_schema)
    values: list[GelInputValue] = [1, 2]
    result = execute_gel(program, {"values": values})
    values.append(3)

    assert result == (1, 2)
    with pytest.raises(GelInputError, match="missing"):
        execute_gel(program, {})
    with pytest.raises(GelInputError, match="extra"):
        execute_gel(program, {"values": [1], "other": 2})
    with pytest.raises(GelInputError, match="integer"):
        execute_gel(program, {"values": [True]})


def test_output_schema_is_checked_after_execution() -> None:
    with pytest.raises(GelOutputError, match="bounds"):
        run("return 11;", GelIntegerSchema(0, 10))


def test_strings_use_json_escapes_and_have_no_implicit_operations() -> None:
    assert run('return length("a\\n\\u03b2");') == 3
    with pytest.raises(GelValidationError):
        prepared('return "a" + "b";', STRING)
    with pytest.raises(GelParseError, match="string"):
        prepared('return "unterminated;', STRING)


@dataclass
class ScriptedRandomContext:
    values: list[int]
    calls: list[tuple[int, int]]

    def random_int(self, lower: int, upper: int, /) -> int:
        self.calls.append((lower, upper))
        return self.values.pop(0)


def test_random_context_is_explicit_and_only_executed_calls_draw() -> None:
    program = prepared("return random_int(2, 5);")
    context = ScriptedRandomContext([4], [])
    assert execute_gel(program, {}, context) == 4
    assert context.calls == [(2, 5)]

    short_circuit = prepared("return false and random_int(0, 2) == 1;", BOOLEAN)
    unused = ScriptedRandomContext([1], [])
    assert execute_gel(short_circuit, {}, unused) is False
    assert unused.calls == []

    without_random = prepared("return 1;")
    assert execute_gel(without_random, {}) == 1


def test_random_context_failures_are_explicit() -> None:
    program = prepared("return random_int(1, 3);")
    with pytest.raises(GelRandomContextError, match="explicit"):
        execute_gel(program, {})
    with pytest.raises(GelRandomContextError, match="lower < upper"):
        execute_gel(prepared("return random_int(3, 3);"), {}, ScriptedRandomContext([3], []))
    with pytest.raises(GelRandomContextError, match="outside"):
        execute_gel(program, {}, ScriptedRandomContext([3], []))
    with pytest.raises(GelRandomContextError, match="exact integer"):
        execute_gel(program, {}, ScriptedRandomContext([True], []))


@pytest.mark.parametrize(
    "source",
    [
        "",
        "let value = 1;",
        "return 1",
        "return 1; return 2;",
        "if true { return 1; } else {} return 0;",
        "return 01;",
        "return 1 / 1;",
    ],
)
def test_parse_failures_are_explicit(source: str) -> None:
    with pytest.raises(GelParseError):
        prepared(source)
