# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import FrozenInstanceError, fields
from typing import cast

import pytest

from grass.core import (
    EntityId,
    EntityScope,
    InitialConditions,
    LogicalTime,
    RelationId,
    ScenarioEventRuleId,
    SimulationRunConfig,
    WorldDefinitionError,
    WorldDefinitionId,
    WorldDefinitionRef,
    WorldScope,
    load_world_definition,
)


def valid_document() -> dict[str, object]:
    return {
        "world_definition_id": "world",
        "version": "release candidate/one",
        "schema_version": 1,
        "vocabulary": {
            "entity_types": ["Person", "Organization"],
            "relation_types": ["Employment"],
            "resource_types": ["balance"],
            "state_variable_types": ["condition", "weather"],
        },
        "initial_conditions": {
            "logical_time": 100,
            "entities": [
                {"entity_id": "alice", "entity_type": "Person", "properties": {"rank": 1}},
                {
                    "entity_id": "acme",
                    "entity_type": "Organization",
                    "properties": {},
                },
            ],
            "relations": [
                {
                    "relation_id": "employment",
                    "relation_type": "Employment",
                    "participants": [
                        {"role": "employee", "entity_id": "alice"},
                        {"role": "employer", "entity_id": "acme"},
                    ],
                    "properties": {},
                }
            ],
            "resources": [{"entity_id": "alice", "resource_type": "balance", "quantity": -2}],
            "state_variables": [
                {
                    "scope": {"kind": "ENTITY", "entity_id": "alice"},
                    "state_variable_type": "condition",
                    "value": {"status": "ready"},
                },
                {
                    "scope": {"kind": "WORLD"},
                    "state_variable_type": "weather",
                    "value": "clear",
                },
            ],
        },
        "metadata": {"title": "Example", "tags": ["minimal"]},
    }


def valid_version_two_document() -> dict[str, object]:
    document = valid_document()
    document["schema_version"] = 2
    document["scenario_event_rules"] = [
        {
            "rule_id": "network-outage",
            "trigger": {"kind": "AT_TIME", "logical_time": 200},
        }
    ]
    return document


def test_loads_complete_schema_and_preserves_declaration_order() -> None:
    definition = load_world_definition(valid_document())

    assert definition.world_definition_id == WorldDefinitionId("world")
    assert definition.version == "release candidate/one"
    assert definition.ref == WorldDefinitionRef(WorldDefinitionId("world"), "release candidate/one")
    assert definition.schema_version == 1
    assert definition.initial_conditions.logical_time == LogicalTime(100)
    assert [item.entity_id for item in definition.initial_conditions.entities] == [
        EntityId("alice"),
        EntityId("acme"),
    ]
    assert definition.initial_conditions.relations[0].relation_id == RelationId("employment")
    assert definition.initial_conditions.resources[0].quantity == -2
    assert definition.initial_conditions.state_variables[0].scope == EntityScope(EntityId("alice"))
    assert definition.initial_conditions.state_variables[1].scope == WorldScope()
    assert definition.scenario_event_rules == ()


def test_version_two_loads_minimal_at_time_scenario_rule() -> None:
    definition = load_world_definition(valid_version_two_document())

    assert definition.schema_version == 2
    assert len(definition.scenario_event_rules) == 1
    rule = definition.scenario_event_rules[0]
    assert rule.rule_id == ScenarioEventRuleId("network-outage")
    assert rule.logical_time == LogicalTime(200)
    assert rule.ref(definition.ref).world_definition_ref == definition.ref


def test_empty_vocabulary_and_initial_world_are_valid() -> None:
    document = valid_document()
    document["vocabulary"] = {
        "entity_types": [],
        "relation_types": [],
        "resource_types": [],
        "state_variable_types": [],
    }
    document["initial_conditions"] = {
        "logical_time": 0,
        "entities": [],
        "relations": [],
        "resources": [],
        "state_variables": [],
    }

    definition = load_world_definition(document)

    assert definition.initial_conditions == InitialConditions(LogicalTime(0))
    assert definition.vocabulary.entity_types == frozenset()


def test_definition_data_is_deeply_immutable_and_copied() -> None:
    document = valid_document()
    metadata = cast(dict[str, object], document["metadata"])
    tags = cast(list[str], metadata["tags"])
    definition = load_world_definition(document)

    tags.append("mutated")
    metadata["new"] = True

    assert definition.metadata == {"title": "Example", "tags": ("minimal",)}
    with pytest.raises(TypeError):
        cast(dict[str, object], definition.metadata)["new"] = True
    with pytest.raises(FrozenInstanceError):
        definition.version = "other"  # type: ignore[misc]


@pytest.mark.parametrize("field_name", ["metadata", "vocabulary", "initial_conditions"])
def test_root_schema_rejects_missing_fields(field_name: str) -> None:
    document = valid_document()
    del document[field_name]

    with pytest.raises(WorldDefinitionError, match="fields do not match schema"):
        load_world_definition(document)


def test_schema_rejects_extra_fields_at_nested_levels() -> None:
    document = valid_document()
    vocabulary = cast(dict[str, object], document["vocabulary"])
    vocabulary["future_types"] = []

    with pytest.raises(WorldDefinitionError, match="vocabulary fields do not match schema"):
        load_world_definition(document)


@pytest.mark.parametrize("schema_version", [0, 3, True])
def test_rejects_invalid_or_unsupported_schema_version(schema_version: object) -> None:
    document = valid_document()
    document["schema_version"] = schema_version

    with pytest.raises(WorldDefinitionError, match="schema_version"):
        load_world_definition(document)


