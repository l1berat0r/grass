# SPDX-License-Identifier: GPL-3.0-only

import asyncio
from dataclasses import dataclass, field

import pytest

from grass.core import (
    ActionPrimitive,
    BoundedReaction,
    DecisionInvocationResult,
    DecisionOutcomeKind,
    DecisionOutputError,
    DecisionPoint,
    DecisionPointId,
    DecisionPointReason,
    DecisionPointScope,
    DecisionProposal,
    DecisionProviderBinding,
    DecisionRequest,
    EntityId,
    LogicalTime,
    ModelProviderBinding,
    ModelProviderBindingId,
    ModelRequest,
    ModelResponse,
    Observation,
    ObservationId,
    Plan,
    PlanId,
    PlanRef,
    PlanStep,
    PlanStepId,
    PlanStepOrigin,
    Provenance,
    ProviderBindingId,
    ProviderExecutionLocation,
    ScriptedDecisionProvider,
)
from grass.providers import (
    DecisionModelCodec,
    ModelBackedDecisionInvoker,
    SyncDecisionProviderAdapter,
)


def decision_request(*, with_plan: bool = False) -> DecisionRequest:
    actor = EntityId("actor")
    observation = Observation(
        ObservationId("observation"),
        actor,
        {"message": "Please wait"},
        Provenance("ENGINE"),
        LogicalTime(4),
    )
    plan = None
    subject = None
    if with_plan:
        plan = Plan(
            PlanId("existing-plan"),
            1,
            actor,
            "Existing objective",
            (
                PlanStep(
                    PlanStepId("existing-step"),
                    ActionPrimitive.WAIT,
                    None,
                    {},
                    {},
                    frozenset(),
                    PlanStepOrigin.ACTOR_INTENT,
                ),
            ),
            None,
            Provenance("ACTOR"),
            LogicalTime(2),
        )
        subject = plan.ref
    point = DecisionPoint(
        DecisionPointId("point"),
        actor,
        DecisionPointReason.MATERIAL_OBSERVATION,
        DecisionPointScope.FULL,
        frozenset({observation.observation_id}),
        subject,
    )
    return DecisionRequest(point, (observation,), plan)


@dataclass
class StableAllocator:
    plan_calls: int = 0
    step_keys: list[str] = field(default_factory=list)

    def plan_id(self, request: DecisionRequest, /) -> PlanId:
        self.plan_calls += 1
        return PlanId(f"trusted-{request.decision_point.decision_point_id.value}")

    def plan_step_id(self, request: DecisionRequest, local_key: str, /) -> PlanStepId:
        self.step_keys.append(local_key)
        return PlanStepId(f"trusted-{local_key}")


def response(output: dict[str, object]) -> ModelResponse:
    return ModelResponse(output, "fake-model-provider", "model-actual", "request-1", "complete")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "with_plan,output,expected_kind",
    [
        (True, {"kind": "CONTINUE_PLAN"}, DecisionOutcomeKind.CONTINUE_PLAN),
        (
            False,
            {"kind": "BOUNDED_REACTION", "intent_description": "Reply", "content": None},
            DecisionOutcomeKind.BOUNDED_REACTION,
        ),
        (
            True,
            {
                "kind": "REVISE_PLAN",
                "objective": "Revised",
                "steps": [
                    {
                        "key": "first",
                        "primitive": "WAIT",
                        "bindings": {},
                        "parameters": {},
                        "dependencies": [],
                        "description": None,
                    }
                ],
            },
            DecisionOutcomeKind.REVISE_PLAN,
        ),
        (
            False,
            {
                "kind": "REPLACE_PLAN",
                "objective": "New",
                "steps": [
                    {
                        "key": "first",
                        "primitive": "WAIT",
                        "bindings": {},
                        "parameters": {},
                        "dependencies": [],
                        "description": None,
                    }
                ],
            },
            DecisionOutcomeKind.REPLACE_PLAN,
        ),
    ],
)
def test_codec_supports_all_decision_kinds_with_trusted_ids(
    with_plan: bool, output: dict[str, object], expected_kind: DecisionOutcomeKind
) -> None:
    request = decision_request(with_plan=with_plan)
    allocator = StableAllocator()

    proposal = DecisionModelCodec().decode(request, response(output), allocator)

    assert proposal.kind is expected_kind
    if proposal.proposed_plan is not None:
        assert proposal.proposed_plan.actor_id == EntityId("actor")
        assert proposal.proposed_plan.steps[0].step_id == PlanStepId("trusted-first")
        if expected_kind is DecisionOutcomeKind.REVISE_PLAN:
            assert proposal.proposed_plan.ref == PlanRef(PlanId("existing-plan"), 2)
            assert allocator.plan_calls == 0
        else:
            assert proposal.proposed_plan.plan_id == PlanId("trusted-point")


