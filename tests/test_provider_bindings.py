# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import fields

import pytest

from grass.core import (
    DecisionProviderBinding,
    DecisionProviderRouting,
    EntityId,
    ModelProviderBinding,
    ModelProviderBindingId,
    ProviderBindingConfiguration,
    ProviderBindingError,
    ProviderBindingId,
    ProviderBindingScope,
    ProviderExecutionLocation,
    SimulationRunConfig,
    WorldDefinitionId,
    WorldDefinitionRef,
    resolve_decision_provider_binding,
)


def provider_configuration() -> ProviderBindingConfiguration:
    model_id = ModelProviderBindingId("ollama-qwen")
    bindings = {
        ProviderBindingId("default"): DecisionProviderBinding(
            ProviderBindingId("default"),
            "openai-decision",
            ProviderExecutionLocation.SERVER_MANAGED,
            ModelProviderBindingId("openai-gpt"),
        ),
        ProviderBindingId("group"): DecisionProviderBinding(
            ProviderBindingId("group"),
            "ollama-decision",
            ProviderExecutionLocation.SERVER_MANAGED,
            model_id,
        ),
        ProviderBindingId("actor"): DecisionProviderBinding(
            ProviderBindingId("actor"),
            "human-decision",
            ProviderExecutionLocation.CLIENT_MANAGED,
        ),
    }
    return ProviderBindingConfiguration(
        routing=DecisionProviderRouting(
            ProviderBindingId("default"),
            group_bindings={"local": ProviderBindingId("group")},
            actor_group_assignments={
                EntityId("group-actor"): "local",
                EntityId("actor-override"): "local",
            },
            actor_bindings={EntityId("actor-override"): ProviderBindingId("actor")},
        ),
        decision_bindings=bindings,
        model_bindings={
            ModelProviderBindingId("openai-gpt"): ModelProviderBinding(
                ModelProviderBindingId("openai-gpt"), "openai-primary", "gpt-test"
            ),
            model_id: ModelProviderBinding(model_id, "ollama-local", "qwen-test"),
        },
    )


def test_actor_group_default_routing_precedence_and_model_resolution() -> None:
    configuration = provider_configuration()

    default = resolve_decision_provider_binding(configuration, EntityId("other"))
    group = resolve_decision_provider_binding(configuration, EntityId("group-actor"))
    actor = resolve_decision_provider_binding(configuration, EntityId("actor-override"))

    assert default.scope is ProviderBindingScope.DEFAULT
    assert default.binding.binding_id == ProviderBindingId("default")
    assert default.model_binding is not None
    assert default.model_binding.model == "gpt-test"
    assert group.scope is ProviderBindingScope.GROUP
    assert group.routing_group == "local"
    assert group.binding.binding_id == ProviderBindingId("group")
    assert actor.scope is ProviderBindingScope.ACTOR
    assert actor.binding.binding_id == ProviderBindingId("actor")
    assert actor.model_binding is None


def test_provider_configuration_is_immutable_and_rejects_unknown_references() -> None:
    configuration = provider_configuration()

    with pytest.raises(TypeError):
        configuration.decision_bindings[ProviderBindingId("new")] = (  # type: ignore[index]
            configuration.decision_bindings[ProviderBindingId("default")]
        )

    with pytest.raises(ProviderBindingError, match="unknown decision binding"):
        ProviderBindingConfiguration(
            DecisionProviderRouting(ProviderBindingId("missing")),
            {},
            {},
        )


def test_run_config_adds_only_optional_non_secret_provider_bindings() -> None:
    world_ref = WorldDefinitionRef(WorldDefinitionId("world"), "v1")
    old_style = SimulationRunConfig(world_ref)
    configured = SimulationRunConfig(world_ref, provider_configuration())

    assert old_style.provider_bindings is None
    assert configured.provider_bindings is not None
    assert [field.name for field in fields(configured)] == [
        "world_definition_ref",
        "provider_bindings",
    ]
    assert "credential" not in repr(configured).lower()
    assert "api_key" not in repr(configured).lower()