def test_semantic_version_is_opaque_but_non_empty() -> None:
    document = valid_document()
    document["version"] = "not-semver/by-design"
    assert load_world_definition(document).version == "not-semver/by-design"

    document["version"] = ""
    with pytest.raises(WorldDefinitionError, match="non-empty"):
        load_world_definition(document)


@pytest.mark.parametrize(
    "registry",
    ["entity_types", "relation_types", "resource_types", "state_variable_types"],
)
def test_rejects_duplicate_vocabulary_names(registry: str) -> None:
    document = valid_document()
    vocabulary = cast(dict[str, object], document["vocabulary"])
    vocabulary[registry] = ["duplicate", "duplicate"]

    with pytest.raises(WorldDefinitionError, match="duplicate names"):
        load_world_definition(document)


@pytest.mark.parametrize(
    "category, duplicate",
    [
        (
            "entities",
            {"entity_id": "alice", "entity_type": "Person", "properties": {}},
        ),
        (
            "relations",
            {
                "relation_id": "employment",
                "relation_type": "Employment",
                "participants": [{"role": "employee", "entity_id": "alice"}],
                "properties": {},
            },
        ),
        (
            "resources",
            {"entity_id": "alice", "resource_type": "balance", "quantity": 9},
        ),
        (
            "state_variables",
            {
                "scope": {"kind": "WORLD"},
                "state_variable_type": "weather",
                "value": "rain",
            },
        ),
    ],
)
def test_rejects_duplicate_initial_projected_keys(category: str, duplicate: object) -> None:
    document = valid_document()
    initial = cast(dict[str, object], document["initial_conditions"])
    values = cast(list[object], initial[category])
    values.append(duplicate)

    with pytest.raises(WorldDefinitionError, match="must be unique"):
        load_world_definition(document)


@pytest.mark.parametrize(
    "category, field_name",
    [
        ("entities", "entity_type"),
        ("relations", "relation_type"),
        ("resources", "resource_type"),
        ("state_variables", "state_variable_type"),
    ],
)
def test_rejects_undeclared_initial_type_usage(category: str, field_name: str) -> None:
    document = valid_document()
    initial = cast(dict[str, object], document["initial_conditions"])
    item = cast(dict[str, object], cast(list[object], initial[category])[0])
    item[field_name] = "Undeclared"

    with pytest.raises(WorldDefinitionError, match="undeclared"):
        load_world_definition(document)


@pytest.mark.parametrize("category", ["relations", "resources", "state_variables"])
def test_rejects_initial_references_to_missing_entities(category: str) -> None:
    document = valid_document()
    initial = cast(dict[str, object], document["initial_conditions"])
    item = cast(dict[str, object], cast(list[object], initial[category])[0])
    if category == "relations":
        participants = cast(list[dict[str, object]], item["participants"])
        participants[0]["entity_id"] = "missing"
    elif category == "resources":
        item["entity_id"] = "missing"
    else:
        item["scope"] = {"kind": "ENTITY", "entity_id": "missing"}

    with pytest.raises(WorldDefinitionError, match="initial Entities"):
        load_world_definition(document)


@pytest.mark.parametrize("quantity", [True, float("nan"), float("inf")])
def test_rejects_invalid_resource_quantities(quantity: object) -> None:
    document = valid_document()
    initial = cast(dict[str, object], document["initial_conditions"])
    resource = cast(dict[str, object], cast(list[object], initial["resources"])[0])
    resource["quantity"] = quantity

    with pytest.raises(WorldDefinitionError, match="integer or finite float"):
        load_world_definition(document)


def test_rejects_opaque_structured_values() -> None:
    document = valid_document()
    document["metadata"] = {"invalid": object()}

    with pytest.raises(WorldDefinitionError, match="unsupported"):
        load_world_definition(document)


def test_schema_versions_keep_exact_distinct_root_fields() -> None:
    version_one = valid_document()
    version_one["scenario_event_rules"] = []
    with pytest.raises(WorldDefinitionError, match="extra=.*scenario_event_rules"):
        load_world_definition(version_one)

    version_two = valid_version_two_document()
    del version_two["scenario_event_rules"]
    with pytest.raises(WorldDefinitionError, match="missing=.*scenario_event_rules"):
        load_world_definition(version_two)


@pytest.mark.parametrize(
    "rules,message",
    [
        (
            [
                {"rule_id": "duplicate", "trigger": {"kind": "AT_TIME", "logical_time": 200}},
                {"rule_id": "duplicate", "trigger": {"kind": "AT_TIME", "logical_time": 201}},
            ],
            "rule IDs must be unique",
        ),
        (
            [{"rule_id": "past", "trigger": {"kind": "AT_TIME", "logical_time": 99}}],
            "cannot precede",
        ),
        (
            [{"rule_id": "random", "trigger": {"kind": "RANDOM_TIME", "logical_time": 200}}],
            "must be AT_TIME",
        ),
    ],
)
def test_version_two_rejects_invalid_scenario_rules(rules: list[object], message: str) -> None:
    document = valid_version_two_document()
    document["scenario_event_rules"] = rules

    with pytest.raises(WorldDefinitionError, match=message):
        load_world_definition(document)


def test_simulation_run_config_contains_only_world_definition_ref() -> None:
    ref = WorldDefinitionRef(WorldDefinitionId("world"), "v1")
    config = SimulationRunConfig(ref)

    assert config.world_definition_ref == ref
    assert [item.name for item in fields(config)] == ["world_definition_ref"]
