# SPDX-License-Identifier: GPL-3.0-only

"""Asynchronous decision acquisition and post-invocation revalidation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol, TypeAlias

from grass.core._structured_data import StructuredValue
from grass.core.branches import HistoryPosition
from grass.core.cognition import DecisionPoint
from grass.core.decisions import (
    CognitionValidationError,
    DecisionProposal,
    DecisionRequest,
    PreparedCognitionTransition,
    build_decision_request,
    prepare_decision_proposal_transition,
)
from grass.core.events import CauseRef, CommittedTransition
from grass.core.identifiers import (
    CorrelationId,
    DecisionPointId,
    EventId,
    ModelProviderBindingId,
    ProviderBindingId,
)
from grass.core.logical_time import LogicalTime
from grass.core.model_providers import ModelUsage, ProviderInvocationError
from grass.core.provenance import Provenance, ProvenanceSourceRef
from grass.core.provider_bindings import (
    ProviderBindingConfiguration,
    ProviderBindingError,
    ProviderExecutionLocation,
    ResolvedDecisionProviderBinding,
    resolve_decision_provider_binding,
)
from grass.core.references import TransitionRef
from grass.core.state import SimulationState


class DecisionOutputError(ValueError):
    """An invoker produced an invalid semantic DecisionProposal."""


class StaleDecisionContextError(ValueError):
    """Acquired cognition no longer matches its actor-relative semantic input."""


@dataclass(frozen=True, slots=True)
class ProviderInvocationReceipt:
    """Safe actual-provider facts from one successful invocation."""

    RECEIPT_VERSION: ClassVar[int] = 1

    decision_binding_id: ProviderBindingId
    model_binding_id: ModelProviderBindingId | None
    execution_location: ProviderExecutionLocation
    invoker_ref: str
    provider: str
    model: str | None = None
    provider_request_id: str | None = None
    result_status: str | None = None
    usage: ModelUsage | None = None

    def __post_init__(self) -> None:
        if type(self.decision_binding_id) is not ProviderBindingId:
            raise TypeError("decision_binding_id must be a ProviderBindingId")
        if (
            self.model_binding_id is not None
            and type(self.model_binding_id) is not ModelProviderBindingId
        ):
            raise TypeError("model_binding_id must be a ModelProviderBindingId or None")
        if type(self.execution_location) is not ProviderExecutionLocation:
            raise TypeError("execution_location must be a ProviderExecutionLocation")
        _non_empty_string(self.invoker_ref, "invoker_ref")
        _non_empty_string(self.provider, "provider")
        if self.model is not None:
            _non_empty_string(self.model, "model")
        if self.provider_request_id is not None:
            _non_empty_string(self.provider_request_id, "provider_request_id")
        if self.result_status is not None:
            _non_empty_string(self.result_status, "result_status")
        if self.usage is not None and type(self.usage) is not ModelUsage:
            raise TypeError("usage must be ModelUsage or None")
        if (self.model_binding_id is None) != (self.model is None):
            raise ValueError("model identity requires both model binding and actual model")


def _non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class DecisionInvocationResult:
    proposal: DecisionProposal
    receipt: ProviderInvocationReceipt

    def __post_init__(self) -> None:
        if type(self.proposal) is not DecisionProposal:
            raise TypeError("proposal must be a DecisionProposal")
        if type(self.receipt) is not ProviderInvocationReceipt:
            raise TypeError("receipt must be a ProviderInvocationReceipt")


class DecisionInvoker(Protocol):
    async def invoke(self, request: DecisionRequest, /) -> DecisionInvocationResult:
        """Acquire one non-authoritative semantic decision asynchronously."""

        ...


@dataclass(frozen=True, slots=True)
class DecisionInvocationContext:
    """Immutable semantic and routing context captured before external I/O."""

    base_position: HistoryPosition
    logical_time: LogicalTime
    request: DecisionRequest
    resolved_binding: ResolvedDecisionProviderBinding

    def __post_init__(self) -> None:
        if type(self.base_position) is not HistoryPosition:
            raise TypeError("base_position must be a HistoryPosition")
        if type(self.logical_time) is not LogicalTime:
            raise TypeError("logical_time must be a LogicalTime")
        if type(self.request) is not DecisionRequest:
            raise TypeError("request must be a DecisionRequest")
        if type(self.resolved_binding) is not ResolvedDecisionProviderBinding:
            raise TypeError("resolved_binding must be a ResolvedDecisionProviderBinding")

    @property
    def decision_point(self) -> DecisionPoint:
        return self.request.decision_point


@dataclass(frozen=True, slots=True)
class DecisionAcquisitionSuccess:
    context: DecisionInvocationContext
    result: DecisionInvocationResult

    def __post_init__(self) -> None:
        if type(self.context) is not DecisionInvocationContext:
            raise TypeError("context must be a DecisionInvocationContext")
        if type(self.result) is not DecisionInvocationResult:
            raise TypeError("result must be a DecisionInvocationResult")


@dataclass(frozen=True, slots=True)
class DecisionAcquisitionFailure:
    context: DecisionInvocationContext
    error: ProviderInvocationError | DecisionOutputError

    def __post_init__(self) -> None:
        if type(self.context) is not DecisionInvocationContext:
            raise TypeError("context must be a DecisionInvocationContext")
        if not isinstance(self.error, (ProviderInvocationError, DecisionOutputError)):
            raise TypeError("error must be a provider invocation or decision output error")


DecisionAcquisitionOutcome: TypeAlias = DecisionAcquisitionSuccess | DecisionAcquisitionFailure


def capture_decision_invocation_context(
    state: SimulationState,
    decision_point_id: DecisionPointId,
    configuration: ProviderBindingConfiguration,
    base_position: HistoryPosition,
    /,
    *,
    base_history: Sequence[CommittedTransition],
) -> DecisionInvocationContext:
    """Capture one pending DecisionPoint's exact input and effective binding."""

    if type(state) is not SimulationState:
        raise TypeError("state must be a SimulationState")
    if type(base_position) is not HistoryPosition:
        raise TypeError("base_position must be a HistoryPosition")
    if base_position.branch_id != state.position.branch_id:
        raise ValueError("base position and state branches must match")
    history = tuple(base_history)
    if not history or not all(type(item) is CommittedTransition for item in history):
        raise ValueError("decision invocation requires non-empty committed base history")
    if base_position.transition_ref != history[-1].transition_ref:
        raise ValueError("base position must identify the visible history head")
    request = build_decision_request(state, decision_point_id)
    resolved = resolve_decision_provider_binding(configuration, request.decision_point.actor_id)
    return DecisionInvocationContext(base_position, history[-1].logical_time, request, resolved)


