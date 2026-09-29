# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from pathlib import Path

import pytest

import grass.worlds.templates as templates
from grass.core import SimulationRunConfig, WorldDefinition, WorldDefinitionId
from grass.worlds import (
    OccurrenceRuntimeComposer,
    WorldCompositionError,
    WorldPackage,
    WorldPackageFormatError,
    WorldTemplateDestinationError,
    WorldTemplateDestinationExistsError,
    WorldTemplateNotFoundError,
    get_world_template,
    initialize_world_template,
    list_world_templates,
    load_world_package,
)
from grass.worlds.package import load_world_package as package_load_world_package


def test_registry_metadata_comes_from_fixed_inventory_and_valid_package() -> None:
    listed = list_world_templates()

    assert [item.name for item in listed] == ["occurrence-counter"]
    assert listed[0] == get_world_template("occurrence-counter")
    assert listed[0].description == (
        "A minimal occurrence-only world that increments one StateVariable through GEL."
    )
    assert listed[0].package_version == 1
    assert listed[0].world_definition_ref.world_definition_id == WorldDefinitionId(
        "occurrence-counter"
    )
    assert listed[0].schema_version == 3
    assert listed[0].files == (
        "README.md",
        "mechanics/increment.gel",
        "package.json",
        "world.json",
    )

    with pytest.raises(WorldTemplateNotFoundError, match="does not exist"):
        get_world_template("missing")


def test_registry_specs_are_name_ordered_and_unique() -> None:
    first = templates._TemplateSpec("first", "First", ("package.json",))
    second = templates._TemplateSpec("second", "Second", ("package.json",))

    assert templates._validated_specs((second, first)) == (first, second)
    with pytest.raises(ValueError, match="names must be unique"):
        templates._validated_specs((first, first))


def test_initialized_template_is_an_ordinary_valid_occurrence_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "demo"
    published_packages: list[WorldPackage] = []

    def recording_load(directory: os.PathLike[str] | str) -> WorldPackage:
        loaded = package_load_world_package(directory)
        if Path(directory) == destination:
            published_packages.append(loaded)
        return loaded

    monkeypatch.setattr(templates, "load_world_package", recording_load)

    package = initialize_world_template("occurrence-counter", destination)
    loaded = load_world_package(destination)

    assert published_packages == [package]
    assert package is published_packages[0]
    assert package == loaded
    assert package.world_definition.world_definition_id == WorldDefinitionId("demo")
    assert package.world_definition.ref.version == "1.0.0"
    assert (destination / "README.md").is_file()
    assert (destination / "mechanics" / "increment.gel").read_text(encoding="utf-8") == (
        "return {new_value: current_value + 1};\n"
    )
    OccurrenceRuntimeComposer().validate(
        package.world_definition,
        SimulationRunConfig(package.world_definition.ref),
    )


