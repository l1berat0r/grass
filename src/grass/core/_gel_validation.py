# SPDX-License-Identifier: GPL-3.0-only

"""Private GEL v1 schema, value, and static type validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias, cast

from grass.core._gel_syntax import (
    BinaryExpr,
    BooleanExpr,
    CallExpr,
    Expression,
    FieldExpr,
    ForStatement,
    IfStatement,
    IntegerExpr,
    LetStatement,
    ListExpr,
    ObjectExpr,
    ProgramNode,
    SetStatement,
    Statement,
    StringExpr,
    UnaryExpr,
    VariableExpr,
)
from grass.core.gel import (
    GEL_V1_INTEGER_MAX,
    GEL_V1_INTEGER_MIN,
    GEL_V1_LIMITS,
    GelBooleanSchema,
    GelBudgetExceededError,
    GelError,
    GelInputError,
    GelInputValue,
    GelIntegerSchema,
    GelListSchema,
    GelObjectSchema,
    GelOutputError,
    GelSchema,
    GelStringSchema,
    GelValidationError,
    GelValue,
)

_MAPPING_PROXY_TYPE: type[object] = type(MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class _BooleanType:
    pass


@dataclass(frozen=True, slots=True)
class _IntegerType:
    pass


@dataclass(frozen=True, slots=True)
class _StringType:
    pass


@dataclass(frozen=True, slots=True)
class _ListType:
    item_type: _ValueType


@dataclass(frozen=True, slots=True)
class _EmptyListType:
    pass


@dataclass(frozen=True, slots=True)
class _ObjectType:
    fields: tuple[tuple[str, _ValueType], ...]

    def field(self, name: str) -> _ValueType | None:
        return next(
            (value_type for field_name, value_type in self.fields if field_name == name), None
        )


_ValueType: TypeAlias = (
    _BooleanType | _IntegerType | _StringType | _ListType | _EmptyListType | _ObjectType
)
_BOOLEAN = _BooleanType()
_INTEGER = _IntegerType()
_STRING = _StringType()
_EMPTY_LIST = _EmptyListType()


@dataclass(frozen=True, slots=True)
class _Binding:
    value_type: _ValueType
    mutable: bool


class _TypeEnvironment:
    def __init__(self, inputs: GelObjectSchema) -> None:
        self.scopes: list[dict[str, _Binding]] = [
            {
                name: _Binding(_type_from_schema(schema), False)
                for name, schema in inputs.fields.items()
            },
            {},
        ]

    def lookup(self, name: str) -> _Binding | None:
        for scope in reversed(self.scopes):
            binding = scope.get(name)
            if binding is not None:
                return binding
        return None

    def declare(self, name: str, binding: _Binding, line: int, column: int) -> None:
        if self.lookup(name) is not None:
            raise _error(line, column, f"name {name!r} would shadow an existing name")
        self.scopes[-1][name] = binding


def _error(line: int, column: int, message: str) -> GelValidationError:
    return GelValidationError(f"line {line}, column {column}: {message}")


def _type_from_schema(schema: GelSchema) -> _ValueType:
    if type(schema) is GelBooleanSchema:
        return _BOOLEAN
    if type(schema) is GelIntegerSchema:
        return _INTEGER
    if type(schema) is GelStringSchema:
        return _STRING
    if type(schema) is GelListSchema:
        return _ListType(_type_from_schema(schema.item_schema))
    if type(schema) is GelObjectSchema:
        return _ObjectType(
            tuple(sorted((name, _type_from_schema(item)) for name, item in schema.fields.items()))
        )
    raise TypeError("unsupported GEL schema")


def validate_schema_limits(schema: GelSchema, node_limit: int, description: str) -> None:
    """Validate fixed recursive schema limits without recursive host traversal."""

    pending: list[tuple[GelSchema, int]] = [(schema, 1)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > node_limit:
            raise GelBudgetExceededError(f"GEL {description} node limit exceeded")
        if depth > GEL_V1_LIMITS.structured_depth:
            raise GelBudgetExceededError(f"GEL {description} depth limit exceeded")
        children: tuple[GelSchema, ...] = ()
        if type(current) is GelListSchema:
            children = (current.item_schema,)
        elif type(current) is GelObjectSchema:
            children = tuple(current.fields.values())
        if nodes + len(pending) + len(children) > node_limit:
            raise GelBudgetExceededError(f"GEL {description} node limit exceeded")
        pending.extend((item, depth + 1) for item in children)


def validate_and_freeze_input(
    schema: GelObjectSchema, value: dict[str, GelInputValue], /
) -> Mapping[str, GelValue]:
    """Validate and isolate invocation input from caller-owned values."""

    frozen = _validate_and_freeze(
        schema,
        value,
        GelInputError,
        GEL_V1_LIMITS.input_nodes,
        "input",
    )
    if not isinstance(frozen, Mapping):  # pragma: no cover - guaranteed by schema
        raise AssertionError("GEL object input did not produce a mapping")
    return frozen


def validate_and_freeze_output(schema: GelSchema, value: GelValue, /) -> GelValue:
    """Validate and isolate one returned GEL value."""

    return _validate_and_freeze(
        schema,
        value,
        GelOutputError,
        GEL_V1_LIMITS.result_nodes,
        "output",
    )


def _validate_and_freeze(
    schema: GelSchema,
    value: object,
    error_type: type[GelError],
    node_limit: int,
    description: str,
) -> GelValue:
    nodes = [0]

    def visit(current_schema: GelSchema, current_value: object, depth: int, path: str) -> GelValue:
        nodes[0] += 1
        if nodes[0] > node_limit:
            raise GelBudgetExceededError(f"GEL {description} node limit exceeded")
        if depth > GEL_V1_LIMITS.structured_depth:
            raise GelBudgetExceededError(f"GEL {description} depth limit exceeded")
        if type(current_schema) is GelBooleanSchema:
            if type(current_value) is not bool:
                raise error_type(f"{path} must be a boolean")
            return current_value
        if type(current_schema) is GelIntegerSchema:
            if type(current_value) is not int:
                raise error_type(f"{path} must be an integer")
            if current_value < current_schema.minimum or current_value > current_schema.maximum:
                raise error_type(f"{path} is outside its integer schema bounds")
            return current_value
        if type(current_schema) is GelStringSchema:
            if type(current_value) is not str:
                raise error_type(f"{path} must be a string")
            if len(current_value) > current_schema.max_length:
                raise error_type(f"{path} exceeds its string schema limit")
            return current_value
        if type(current_schema) is GelListSchema:
            if type(current_value) not in (list, tuple):
                raise error_type(f"{path} must be a list")
            sequence = cast("list[object] | tuple[object, ...]", current_value)
            if len(sequence) > current_schema.max_items:
                raise error_type(f"{path} exceeds its list schema limit")
            return tuple(
                visit(current_schema.item_schema, item, depth + 1, f"{path}[{index}]")
                for index, item in enumerate(sequence)
            )
        if type(current_schema) is GelObjectSchema:
            accepted_mapping_types = (
                (dict, _MAPPING_PROXY_TYPE) if error_type is GelOutputError else (dict,)
            )
            if type(current_value) not in accepted_mapping_types:
                raise error_type(f"{path} must be an exact host mapping")
            mapping = cast("Mapping[object, object]", current_value)
            if len(mapping) > GEL_V1_LIMITS.collection_items:
                raise GelBudgetExceededError(f"GEL {description} object item limit exceeded")
            if not all(type(key) is str for key in mapping):
                raise error_type(f"{path} object keys must be strings")
            if any(len(cast("str", key)) > GEL_V1_LIMITS.string_characters for key in mapping):
                raise GelBudgetExceededError(
                    f"GEL {description} object key character limit exceeded"
                )
            actual = frozenset(cast("str", key) for key in mapping)
            expected = frozenset(current_schema.fields)
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                raise error_type(
                    f"{path} object fields do not match schema; missing={missing}, extra={extra}"
                )
            return MappingProxyType(
                {
                    name: visit(
                        field_schema,
                        mapping[name],
                        depth + 1,
                        f"{path}.{name}",
                    )
                    for name, field_schema in current_schema.fields.items()
                }
            )
        raise TypeError("unsupported GEL schema")

    return visit(schema, value, 1, description)


def validate_program(
    program: ProgramNode, input_schema: GelObjectSchema, output_schema: GelSchema, /
) -> None:
    """Statically type-check a private GEL AST against its declared boundary."""

    environment = _TypeEnvironment(input_schema)
    for statement in program.statements:
        _validate_statement(statement, environment)
    expected = _type_from_schema(output_schema)
    return_expression = program.return_statement.expression
    actual = _validate_expression(return_expression, environment, expected)
    _require_type(actual, expected, return_expression, "return value")


def _validate_block(statements: tuple[Statement, ...], environment: _TypeEnvironment) -> None:
    environment.scopes.append({})
    try:
        for statement in statements:
            _validate_statement(statement, environment)
    finally:
        environment.scopes.pop()


def _validate_statement(statement: Statement, environment: _TypeEnvironment) -> None:
    if type(statement) is LetStatement:
        value_type = _validate_expression(statement.expression, environment)
        if _contains_empty_list(value_type):
            raise _error(
                statement.line, statement.column, "empty list local has no inferred item type"
            )
        environment.declare(
            statement.name, _Binding(value_type, True), statement.line, statement.column
        )
        return
    if type(statement) is SetStatement:
        binding = environment.lookup(statement.name)
        if binding is None:
            raise _error(statement.line, statement.column, f"unknown local {statement.name!r}")
        if not binding.mutable:
            raise _error(statement.line, statement.column, f"name {statement.name!r} is read-only")
        value_type = _validate_expression(statement.expression, environment, binding.value_type)
        _require_type(value_type, binding.value_type, statement.expression, "reassigned value")
        return
    if type(statement) is IfStatement:
        condition_type = _validate_expression(statement.condition, environment)
        _require_type(condition_type, _BOOLEAN, statement.condition, "if condition")
        _validate_block(statement.then_body, environment)
        _validate_block(statement.else_body, environment)
        return
    if type(statement) is ForStatement:
        iterable_type = _validate_expression(statement.iterable, environment)
        if type(iterable_type) is not _ListType:
            raise _error(statement.line, statement.column, "for requires a statically typed list")
        environment.scopes.append({})
        try:
            environment.declare(
                statement.item_name,
                _Binding(iterable_type.item_type, False),
                statement.line,
                statement.column,
            )
            _validate_block(statement.body, environment)
        finally:
            environment.scopes.pop()
        return
    raise TypeError("unsupported GEL statement")


def _validate_expression(
    expression: Expression,
    environment: _TypeEnvironment,
    expected: _ValueType | None = None,
) -> _ValueType:
    if type(expression) is IntegerExpr:
        if expression.value > GEL_V1_INTEGER_MAX:
            raise _error(expression.line, expression.column, "integer literal exceeds GEL v1 range")
        return _INTEGER
    if type(expression) is BooleanExpr:
        return _BOOLEAN
    if type(expression) is StringExpr:
        return _STRING
    if type(expression) is VariableExpr:
        binding = environment.lookup(expression.name)
        if binding is None:
            raise _error(
                expression.line, expression.column, f"unknown variable {expression.name!r}"
            )
        return binding.value_type
    if type(expression) is ListExpr:
        expected_list = expected if type(expected) is _ListType else None
        if not expression.items:
            return _EMPTY_LIST if expected_list is None else expected_list
        item_types = tuple(
            _validate_expression(
                item, environment, None if expected_list is None else expected_list.item_type
            )
            for item in expression.items
        )
        item_type = item_types[0] if expected_list is None else expected_list.item_type
        for actual in item_types:
            _require_type(actual, item_type, expression, "list item")
        value_type = _ListType(item_type)
        if _contains_empty_list(value_type):
            raise _error(
                expression.line,
                expression.column,
                "empty list literal requires an expected list type",
            )
        _validate_type_depth(value_type, expression)
        return value_type
    if type(expression) is ObjectExpr:
        names = tuple(name for name, _ in expression.fields)
        if len(set(names)) != len(names):
            raise _error(expression.line, expression.column, "object literal fields must be unique")
        expected_object = expected if type(expected) is _ObjectType else None
        if expected_object is not None:
            expected_fields = dict(expected_object.fields)
            if frozenset(names) != frozenset(expected_fields):
                raise _error(
                    expression.line,
                    expression.column,
                    "object literal fields do not match expected object type",
                )
            for name, item in expression.fields:
                actual = _validate_expression(item, environment, expected_fields[name])
                _require_type(actual, expected_fields[name], item, f"object field {name!r}")
            return expected_object
        object_type = _ObjectType(
            tuple(
                sorted(
                    (name, _validate_expression(item, environment))
                    for name, item in expression.fields
                )
            )
        )
        if _contains_empty_list(object_type):
            raise _error(
                expression.line,
                expression.column,
                "empty list literal requires an expected list type",
            )
        _validate_type_depth(object_type, expression)
        return object_type
    if type(expression) is UnaryExpr:
        if expression.operator == "-":
            if type(expression.operand) is IntegerExpr and expression.operand.value == 2**63:
                return _INTEGER
            operand = _validate_expression(expression.operand, environment)
            _require_type(operand, _INTEGER, expression.operand, "unary '-' operand")
            return _INTEGER
        operand = _validate_expression(expression.operand, environment)
        _require_type(operand, _BOOLEAN, expression.operand, "'not' operand")
        return _BOOLEAN
    if type(expression) is BinaryExpr:
        left = _validate_expression(expression.left, environment)
        right = _validate_expression(expression.right, environment)
        if expression.operator in ("+", "-", "*", "//", "%"):
            _require_type(left, _INTEGER, expression.left, "arithmetic operand")
            _require_type(right, _INTEGER, expression.right, "arithmetic operand")
            return _INTEGER
        if expression.operator in ("and", "or"):
            _require_type(left, _BOOLEAN, expression.left, "boolean operand")
            _require_type(right, _BOOLEAN, expression.right, "boolean operand")
            return _BOOLEAN
        if expression.operator in ("==", "!="):
            if left != right or type(left) not in (_BooleanType, _IntegerType, _StringType):
                raise _error(
                    expression.line,
                    expression.column,
                    "equality requires same-type scalar operands",
                )
            return _BOOLEAN
        _require_type(left, _INTEGER, expression.left, "ordering operand")
        _require_type(right, _INTEGER, expression.right, "ordering operand")
        return _BOOLEAN
    if type(expression) is FieldExpr:
        target = _validate_expression(expression.target, environment)
        if type(target) is not _ObjectType:
            raise _error(expression.line, expression.column, "field access requires an object")
        field_type = target.field(expression.field_name)
        if field_type is None:
            raise _error(
                expression.line,
                expression.column,
                f"unknown object field {expression.field_name!r}",
            )
        return field_type
    if type(expression) is CallExpr:
        return _validate_call(expression, environment)
    raise TypeError("unsupported GEL expression")


def _validate_call(expression: CallExpr, environment: _TypeEnvironment) -> _ValueType:
    name = expression.function_name
    arguments = expression.arguments
    if name == "abs":
        _arity(expression, 1)
        _integer_arguments(arguments, environment)
        return _INTEGER
    if name in ("min", "max"):
        _arity(expression, 2)
        _integer_arguments(arguments, environment)
        return _INTEGER
    if name == "clamp":
        _arity(expression, 3)
        _integer_arguments(arguments, environment)
        return _INTEGER
    if name == "length":
        _arity(expression, 1)
        argument = _validate_expression(arguments[0], environment)
        if type(argument) not in (_StringType, _ListType):
            raise _error(expression.line, expression.column, "length requires a string or list")
        return _INTEGER
    if name == "random_int":
        _arity(expression, 2)
        _integer_arguments(arguments, environment)
        return _INTEGER
    raise _error(expression.line, expression.column, f"unknown safe function {name!r}")


def _arity(expression: CallExpr, expected: int) -> None:
    if len(expression.arguments) != expected:
        raise _error(
            expression.line,
            expression.column,
            f"{expression.function_name} requires exactly {expected} arguments",
        )


def _integer_arguments(arguments: tuple[Expression, ...], environment: _TypeEnvironment) -> None:
    for argument in arguments:
        actual = _validate_expression(argument, environment)
        _require_type(actual, _INTEGER, argument, "function argument")


def _require_type(
    actual: _ValueType,
    expected: _ValueType,
    expression: Expression,
    description: str,
) -> None:
    if type(actual) is _EmptyListType and type(expected) is _ListType:
        return
    if actual != expected:
        raise _error(expression.line, expression.column, f"{description} has the wrong static type")


def _contains_empty_list(value_type: _ValueType) -> bool:
    pending = [value_type]
    while pending:
        current = pending.pop()
        if type(current) is _EmptyListType:
            return True
        if type(current) is _ListType:
            pending.append(current.item_type)
        elif type(current) is _ObjectType:
            pending.extend(item for _, item in current.fields)
    return False


def _validate_type_depth(value_type: _ValueType, expression: Expression) -> None:
    pending: list[tuple[_ValueType, int]] = [(value_type, 1)]
    while pending:
        current, depth = pending.pop()
        if depth > GEL_V1_LIMITS.structured_depth:
            raise GelBudgetExceededError(
                f"line {expression.line}, column {expression.column}: "
                "GEL intermediate value depth limit exceeded"
            )
        if type(current) is _ListType:
            pending.append((current.item_type, depth + 1))
        elif type(current) is _ObjectType:
            pending.extend((item, depth + 1) for _, item in current.fields)


def ensure_integer(value: int, /) -> int:
    """Enforce the GEL v1 integer domain on one runtime result."""

    if value < GEL_V1_INTEGER_MIN or value > GEL_V1_INTEGER_MAX:
        from grass.core.gel import GelNumericError

        raise GelNumericError("GEL integer operation overflowed the v1 range")
    return value
