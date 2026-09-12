# SPDX-License-Identifier: GPL-3.0-only

import asyncio

from grass.core import (
    BoundedReaction,
    DecisionOutcomeKind,
    DecisionPoint,
    DecisionPointId,
    DecisionPointReason,
    DecisionPointScope,
    DecisionProposal,
    DecisionProviderBinding,
    DecisionRequest,
    EntityId,
    ProviderBindingId,
    ProviderExecutionLocation,
)
from grass.providers import HumanDecisionInvoker


class ImmediateHumanSource:
    def __init__(self) -> None:
        self.requests: list[DecisionRequest] = []

    async def acquire(self, request: DecisionRequest, /) -> DecisionProposal:
        self.requests.append(request)
        return DecisionProposal(
            DecisionOutcomeKind.BOUNDED_REACTION,
            bounded_reaction=BoundedReaction("Wait"),
        )


def request() -> DecisionRequest:
    return DecisionRequest(
        DecisionPoint(
            DecisionPointId("point"),
            EntityId("actor"),
            DecisionPointReason.PLAN_REQUIRED,
            DecisionPointScope.FULL,
            frozenset(),
        ),
        (),
        None,
    )


def test_human_invoker_awaits_transport_neutral_source_and_returns_receipt() -> None:
    source = ImmediateHumanSource()
    invoker = HumanDecisionInvoker(
        source,
        DecisionProviderBinding(
            ProviderBindingId("human"),
            "human",
            ProviderExecutionLocation.CLIENT_MANAGED,
        ),
    )

    result = asyncio.run(invoker.invoke(request()))

    assert source.requests == [request()]
    assert result.proposal.kind is DecisionOutcomeKind.BOUNDED_REACTION
    assert result.receipt.execution_location is ProviderExecutionLocation.CLIENT_MANAGED
    assert result.receipt.provider == "human"
    assert not hasattr(source.requests[0], "state")
