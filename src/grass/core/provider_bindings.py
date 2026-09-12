# SPDX-License-Identifier: GPL-3.0-only

"""Non-secret provider bindings and deterministic actor routing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar

from grass.core.identifiers import EntityId, ModelProviderBindingId, ProviderBindingId


def _non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


class ProviderBindingError(ValueError):
    """Provider binding configuration or resolution is invalid."""


class ProviderExecutionLocation(StrEnum):
    SERVER_MANAGED = "SERVER_MANAGED"
    CLIENT_MANAGED = "CLIENT_MANAGED"


class ProviderBindingScope(StrEnum):
    DEFAULT = "DEFAULT"
    GROUP = "GROUP"
    ACTOR = "ACTOR"


@dataclass(frozen=True, slots=True)
class ModelProviderBinding:
    binding_id: ModelProviderBindingId
    provider_ref: str
    model: str

    def __post_init__(self) -> None:
        if type(self.binding_id) is not ModelProviderBindingId:
            raise TypeError("binding_id must be a ModelProviderBindingId")
        _non_empty_string(self.provider_ref, "provider_ref")
        _non_empty_string(self.model, "model")


@dataclass(frozen=True, slots=True)
class DecisionProviderBinding:
    binding_id: ProviderBindingId
    invoker_ref: str
    execution_location: ProviderExecutionLocation
    model_binding_id: ModelProviderBindingId | None = None

    def __post_init__(self) -> None:
        if type(self.binding_id) is not ProviderBindingId:
            raise TypeError("binding_id must be a ProviderBindingId")
        _non_empty_string(self.invoker_ref, "invoker_ref")
        if type(self.execution_location) is not ProviderExecutionLocation:
            raise TypeError("execution_location must be a ProviderExecutionLocation")
        if (
            self.model_binding_id is not None
            and type(self.model_binding_id) is not ModelProviderBindingId
        ):
            raise TypeError("model_binding_id must be a ModelProviderBindingId or None")


def _empty_group_bindings() -> Mapping[str, ProviderBindingId]:
    return MappingProxyType({})


def _empty_actor_groups() -> Mapping[EntityId, str]:
    return MappingProxyType({})


def _empty_actor_bindings() -> Mapping[EntityId, ProviderBindingId]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class DecisionProviderRouting:
    """One default with optional single-group and actor-specific overrides."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    default_binding_id: ProviderBindingId
    group_bindings: Mapping[str, ProviderBindingId] = field(default_factory=_empty_group_bindings)
    actor_group_assignments: Mapping[EntityId, str] = field(default_factory=_empty_actor_groups)
    actor_bindings: Mapping[EntityId, ProviderBindingId] = field(
        default_factory=_empty_actor_bindings
    )

    def __post_init__(self) -> None:
        if type(self.default_binding_id) is not ProviderBindingId:
            raise TypeError("default_binding_id must be a ProviderBindingId")
        groups = dict(self.group_bindings)
        assignments = dict(self.actor_group_assignments)
        actors = dict(self.actor_bindings)
        if not all(type(key) is str and key != "" for key in groups):
            raise TypeError("group binding keys must be non-empty strings")
        if not all(type(value) is ProviderBindingId for value in groups.values()):
            raise TypeError("group bindings must contain ProviderBindingId values")
        if not all(type(key) is EntityId for key in assignments):
            raise TypeError("actor group assignments must use EntityId keys")
        if not all(type(value) is str and value != "" for value in assignments.values()):
            raise TypeError("actor group assignments must contain non-empty strings")
        if not all(type(key) is EntityId for key in actors):
            raise TypeError("actor bindings must use EntityId keys")
        if not all(type(value) is ProviderBindingId for value in actors.values()):
            raise TypeError("actor bindings must contain ProviderBindingId values")
        unknown_groups = frozenset(assignments.values()).difference(groups)
        if unknown_groups:
            raise ProviderBindingError("actor group assignments must reference configured groups")
        object.__setattr__(self, "group_bindings", MappingProxyType(groups))
        object.__setattr__(self, "actor_group_assignments", MappingProxyType(assignments))
        object.__setattr__(self, "actor_bindings", MappingProxyType(actors))