@pytest.mark.parametrize(
    "output",
    [
        {"kind": "UNKNOWN"},
        {"kind": "CONTINUE_PLAN", "plan_id": "model-id"},
        {
            "kind": "REPLACE_PLAN",
            "objective": "Bad IDs",
            "steps": [
                {
                    "key": "one",
                    "step_id": "model-step-id",
                    "primitive": "WAIT",
                    "bindings": {},
                    "parameters": {},
                    "dependencies": [],
                    "description": None,
                }
            ],
        },
        {
            "kind": "REPLACE_PLAN",
            "objective": "Duplicate dependencies",
            "steps": [
                {
                    "key": "first",
                    "primitive": "WAIT",
                    "bindings": {},
                    "parameters": {},
                    "dependencies": [],
                    "description": None,
                },
                {
                    "key": "second",
                    "primitive": "WAIT",
                    "bindings": {},
                    "parameters": {},
                    "dependencies": [
                        {"key": "first", "condition": "SUCCESS"},
                        {"key": "first", "condition": "SUCCESS"},
                    ],
                    "description": None,
                },
            ],
        },
    ],
)
def test_codec_rejects_unknown_extra_and_model_authoritative_ids(
    output: dict[str, object],
) -> None:
    with pytest.raises(DecisionOutputError):
        DecisionModelCodec().decode(decision_request(), response(output), StableAllocator())


def test_model_request_contains_only_actor_relative_context_and_no_grass_ids() -> None:
    model_request = DecisionModelCodec().build_request(decision_request(with_plan=True), "model")
    rendered = repr(model_request.context.sections)

    assert "Please wait" in rendered
    assert "Existing objective" in rendered
    assert "existing-plan" not in rendered
    assert "existing-step" not in rendered
    assert not hasattr(model_request, "state")
    assert not hasattr(model_request, "world")


class FakeModelProvider:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.requests: list[ModelRequest] = []

    async def invoke(self, request: ModelRequest, /) -> ModelResponse:
        self.requests.append(request)
        return response(self.output)


def test_model_backed_invoker_returns_semantic_proposal_and_actual_receipt() -> None:
    decision_binding = DecisionProviderBinding(
        ProviderBindingId("decision"),
        "model-decision",
        ProviderExecutionLocation.SERVER_MANAGED,
        ModelProviderBindingId("model-binding"),
    )
    model_binding = ModelProviderBinding(
        ModelProviderBindingId("model-binding"), "fake", "requested-model"
    )
    provider = FakeModelProvider(
        {"kind": "BOUNDED_REACTION", "intent_description": "Answer", "content": "yes"}
    )
    invoker = ModelBackedDecisionInvoker(
        provider, decision_binding, model_binding, StableAllocator()
    )

    result = asyncio.run(invoker.invoke(decision_request()))

    assert type(result) is DecisionInvocationResult
    assert result.proposal.kind is DecisionOutcomeKind.BOUNDED_REACTION
    assert provider.requests[0].model == "requested-model"
    assert result.receipt.provider == "fake-model-provider"
    assert result.receipt.model == "model-actual"


class InvalidModelProvider:
    async def invoke(self, request: ModelRequest, /) -> ModelResponse:
        return object()  # type: ignore[return-value]


def test_model_backed_invoker_rejects_invalid_model_provider_output() -> None:
    invoker = ModelBackedDecisionInvoker(
        InvalidModelProvider(),
        DecisionProviderBinding(
            ProviderBindingId("decision"),
            "model-decision",
            ProviderExecutionLocation.SERVER_MANAGED,
            ModelProviderBindingId("model-binding"),
        ),
        ModelProviderBinding(ModelProviderBindingId("model-binding"), "fake", "model"),
        StableAllocator(),
    )

    with pytest.raises(DecisionOutputError, match="ModelProvider returned invalid output"):
        asyncio.run(invoker.invoke(decision_request()))


def test_synchronous_decision_provider_remains_usable_through_async_adapter() -> None:
    request = decision_request()
    proposal = DecisionProposal(
        DecisionOutcomeKind.BOUNDED_REACTION,
        bounded_reaction=BoundedReaction("Wait"),
    )
    provider = ScriptedDecisionProvider({DecisionPointId("point"): proposal})
    adapter = SyncDecisionProviderAdapter(
        provider,
        DecisionProviderBinding(
            ProviderBindingId("sync"),
            "scripted",
            ProviderExecutionLocation.SERVER_MANAGED,
        ),
        provider_name="scripted",
    )

    result = asyncio.run(adapter.invoke(request))

    assert result.proposal is proposal
    assert provider.requests == (request,)
    assert result.receipt.decision_binding_id == ProviderBindingId("sync")
