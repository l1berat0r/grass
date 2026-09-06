# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from grass.core import Provenance, ProvenanceSourceRef
from grass.core.provenance import MetadataValue


def test_provenance_records_origin_without_closed_source_vocabulary() -> None:
    source_ref = ProvenanceSourceRef("resolver-binding", "local/scripted")
    provenance = Provenance("WORLD_RESOLVER", source_ref)

    assert provenance.source_kind == "WORLD_RESOLVER"
    assert provenance.source_ref == source_ref
    assert provenance.metadata == {}


def test_provenance_requires_non_empty_source_values() -> None:
    with pytest.raises(ValueError, match="source kind must not be empty"):
        Provenance("")
    with pytest.raises(ValueError, match="source reference kind must not be empty"):
        ProvenanceSourceRef("", "source")
    with pytest.raises(ValueError, match="source reference value must not be empty"):
        ProvenanceSourceRef("kind", "")


def test_provenance_rejects_invalid_source_reference() -> None:
    with pytest.raises(TypeError, match="source_ref must be"):
        Provenance("ENGINE", cast(ProvenanceSourceRef, "not-a-reference"))


def test_provenance_metadata_is_recursively_copied_and_frozen() -> None:
    options: list[MetadataValue] = [1, {"enabled": True}]
    nested: dict[str, MetadataValue] = {"name": "scripted", "options": options}
    metadata: dict[str, MetadataValue] = {"provider": nested}

    provenance = Provenance("ENGINE", metadata=metadata)
    nested["name"] = "changed"
    options.append(2)
    metadata["new"] = "value"

    provider = provenance.metadata["provider"]
    assert isinstance(provider, Mapping)
    assert provider["name"] == "scripted"
    assert provider["options"] == (1, {"enabled": True})
    assert "new" not in provenance.metadata

    with pytest.raises(TypeError):
        cast(dict[str, MetadataValue], provenance.metadata)["new"] = "value"
    with pytest.raises(TypeError):
        cast(dict[str, MetadataValue], provider)["name"] = "changed"

    frozen_options = provider["options"]
    assert isinstance(frozen_options, Sequence)
    assert not isinstance(frozen_options, str)
    assert isinstance(frozen_options, tuple)
    with pytest.raises(AttributeError):
        frozen_options.append(2)  # type: ignore[attr-defined]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_provenance_metadata_rejects_non_finite_floats(value: float) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        Provenance("ENGINE", metadata={"value": value})


def test_provenance_metadata_rejects_unsupported_values() -> None:
    unsupported = cast(MetadataValue, {"not", "structured"})

    with pytest.raises(TypeError, match="unsupported metadata value"):
        Provenance("ENGINE", metadata={"value": unsupported})


def test_provenance_is_immutable() -> None:
    provenance = Provenance("ENGINE")

    with pytest.raises(FrozenInstanceError):
        provenance.source_kind = "OPERATOR"  # type: ignore[misc]
    with pytest.raises(TypeError, match="unhashable type"):
        hash(provenance)
