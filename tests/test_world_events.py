# SPDX-License-Identifier: GPL-3.0-only

from typing import cast

import pytest

from grass.core import (
    EntityCreatedPayload,
    EntityId,
    EntityScope,
    Event,
    EventPayload,
    RelationCreatedPayload,
    ResourceChangedPayload,
    StateVariableChangedPayload,
    WorldEventPayloadError,
    WorldScope,
    decode_world_event,
)
from grass.core._structured_data import StructuredValue
from grass.core.world_events import (
    ENTITY_CREATED,
    RELATION_CREATED,
    RESOURCE_CHANGED,
    STATE_VARIABLE_CHANGED,
)
from tests.support import event_to_commit, rooted_store, transition_to_commit


def committed_event(
    event_type: str,
    payload: EventPayload,
    *,
    event_version: int = 1,
) -> Event:
    store = rooted_store("branch")
    transition = store.commit_transition(
        transition_to_commit(
            "branch",
            "transition",
            10,
            [
                event_to_commit(
                    "event",
                    event_type=event_type,
                    event_version=event_version,
                    payload=payload,
                )
            ],
        )
    )
    return transition.events[0]


def test_decodes_entity_created_with_frozen_properties() -> None:
    decoded = decode_world_event(
        committed_event(
            ENTITY_CREATED,
            {
                "entity_id": "person-1",
                "entity_type": "Person",
                "properties": {"name": "A", "tags": ["one"]},
            },
        )
    )

    assert decoded == EntityCreatedPayload(
        EntityId("person-1"),
        "Person",
        {"name": "A", "tags": ("one",)},
    )
    assert decoded.properties["tags"] == ("one",)


def test_exported_payload_value_copies_and_freezes_direct_input() -> None:
    tags: list[StructuredValue] = ["one"]
    payload = EntityCreatedPayload(
        EntityId("person-1"),
        "Person",
        {"tags": tags},
    )

    tags.append("two")

    assert payload.properties == {"tags": ("one",)}
    with pytest.raises(TypeError):
        cast(dict[str, object], payload.properties)["new"] = True


def test_relation_participants_allow_repeated_roles_and_multiple_roles_per_entity() -> None:
    decoded = decode_world_event(
        committed_event(
            RELATION_CREATED,
            {
                "relation_id": "relation-1",
                "relation_type": "Association",
                "participants": [
                    {"role": "member", "entity_id": "one"},
                    {"role": "member", "entity_id": "two"},
                    {"role": "owner", "entity_id": "one"},
                ],
                "properties": {},
            },
        )
    )

    assert isinstance(decoded, RelationCreatedPayload)
    assert {(item.role, item.entity_id.value) for item in decoded.participants} == {
        ("member", "one"),
        ("member", "two"),
        ("owner", "one"),
    }


@pytest.mark.parametrize("quantity", [-5, 0, 1.25])
def test_resource_quantity_accepts_exact_finite_numbers(quantity: int | float) -> None:
    decoded = decode_world_event(
        committed_event(
            RESOURCE_CHANGED,
            {
                "entity_id": "entity",
                "resource_type": "balance",
                "quantity_after": quantity,
            },
        )
    )

    assert decoded == ResourceChangedPayload(EntityId("entity"), "balance", quantity)


def test_resource_quantity_rejects_boolean() -> None:
    event = committed_event(
        RESOURCE_CHANGED,
        {
            "entity_id": "entity",
            "resource_type": "balance",
            "quantity_after": True,
        },
    )

    with pytest.raises(WorldEventPayloadError, match="integer or finite float"):
        decode_world_event(event)


@pytest.mark.parametrize(
    "scope, expected",
    [
        ({"kind": "WORLD"}, WorldScope()),
        ({"kind": "ENTITY", "entity_id": "entity"}, EntityScope(EntityId("entity"))),
    ],
)
def test_decodes_explicit_state_variable_scopes(
    scope: EventPayload, expected: WorldScope | EntityScope
) -> None:
    decoded = decode_world_event(
        committed_event(
            STATE_VARIABLE_CHANGED,
            {
                "scope": scope,
                "state_variable_type": "condition",
                "value_after": {"level": 2},
            },
        )
    )

    assert decoded == StateVariableChangedPayload(expected, "condition", {"level": 2})


@pytest.mark.parametrize(
    "payload",
    [
        {"entity_id": "entity", "entity_type": "Person"},
        {
            "entity_id": "entity",
            "entity_type": "Person",
            "properties": {},
            "unexpected": True,
        },
    ],
)
def test_payload_schema_rejects_missing_and_extra_fields(payload: EventPayload) -> None:
    event = committed_event(ENTITY_CREATED, payload)

    with pytest.raises(WorldEventPayloadError, match="fields do not match schema"):
        decode_world_event(event)


@pytest.mark.parametrize(
    "participants, message",
    [
        ([], "non-empty sequence"),
        (
            [
                {"role": "member", "entity_id": "one"},
                {"role": "member", "entity_id": "one"},
            ],
            "duplicate bindings",
        ),
        ([{"role": "member"}], "fields do not match schema"),
    ],
)
def test_relation_participant_schema_is_strict(
    participants: list[dict[str, str]], message: str
) -> None:
    event = committed_event(
        RELATION_CREATED,
        {
            "relation_id": "relation",
            "relation_type": "Association",
            "participants": cast(EventPayload, participants),
            "properties": {},
        },
    )

    with pytest.raises(WorldEventPayloadError, match=message):
        decode_world_event(event)


def test_decoder_rejects_unknown_type_and_unsupported_version() -> None:
    unknown = committed_event("FutureEvent", {})
    unsupported = committed_event(
        ENTITY_CREATED,
        {"entity_id": "entity", "entity_type": "Person", "properties": {}},
        event_version=2,
    )

    with pytest.raises(WorldEventPayloadError, match="unknown world Event"):
        decode_world_event(unknown)
    with pytest.raises(WorldEventPayloadError, match="unsupported EntityCreated version"):
        decode_world_event(unsupported)


@pytest.mark.parametrize(
    "scope",
    [
        {"kind": "LOCATION", "entity_id": "entity"},
        {"kind": "WORLD", "entity_id": "extra"},
        {"kind": "ENTITY"},
    ],
)
def test_state_variable_scope_schema_is_strict(scope: EventPayload) -> None:
    event = committed_event(
        STATE_VARIABLE_CHANGED,
        {
            "scope": scope,
            "state_variable_type": "condition",
            "value_after": None,
        },
    )

    with pytest.raises(WorldEventPayloadError):
        decode_world_event(event)
