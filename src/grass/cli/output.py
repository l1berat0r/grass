# SPDX-License-Identifier: GPL-3.0-only

"""Explicit deterministic presentation serializers for local CLI schema v1."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from typing import TextIO, TypeAlias

from grass.application import (
    ActorHistoryEntry,
    ActorView,
    BranchView,
    DecisionView,
    HistoryView,
    JobView,
    QueryPosition,
    StateView,
    VerificationReport,
)
from grass.core import (
    BinaryProgress,
    BoundedReactionDecision,
    Branch,
    CauseRef,
    CommittedTransition,
    ContinuePlanDecision,
    Decision,
    DecisionPoint,
    Entity,
    EntityScope,
    Event,
    HistoryPosition,
    Job,
    LinearProgress,
    Observation,
    Plan,
    PlanRef,
    PlanStep,
    PlanStepRef,
    ProjectionPosition,
    Provenance,
    Relation,
    ReplacePlanDecision,
    ResourceKey,
    RevisePlanDecision,
    SimulationRunConfig,
    SimulationState,
    StateVariableKey,
    TransitionRef,
    WorldDefinitionRef,
    WorldScope,
)
from grass.core.provider_bindings import ProviderBindingConfiguration
from grass.persistence import SimulationRunRecord
from grass.runtime import AdvanceResult, StepResult

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | Sequence["JsonValue"] | Mapping[str, "JsonValue"]


def structured(value: object, /) -> JsonValue:
    """Convert an already validated structured value into deterministic JSON data."""

    if value is None or type(value) in (bool, int, float, str):
        return value  # type: ignore[return-value]
    if isinstance(value, Mapping):
        return {str(key): structured(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [structured(item) for item in value]
    raise TypeError(f"unsupported structured value: {type(value).__name__}")


def utc_timestamp(value: datetime, /) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError("timestamp must be a timezone-aware datetime")
    return value.astimezone(UTC).replace(microsecond=0, tzinfo=None).isoformat(timespec="seconds")


def world_definition_ref(value: WorldDefinitionRef, /) -> dict[str, JsonValue]:
    return {
        "world_definition_id": value.world_definition_id.value,
        "version": value.version,
    }


def transition_ref(value: TransitionRef | None, /) -> JsonValue:
    if value is None:
        return None
    return {
        "origin_branch_id": value.branch_id.value,
        "transition_id": value.transition_id.value,
    }


def history_position(value: HistoryPosition, /) -> dict[str, JsonValue]:
    return {
        "viewed_branch_id": value.branch_id.value,
        "transition_ref": transition_ref(value.transition_ref),
    }


def query_position(value: QueryPosition, /) -> dict[str, JsonValue]:
    return {
        "run_id": value.run_id.value,
        **history_position(value.history_position),
        "logical_time_ns": value.logical_time.nanoseconds_from_origin,
    }


def provenance(value: Provenance, /) -> dict[str, JsonValue]:
    source_ref: JsonValue = None
    if value.source_ref is not None:
        source_ref = {"kind": value.source_ref.kind, "value": value.source_ref.value}
    return {
        "source_kind": value.source_kind,
        "source_ref": source_ref,
        "metadata": structured(value.metadata),
    }


def cause_ref(value: CauseRef, /) -> dict[str, JsonValue]:
    return {"kind": value.kind, "value": value.value}


def event(value: Event, /) -> dict[str, JsonValue]:
    return {
        "event_id": value.event_id.value,
        "branch_id": value.branch_id.value,
        "sequence": value.sequence,
        "logical_time_ns": value.logical_time.nanoseconds_from_origin,
        "transition_id": value.transition_id.value,
        "event_type": value.event_type,
        "event_version": value.event_version,
        "payload": structured(value.payload),
        "provenance": provenance(value.provenance),
        "causation_refs": [cause_ref(item) for item in value.causation_refs],
        "correlation_id": None if value.correlation_id is None else value.correlation_id.value,
    }


def committed_transition(value: CommittedTransition, /) -> dict[str, JsonValue]:
    return {
        "transition_ref": transition_ref(value.transition_ref),
        "logical_time_ns": value.logical_time.nanoseconds_from_origin,
        "events": [event(item) for item in value.events],
    }


def run_record(value: SimulationRunRecord, /) -> dict[str, JsonValue]:
    return {
        "run_id": value.run_id.value,
        "root_branch_id": value.root_branch_id.value,
        "world_definition_ref": world_definition_ref(value.world_definition_ref),
        "world_material_kind": value.world_material_kind.value,
        "created_at": utc_timestamp(value.created_at),
    }


def branch(value: Branch, /) -> dict[str, JsonValue]:
    return {
        "branch_id": value.branch_id.value,
        "parent_branch_id": (
            None if value.parent_branch_id is None else value.parent_branch_id.value
        ),
        "fork_position": (
            None if value.fork_position is None else history_position(value.fork_position)
        ),
    }


def branch_view(value: BranchView, /) -> dict[str, JsonValue]:
    return {
        "position": query_position(value.position),
        "branch": branch(value.branch),
        "visible_transition_count": value.visible_transition_count,
        "origin_transition_count": value.origin_transition_count,
    }


def _scope(value: WorldScope | EntityScope, /) -> dict[str, JsonValue]:
    if type(value) is WorldScope:
        return {"kind": "WORLD"}
    if type(value) is EntityScope:
        return {"kind": "ENTITY", "entity_id": value.entity_id.value}
    raise TypeError("unsupported StateVariable scope")


def _resource_key(value: ResourceKey, /) -> dict[str, JsonValue]:
    return {"entity_id": value.entity_id.value, "resource_type": value.resource_type}


def _state_variable_key(value: StateVariableKey, /) -> dict[str, JsonValue]:
    return {
        "scope": _scope(value.scope),
        "state_variable_type": value.state_variable_type,
    }


def entity(value: Entity, /) -> dict[str, JsonValue]:
    return {
        "entity_id": value.entity_id.value,
        "entity_type": value.entity_type,
        "properties": structured(value.properties),
        "active": value.active,
    }


def relation(value: Relation, /) -> dict[str, JsonValue]:
    participants = sorted(value.participants, key=lambda item: (item.role, item.entity_id.value))
    return {
        "relation_id": value.relation_id.value,
        "relation_type": value.relation_type,
        "participants": [
            {"role": item.role, "entity_id": item.entity_id.value} for item in participants
        ],
        "properties": structured(value.properties),
        "active": value.active,
    }


def plan_ref(value: PlanRef | None, /) -> JsonValue:
    if value is None:
        return None
    return {"plan_id": value.plan_id.value, "version": value.version}


def plan_step_ref(value: PlanStepRef, /) -> dict[str, JsonValue]:
    return {
        "plan_ref": plan_ref(value.plan_ref),
        "step_id": value.step_id.value,
    }


def plan_step(value: PlanStep, /) -> dict[str, JsonValue]:
    dependencies = sorted(
        value.dependencies,
        key=lambda item: (item.step_id.value, item.condition.value),
    )
    blueprint: JsonValue = None
    if value.blueprint_ref is not None:
        blueprint = {
            "blueprint_id": value.blueprint_ref.blueprint_id.value,
            "version": value.blueprint_ref.version,
        }
    return {
        "step_id": value.step_id.value,
        "primitive": value.primitive.value,
        "blueprint_ref": blueprint,
        "bindings": structured(value.bindings),
        "parameters": structured(value.parameters),
        "dependencies": [
            {"step_id": item.step_id.value, "condition": item.condition.value}
            for item in dependencies
        ],
        "origin": value.origin.value,
        "description": value.description,
    }


def plan(value: Plan, /) -> dict[str, JsonValue]:
    return {
        "plan_id": value.plan_id.value,
        "version": value.version,
        "actor_id": value.actor_id.value,
        "objective": value.objective,
        "steps": [plan_step(item) for item in value.steps],
        "replaces_plan_ref": plan_ref(value.replaces_plan_ref),
        "provenance": provenance(value.provenance),
        "recorded_at_ns": value.recorded_at.nanoseconds_from_origin,
    }


def _progress(value: LinearProgress | BinaryProgress, /) -> dict[str, JsonValue]:
    if type(value) is LinearProgress:
        return {"kind": "LINEAR", "completed": value.completed, "total": value.total}
    if type(value) is BinaryProgress:
        return {"kind": "BINARY", "complete": value.complete}
    raise TypeError("unsupported Job progress")


def _state_variable_sort_key(item: tuple[StateVariableKey, object], /) -> tuple[str, str, str]:
    key = item[0]
    entity_id = key.scope.entity_id.value if type(key.scope) is EntityScope else ""
    return (key.scope.kind, entity_id, key.state_variable_type)


def job(value: Job, /) -> dict[str, JsonValue]:
    return {
        "job_id": value.job_id.value,
        "plan_step_ref": plan_step_ref(value.plan_step_ref),
        "status": value.status.value,
        "progress": _progress(value.progress),
        "creation_provenance": provenance(value.creation_provenance),
        "created_at_ns": value.created_at.nanoseconds_from_origin,
    }


def observation(value: Observation, /) -> dict[str, JsonValue]:
    return {
        "observation_id": value.observation_id.value,
        "actor_id": value.actor_id.value,
        "content": structured(value.content),
        "provenance": provenance(value.provenance),
        "observed_at_ns": value.observed_at.nanoseconds_from_origin,
    }


def decision_point(value: DecisionPoint, /) -> dict[str, JsonValue]:
    return {
        "decision_point_id": value.decision_point_id.value,
        "actor_id": value.actor_id.value,
        "reason": value.reason.value,
        "scope": value.scope.value,
        "observation_ids": sorted(item.value for item in value.observation_ids),
        "subject_plan_ref": plan_ref(value.subject_plan_ref),
    }


def decision(value: Decision, /) -> dict[str, JsonValue]:
    outcome = value.outcome
    outcome_data: dict[str, JsonValue] = {"kind": outcome.kind.value}
    if isinstance(outcome, (RevisePlanDecision, ReplacePlanDecision)):
        outcome_data["resulting_plan_ref"] = plan_ref(outcome.resulting_plan_ref)
    elif type(outcome) is BoundedReactionDecision:
        outcome_data["intent_description"] = outcome.bounded_reaction.intent_description
        outcome_data["content"] = structured(outcome.bounded_reaction.content)
    elif type(outcome) is not ContinuePlanDecision:
        raise TypeError("unsupported Decision outcome")
    return {
        "decision_point_id": value.decision_point_id.value,
        "outcome": outcome_data,
        "provenance": provenance(value.provenance),
        "recorded_at_ns": value.recorded_at.nanoseconds_from_origin,
    }


def projection_position(value: ProjectionPosition, /) -> dict[str, JsonValue]:
    return {
        "branch_id": value.branch_id.value,
        "last_transition_ref": transition_ref(value.last_transition_ref),
        "last_sequence": value.last_sequence,
        "logical_time_ns": (
            None if value.logical_time is None else value.logical_time.nanoseconds_from_origin
        ),
    }


def simulation_state(value: SimulationState, /) -> dict[str, JsonValue]:
    resources = sorted(
        value.world.resources.items(),
        key=lambda item: (item[0].entity_id.value, item[0].resource_type),
    )
    state_variables = sorted(
        value.world.state_variables.items(),
        key=_state_variable_sort_key,
    )
    return {
        "position": projection_position(value.position),
        "world": {
            "entities": [
                entity(item)
                for item in sorted(
                    value.world.entities.values(), key=lambda item: item.entity_id.value
                )
            ],
            "relations": [
                relation(item)
                for item in sorted(
                    value.world.relations.values(), key=lambda item: item.relation_id.value
                )
            ],
            "resources": [
                {"key": _resource_key(key), "quantity": quantity} for key, quantity in resources
            ],
            "state_variables": [
                {"key": _state_variable_key(key), "value": structured(item)}
                for key, item in state_variables
            ],
        },
        "execution": {
            "plans": [
                plan(item)
                for item in sorted(
                    value.execution.plans.values(),
                    key=lambda item: (item.plan_id.value, item.version),
                )
            ],
            "jobs": [
                job(item)
                for item in sorted(
                    value.execution.jobs.values(), key=lambda item: item.job_id.value
                )
            ],
        },
        "cognition": {
            "observations": [
                observation(item)
                for item in sorted(
                    value.cognition.observations.values(),
                    key=lambda item: item.observation_id.value,
                )
            ],
            "decision_points": [
                decision_point(item)
                for item in sorted(
                    value.cognition.decision_points.values(),
                    key=lambda item: item.decision_point_id.value,
                )
            ],
            "decisions": [
                decision(item)
                for _, item in sorted(
                    value.cognition.decisions.items(), key=lambda item: item[0].value
                )
            ],
        },
    }


def state_view(value: StateView, /) -> dict[str, JsonValue]:
    return {"position": query_position(value.position), "state": simulation_state(value.state)}


def history_view(value: HistoryView, /) -> dict[str, JsonValue]:
    return {
        "position": query_position(value.position),
        "scope": value.scope.value,
        "transitions": [committed_transition(item) for item in value.transitions],
    }


def job_view(value: JobView, /) -> dict[str, JsonValue]:
    return {
        "position": query_position(value.position),
        "job": job(value.job),
        "plan": plan(value.plan),
        "step": plan_step(value.step),
    }


def decision_view(value: DecisionView, /) -> dict[str, JsonValue]:
    return {
        "position": query_position(value.position),
        "decision_point": decision_point(value.decision_point),
        "status": value.status.value,
        "decision": None if value.decision is None else decision(value.decision),
    }


def actor_view(value: ActorView, /) -> dict[str, JsonValue]:
    return {
        "position": query_position(value.position),
        "entity": entity(value.entity),
        "evidence": [item.value for item in value.evidence],
        "plans": [plan(item) for item in value.plans],
        "observations": [observation(item) for item in value.observations],
        "decisions": [decision_view(item) for item in value.decisions],
        "jobs": [job_view(item) for item in value.jobs],
    }


def actor_history_entry(value: ActorHistoryEntry, /) -> dict[str, JsonValue]:
    return {
        "transition": committed_transition(value.transition),
        "attributions": [
            {"event_id": item.event_id.value, "kind": item.kind.value}
            for item in value.attributions
        ],
    }


def step_result(value: StepResult, /) -> dict[str, JsonValue]:
    return {
        "position_before": history_position(value.position_before),
        "position_after": history_position(value.position_after),
        "logical_time_ns": value.logical_time.nanoseconds_from_origin,
        "work_kind": None if value.work_kind is None else value.work_kind.value,
        "committed_transition": (
            None
            if value.committed_transition is None
            else committed_transition(value.committed_transition)
        ),
        "stop_reason": None if value.stop_reason is None else value.stop_reason.value,
        "waiting_decision_point_ids": sorted(
            item.value for item in value.waiting_decision_point_ids
        ),
    }


def advance_result(value: AdvanceResult, /) -> dict[str, JsonValue]:
    return {
        "position": history_position(value.position),
        "logical_time_ns": value.logical_time.nanoseconds_from_origin,
        "committed_steps": value.committed_steps,
        "stop_reason": value.stop_reason.value,
        "waiting_decision_point_ids": sorted(
            item.value for item in value.waiting_decision_point_ids
        ),
    }


def verification_report(value: VerificationReport, /) -> dict[str, JsonValue]:
    return {
        "run_id": value.run_id.value,
        "world_material_kind": value.world_material_kind.value,
        "branch_count": value.branch_count,
        "transition_count": value.transition_count,
        "event_count": value.event_count,
        "snapshot_file_count": value.snapshot_file_count,
    }


def provider_bindings(value: ProviderBindingConfiguration | None, /) -> dict[str, JsonValue]:
    if value is None:
        return {
            "configured": False,
            "routing": None,
            "decision_bindings": [],
            "model_bindings": [],
        }
    routing = value.routing
    return {
        "configured": True,
        "routing": {
            "default_binding_id": routing.default_binding_id.value,
            "group_bindings": [
                {"group": key, "binding_id": item.value}
                for key, item in sorted(routing.group_bindings.items())
            ],
            "actor_group_assignments": [
                {"actor_id": key.value, "group": item}
                for key, item in sorted(
                    routing.actor_group_assignments.items(), key=lambda item: item[0].value
                )
            ],
            "actor_bindings": [
                {"actor_id": key.value, "binding_id": item.value}
                for key, item in sorted(
                    routing.actor_bindings.items(), key=lambda item: item[0].value
                )
            ],
        },
        "decision_bindings": [
            {
                "binding_id": item.binding_id.value,
                "invoker_ref": item.invoker_ref,
                "execution_location": item.execution_location.value,
                "model_binding_id": (
                    None if item.model_binding_id is None else item.model_binding_id.value
                ),
            }
            for item in sorted(
                value.decision_bindings.values(), key=lambda item: item.binding_id.value
            )
        ],
        "model_bindings": [
            {
                "binding_id": item.binding_id.value,
                "provider_ref": item.provider_ref,
                "model": item.model,
            }
            for item in sorted(
                value.model_bindings.values(), key=lambda item: item.binding_id.value
            )
        ],
    }


def run_config(value: SimulationRunConfig, /) -> dict[str, JsonValue]:
    return {
        "world_definition_ref": world_definition_ref(value.world_definition_ref),
        "provider_bindings": provider_bindings(value.provider_bindings),
    }


def success_document(command: str, data: Mapping[str, JsonValue], /) -> dict[str, JsonValue]:
    return {"schema_version": 1, "command": command, "data": dict(data)}


def error_document(command: str, code: str, message: str, /) -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "command": command,
        "error": {"code": code, "message": message},
    }


def write_json(stream: TextIO, document: Mapping[str, JsonValue], /) -> None:
    stream.write(json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    stream.write("\n")


def write_human(stream: TextIO, data: Mapping[str, JsonValue], /) -> None:
    for key, value in data.items():
        if isinstance(value, list):
            stream.write(f"{key}:\n")
            if not value:
                stream.write("  (none)\n")
            for item in value:
                stream.write(f"  {json.dumps(item, ensure_ascii=True, sort_keys=True)}\n")
        elif isinstance(value, dict):
            stream.write(f"{key}: {json.dumps(value, ensure_ascii=True, sort_keys=True)}\n")
        elif isinstance(value, Enum):  # pragma: no cover - serializers emit values
            stream.write(f"{key}: {value.value}\n")
        else:
            stream.write(f"{key}: {value}\n")