def _empty_decision_bindings() -> Mapping[ProviderBindingId, DecisionProviderBinding]:
    return MappingProxyType({})


def _empty_model_bindings() -> Mapping[ModelProviderBindingId, ModelProviderBinding]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ProviderBindingConfiguration:
    """Run-owned provider catalogs and actor routing without credentials."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    routing: DecisionProviderRouting
    decision_bindings: Mapping[ProviderBindingId, DecisionProviderBinding] = field(
        default_factory=_empty_decision_bindings
    )
    model_bindings: Mapping[ModelProviderBindingId, ModelProviderBinding] = field(
        default_factory=_empty_model_bindings
    )

    def __post_init__(self) -> None:
        if type(self.routing) is not DecisionProviderRouting:
            raise TypeError("routing must be DecisionProviderRouting")
        decisions = dict(self.decision_bindings)
        models = dict(self.model_bindings)
        if not all(
            type(key) is ProviderBindingId
            and type(value) is DecisionProviderBinding
            and key == value.binding_id
            for key, value in decisions.items()
        ):
            raise TypeError("decision_bindings must be keyed by each binding's identity")
        if not all(
            type(key) is ModelProviderBindingId
            and type(value) is ModelProviderBinding
            and key == value.binding_id
            for key, value in models.items()
        ):
            raise TypeError("model_bindings must be keyed by each binding's identity")
        referenced = {
            self.routing.default_binding_id,
            *self.routing.group_bindings.values(),
            *self.routing.actor_bindings.values(),
        }
        if not referenced.issubset(decisions):
            raise ProviderBindingError("provider routing references an unknown decision binding")
        if any(
            binding.model_binding_id is not None and binding.model_binding_id not in models
            for binding in decisions.values()
        ):
            raise ProviderBindingError("decision binding references an unknown model binding")
        object.__setattr__(self, "decision_bindings", MappingProxyType(decisions))
        object.__setattr__(self, "model_bindings", MappingProxyType(models))


@dataclass(frozen=True, slots=True)
class ResolvedDecisionProviderBinding:
    binding: DecisionProviderBinding
    scope: ProviderBindingScope
    routing_group: str | None = None
    model_binding: ModelProviderBinding | None = None

    def __post_init__(self) -> None:
        if type(self.binding) is not DecisionProviderBinding:
            raise TypeError("binding must be a DecisionProviderBinding")
        if type(self.scope) is not ProviderBindingScope:
            raise TypeError("scope must be a ProviderBindingScope")
        if self.routing_group is not None:
            _non_empty_string(self.routing_group, "routing_group")
        if (self.scope is ProviderBindingScope.GROUP) != (self.routing_group is not None):
            raise ValueError("only group-scoped resolutions contain a routing group")
        if self.model_binding is not None and type(self.model_binding) is not ModelProviderBinding:
            raise TypeError("model_binding must be a ModelProviderBinding or None")
        if self.binding.model_binding_id != (
            None if self.model_binding is None else self.model_binding.binding_id
        ):
            raise ValueError("resolved model binding must match the decision binding")


def resolve_decision_provider_binding(
    configuration: ProviderBindingConfiguration,
    actor_id: EntityId,
    /,
) -> ResolvedDecisionProviderBinding:
    """Resolve actor, routing-group, then default precedence without fallback."""

    if type(configuration) is not ProviderBindingConfiguration:
        raise TypeError("configuration must be a ProviderBindingConfiguration")
    if type(actor_id) is not EntityId:
        raise TypeError("actor_id must be an EntityId")
    routing = configuration.routing
    routing_group: str | None = None
    if actor_id in routing.actor_bindings:
        binding_id = routing.actor_bindings[actor_id]
        scope = ProviderBindingScope.ACTOR
    elif actor_id in routing.actor_group_assignments:
        routing_group = routing.actor_group_assignments[actor_id]
        binding_id = routing.group_bindings[routing_group]
        scope = ProviderBindingScope.GROUP
    else:
        binding_id = routing.default_binding_id
        scope = ProviderBindingScope.DEFAULT
    binding = configuration.decision_bindings[binding_id]
    model = (
        None
        if binding.model_binding_id is None
        else configuration.model_bindings[binding.model_binding_id]
    )
    return ResolvedDecisionProviderBinding(binding, scope, routing_group, model)
