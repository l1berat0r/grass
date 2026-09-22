# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO

from grass.cli.output import (
    committed_transition,
    success_document,
    utc_timestamp,
    write_json,
)
from grass.core import CauseRef, CorrelationId, Provenance, ProvenanceSourceRef
from tests.support import event_to_commit, rooted_store, transition_to_commit


def test_json_v1_preserves_atomic_events_and_complete_provenance() -> None:
    store = rooted_store("root")
    transition = store.commit_transition(
        transition_to_commit(
            "root",
            "atomic",
            12,
            (
                event_to_commit(
                    "first",
                    payload={"z": 1, "a": [True]},
                    provenance=Provenance(
                        "DECISION_PROVIDER",
                        ProvenanceSourceRef("binding", "human"),
                        {"provider": "human"},
                    ),
                    causation_refs=(CauseRef("observation", "one"),),
                    correlation_id=CorrelationId("correlation"),
                ),
                event_to_commit("second"),
            ),
        )
    )

    data = committed_transition(transition)

    assert data["transition_ref"] == {
        "origin_branch_id": "test:root",
        "transition_id": "test:atomic",
    }
    events = data["events"]
    assert isinstance(events, list)
    assert [item["event_id"] for item in events] == ["test:first", "test:second"]
    assert events[0]["provenance"] == {
        "source_kind": "DECISION_PROVIDER",
        "source_ref": {"kind": "binding", "value": "human"},
        "metadata": {"provider": "human"},
    }
    assert events[0]["causation_refs"] == [{"kind": "observation", "value": "one"}]
    assert events[0]["correlation_id"] == "correlation"


def test_json_document_is_deterministic_and_timestamp_is_normalized() -> None:
    timestamp = datetime(
        2026,
        9,
        20,
        14,
        3,
        2,
        999999,
        tzinfo=timezone(timedelta(hours=2)),
    )
    assert utc_timestamp(timestamp) == "2026-09-20T12:03:02"
    assert utc_timestamp(timestamp.astimezone(UTC)) == "2026-09-20T12:03:02"

    stream = StringIO()
    write_json(stream, success_document("test", {"z": 1, "a": 2}))

    assert stream.getvalue() == '{"command":"test","data":{"a":2,"z":1},"schema_version":1}\n'
    assert json.loads(stream.getvalue())["schema_version"] == 1
