# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest

from grass.application import LocalSimulationApplication
from grass.cli.human import CliHumanDecisionSource
from grass.core import (
    DecisionOutcomeKind,
    DecisionOutputError,
    DecisionProviderBinding,
    DecisionProviderRouting,
    EntityId,
    ProviderBindingConfiguration,
    ProviderBindingId,
    ProviderExecutionLocation,
    SimulationRunConfig,
)
from grass.persistence import SqlitePersistence
from grass.providers import HumanDecisionInvoker
from grass.worlds import FilesystemWorldSnapshotStore, load_world_package
from tests.test_application_commands import DecisionRuntimeComposer
from tests.test_model_decisions import decision_request
from tests.test_world_packages import write_world_package


def test_cli_human_source_allocates_ids_for_local_step_keys() -> None:
    document = {
        "kind": "REPLACE_PLAN",
        "objective": "Respond",
        "steps": [
            {
                "key": "reply",
                "primitive": "COMMUNICATE",
                "bindings": {},
                "parameters": {},
                "dependencies": [],
                "description": "Reply",
            }
        ],
    }
    stderr = StringIO()
    source = CliHumanDecisionSource(StringIO(json.dumps(document) + "\n"), stderr)

    proposal = asyncio.run(source.acquire(decision_request()))

    assert proposal.kind is DecisionOutcomeKind.REPLACE_PLAN
    assert proposal.proposed_plan is not None
    UUID(proposal.proposed_plan.plan_id.value)
    UUID(proposal.proposed_plan.steps[0].step_id.value)
    assert "local keys" in stderr.getvalue()
    assert "Please wait" in stderr.getvalue()


def test_cli_human_source_rejects_non_strict_input() -> None:
    source = CliHumanDecisionSource(
        StringIO('{"kind":"CONTINUE_PLAN","kind":"CONTINUE_PLAN"}\n'),
        StringIO(),
    )

    with pytest.raises(DecisionOutputError, match="strict JSON"):
        asyncio.run(source.acquire(decision_request(with_plan=True)))


def test_cli_human_prompt_escapes_terminal_control_text() -> None:
    request = decision_request()
    actor_id = EntityId("actor\n\x1b[31m")
    observation = replace(request.observations[0], actor_id=actor_id)
    point = replace(request.decision_point, actor_id=actor_id)
    escaped_request = replace(
        request,
        decision_point=point,
        observations=(observation,),
    )
    stderr = StringIO()
    source = CliHumanDecisionSource(
        StringIO('{"kind":"BOUNDED_REACTION","intent_description":"ok","content":null}\n'),
        stderr,
    )

    asyncio.run(source.acquire(escaped_request))

    prompt = stderr.getvalue()
    assert "actor\\n\\u001b[31m" in prompt
    assert "\x1b" not in prompt


def test_cli_human_decision_uses_application_runtime_and_provenance(tmp_path: Path) -> None:
    document: dict[str, object] = {
        "world_definition_id": "decision-world",
        "version": "1.0",
        "schema_version": 3,
        "vocabulary": {
            "entity_types": ["Person"],
            "relation_types": [],
            "resource_types": [],
            "state_variable_types": [],
        },
        "initial_conditions": {
            "logical_time": 0,
            "entities": [{"entity_id": "actor", "entity_type": "Person", "properties": {}}],
            "relations": [],
            "resources": [],
            "state_variables": [],
        },
        "metadata": {},
        "scenario_event_rules": [],
    }
    author, _, _, _ = write_world_package(
        tmp_path,
        name="decision-world",
        document=document,
    )
    package = load_world_package(author)
    binding_id = ProviderBindingId("human")
    binding = DecisionProviderBinding(
        binding_id,
        "human",
        ProviderExecutionLocation.SERVER_MANAGED,
    )
    config = SimulationRunConfig(
        package.world_definition.ref,
        ProviderBindingConfiguration(
            DecisionProviderRouting(binding_id),
            {binding_id: binding},
        ),
    )
    source = CliHumanDecisionSource(
        StringIO(
            json.dumps(
                {
                    "kind": "BOUNDED_REACTION",
                    "intent_description": "Acknowledge",
                    "content": None,
                }
            )
            + "\n"
        ),
        StringIO(),
    )
    application = LocalSimulationApplication(
        SqlitePersistence(tmp_path / "grass.db"),
        FilesystemWorldSnapshotStore(tmp_path / "snapshots"),
        composer=DecisionRuntimeComposer(),
        decision_invokers={binding_id: HumanDecisionInvoker(source, binding)},
    )
    opened = application.create_run(package, config)

    asyncio.run(opened.step())
    asyncio.run(opened.step())
    selected = application.queries.get_decisions(opened.run_id)[0]

    assert selected.decision is not None
    assert selected.decision.outcome.kind is DecisionOutcomeKind.BOUNDED_REACTION
    assert selected.decision.provenance.metadata["provider"] == "human"
