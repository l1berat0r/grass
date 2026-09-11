# SPDX-License-Identifier: GPL-3.0-only

"""Private GEL v1 tokenizer, AST, and recursive-descent parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TypeAlias

from grass.core.gel import (
    GEL_V1_LIMITS,
    GelBudgetExceededError,
    GelParseError,
    GelValidationError,
)


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str | int | bool | None
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class IntegerExpr:
    value: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class BooleanExpr:
    value: bool
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class StringExpr:
    value: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class VariableExpr:
    name: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ListExpr:
    items: tuple[Expression, ...]
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ObjectExpr:
    fields: tuple[tuple[str, Expression], ...]
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class UnaryExpr:
    operator: str
    operand: Expression
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class BinaryExpr:
    operator: str
    left: Expression
    right: Expression
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class FieldExpr:
    target: Expression
    field_name: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class CallExpr:
    function_name: str
    arguments: tuple[Expression, ...]
    line: int
    column: int


Expression: TypeAlias = (
    IntegerExpr
    | BooleanExpr
    | StringExpr
    | VariableExpr
    | ListExpr
    | ObjectExpr
    | UnaryExpr
    | BinaryExpr
    | FieldExpr
    | CallExpr
)


@dataclass(frozen=True, slots=True)
class LetStatement:
    name: str
    expression: Expression
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SetStatement:
    name: str
    expression: Expression
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class IfStatement:
    condition: Expression
    then_body: tuple[Statement, ...]
    else_body: tuple[Statement, ...]
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ForStatement:
    item_name: str
    iterable: Expression
    body: tuple[Statement, ...]
    line: int
    column: int


Statement: TypeAlias = LetStatement | SetStatement | IfStatement | ForStatement


@dataclass(frozen=True, slots=True)
class ReturnStatement:
    expression: Expression
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ProgramNode:
    statements: tuple[Statement, ...]
    return_statement: ReturnStatement


_KEYWORD_KINDS = {
    "let": "LET",
    "set": "SET",
    "if": "IF",
    "else": "ELSE",
    "for": "FOR",
    "in": "IN",
    "return": "RETURN",
    "true": "TRUE",
    "false": "FALSE",
    "and": "AND",
    "or": "OR",
    "not": "NOT",
}
_SINGLE_TOKENS = {
    "+": "PLUS",
    "-": "MINUS",
    "*": "STAR",
    "%": "PERCENT",
    "=": "ASSIGN",
    "<": "LESS",
    ">": "GREATER",
    ".": "DOT",
    "(": "LEFT_PAREN",
    ")": "RIGHT_PAREN",
    "{": "LEFT_BRACE",
    "}": "RIGHT_BRACE",
    "[": "LEFT_BRACKET",
    "]": "RIGHT_BRACKET",
    ",": "COMMA",
    ":": "COLON",
    ";": "SEMICOLON",
}
_DOUBLE_TOKENS = {
    "//": "FLOOR_DIVIDE",
    "==": "EQUAL",
    "!=": "NOT_EQUAL",
    "<=": "LESS_EQUAL",
    ">=": "GREATER_EQUAL",
}


def _parse_error(line: int, column: int, message: str) -> GelParseError:
    return GelParseError(f"line {line}, column {column}: {message}")


def _tokenize(source: str) -> tuple[Token, ...]:
    tokens: list[Token] = []
    index = 0
    line = 1
    column = 1

    def append(kind: str, value: str | int | bool | None, at_line: int, at_column: int) -> None:
        tokens.append(Token(kind, value, at_line, at_column))
        if len(tokens) > GEL_V1_LIMITS.tokens:
            raise GelBudgetExceededError("GEL token limit exceeded")

    while index < len(source):
        character = source[index]
        if character in " \t\r":
            index += 1
            column += 1
            continue
        if character == "\n":
            index += 1
            line += 1
            column = 1
            continue

        at_line = line
        at_column = column
        pair = source[index : index + 2]
        if pair in _DOUBLE_TOKENS:
            append(_DOUBLE_TOKENS[pair], pair, at_line, at_column)
            index += 2
            column += 2
            continue
        if character == '"':
            start = index
            index += 1
            column += 1
            escaped = False
            while index < len(source):
                current = source[index]
                if current in "\n\r":
                    raise _parse_error(
                        at_line, at_column, "string literal cannot contain a newline"
                    )
                index += 1
                column += 1
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    break
            else:
                raise _parse_error(at_line, at_column, "unterminated string literal")
            raw = source[start:index]
            try:
                decoded = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise _parse_error(
                    at_line, at_column, "invalid JSON-style string literal"
                ) from error
            if type(decoded) is not str:  # pragma: no cover - JSON string syntax guarantees this
                raise AssertionError("decoded GEL string is not a string")
            if len(decoded) > GEL_V1_LIMITS.string_characters:
                raise GelBudgetExceededError("GEL string character limit exceeded")
            append("STRING", decoded, at_line, at_column)
            continue
        if character.isascii() and character.isdigit():
            start = index
            while index < len(source) and source[index].isascii() and source[index].isdigit():
                index += 1
                column += 1
            text = source[start:index]
            if len(text) > 1 and text[0] == "0":
                raise _parse_error(at_line, at_column, "integer literals cannot have leading zeros")
            if len(text) > 19 or (len(text) == 19 and text > str(2**63)):
                raise GelValidationError(
                    f"line {at_line}, column {at_column}: integer literal exceeds GEL v1 range"
                )
            append("INTEGER", int(text), at_line, at_column)
            continue
        if character.isascii() and (character.isalpha() or character == "_"):
            start = index
            while index < len(source):
                current = source[index]
                if not (current.isascii() and (current.isalnum() or current == "_")):
                    break
                index += 1
                column += 1
            text = source[start:index]
            append(_KEYWORD_KINDS.get(text, "IDENTIFIER"), text, at_line, at_column)
            continue
        kind = _SINGLE_TOKENS.get(character)
        if kind is not None:
            append(kind, character, at_line, at_column)
            index += 1
            column += 1
            continue
        raise _parse_error(at_line, at_column, f"unexpected character {character!r}")

    tokens.append(Token("EOF", None, line, column))
    return tuple(tokens)


class _Parser:
    def __init__(self, tokens: tuple[Token, ...]) -> None:
        self._tokens = tokens
        self._current = 0
        self._node_count = 0
        self._nesting = 0

    def parse(self) -> ProgramNode:
        self._count_node()
        statements: list[Statement] = []
        while not self._check("RETURN") and not self._check("EOF"):
            statements.append(self._statement())
        if not self._match("RETURN"):
            token = self._peek()
            raise _parse_error(token.line, token.column, "program requires one final return")
        return_token = self._previous()
        expression = self._expression()
        self._consume("SEMICOLON", "expected ';' after return value")
        self._consume("EOF", "return must be the final top-level statement")
        self._count_node()
        return_statement = ReturnStatement(
            expression,
            return_token.line,
            return_token.column,
        )
        program = ProgramNode(tuple(statements), return_statement)
        self._validate_depth(program, return_token)
        return program

    def _statement(self) -> Statement:
        if self._match("LET"):
            token = self._previous()
            name = self._consume_identifier("expected local name after 'let'")
            self._consume("ASSIGN", "expected '=' after local name")
            expression = self._expression()
            self._consume("SEMICOLON", "expected ';' after local declaration")
            self._count_node()
            return LetStatement(_string_value(name), expression, token.line, token.column)
        if self._match("SET"):
            token = self._previous()
            name = self._consume_identifier("expected local name after 'set'")
            self._consume("ASSIGN", "expected '=' after local name")
            expression = self._expression()
            self._consume("SEMICOLON", "expected ';' after local reassignment")
            self._count_node()
            return SetStatement(_string_value(name), expression, token.line, token.column)
        if self._match("IF"):
            token = self._previous()
            condition = self._expression()
            then_body = self._block()
            self._consume("ELSE", "expected 'else' after if block")
            else_body = self._block()
            self._count_node()
            return IfStatement(condition, then_body, else_body, token.line, token.column)
        if self._match("FOR"):
            token = self._previous()
            name = self._consume_identifier("expected item name after 'for'")
            self._consume("IN", "expected 'in' after loop item name")
            iterable = self._expression()
            body = self._block()
            self._count_node()
            return ForStatement(_string_value(name), iterable, body, token.line, token.column)
        token = self._peek()
        if token.kind == "RETURN":
            raise _parse_error(token.line, token.column, "early return is not supported")
        raise _parse_error(token.line, token.column, "expected a GEL statement")

    def _block(self) -> tuple[Statement, ...]:
        self._consume("LEFT_BRACE", "expected '{' to begin block")
        self._enter_nesting()
        try:
            statements: list[Statement] = []
            while not self._check("RIGHT_BRACE") and not self._check("EOF"):
                statements.append(self._statement())
            self._consume("RIGHT_BRACE", "expected '}' after block")
            return tuple(statements)
        finally:
            self._leave_nesting()

    def _expression(self) -> Expression:
        self._enter_nesting()
        try:
            return self._or()
        finally:
            self._leave_nesting()

    def _or(self) -> Expression:
        expression = self._and()
        while self._match("OR"):
            expression = self._binary(expression, self._previous(), self._and())
        return expression

    def _and(self) -> Expression:
        expression = self._equality()
        while self._match("AND"):
            expression = self._binary(expression, self._previous(), self._equality())
        return expression

    def _equality(self) -> Expression:
        expression = self._ordering()
        while self._match("EQUAL", "NOT_EQUAL"):
            expression = self._binary(expression, self._previous(), self._ordering())
        return expression

    def _ordering(self) -> Expression:
        expression = self._additive()
        while self._match("LESS", "LESS_EQUAL", "GREATER", "GREATER_EQUAL"):
            expression = self._binary(expression, self._previous(), self._additive())
        return expression

    def _additive(self) -> Expression:
        expression = self._multiplicative()
        while self._match("PLUS", "MINUS"):
            expression = self._binary(expression, self._previous(), self._multiplicative())
        return expression

    def _multiplicative(self) -> Expression:
        expression = self._unary()
        while self._match("STAR", "FLOOR_DIVIDE", "PERCENT"):
            expression = self._binary(expression, self._previous(), self._unary())
        return expression

    def _unary(self) -> Expression:
        if self._match("MINUS", "NOT"):
            token = self._previous()
            self._enter_nesting()
            try:
                operand = self._unary()
            finally:
                self._leave_nesting()
            self._count_node()
            return UnaryExpr(str(token.value), operand, token.line, token.column)
        return self._field_access()

    def _field_access(self) -> Expression:
        expression = self._primary()
        while self._match("DOT"):
            dot = self._previous()
            field = self._consume_identifier("expected field name after '.'")
            self._count_node()
            expression = FieldExpr(
                expression,
                _string_value(field),
                dot.line,
                dot.column,
            )
        return expression

    def _primary(self) -> Expression:
        if self._match("INTEGER"):
            token = self._previous()
            self._count_node()
            return IntegerExpr(_integer_value(token), token.line, token.column)
        if self._match("TRUE", "FALSE"):
            token = self._previous()
            self._count_node()
            return BooleanExpr(token.kind == "TRUE", token.line, token.column)
        if self._match("STRING"):
            token = self._previous()
            self._count_node()
            return StringExpr(_string_value(token), token.line, token.column)
        if self._match("IDENTIFIER"):
            token = self._previous()
            identifier = _string_value(token)
            if self._match("LEFT_PAREN"):
                arguments: list[Expression] = []
                if not self._check("RIGHT_PAREN"):
                    while True:
                        arguments.append(self._expression())
                        if not self._match("COMMA"):
                            break
                self._consume("RIGHT_PAREN", "expected ')' after function arguments")
                self._count_node()
                return CallExpr(identifier, tuple(arguments), token.line, token.column)
            self._count_node()
            return VariableExpr(identifier, token.line, token.column)
        if self._match("LEFT_PAREN"):
            expression = self._expression()
            self._consume("RIGHT_PAREN", "expected ')' after expression")
            return expression
        if self._match("LEFT_BRACKET"):
            token = self._previous()
            items: list[Expression] = []
            if not self._check("RIGHT_BRACKET"):
                while True:
                    items.append(self._expression())
                    if len(items) > GEL_V1_LIMITS.collection_items:
                        raise GelBudgetExceededError("GEL list literal item limit exceeded")
                    if not self._match("COMMA"):
                        break
            self._consume("RIGHT_BRACKET", "expected ']' after list literal")
            self._count_node()
            return ListExpr(tuple(items), token.line, token.column)
        if self._match("LEFT_BRACE"):
            token = self._previous()
            fields: list[tuple[str, Expression]] = []
            if not self._check("RIGHT_BRACE"):
                while True:
                    field_token = self._consume_identifier("expected object field name")
                    self._consume("COLON", "expected ':' after object field name")
                    fields.append((_string_value(field_token), self._expression()))
                    if len(fields) > GEL_V1_LIMITS.collection_items:
                        raise GelBudgetExceededError("GEL object literal field limit exceeded")
                    if not self._match("COMMA"):
                        break
            self._consume("RIGHT_BRACE", "expected '}' after object literal")
            self._count_node()
            return ObjectExpr(tuple(fields), token.line, token.column)
        token = self._peek()
        raise _parse_error(token.line, token.column, "expected an expression")

    def _binary(self, left: Expression, operator: Token, right: Expression) -> BinaryExpr:
        self._count_node()
        return BinaryExpr(str(operator.value), left, right, operator.line, operator.column)

    def _match(self, *kinds: str) -> bool:
        if not any(self._check(kind) for kind in kinds):
            return False
        self._advance()
        return True

    def _consume(self, kind: str, message: str) -> Token:
        if self._check(kind):
            return self._advance()
        token = self._peek()
        raise _parse_error(token.line, token.column, message)

    def _consume_identifier(self, message: str) -> Token:
        return self._consume("IDENTIFIER", message)

    def _check(self, kind: str) -> bool:
        return self._peek().kind == kind

    def _advance(self) -> Token:
        token = self._peek()
        if token.kind != "EOF":
            self._current += 1
        return token

    def _peek(self) -> Token:
        return self._tokens[self._current]

    def _previous(self) -> Token:
        return self._tokens[self._current - 1]

    def _count_node(self) -> None:
        self._node_count += 1
        if self._node_count > GEL_V1_LIMITS.ast_nodes:
            raise GelBudgetExceededError("GEL AST node limit exceeded")

    def _enter_nesting(self) -> None:
        self._nesting += 1
        if self._nesting > GEL_V1_LIMITS.ast_depth:
            raise GelBudgetExceededError("GEL parser depth limit exceeded")

    def _leave_nesting(self) -> None:
        self._nesting -= 1

    def _validate_depth(self, program: ProgramNode, token: Token) -> None:
        pending: list[tuple[object, int]] = [(program, 1)]
        while pending:
            node, depth = pending.pop()
            if depth > GEL_V1_LIMITS.ast_depth:
                raise GelBudgetExceededError(
                    f"line {token.line}, column {token.column}: GEL AST depth limit exceeded"
                )
            pending.extend((child, depth + 1) for child in _children(node))


def _children(node: object) -> tuple[object, ...]:
    if isinstance(node, ProgramNode):
        return (*node.statements, node.return_statement)
    if isinstance(node, ReturnStatement):
        return (node.expression,)
    if isinstance(node, (LetStatement, SetStatement)):
        return (node.expression,)
    if isinstance(node, IfStatement):
        return (node.condition, *node.then_body, *node.else_body)
    if isinstance(node, ForStatement):
        return (node.iterable, *node.body)
    if isinstance(node, ListExpr):
        return node.items
    if isinstance(node, ObjectExpr):
        return tuple(expression for _, expression in node.fields)
    if isinstance(node, UnaryExpr):
        return (node.operand,)
    if isinstance(node, BinaryExpr):
        return (node.left, node.right)
    if isinstance(node, FieldExpr):
        return (node.target,)
    if isinstance(node, CallExpr):
        return node.arguments
    return ()


def _string_value(token: Token) -> str:
    if type(token.value) is not str:  # pragma: no cover - parser token contracts
        raise AssertionError("GEL token is not a string token")
    return token.value


def _integer_value(token: Token) -> int:
    if type(token.value) is not int:  # pragma: no cover - parser token contracts
        raise AssertionError("GEL token is not an integer token")
    return token.value


def parse_gel(source: str, /) -> ProgramNode:
    """Parse already size-bounded GEL v1 source into a private immutable AST."""

    return _Parser(_tokenize(source)).parse()