def _canonical_key(context: DecisionInvocationContext) -> tuple[str, str]:
    point = context.request.decision_point
    return point.actor_id.value, point.decision_point_id.value


async def acquire_decisions(
    contexts: Sequence[DecisionInvocationContext],
    invokers: Mapping[ProviderBindingId, DecisionInvoker],
    /,
) -> tuple[DecisionAcquisitionOutcome, ...]:
    """Acquire one same-frontier, distinct-actor batch in canonical result order."""

    values = tuple(contexts)
    if not all(type(item) is DecisionInvocationContext for item in values):
        raise TypeError("contexts must contain DecisionInvocationContext values")
    ordered = tuple(sorted(values, key=_canonical_key))
    if not ordered:
        return ()
    if len({_canonical_key(item) for item in ordered}) != len(ordered):
        raise ValueError("decision invocation contexts must be unique")
    if len({item.decision_point.actor_id for item in ordered}) != len(ordered):
        raise ValueError("a concurrent batch may contain at most one DecisionPoint per actor")
    first = ordered[0]
    if any(
        item.base_position != first.base_position or item.logical_time != first.logical_time
        for item in ordered[1:]
    ):
        raise ValueError("a concurrent batch must share one history frontier")
    configured_invokers = dict(invokers)
    if not all(type(key) is ProviderBindingId for key in configured_invokers):
        raise TypeError("invokers must use ProviderBindingId keys")
    missing = {
        item.resolved_binding.binding.binding_id
        for item in ordered
        if item.resolved_binding.binding.binding_id not in configured_invokers
    }
    if missing:
        raise ProviderBindingError("no DecisionInvoker is configured for a resolved binding")

    async def invoke_one(context: DecisionInvocationContext) -> DecisionAcquisitionOutcome:
        binding_id = context.resolved_binding.binding.binding_id
        invoker = configured_invokers[binding_id]
        try:
            result = await invoker.invoke(context.request)
        except (ProviderInvocationError, DecisionOutputError) as error:
            return DecisionAcquisitionFailure(context, error)
        if type(result) is not DecisionInvocationResult:
            return DecisionAcquisitionFailure(
                context, DecisionOutputError("DecisionInvoker returned invalid output")
            )
        if result.receipt.decision_binding_id != binding_id:
            return DecisionAcquisitionFailure(
                context, DecisionOutputError("invocation receipt does not match resolved binding")
            )
        return DecisionAcquisitionSuccess(context, result)

    # asyncio.gather preserves input order; provider completion order is deliberately ignored.
    return tuple(await asyncio.gather(*(invoke_one(item) for item in ordered)))


