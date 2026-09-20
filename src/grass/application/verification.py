# SPDX-License-Identifier: GPL-3.0-only

"""Read-only integrity and replay verification for persisted local runs."""

from __future__ import annotations

from grass.application._material import LocalSimulationStorage, load_run_material
from grass.application.contracts import VerificationIntegrityError, VerificationReport
from grass.core.genesis import GenesisError, validate_committed_genesis
from grass.core.initialization_events import SIMULATION_INITIALIZED
from grass.core.replay import replay_branch
from grass.persistence.contracts import RunId, WorldMaterialKind
from grass.worlds.snapshots import FilesystemWorldSnapshotStore


class LocalSimulationVerifier:
    """Validate canonical material, topology, genesis, and replay without execution."""

    def __init__(
        self,
        storage: LocalSimulationStorage,
        snapshot_store: FilesystemWorldSnapshotStore,
    ) -> None:
        self._storage = storage
        self._snapshot_store = snapshot_store

    def verify_run(self, run_id: RunId) -> VerificationReport:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        try:
            material = load_run_material(self._storage, self._snapshot_store, run_id)
        except ValueError as error:
            raise VerificationIntegrityError("persisted run material is inconsistent") from error

        snapshot_file_count = (
            len(material.snapshot.material_files) if material.snapshot is not None else None
        )
        if material.record.world_material_kind is WorldMaterialKind.PACKAGE_SNAPSHOT:
            if material.snapshot is None:
                raise VerificationIntegrityError("package-backed run has no loaded snapshot")
        elif material.record.world_material_kind is WorldMaterialKind.DEFINITION_ONLY:
            if material.snapshot is not None:
                raise VerificationIntegrityError("definition-only run loaded package material")
        else:  # pragma: no cover - SimulationRunRecord rejects unknown enum values
            raise VerificationIntegrityError("run has unsupported world material kind")

        store = self._storage.event_store(run_id)
        try:
            branches = tuple(store.list_branches())
            if not branches:
                raise VerificationIntegrityError("run has no branches")
            branch_ids = tuple(branch.branch_id for branch in branches)
            if len(set(branch_ids)) != len(branch_ids):
                raise VerificationIntegrityError("branch catalog contains duplicate identifiers")
            roots = tuple(branch for branch in branches if branch.fork_position is None)
            if len(roots) != 1 or roots[0].branch_id != material.record.root_branch_id:
                raise VerificationIntegrityError(
                    "run must have exactly one parentless root matching its record"
                )
            known_branch_ids = frozenset(branch_ids)
            for branch in branches:
                if store.read_branch(branch.branch_id) != branch:
                    raise VerificationIntegrityError(
                        "branch catalog disagrees with exact topology read"
                    )
                if (
                    branch.fork_position is not None
                    and branch.fork_position.branch_id not in known_branch_ids
                ):
                    raise VerificationIntegrityError("branch parent is absent from catalog")

            root_origin = tuple(store.read_transitions(material.record.root_branch_id))
            if not root_origin:
                raise VerificationIntegrityError("root branch is empty or uninitialized")
            try:
                validate_committed_genesis(
                    material.definition,
                    material.config,
                    root_origin[0],
                )
            except GenesisError as error:
                raise VerificationIntegrityError("root genesis is invalid") from error

            genesis_ref = root_origin[0].transition_ref
            genesis_event_id = root_origin[0].events[0].event_id
            transition_refs = set()
            event_ids = set()
            transition_count = 0
            event_count = 0
            for branch in branches:
                head = store.head_position(branch.branch_id)
                visible = tuple(store.read_visible_transitions(head))
                if not visible or head.transition_ref is None:
                    raise VerificationIntegrityError("branch has empty visible history")
                if visible[-1].transition_ref != head.transition_ref:
                    raise VerificationIntegrityError(
                        "branch visible history does not end at its exact head"
                    )
                origin = tuple(store.read_transitions(branch.branch_id))
                if any(transition.branch_id != branch.branch_id for transition in origin):
                    raise VerificationIntegrityError(
                        "branch-origin history contains another branch's transition"
                    )
                visible_origin = tuple(
                    transition for transition in visible if transition.branch_id == branch.branch_id
                )
                if visible_origin != origin:
                    raise VerificationIntegrityError(
                        "branch-origin history disagrees with exact visible history"
                    )
                replay_branch(store, head)
                for transition in origin:
                    if transition.transition_ref in transition_refs:
                        raise VerificationIntegrityError("transition identity is not unique")
                    transition_refs.add(transition.transition_ref)
                    transition_count += 1
                    for event in transition.events:
                        if event.event_id in event_ids:
                            raise VerificationIntegrityError("Event identity is not unique")
                        event_ids.add(event.event_id)
                        event_count += 1
                        if event.event_type == SIMULATION_INITIALIZED and not (
                            transition.transition_ref == genesis_ref
                            and event.event_id == genesis_event_id
                        ):
                            raise VerificationIntegrityError(
                                "SimulationInitialized appears after genesis"
                            )
        except VerificationIntegrityError:
            raise
        except (TypeError, ValueError, RuntimeError) as error:
            raise VerificationIntegrityError(
                "persisted branch history failed integrity verification"
            ) from error

        return VerificationReport(
            run_id,
            material.record.world_material_kind,
            len(branches),
            transition_count,
            event_count,
            snapshot_file_count,
        )


def verify_run(
    storage: LocalSimulationStorage,
    snapshot_store: FilesystemWorldSnapshotStore,
    run_id: RunId,
    /,
) -> VerificationReport:
    """Convenience entry point for one read-only local verification."""

    return LocalSimulationVerifier(storage, snapshot_store).verify_run(run_id)
