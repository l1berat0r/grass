# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import cast

import pytest

from grass.core import (
    GEL_V1_INTEGER_MAX,
    GEL_V1_INTEGER_MIN,
    GEL_V1_LIMITS,
    GelBudgetExceededError,
    GelInputError,
    GelInputValue,
    GelIntegerSchema,
    GelListSchema,
    GelObjectSchema,
    GelOutputError,
    GelParseError,
    GelProgram,
    GelRandomContextError,
    GelSchema,
    GelStringSchema,
    GelValidationError,
    execute_gel,
    prepare_gel,
)

INTEGER = GelIntegerSchema(GEL_V1_INTEGER_MIN, GEL_V1_INTEGER_MAX)
NO_INPUT = GelObjectSchema({})


def program(
    source: str,
    output_schema: GelSchema = INTEGER,
    input_schema: GelObjectSchema = NO_INPUT,
) -> GelProgram:
    return GelProgram(source, 1, input_schema, output_schema)


@pytest.mark.parametrize(
    "source",
    [
        "import os; return 0;",
        "while true {} return 0;",
        "return values[0];",
        "return actor.method();",
        'return open("file");',
        'return __import__("os");',
        "return 1.5;",
        "return null;",
        "try {} return 0;",
    ],
)
def test_closed_language_rejects_host_capability_shapes(source: str) -> None:
    with pytest.raises((GelParseError, GelValidationError)):
        prepare_gel(program(source))


