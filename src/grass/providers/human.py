# SPDX-License-Identifier: GPL-3.0-only

"""Transport-neutral asynchronous human decision acquisition boundary."""

from __future__ import annotations

from typing import Protocol

from grass.core.decision_invocations import (
    DecisionInvocationResult,
    DecisionOutputError,
    ProviderInvocationReceipt,
)
from grass.core.decisions import DecisionProposal, DecisionRequest
from grass.core.provider_bindings import DecisionProviderBinding


class HumanDecisionSource(Protocol):
    async def acquire(self, request: DecisionRequest, /) -> DecisionProposal:
        """Await one human proposal through an external transport-neutral source."""

        ...


class HumanDecisionInvoker:
    """Await a human source without assigning waiting any simulation-time meaning."""

    def __init__(
        self,
        source: HumanDecisionSource,
        binding: DecisionProviderBinding,
        *,
        provider_name: str = "human",
    ) -> None:
        if binding.model_binding_id is not None:
            raise ValueError("a human decision binding cannot reference a model")
        if type(provider_name) is not str or provider_name == "":
            raise ValueError("provider_name must be a non-empty string")
        self._source = source
        self._binding = binding
        self._provider_name = provider_name

    async def invoke(self, request: DecisionRequest, /) -> DecisionInvocationResult:
        proposal = await self._source.acquire(request)
        if type(proposal) is not DecisionProposal:
            raise DecisionOutputError("human source returned invalid output")
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
