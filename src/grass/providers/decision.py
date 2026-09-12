# SPDX-License-Identifier: GPL-3.0-only

"""Decision invokers and the provider-independent model decision codec."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from grass.core._structured_data import StructuredValue
from grass.core.cognition import BoundedReaction, DecisionOutcomeKind, ProposedPlan
from grass.core.decision_invocations import (
    DecisionInvocationResult,
    DecisionOutputError,
    ProviderInvocationReceipt,
)
from grass.core.decisions import DecisionProposal, DecisionProvider, DecisionRequest
from grass.core.execution import (
    ActionPrimitive,
    PlanDependency,
    PlanDependencyCondition,
    PlanStep,
    PlanStepOrigin,
)
from grass.core.identifiers import PlanId, PlanStepId
from grass.core.model_providers import ActorModelContext, ModelProvider, ModelRequest, ModelResponse
from grass.core.provider_bindings import DecisionProviderBinding, ModelProviderBinding

MODEL_DECISION_CONTEXT_VERSION = 1
MODEL_DECISION_MAX_OUTPUT_TOKENS = 4096
MODEL_DECISION_MAX_STEPS = 64

_INSTRUCTIONS = """Return exactly one structured actor decision matching the supplied schema.
Do not claim that intended outcomes already happened. Plans contain actor intentions only.
Use local step keys for dependency references. Do not emit GRASS identifiers."""

_OUTPUT_SCHEMA: Mapping[str, StructuredValue] = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind"],
            "properties": {"kind": {"const": "CONTINUE_PLAN"}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "intent_description", "content"],
            "properties": {
                "kind": {"const": "BOUNDED_REACTION"},
                "intent_description": {"type": "string", "minLength": 1},
                "content": {},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "objective", "steps"],
            "properties": {
                "kind": {"enum": ["REVISE_PLAN", "REPLACE_PLAN"]},
                "objective": {"type": "string", "minLength": 1},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MODEL_DECISION_MAX_STEPS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "key",
                            "primitive",
                            "bindings",
                            "parameters",
                            "dependencies",
                            "description",
                        ],
                        "properties": {
                            "key": {"type": "string", "minLength": 1},
                            "primitive": {
                                "type": "string",
                                "enum": [item.value for item in ActionPrimitive],
                            },
                            "bindings": {"type": "object"},
                            "parameters": {"type": "object"},
                            "dependencies": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["key", "condition"],
                                    "properties": {
                                        "key": {"type": "string", "minLength": 1},
                                        "condition": {
                                            "type": "string",
                                            "enum": [
                                                item.value for item in PlanDependencyCondition
                                            ],
                                        },
                                    },
                                },
                            },
                            "description": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    ]
}


class DecisionModelIdAllocator(Protocol):
    def plan_id(self, request: DecisionRequest, /) -> PlanId:
        """Allocate one trusted Plan identity for a new/replacement Plan."""

        ...

    def plan_step_id(self, request: DecisionRequest, local_key: str, /) -> PlanStepId:
        """Allocate one trusted PlanStep identity for a local model key."""

        ...


def _exact_fields(value: Mapping[str, object], fields: frozenset[str], name: str) -> None:
    if frozenset(value) != fields:
        raise DecisionOutputError(f"{name} must contain exactly {sorted(fields)}")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(type(key) is str for key in value):
        raise DecisionOutputError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise DecisionOutputError(f"{name} must be an array")
    return tuple(value)


def _string(value: object, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or value == "":
        raise DecisionOutputError(f"{name} must be a non-empty string")
    return value


def _structured_mapping(value: object, name: str) -> Mapping[str, StructuredValue]:
    mapping = _mapping(value, name)
    return mapping  # type: ignore[return-value]


def _plan_context(request: DecisionRequest) -> StructuredValue:
    plan = request.subject_plan
    if plan is None:
        return None
    aliases = {step.step_id: f"step_{index}" for index, step in enumerate(plan.steps, start=1)}
    return {
        "objective": plan.objective,
        "steps": tuple(
            {
                "key": aliases[step.step_id],
                "primitive": step.primitive.value,
                "bindings": step.bindings,
                "parameters": step.parameters,
                "dependencies": tuple(
                    {
                        "key": aliases[dependency.step_id],
                        "condition": dependency.condition.value,
                    }
                    for dependency in sorted(
                        step.dependencies,
                        key=lambda item: (item.step_id.value, item.condition.value),
                    )
                ),
                "description": step.description,
            }
            for step in plan.steps
        ),
    }


class DecisionModelCodec:
    """Translate between actor-relative decisions and generic structured model I/O."""

    def build_request(self, request: DecisionRequest, model: str, /) -> ModelRequest:
        if type(request) is not DecisionRequest:
            raise TypeError("request must be a DecisionRequest")
        observations: tuple[StructuredValue, ...] = tuple(
            {
                "content": observation.content,
                "observed_at": observation.observed_at.nanoseconds_from_origin,
            }
            for observation in request.observations
        )
        sections = cast(
            Mapping[str, StructuredValue],
            {
                "decision": {
                    "reason": request.decision_point.reason.value,
                    "scope": request.decision_point.scope.value,
                    "observations": observations,
                    "subject_plan": _plan_context(request),
                }
            },
        )
        context = ActorModelContext(MODEL_DECISION_CONTEXT_VERSION, sections)
        return ModelRequest(
            model=model,
            instructions=_INSTRUCTIONS,
            context=context,
            output_schema=_OUTPUT_SCHEMA,
            max_output_tokens=MODEL_DECISION_MAX_OUTPUT_TOKENS,
        )

    def decode(
        self,
        request: DecisionRequest,
        response: ModelResponse,
        allocator: DecisionModelIdAllocator,
        /,
    ) -> DecisionProposal:
        if type(request) is not DecisionRequest:
            raise TypeError("request must be a DecisionRequest")
        if type(response) is not ModelResponse:
            raise TypeError("response must be a ModelResponse")
        document = _mapping(response.output, "model decision")
        kind_value = document.get("kind")
        if type(kind_value) is not str:
            raise DecisionOutputError("model decision kind must be a string")
        try:
            kind = DecisionOutcomeKind(kind_value)
        except ValueError as error:
            raise DecisionOutputError("model decision kind is unknown") from error
        if kind is DecisionOutcomeKind.CONTINUE_PLAN:
            _exact_fields(document, frozenset({"kind"}), "CONTINUE_PLAN")
            try:
                return DecisionProposal(kind)
            except (TypeError, ValueError) as error:
                raise DecisionOutputError("CONTINUE_PLAN is invalid for this request") from error
        if kind is DecisionOutcomeKind.BOUNDED_REACTION:
            _exact_fields(
                document,
                frozenset({"kind", "intent_description", "content"}),
                "BOUNDED_REACTION",
            )
            intent = _string(document["intent_description"], "intent_description")
            assert intent is not None
            try:
                return DecisionProposal(
                    kind,
                    bounded_reaction=BoundedReaction(intent, document["content"]),  # type: ignore[arg-type]
                )
            except (TypeError, ValueError) as error:
                raise DecisionOutputError("bounded reaction is invalid") from error

        _exact_fields(document, frozenset({"kind", "objective", "steps"}), kind.value)
        objective = _string(document["objective"], "objective")
        assert objective is not None
        raw_steps = _sequence(document["steps"], "steps")
        if not raw_steps or len(raw_steps) > MODEL_DECISION_MAX_STEPS:
            raise DecisionOutputError("steps must contain between 1 and 64 entries")
        drafts: list[
            tuple[
                str,
                ActionPrimitive,
                Mapping[str, StructuredValue],
                Mapping[str, StructuredValue],
                tuple[tuple[str, PlanDependencyCondition], ...],
                str | None,
            ]
        ] = []
        keys: set[str] = set()
        for index, raw_step in enumerate(raw_steps):
            step = _mapping(raw_step, f"steps[{index}]")
            _exact_fields(
                step,
                frozenset(
                    {
                        "key",
                        "primitive",
                        "bindings",
                        "parameters",
                        "dependencies",
                        "description",
                    }
                ),
                f"steps[{index}]",
            )
            key = _string(step["key"], f"steps[{index}].key")
            assert key is not None
            if key in keys:
                raise DecisionOutputError("model step keys must be unique")
            keys.add(key)
            try:
                primitive_value = _string(step["primitive"], "primitive")
                assert primitive_value is not None
                primitive = ActionPrimitive(primitive_value)
            except (TypeError, ValueError) as error:
                raise DecisionOutputError("model step primitive is unknown") from error
            dependencies: list[tuple[str, PlanDependencyCondition]] = []
            for dependency_index, raw_dependency in enumerate(
                _sequence(step["dependencies"], f"steps[{index}].dependencies")
            ):
                dependency = _mapping(raw_dependency, "dependency")
                _exact_fields(dependency, frozenset({"key", "condition"}), "dependency")
                dependency_key = _string(dependency["key"], "dependency.key")
                assert dependency_key is not None
                try:
                    condition_value = _string(dependency["condition"], "dependency.condition")
                    assert condition_value is not None
                    condition = PlanDependencyCondition(condition_value)
                except (TypeError, ValueError) as error:
                    raise DecisionOutputError(
                        f"dependency {dependency_index} condition is unknown"
                    ) from error
                dependencies.append((dependency_key, condition))
            if len(set(dependencies)) != len(dependencies):
                raise DecisionOutputError("model step dependencies must be unique")
            drafts.append(
                (
                    key,
                    primitive,
                    _structured_mapping(step["bindings"], "bindings"),
                    _structured_mapping(step["parameters"], "parameters"),
                    tuple(dependencies),
                    _string(step["description"], "description", nullable=True),
                )
            )
        if any(dependency_key not in keys for draft in drafts for dependency_key, _ in draft[4]):
            raise DecisionOutputError("dependencies must reference local model step keys")
        try:
            step_ids = {
                key: allocator.plan_step_id(request, key)
                for key, _primitive, _bindings, _parameters, _dependencies, _description in drafts
            }
            steps = tuple(
                PlanStep(
                    step_id=step_ids[key],
                    primitive=primitive,
                    blueprint_ref=None,
                    bindings=bindings,
                    parameters=parameters,
                    dependencies=frozenset(
                        PlanDependency(step_ids[dependency_key], condition)
                        for dependency_key, condition in dependencies
                    ),
                    origin=PlanStepOrigin.ACTOR_INTENT,
                    description=description,
                )
                for key, primitive, bindings, parameters, dependencies, description in drafts
            )
            subject = request.subject_plan
            if kind is DecisionOutcomeKind.REVISE_PLAN:
                if subject is None:
                    raise DecisionOutputError("REVISE_PLAN requires a subject Plan")
                plan_id = subject.plan_id
                version = subject.version + 1
                replaces = subject.replaces_plan_ref
            else:
                plan_id = allocator.plan_id(request)
                version = 1
                replaces = None if subject is None else subject.ref
            plan = ProposedPlan(
                plan_id,
                version,
                request.decision_point.actor_id,
                objective,
                steps,
                replaces,
            )
            return DecisionProposal(kind, proposed_plan=plan)
        except DecisionOutputError:
            raise
        except (TypeError, ValueError) as error:
            raise DecisionOutputError("model Plan draft is invalid") from error


class SyncDecisionProviderAdapter:
    """Thin async adapter for an inexpensive synchronous DecisionProvider."""

    def __init__(
        self,
        provider: DecisionProvider,
        binding: DecisionProviderBinding,
        *,
        provider_name: str,
    ) -> None:
        if binding.model_binding_id is not None:
            raise ValueError("a synchronous DecisionProvider binding cannot reference a model")
        if type(provider_name) is not str or provider_name == "":
            raise ValueError("provider_name must be a non-empty string")
        self._provider = provider
        self._binding = binding
        self._provider_name = provider_name

    async def invoke(self, request: DecisionRequest, /) -> DecisionInvocationResult:
        proposal = self._provider.decide(request)
        if type(proposal) is not DecisionProposal:
            raise DecisionOutputError("synchronous DecisionProvider returned invalid output")
        return DecisionInvocationResult(
            proposal,
            ProviderInvocationReceipt(
                self._binding.binding_id,
                None,
                self._binding.execution_location,
                self._binding.invoker_ref,
                self._provider_name,
            ),
        )


class ModelBackedDecisionInvoker:
    """Model-backed decision policy above the generic ModelProvider transport."""

    def __init__(
        self,
        provider: ModelProvider,
        decision_binding: DecisionProviderBinding,
        model_binding: ModelProviderBinding,
        allocator: DecisionModelIdAllocator,
        *,
        codec: DecisionModelCodec | None = None,
    ) -> None:
        if decision_binding.model_binding_id != model_binding.binding_id:
            raise ValueError("decision and model bindings must match")
        self._provider = provider
        self._decision_binding = decision_binding
        self._model_binding = model_binding
        self._allocator = allocator
        self._codec = DecisionModelCodec() if codec is None else codec

    async def invoke(self, request: DecisionRequest, /) -> DecisionInvocationResult:
        model_request = self._codec.build_request(request, self._model_binding.model)
        response = await self._provider.invoke(model_request)
        if type(response) is not ModelResponse:
            raise DecisionOutputError("ModelProvider returned invalid output")
        proposal = self._codec.decode(request, response, self._allocator)
        return DecisionInvocationResult(
            proposal,
            ProviderInvocationReceipt(
                decision_binding_id=self._decision_binding.binding_id,
                model_binding_id=self._model_binding.binding_id,
                execution_location=self._decision_binding.execution_location,
                invoker_ref=self._decision_binding.invoker_ref,
                provider=response.provider,
                model=response.model,
                provider_request_id=response.provider_request_id,
                result_status=response.result_status,
                usage=response.usage,
            ),
        )