def test_source_token_ast_and_parser_depth_budgets() -> None:
    with pytest.raises(GelBudgetExceededError, match="source"):
        prepare_gel(program(" " * (GEL_V1_LIMITS.source_characters + 1)))

    token_heavy = " ".join(
        f"let value{index} = 0;" for index in range(GEL_V1_LIMITS.tokens // 5 + 1)
    )
    with pytest.raises(GelBudgetExceededError, match="token"):
        prepare_gel(program(token_heavy + " return 0;"))

    ast_heavy = "return " + "+".join("1" for _ in range(1_025)) + ";"
    with pytest.raises(GelBudgetExceededError, match="AST node"):
        prepare_gel(program(ast_heavy))

    deeply_nested = "return " + "(" * 65 + "1" + ")" * 65 + ";"
    with pytest.raises(GelBudgetExceededError, match="depth"):
        prepare_gel(program(deeply_nested))

    with pytest.raises(GelValidationError, match="integer literal"):
        prepare_gel(program("return " + "9" * 5_000 + ";"))


def test_collection_schema_and_schema_depth_limits() -> None:
    with pytest.raises(ValueError, match="max_items"):
        GelListSchema(INTEGER, GEL_V1_LIMITS.collection_items + 1)

    list_literal = "return [" + ",".join("1" for _ in range(1_025)) + "];"
    with pytest.raises(GelBudgetExceededError, match="list literal"):
        prepare_gel(program(list_literal, GelListSchema(INTEGER, 1_024)))

    schema: GelSchema = INTEGER
    for _ in range(GEL_V1_LIMITS.structured_depth):
        schema = GelListSchema(schema, 1)
    with pytest.raises(GelBudgetExceededError, match="schema depth"):
        prepare_gel(program("return 0;", schema))

    shared_child = GelObjectSchema(
        {f"field_{index}": INTEGER for index in range(GEL_V1_LIMITS.collection_items)}
    )
    aliased_result = GelObjectSchema(
        {
            "first": shared_child,
            "second": shared_child,
            "third": shared_child,
            "fourth": shared_child,
        }
    )
    with pytest.raises(GelBudgetExceededError, match="output schema node"):
        prepare_gel(program("return {};", aliased_result))


class MisreportedSchemaMapping(Mapping[str, GelSchema]):
    def __getitem__(self, key: str) -> GelSchema:
        del key
        return INTEGER

    def __iter__(self) -> Iterator[str]:
        return (f"field_{index}" for index in range(GEL_V1_LIMITS.collection_items + 1))

    def __len__(self) -> int:
        return 0


def test_object_schema_counts_copied_fields_instead_of_trusting_mapping_length() -> None:
    with pytest.raises(ValueError, match="collection"):
        GelObjectSchema(MisreportedSchemaMapping())


def test_intermediate_value_depth_is_bounded_even_when_not_returned() -> None:
    nested = "[" * GEL_V1_LIMITS.structured_depth + "1" + "]" * GEL_V1_LIMITS.structured_depth
    with pytest.raises(GelBudgetExceededError, match="intermediate value depth"):
        prepare_gel(program(f"let nested = {nested}; return 0;"))


def test_execution_operation_and_aggregate_iteration_budgets() -> None:
    statements = "".join("set total = total + 1;" for _ in range(100))
    source = f"let total = 0; for item in values {{{statements}}} return total;"
    input_schema = GelObjectSchema({"values": GelListSchema(INTEGER, 1_024)})
    prepared = prepare_gel(program(source, INTEGER, input_schema))
    with pytest.raises(GelBudgetExceededError, match="operation"):
        execute_gel(prepared, {"values": [0] * 1_024})

    nested = prepare_gel(
        program(
            "for outer in values { for inner in values {} } return 0;",
            INTEGER,
            GelObjectSchema({"values": GelListSchema(INTEGER, 101)}),
        )
    )
    with pytest.raises(GelBudgetExceededError, match="iteration"):
        execute_gel(nested, {"values": [0] * 101})

    loop_body = "".join("set total = total + 1;" for _ in range(249))
    trailing = "".join("set total = total + 1;" for _ in range(72))
    exact_source = (
        f"let total = 0; for item in values {{{loop_body}}} {trailing}"
        "if true {} else {} let unused_one = 0; let unused_two = 0; return total;"
    )
    exact_schema = GelObjectSchema({"values": GelListSchema(INTEGER, 100)})
    at_limit = prepare_gel(program(exact_source, INTEGER, exact_schema))
    assert execute_gel(at_limit, {"values": [0] * 100}) == 24_972

    over_limit = prepare_gel(program(exact_source[:-6] + "-total;", INTEGER, exact_schema))
    with pytest.raises(GelBudgetExceededError, match="operation"):
        execute_gel(over_limit, {"values": [0] * 100})


def test_input_and_result_node_budgets() -> None:
    item_schema = GelListSchema(INTEGER, 20)
    value_schema = GelListSchema(item_schema, 1_024)
    input_schema = GelObjectSchema({"values": value_schema})
    prepared = prepare_gel(program("return 0;", INTEGER, input_schema))
    oversized_input = {"values": [[0] * 16 for _ in range(1_024)]}
    with pytest.raises(GelBudgetExceededError, match="input node"):
        execute_gel(prepared, cast("dict[str, GelInputValue]", oversized_input))

    result_schema = GelListSchema(GelListSchema(INTEGER, 50), 100)
    passthrough = prepare_gel(
        program(
            "return values;",
            result_schema,
            GelObjectSchema({"values": result_schema}),
        )
    )
    with pytest.raises(GelBudgetExceededError, match="output node"):
        execute_gel(passthrough, {"values": [[0] * 50 for _ in range(100)]})

    exact_input = prepare_gel(
        program("return value;", INTEGER, GelObjectSchema({"value": INTEGER}))
    )
    oversized_object: dict[str, GelInputValue] = {
        f"field_{index}": index for index in range(GEL_V1_LIMITS.collection_items + 1)
    }
    with pytest.raises(GelBudgetExceededError, match="object item"):
        execute_gel(exact_input, oversized_object)


def test_string_and_output_bounds_are_enforced() -> None:
    schema = GelStringSchema(GEL_V1_LIMITS.string_characters)
    prepared = prepare_gel(
        GelProgram(
            "return text;",
            1,
            GelObjectSchema({"text": schema}),
            GelStringSchema(3),
        )
    )
    with pytest.raises(GelOutputError, match="string schema"):
        execute_gel(prepared, {"text": "four"})


class HostMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        return 1

    def __iter__(self) -> Iterator[str]:
        return iter(("value",))

    def __len__(self) -> int:
        return 1


def test_custom_host_objects_and_scalar_subclasses_are_rejected() -> None:
    prepared = prepare_gel(
        program(
            "return value;",
            INTEGER,
            GelObjectSchema({"value": INTEGER}),
        )
    )
    with pytest.raises(TypeError, match="exact dict"):
        execute_gel(prepared, HostMapping())  # type: ignore[arg-type]

    class IntegerSubclass(int):
        pass

    with pytest.raises(GelInputError, match="integer"):
        execute_gel(prepared, {"value": IntegerSubclass(1)})


class BrokenRandomContext:
    def random_int(self, lower: int, upper: int, /) -> int:
        del lower, upper
        raise RuntimeError("host failure")


class BrokenRandomProperty:
    @property
    def random_int(self) -> object:
        raise RuntimeError("host property failure")


def test_random_host_failure_is_translated() -> None:
    prepared = prepare_gel(program("return random_int(0, 2);"))
    with pytest.raises(GelRandomContextError, match="context failed"):
        execute_gel(prepared, {}, BrokenRandomContext())
    with pytest.raises(GelRandomContextError, match="context failed"):
        execute_gel(prepared, {}, BrokenRandomProperty())  # type: ignore[arg-type]


def test_interpreter_does_not_call_host_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("host capability was invoked")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("os.getenv", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)

    prepared = prepare_gel(program("let value = 2; return value * 3;"))
    assert execute_gel(prepared, {}) == 6