@pytest.mark.parametrize("existing_kind", ["file", "directory", "symlink", "dangling"])
def test_initialization_never_replaces_existing_paths(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    destination = tmp_path / "demo"
    target = tmp_path / "target"
    if existing_kind == "file":
        destination.write_text("keep", encoding="utf-8")
    elif existing_kind == "directory":
        destination.mkdir()
        (destination / "keep").write_text("keep", encoding="utf-8")
    elif existing_kind == "symlink":
        target.mkdir()
        destination.symlink_to(target, target_is_directory=True)
    else:
        destination.symlink_to(target, target_is_directory=True)

    with pytest.raises(WorldTemplateDestinationExistsError, match="already exists"):
        initialize_world_template("occurrence-counter", destination)

    if existing_kind == "file":
        assert destination.read_text(encoding="utf-8") == "keep"
    elif existing_kind == "directory":
        assert (destination / "keep").read_text(encoding="utf-8") == "keep"
    else:
        assert destination.is_symlink()


def test_initialization_rejects_invalid_destination_without_creating_it(
    tmp_path: Path,
) -> None:
    invalid_slug = tmp_path / "Not-Safe"
    missing_parent = tmp_path / "missing" / "demo"

    with pytest.raises(WorldTemplateDestinationError, match="basename"):
        initialize_world_template("occurrence-counter", invalid_slug)
    with pytest.raises(WorldTemplateDestinationError, match="parent"):
        initialize_world_template("occurrence-counter", missing_parent)

    assert not invalid_slug.exists()
    assert not missing_parent.exists()


def test_failed_destination_validation_removes_only_created_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "demo"

    def failing_load(directory: os.PathLike[str] | str) -> WorldPackage:
        package = package_load_world_package(directory)
        if package.world_definition.world_definition_id == WorldDefinitionId("demo"):
            raise WorldPackageFormatError("injected initialized package failure")
        return package

    monkeypatch.setattr(templates, "load_world_package", failing_load)

    with pytest.raises(WorldTemplateDestinationError, match="initialization failed"):
        initialize_world_template("occurrence-counter", destination)

    assert not destination.exists()


def test_failed_publication_removes_only_the_created_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "demo"
    write_files = templates._write_files

    def failing_write(root: Path, files: dict[str, bytes]) -> None:
        write_files(root, files)
        if root == destination:
            raise OSError("injected publication failure")

    monkeypatch.setattr(templates, "_write_files", failing_write)

    with pytest.raises(WorldTemplateDestinationError, match="initialization failed"):
        initialize_world_template("occurrence-counter", destination)

    assert not destination.exists()


def test_corrupted_published_destination_fails_validation_and_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "demo"
    write_files = templates._write_files

    def corrupting_write(root: Path, files: dict[str, bytes]) -> None:
        write_files(root, files)
        if root == destination:
            (root / "world.json").write_text("not json\n", encoding="utf-8")

    monkeypatch.setattr(templates, "_write_files", corrupting_write)

    with pytest.raises(WorldTemplateDestinationError, match="initialization failed"):
        initialize_world_template("occurrence-counter", destination)

    assert not destination.exists()


def test_published_destination_composition_failure_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "demo"
    validate = OccurrenceRuntimeComposer.validate
    demo_validations = 0

    def failing_validate(
        self: OccurrenceRuntimeComposer,
        world_definition: WorldDefinition,
        config: SimulationRunConfig,
    ) -> None:
        nonlocal demo_validations
        validate(self, world_definition, config)
        if world_definition.world_definition_id == WorldDefinitionId("demo"):
            demo_validations += 1
            if demo_validations == 2:
                raise WorldCompositionError("injected published composition failure")

    monkeypatch.setattr(OccurrenceRuntimeComposer, "validate", failing_validate)

    with pytest.raises(WorldTemplateDestinationError, match="initialization failed"):
        initialize_world_template("occurrence-counter", destination)

    assert demo_validations == 2
    assert not destination.exists()


def test_failed_publication_does_not_remove_a_replaced_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "demo"
    write_files = templates._write_files

    def replacing_write(root: Path, files: dict[str, bytes]) -> None:
        if root != destination:
            write_files(root, files)
            return
        for child in root.iterdir():
            child.unlink()
        root.rmdir()
        root.mkdir()
        (root / "keep").write_text("keep", encoding="utf-8")
        raise OSError("injected destination replacement")

    monkeypatch.setattr(templates, "_write_files", replacing_write)

    with pytest.raises(WorldTemplateDestinationError, match="initialization failed"):
        initialize_world_template("occurrence-counter", destination)

    assert (destination / "keep").read_text(encoding="utf-8") == "keep"


def test_cleanup_does_not_delete_a_destination_replaced_after_guard_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "demo"
    guard = templates._create_destination(destination)
    destination_is_guarded = templates._destination_is_guarded
    replaced = False

    def replacing_check(path: Path, selected_guard: templates._DestinationGuard) -> bool:
        nonlocal replaced
        guarded = destination_is_guarded(path, selected_guard)
        if path == destination and guarded and not replaced:
            replaced = True
            for child in path.iterdir():
                child.unlink()
            path.rmdir()
            path.mkdir()
            (path / "keep").write_text("keep", encoding="utf-8")
        return guarded

    monkeypatch.setattr(templates, "_destination_is_guarded", replacing_check)

    templates._remove_created_directory(destination, guard)

    assert (destination / "keep").read_text(encoding="utf-8") == "keep"
