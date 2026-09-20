# SPDX-License-Identifier: GPL-3.0-only

"""Trusted composition boundary for validated runtime dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from grass.core.decision_invocations import DecisionInvoker
from grass.core.event_store import EventStore
from grass.core.identifiers import ProviderBindingId
from grass.core.world_definitions import SimulationRunConfig, WorldDefinition
from grass.runtime.contracts import RuntimeIdentitySource
from grass.runtime.engine import SimulationEngine


class RuntimeComposer(Protocol):
    """Validate and compose trusted runtime dependencies for one world."""

    def validate(
        self,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        /,
    ) -> None:
        """Validate composition without I/O, allocation, or other side effects."""

        ...

    def compose(
        self,
        *,
        event_store: EventStore,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        identity_source: RuntimeIdentitySource,
        decision_invokers: Mapping[ProviderBindingId, DecisionInvoker] | None = None,
    ) -> SimulationEngine:
        """Build an engine from already trusted installed runtime components."""

        ...