def provider_invocation_provenance(receipt: ProviderInvocationReceipt, /) -> Provenance:
    """Convert one safe receipt into existing Event provenance."""

    if type(receipt) is not ProviderInvocationReceipt:
        raise TypeError("receipt must be a ProviderInvocationReceipt")
    metadata: dict[str, StructuredValue] = {
        "receipt_version": receipt.RECEIPT_VERSION,
        "execution_location": receipt.execution_location.value,
        "invoker_ref": receipt.invoker_ref,
        "provider": receipt.provider,
        "model_binding_id": (
            None if receipt.model_binding_id is None else receipt.model_binding_id.value
        ),
        "model": receipt.model,
        "provider_request_id": receipt.provider_request_id,
        "result_status": receipt.result_status,
        "usage": (
            None
            if receipt.usage is None
            else {
                "input_tokens": receipt.usage.input_tokens,
                "output_tokens": receipt.usage.output_tokens,
            }
        ),
    }
    return Provenance(
        "DECISION_PROVIDER",
        ProvenanceSourceRef("provider_binding", receipt.decision_binding_id.value),
        metadata,
    )


def prepare_invoked_decision_transition(
    acquisition: DecisionAcquisitionSuccess,
    state: SimulationState,
    configuration: ProviderBindingConfiguration,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    *,
    base_history: Sequence[CommittedTransition],
    causation_refs: Sequence[CauseRef] = (),
    correlation_id: CorrelationId | None = None,
) -> PreparedCognitionTransition:
    """Revalidate acquired cognition and prepare it without invoking a provider."""

    if type(acquisition) is not DecisionAcquisitionSuccess:
        raise TypeError("acquisition must be a DecisionAcquisitionSuccess")
    context = acquisition.context
    if (
        context.base_position.branch_id != state.position.branch_id
        or transition_ref.branch_id != state.position.branch_id
    ):
        raise StaleDecisionContextError("invocation result belongs to another branch")
    point_id = context.decision_point.decision_point_id
    try:
        current = build_decision_request(state, point_id)
    except CognitionValidationError as error:
        raise StaleDecisionContextError(
            "DecisionPoint is no longer pending after invocation"
        ) from error
    if current != context.request:
        raise StaleDecisionContextError("actor-relative DecisionRequest changed after invocation")
    resolved = resolve_decision_provider_binding(configuration, current.decision_point.actor_id)
    if resolved != context.resolved_binding:
        raise StaleDecisionContextError("effective provider binding changed after invocation")
    receipt = acquisition.result.receipt
    if receipt.decision_binding_id != resolved.binding.binding_id:
        raise DecisionOutputError("invocation receipt does not match effective binding")
    if receipt.execution_location is not resolved.binding.execution_location:
        raise DecisionOutputError("invocation receipt has the wrong execution location")
    if receipt.invoker_ref != resolved.binding.invoker_ref:
        raise DecisionOutputError("invocation receipt does not match effective invoker")
    expected_model_id = (
        None if resolved.model_binding is None else resolved.model_binding.binding_id
    )
    if receipt.model_binding_id != expected_model_id:
        raise DecisionOutputError("invocation receipt does not match effective model binding")
    return prepare_decision_proposal_transition(
        acquisition.result.proposal,
        provider_invocation_provenance(receipt),
        state,
        point_id,
        transition_ref,
        event_ids,
        base_history=base_history,
        causation_refs=causation_refs,
        correlation_id=correlation_id,
    )
