# SPDX-License-Identifier: GPL-3.0-only

"""Strict loading of authored WorldPackage format 1 directories."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import ClassVar, cast

from grass.core.world_definitions import WorldDefinition, load_world_definition

WORLD_PACKAGE_VERSION = 1
WORLD_PACKAGE_MANIFEST = "package.json"
_SAFE_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class WorldPackageError(RuntimeError):
    """A WorldPackage cannot be loaded or does not satisfy format 1."""


class WorldPackageFormatError(WorldPackageError):
    """A material package document or path is malformed."""


class WorldPackageValidationError(WorldPackageError):
    """Resolved package material is not a valid runnable WorldDefinition."""


class UnsupportedWorldPackageVersionError(WorldPackageFormatError):
    """A package manifest declares an unsupported format version."""


class WorldPackagePathError(WorldPackageFormatError):
    """A package path is unsafe or not in canonical relative POSIX form."""


class WorldPackageMaterialError(WorldPackageFormatError):
    """Required package material is missing, unreadable, or not a regular file."""


@dataclass(frozen=True, slots=True)
class WorldPackageManifest:
    """The exact semantic content of a format-1 package manifest."""

    package_version: int
    world_definition: str

    def __post_init__(self) -> None:
        if type(self.package_version) is not int:
            raise TypeError("package_version must be an integer")
        if self.package_version != WORLD_PACKAGE_VERSION:
            raise UnsupportedWorldPackageVersionError(
                f"unsupported WorldPackage version: {self.package_version}"
            )
        _canonical_relative_path(self.world_definition, "world_definition")


@dataclass(frozen=True, slots=True)
class WorldPackage:
    """A validated semantic definition and its exact material package bytes."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    manifest: WorldPackageManifest
    world_definition: WorldDefinition
    material_files: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if type(self.manifest) is not WorldPackageManifest:
            raise TypeError("manifest must be a WorldPackageManifest")
        if type(self.world_definition) is not WorldDefinition:
            raise TypeError("world_definition must be a WorldDefinition")
        if not isinstance(self.material_files, Mapping):
            raise TypeError("material_files must be a mapping")
        copied: dict[str, bytes] = {}
        for relative_path, content in self.material_files.items():
            if type(relative_path) is not str:
                raise TypeError("file paths must be strings")
            _canonical_relative_path(relative_path, "material file path")
            if type(content) is not bytes:
                raise TypeError("material file contents must be bytes")
            copied[relative_path] = content
        if WORLD_PACKAGE_MANIFEST not in copied:
            raise WorldPackageMaterialError("package material does not contain package.json")
        if self.manifest.world_definition not in copied:
            raise WorldPackageMaterialError(
                "package material does not contain the referenced WorldDefinition"
            )
        _reject_file_directory_collisions(copied)
        object.__setattr__(self, "material_files", MappingProxyType(copied))


class _DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _parse_finite_float(value: str) -> float:
    result = float(value)
    if not isfinite(result):
        raise ValueError("JSON numbers must be finite")
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is not permitted: {value}")


def _load_json(content: bytes, description: str) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise WorldPackageFormatError(f"{description} must be valid UTF-8") from error
    try:
        return cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_float=_parse_finite_float,
                parse_constant=_reject_json_constant,
            ),
        )
    except (json.JSONDecodeError, _DuplicateJsonKeyError, RecursionError, ValueError) as error:
        raise WorldPackageFormatError(f"{description} is not strict JSON: {error}") from error


