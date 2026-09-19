# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from grass.core.mechanics import GelSetStateVariableMechanic
from grass.worlds.package import (
    WorldPackageFormatError,
    WorldPackageMaterialError,
    WorldPackagePathError,
    WorldPackageValidationError,
    load_world_package,
)


def world_document(world_id: str = "example-world") -> dict[str, object]:
    integer_schema = {"type": "INTEGER", "minimum": 0, "maximum": 100}
    return {
        "world_definition_id": world_id,
        "version": "1.0",
        "schema_version": 3,
        "vocabulary": {
            "entity_types": [],
            "relation_types": [],
            "resource_types": [],
            "state_variable_types": ["counter"],
        },
        "initial_conditions": {
            "logical_time": 0,
            "entities": [],
            "relations": [],
            "resources": [],
            "state_variables": [
                {
                    "scope": {"kind": "WORLD"},
                    "state_variable_type": "counter",
                    "value": 1,
                }
            ],
        },
        "metadata": {},
        "scenario_event_rules": [
            {
                "rule_id": "increment",
                "trigger": {"kind": "AT_TIME", "logical_time": 10},
                "mechanic": {
                    "kind": "GEL",
                    "usage": "SET_STATE_VARIABLE",
                    "target": {
                        "scope": {"kind": "WORLD"},
                        "state_variable_type": "counter",
                    },
                    "program": {
                        "source_file": "mechanics/increment.gel",
                        "language_version": 1,
                        "input_schema": {
                            "type": "OBJECT",
                            "fields": {"current_value": integer_schema},
                        },
                        "output_schema": {
                            "type": "OBJECT",
                            "fields": {"new_value": integer_schema},
                        },
                    },
                },
            }
        ],
    }


def write_world_package(
    parent: Path,
    *,
    name: str = "example-world",
    document: dict[str, object] | None = None,
) -> tuple[Path, bytes, bytes, bytes]:
    root = parent / name
    root.mkdir()
    mechanics = root / "mechanics"
    mechanics.mkdir()
    manifest_bytes = b'{"package_version":1,"world_definition":"world.json"}\n'
    world_bytes = json.dumps(
        world_document(name) if document is None else document,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    source_bytes = b"return {new_value: current_value + 1};\n"
    (root / "package.json").write_bytes(manifest_bytes)
    (root / "world.json").write_bytes(world_bytes)
    (mechanics / "increment.gel").write_bytes(source_bytes)
    (root / "README.md").write_text("ignored author material", encoding="utf-8")
    return root, manifest_bytes, world_bytes, source_bytes


def test_load_captures_exact_material_and_resolves_authored_gel(tmp_path: Path) -> None:
    root, manifest_bytes, world_bytes, source_bytes = write_world_package(tmp_path)

    package = load_world_package(root)

    assert package.manifest.world_definition == "world.json"
    assert package.material_files == {
        "package.json": manifest_bytes,
        "world.json": world_bytes,
        "mechanics/increment.gel": source_bytes,
    }
    mechanic = package.world_definition.scenario_event_rules[0].mechanic
    assert type(mechanic) is GelSetStateVariableMechanic
    assert mechanic.program.source == source_bytes.decode("utf-8")
    with pytest.raises(TypeError):
        cast(dict[str, bytes], package.material_files)["extra"] = b"change"


@pytest.mark.parametrize(
    "manifest",
    [
        b'{"package_version":1,"package_version":1,"world_definition":"world.json"}',
        b'{"package_version":1,"world_definition":"../world.json"}',
        b'{"package_version":1,"world_definition":"nested\\\\world.json"}',
    ],
)
def test_manifest_rejects_duplicate_and_unsafe_paths(tmp_path: Path, manifest: bytes) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    (root / "package.json").write_bytes(manifest)

    with pytest.raises((WorldPackageFormatError, WorldPackagePathError)):
        load_world_package(root)


def test_world_json_rejects_nonfinite_and_wrong_schema_version(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    (root / "world.json").write_bytes(b'{"schema_version":1e10000}')
    with pytest.raises(WorldPackageFormatError, match="strict JSON"):
        load_world_package(root)

    (root / "world.json").write_text(
        json.dumps({**world_document(), "schema_version": 2}), encoding="utf-8"
    )
    with pytest.raises(WorldPackageFormatError, match="schema_version 3"):
        load_world_package(root)


def test_authored_directory_and_material_must_not_be_symlinked(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    source = root / "mechanics" / "increment.gel"
    target = root / "source-target.gel"
    source.rename(target)
    source.symlink_to(target)

    with pytest.raises(WorldPackageMaterialError, match="missing or unreadable"):
        load_world_package(root)


def test_directory_basename_must_equal_safe_world_id(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(
        tmp_path, name="different-name", document=world_document("example-world")
    )

    with pytest.raises(WorldPackageFormatError, match="basename"):
        load_world_package(root)


def test_manifest_rejects_unknown_provider_or_python_fields(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    for field in ("provider", "credentials", "python_module"):
        (root / "package.json").write_text(
            json.dumps(
                {
                    "package_version": 1,
                    "world_definition": "world.json",
                    field: "forbidden",
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(WorldPackageFormatError, match="extra"):
            load_world_package(root)


@pytest.mark.parametrize(
    "source_file",
    ["../increment.gel", "/tmp/increment.gel", "mechanics\\increment.gel"],
)
def test_gel_source_rejects_unsafe_paths(tmp_path: Path, source_file: str) -> None:
    document = world_document()
    rule = cast(list[dict[str, object]], document["scenario_event_rules"])[0]
    mechanic = cast(dict[str, object], rule["mechanic"])
    program = cast(dict[str, object], mechanic["program"])
    program["source_file"] = source_file
    root, _, _, _ = write_world_package(tmp_path, document=document)

    with pytest.raises(WorldPackagePathError):
        load_world_package(root)


def test_invalid_or_random_gel_fails_package_validation(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    source = root / "mechanics" / "increment.gel"
    source.write_text("return current_value +;", encoding="utf-8")
    with pytest.raises(WorldPackageValidationError, match="WorldDefinition"):
        load_world_package(root)

    source.write_text("return {new_value: random_int(0, 10)};", encoding="utf-8")
    with pytest.raises(WorldPackageValidationError, match="WorldDefinition"):
        load_world_package(root)


def test_missing_gel_source_is_rejected(tmp_path: Path) -> None:
    root, _, _, _ = write_world_package(tmp_path)
    (root / "mechanics" / "increment.gel").unlink()

    with pytest.raises(WorldPackageMaterialError, match="missing or unreadable"):
        load_world_package(root)


def test_deep_gel_schema_fails_with_bounded_package_error(tmp_path: Path) -> None:
    document = world_document()
    rule = cast(list[dict[str, object]], document["scenario_event_rules"])[0]
    mechanic = cast(dict[str, object], rule["mechanic"])
    program = cast(dict[str, object], mechanic["program"])
    value_schema: dict[str, object] = {
        "type": "INTEGER",
        "minimum": 0,
        "maximum": 100,
    }
    for _ in range(40):
        value_schema = {
            "type": "LIST",
            "item_schema": value_schema,
            "max_items": 1,
        }
    program["input_schema"] = {
        "type": "OBJECT",
        "fields": {"current_value": value_schema},
    }
    program["output_schema"] = {
        "type": "OBJECT",
        "fields": {"new_value": value_schema},
    }
    root, _, _, _ = write_world_package(tmp_path, document=document)

    with pytest.raises(WorldPackageValidationError, match="WorldDefinition"):
        load_world_package(root)
