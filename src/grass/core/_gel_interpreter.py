# SPDX-License-Identifier: GPL-3.0-only

"""Private deterministic resource-bounded GEL v1 interpreter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

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
from grass.core._gel_validation import (
    ensure_integer,
    validate_and_freeze_input,
    validate_and_freeze_output,
)
from grass.core.gel import (
    GEL_V1_INTEGER_MIN,
    GEL_V1_LIMITS,
    GelBudgetExceededError,
    GelExecutionError,
    GelInputValue,
    GelNumericError,
    GelRandomContext,
    GelRandomContextError,
    GelValue,
    PreparedGelProgram,
)


@dataclass(slots=True)
class _RuntimeBinding:
    value: GelValue
    mutable: bool


class _RuntimeEnvironment:
    def __init__(self, inputs: Mapping[str, GelValue]) -> None:
        self.scopes: list[dict[str, _RuntimeBinding]] = [
            {name: _RuntimeBinding(value, False) for name, value in inputs.items()},
            {},
        ]

    def read(self, name: str) -> GelValue:
        for scope in reversed(self.scopes):
            binding = scope.get(name)
            if binding is not None:
                return binding.value
        raise GelExecutionError(f"unknown GEL runtime variable {name!r}")

    def declare(self, name: str, value: GelValue, *, mutable: bool) -> None:
        if any(name in scope for scope in self.scopes):
            raise GelExecutionError(f"GEL runtime name {name!r} would shadow another name")
        self.scopes[-1][name] = _RuntimeBinding(value, mutable)

    def assign(self, name: str, value: GelValue) -> None:
        for scope in reversed(self.scopes):
            binding = scope.get(name)
            if binding is not None:
                if not binding.mutable:
                    raise GelExecutionError(f"GEL runtime name {name!r} is read-only")
                binding.value = value
                return
        raise GelExecutionError(f"unknown GEL runtime local {name!r}")


class _Interpreter:
    def __init__(
        self,
        inputs: Mapping[str, GelValue],
        random_context: GelRandomContext | None,
    ) -> None:
        self.environment = _RuntimeEnvironment(inputs)
        self.random_context = random_context
        self.operations = 0
        self.loop_iterations = 0

    def execute(self, program: ProgramNode) -> GelValue:
        for statement in program.statements:
            self._execute_statement(statement)
        self._tick()
        return self._evaluate(program.return_statement.expression)

    def _tick(self) -> None:
        self.operations += 1
        if self.operations > GEL_V1_LIMITS.execution_operations:
            raise GelBudgetExceededError("GEL execution operation limit exceeded")

    def _enter_iteration(self) -> None:
        self.loop_iterations += 1
        if self.loop_iterations > GEL_V1_LIMITS.loop_iterations:
            raise GelBudgetExceededError("GEL aggregate loop iteration limit exceeded")
        self._tick()

    def _execute_block(self, statements: tuple[Statement, ...]) -> None:
        self.environment.scopes.append({})
        try:
            for statement in statements:
                self._execute_statement(statement)
        finally:
            self.environment.scopes.pop()

    def _execute_statement(self, statement: Statement) -> None:
        self._tick()
        if type(statement) is LetStatement:
            self.environment.declare(
                statement.name,
                self._evaluate(statement.expression),
                mutable=True,
            )
            return
        if type(statement) is SetStatement:
            self.environment.assign(statement.name, self._evaluate(statement.expression))
            return
        if type(statement) is IfStatement:
            condition = self._evaluate(statement.condition)
            if type(condition) is not bool:
                raise GelExecutionError("GEL if condition did not evaluate to boolean")
            self._execute_block(statement.then_body if condition else statement.else_body)
            return
        if type(statement) is ForStatement:
            iterable = self._evaluate(statement.iterable)
            if type(iterable) is not tuple:
                raise GelExecutionError("GEL for expression did not evaluate to a list")
            for item in iterable:
                self._enter_iteration()
                self.environment.scopes.append({})
                try:
                    self.environment.declare(statement.item_name, item, mutable=False)
                    self._execute_block(statement.body)
                finally:
                    self.environment.scopes.pop()
            return
        raise GelExecutionError("unknown GEL runtime statement")

    def _evaluate(self, expression: Expression) -> GelValue:
        self._tick()
        if type(expression) is IntegerExpr:
            return ensure_integer(expression.value)
        if type(expression) is BooleanExpr:
            return expression.value
        if type(expression) is StringExpr:
            return expression.value
        if type(expression) is VariableExpr:
            return self.environment.read(expression.name)
        if type(expression) is ListExpr:
            if len(expression.items) > GEL_V1_LIMITS.collection_items:  # pragma: no cover
                raise GelBudgetExceededError("GEL list item limit exceeded")
            return tuple(self._evaluate(item) for item in expression.items)
        if type(expression) is ObjectExpr:
            if len(expression.fields) > GEL_V1_LIMITS.collection_items:  # pragma: no cover
                raise GelBudgetExceededError("GEL object field limit exceeded")
            return MappingProxyType(
                {name: self._evaluate(item) for name, item in expression.fields}
            )
        if type(expression) is UnaryExpr:
            if (
                expression.operator == "-"
                and type(expression.operand) is IntegerExpr
                and expression.operand.value == 2**63
            ):
                self._tick()
                return GEL_V1_INTEGER_MIN
            operand = self._evaluate(expression.operand)
            if expression.operator == "-":
                return ensure_integer(-self._integer(operand))
            return not self._boolean(operand)
        if type(expression) is BinaryExpr:
            return self._binary(expression)
        if type(expression) is FieldExpr:
            target = self._evaluate(expression.target)
            if not isinstance(target, Mapping):
                raise GelExecutionError("GEL field target did not evaluate to an object")
            try:
                return target[expression.field_name]
            except KeyError as error:  # pragma: no cover - static validation guarantees this
                raise GelExecutionError(
                    f"unknown GEL runtime object field {expression.field_name!r}"
                ) from error
        if type(expression) is CallExpr:
            return self._call(expression)
        raise GelExecutionError("unknown GEL runtime expression")

    def _binary(self, expression: BinaryExpr) -> GelValue:
        left = self._evaluate(expression.left)
        operator = expression.operator
        if operator == "and":
            left_boolean = self._boolean(left)
            return left_boolean and self._boolean(self._evaluate(expression.right))
        if operator == "or":
            left_boolean = self._boolean(left)
            return left_boolean or self._boolean(self._evaluate(expression.right))

        right = self._evaluate(expression.right)
        if operator == "+":
            return ensure_integer(self._integer(left) + self._integer(right))
        if operator == "-":
            return ensure_integer(self._integer(left) - self._integer(right))
        if operator == "*":
            return ensure_integer(self._integer(left) * self._integer(right))
        if operator in ("//", "%"):
            divisor = self._integer(right)
            if divisor == 0:
                raise GelNumericError("GEL division or modulo by zero")
            dividend = self._integer(left)
            result = dividend // divisor if operator == "//" else dividend % divisor
            return ensure_integer(result)
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        left_integer = self._integer(left)
        right_integer = self._integer(right)
        if operator == "<":
            return left_integer < right_integer
        if operator == "<=":
            return left_integer <= right_integer
        if operator == ">":
            return left_integer > right_integer
        if operator == ">=":
            return left_integer >= right_integer
        raise GelExecutionError(f"unknown GEL runtime operator {operator!r}")

    def _call(self, expression: CallExpr) -> GelValue:
        arguments = tuple(self._evaluate(argument) for argument in expression.arguments)
        name = expression.function_name
        if name == "abs":
            return ensure_integer(abs(self._integer(arguments[0])))
        if name == "min":
            return min(self._integer(arguments[0]), self._integer(arguments[1]))
        if name == "max":
            return max(self._integer(arguments[0]), self._integer(arguments[1]))
        if name == "clamp":
            clamp_value, lower, upper = (self._integer(argument) for argument in arguments)
            if lower > upper:
                raise GelExecutionError("GEL clamp lower bound must not exceed upper bound")
            return min(max(clamp_value, lower), upper)
        if name == "length":
            length_value = arguments[0]
            if type(length_value) not in (str, tuple):
                raise GelExecutionError("GEL length argument must be a string or list")
            return len(cast("str | tuple[GelValue, ...]", length_value))
        if name == "random_int":
            return self._random_int(
                self._integer(arguments[0]),
                self._integer(arguments[1]),
            )
        raise GelExecutionError(f"unknown GEL runtime function {name!r}")

    def _random_int(self, lower: int, upper: int) -> int:
        if lower >= upper:
            raise GelRandomContextError("GEL random_int requires lower < upper")
        if self.random_context is None:
            raise GelRandomContextError("GEL random_int requires an explicit random context")
        try:
            operation = getattr(self.random_context, "random_int", None)
            if not callable(operation):
                raise GelRandomContextError("GEL random context must provide random_int")
            result = operation(lower, upper)
        except GelRandomContextError:
            raise
        except Exception as error:
            raise GelRandomContextError("GEL random context failed") from error
        if type(result) is not int:
            raise GelRandomContextError("GEL random context must return an exact integer")
        if result < lower or result >= upper:
            raise GelRandomContextError(
                "GEL random context returned a value outside [lower, upper)"
            )
        return ensure_integer(result)

    @staticmethod
    def _integer(value: GelValue) -> int:
        if type(value) is not int:
            raise GelExecutionError("GEL runtime value is not an integer")
        return value

    @staticmethod
    def _boolean(value: GelValue) -> bool:
        if type(value) is not bool:
            raise GelExecutionError("GEL runtime value is not a boolean")
        return value


def execute_prepared_gel(
    prepared: PreparedGelProgram,
    inputs: dict[str, GelInputValue],
    random_context: GelRandomContext | None,
    /,
) -> GelValue:
    """Execute one trusted private AST with isolated validated values."""

    if type(inputs) is not dict:
        raise TypeError("GEL inputs must be an exact dict")
    ast = prepared._ast
    if type(ast) is not ProgramNode:
        raise TypeError("prepared GEL program has an invalid private representation")
    frozen_inputs = validate_and_freeze_input(prepared.program.input_schema, inputs)
    result = _Interpreter(frozen_inputs, random_context).execute(ast)
    return validate_and_freeze_output(prepared.program.output_schema, result)