def _mapping(value: object, description: str) -> dict[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise WorldPackageFormatError(f"{description} must be a JSON object")
    return cast("dict[str, object]", value)


def _sequence(value: object, description: str) -> Sequence[object]:
    if type(value) is not list:
        raise WorldPackageFormatError(f"{description} must be a JSON array")
    return cast("Sequence[object]", value)


def _exact_fields(value: Mapping[str, object], expected: frozenset[str], description: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise WorldPackageFormatError(
            f"{description} fields do not match schema; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _canonical_relative_path(value: object, description: str) -> str:
    if type(value) is not str or value == "":
        raise WorldPackagePathError(f"{description} must be a non-empty string")
    if "\\" in value or "\x00" in value:
        raise WorldPackagePathError(f"{description} must be a canonical relative POSIX path")
    path = PurePosixPath(value)
    parts = value.split("/")
    if path.is_absolute() or any(part in ("", ".", "..") for part in parts):
        raise WorldPackagePathError(f"{description} must be a canonical relative POSIX path")
    if path.as_posix() != value:
        raise WorldPackagePathError(f"{description} must be a canonical relative POSIX path")
    return value


def _safe_slug(value: str, description: str) -> str:
    if _SAFE_SLUG.fullmatch(value) is None:
        raise WorldPackagePathError(f"{description} must match [a-z0-9]+(?:-[a-z0-9]+)*")
    return value


def _validate_package_directory(root: Path) -> None:
    try:
        mode = root.lstat().st_mode
    except OSError as error:
        raise WorldPackageMaterialError("WorldPackage directory is not accessible") from error
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise WorldPackageMaterialError("WorldPackage path must be a non-symlink directory")


def _read_regular_file(root: Path, relative_path: str) -> bytes:
    canonical = _canonical_relative_path(relative_path, "package material path")
    directory_fds: list[int] = []
    file_fd: int | None = None
    try:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | no_follow
        current_fd = os.open(root, directory_flags)
        directory_fds.append(current_fd)
        parts = PurePosixPath(canonical).parts
        for part in parts[:-1]:
            current_fd = os.open(part, directory_flags, dir_fd=current_fd)
            directory_fds.append(current_fd)
        file_fd = os.open(parts[-1], os.O_RDONLY | no_follow, dir_fd=current_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise WorldPackageMaterialError(
                f"package material is not a non-symlink regular file: {canonical}"
            )
        with os.fdopen(file_fd, "rb", closefd=True) as stream:
            file_fd = None
            return stream.read()
    except WorldPackageError:
        raise
    except OSError as error:
        raise WorldPackageMaterialError(
            f"package material is missing or unreadable: {canonical}"
        ) from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def _manifest(content: bytes) -> WorldPackageManifest:
    document = _mapping(_load_json(content, "package.json"), "package.json")
    _exact_fields(
        document,
        frozenset({"package_version", "world_definition"}),
        "package.json",
    )
    package_version = document["package_version"]
    world_definition = document["world_definition"]
    if type(package_version) is not int:
        raise WorldPackageFormatError("package_version must be an integer")
    if package_version != WORLD_PACKAGE_VERSION:
        raise UnsupportedWorldPackageVersionError(
            f"unsupported WorldPackage version: {package_version}"
        )
    if type(world_definition) is not str:
        raise WorldPackageFormatError("world_definition must be a string")
    return WorldPackageManifest(package_version, world_definition)


def _resolve_authored_gel(
    root: Path,
    world_document: dict[str, object],
    files: dict[str, bytes],
) -> None:
    rules = _sequence(world_document.get("scenario_event_rules"), "scenario_event_rules")
    for raw_rule in rules:
        rule = _mapping(raw_rule, "scenario Event rule")
        raw_mechanic = rule.get("mechanic")
        if type(raw_mechanic) is not dict:
            continue
        mechanic = _mapping(raw_mechanic, "scenario mechanic")
        if mechanic.get("kind") != "GEL":
            continue
        program = _mapping(mechanic.get("program"), "authored GEL program")
        _exact_fields(
            program,
            frozenset({"source_file", "language_version", "input_schema", "output_schema"}),
            "authored GEL program",
        )
        source_file = _canonical_relative_path(program["source_file"], "GEL program source_file")
        content = files.get(source_file)
        if content is None:
            content = _read_regular_file(root, source_file)
            files[source_file] = content
        try:
            source = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise WorldPackageFormatError(
                f"GEL source must be valid UTF-8: {source_file}"
            ) from error
        mechanic["program"] = {
            "source": source,
            "language_version": program["language_version"],
            "input_schema": program["input_schema"],
            "output_schema": program["output_schema"],
        }


def _reject_file_directory_collisions(files: Mapping[str, bytes]) -> None:
    paths = frozenset(files)
    for relative_path in paths:
        parts = PurePosixPath(relative_path).parts
        for count in range(1, len(parts)):
            if PurePosixPath(*parts[:count]).as_posix() in paths:
                raise WorldPackagePathError(
                    "package material path is both a file and a parent directory"
                )


def _load_world_package_directory(
    directory: os.PathLike[str] | str, /, *, require_directory_slug: bool
) -> WorldPackage:
    root = Path(directory)
    _validate_package_directory(root)
    if require_directory_slug:
        _safe_slug(root.name, "WorldPackage directory basename")

    manifest_bytes = _read_regular_file(root, WORLD_PACKAGE_MANIFEST)
    manifest = _manifest(manifest_bytes)
    world_bytes = _read_regular_file(root, manifest.world_definition)
    world_document = _mapping(
        _load_json(world_bytes, manifest.world_definition), "WorldDefinition document"
    )
    schema_version = world_document.get("schema_version")
    if type(schema_version) is not int or schema_version != 3:
        raise WorldPackageFormatError(
            "WorldPackage format 1 requires WorldDefinition schema_version 3"
        )

    files = {
        WORLD_PACKAGE_MANIFEST: manifest_bytes,
        manifest.world_definition: world_bytes,
    }
    _resolve_authored_gel(root, world_document, files)
    try:
        definition = load_world_definition(world_document)
    except (RecursionError, TypeError, ValueError) as error:
        raise WorldPackageValidationError("WorldDefinition document is invalid") from error

    world_slug = _safe_slug(definition.world_definition_id.value, "world_definition_id")
    if require_directory_slug and root.name != world_slug:
        raise WorldPackageFormatError(
            "WorldPackage directory basename must equal world_definition_id"
        )
    occurrence_times = tuple(
        rule.logical_time.nanoseconds_from_origin for rule in definition.scenario_event_rules
    )
    if len(set(occurrence_times)) != len(occurrence_times):
        raise WorldPackageFormatError(
            "WorldPackage scenario occurrences must have distinct logical times"
        )
    return WorldPackage(manifest, definition, files)


def load_world_package(directory: os.PathLike[str] | str, /) -> WorldPackage:
    """Load and fully validate one authored WorldPackage format 1 directory."""

    return _load_world_package_directory(directory, require_directory_slug=True)
