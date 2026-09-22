# SPDX-License-Identifier: GPL-3.0-only

"""Actor-relative terminal implementation of HumanDecisionSource."""

from __future__ import annotations

import json
from math import isfinite
from typing import TextIO, cast
from uuid import uuid4

from grass.cli.output import structured
from grass.core import DecisionOutputError, DecisionProposal, DecisionRequest, PlanId, PlanStepId
from grass.providers import decode_decision_document

_MAX_INPUT_CHARACTERS = 1_048_576


class _DuplicateKeyError(ValueError):
    pass


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("JSON numbers must be finite")
    return parsed


def _constant(value: str) -> object:
    raise ValueError(f"JSON constant is unsupported: {value}")


class CliDecisionIdAllocator:
    """Allocate trusted identities after a terminal decision document is parsed."""

    def plan_id(self, request: DecisionRequest, /) -> PlanId:
        del request
        return PlanId(str(uuid4()))

    def plan_step_id(self, request: DecisionRequest, local_key: str, /) -> PlanStepId:
        del request, local_key
        return PlanStepId(str(uuid4()))


class CliHumanDecisionSource:
    """Read one strict structured actor decision from a local terminal."""

    def __init__(self, stdin: TextIO, stderr: TextIO) -> None:
        self._stdin = stdin
        self._stderr = stderr

    def _prompt(self, request: DecisionRequest) -> None:
        point = request.decision_point
        actor_id = json.dumps(point.actor_id.value, ensure_ascii=True)
        self._stderr.write(
            "Human decision required "
            f"for actor {actor_id}: {point.reason.value} ({point.scope.value})\n"
        )
        for observation in request.observations:
            content = json.dumps(structured(observation.content), ensure_ascii=True, sort_keys=True)
            self._stderr.write(
                f"observation at {observation.observed_at.nanoseconds_from_origin}: {content}\n"
            )
        if request.subject_plan is not None:
            objective = json.dumps(request.subject_plan.objective, ensure_ascii=True)
            self._stderr.write(f"subject objective: {objective}\n")
            for index, step in enumerate(request.subject_plan.steps, start=1):
                description = (
                    ""
                    if step.description is None
                    else " - " + json.dumps(step.description, ensure_ascii=True)
                )
                self._stderr.write(f"step_{index}: {step.primitive.value}{description}\n")
        self._stderr.write(
            "Enter one JSON decision using CONTINUE_PLAN, BOUNDED_REACTION, "
            "REVISE_PLAN, or REPLACE_PLAN. Plan steps use local keys.\n> "
        )
        self._stderr.flush()

    async def acquire(self, request: DecisionRequest, /) -> DecisionProposal:
        if type(request) is not DecisionRequest:
            raise TypeError("request must be a DecisionRequest")
        self._prompt(request)
        line = self._stdin.readline(_MAX_INPUT_CHARACTERS + 1)
        if line == "":
            raise DecisionOutputError("human decision input ended before a document was read")
        if len(line) > _MAX_INPUT_CHARACTERS:
            raise DecisionOutputError("human decision input exceeds the size limit")
        try:
            document = json.loads(
                line,
                object_pairs_hook=_object,
                parse_float=_finite_float,
                parse_constant=_constant,
            )
        except (json.JSONDecodeError, _DuplicateKeyError, ValueError) as error:
            raise DecisionOutputError("human decision must be strict JSON") from error
        return decode_decision_document(
            request,
            cast("object", document),
            CliDecisionIdAllocator(),
        )
