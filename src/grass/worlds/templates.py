# SPDX-License-Identifier: GPL-3.0-only

"""Trusted built-in templates that initialize ordinary WorldPackage directories."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import stat
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import MappingProxyType

from grass.core import SimulationRunConfig, WorldDefinitionRef
from grass.worlds.composition import OccurrenceRuntimeComposer, WorldCompositionError
from grass.worlds.package import WorldPackage, WorldPackageError, load_world_package

_SAFE_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_RESOURCE_DIRECTORY = "_template_data"


class WorldTemplateError(RuntimeError):
    """A trusted built-in WorldPackage template operation failed."""


class WorldTemplateNotFoundError(WorldTemplateError, LookupError):
    """A requested built-in template does not exist."""


class WorldTemplateIntegrityError(WorldTemplateError):
    """Bundled or initialized template material is invalid."""


class WorldTemplateDestinationError(WorldTemplateError):
    """A template cannot be initialized at the requested destination."""


class WorldTemplateDestinationExistsError(WorldTemplateDestinationError, FileExistsError):
    """Template initialization refuses to replace an existing path."""


def _canonical_path(value: str, description: str) -> str:
    path = PurePosixPath(value)
    parts = value.split("/")
    if (
        value == ""
        or "\\" in value
        or "\x00" in value
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in parts)
        or path.as_posix() != value
    ):
        raise ValueError(f"{description} must be a canonical relative POSIX path")
    return value


@dataclass(frozen=True, slots=True)
class WorldTemplateInfo:
    """Validated presentation metadata for one trusted built-in template."""

    name: str
    description: str
    package_version: int
    world_definition_ref: WorldDefinitionRef
    schema_version: int
    files: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.name) is not str or _SAFE_SLUG.fullmatch(self.name) is None:
            raise ValueError("name must be a safe non-empty slug")
        if type(self.description) is not str or self.description == "":
            raise ValueError("description must be a non-empty string")
        if type(self.package_version) is not int or self.package_version < 1:
            raise ValueError("package_version must be a positive integer")
        if type(self.world_definition_ref) is not WorldDefinitionRef:
            raise TypeError("world_definition_ref must be a WorldDefinitionRef")
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError("schema_version must be a positive integer")
        files = tuple(self.files)
        if not files or not all(type(item) is str for item in files):
            raise TypeError("files must contain strings")
        if files != tuple(sorted(files)) or len(set(files)) != len(files):
            raise ValueError("files must be unique and sorted")
        for relative_path in files:
            _canonical_path(relative_path, "template file path")
        object.__setattr__(self, "files", files)


@dataclass(frozen=True, slots=True)
class _TemplateSpec:
    name: str
    description: str
    files: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.name) is not str or _SAFE_SLUG.fullmatch(self.name) is None:
            raise ValueError("template name must be a safe non-empty slug")
        if type(self.description) is not str or self.description == "":
            raise ValueError("template description must be a non-empty string")
        files = tuple(self.files)
        if files != tuple(sorted(files)) or len(set(files)) != len(files):
            raise ValueError("template files must be unique and sorted")
        for relative_path in files:
            _canonical_path(relative_path, "template file path")
        object.__setattr__(self, "files", files)


_SPECS = (
    _TemplateSpec(
        "occurrence-counter",
        "A minimal occurrence-only world that increments one StateVariable through GEL.",
        (
            "README.md",
            "mechanics/increment.gel",
            "package.json",
            "world.json",
        ),
    ),
)
_SPECS_BY_NAME = MappingProxyType({item.name: item for item in _SPECS})


def _spec(name: str) -> _TemplateSpec:
    if type(name) is not str:
        raise TypeError("name must be a string")
    try:
        return _SPECS_BY_NAME[name]
    except KeyError as error:
        raise WorldTemplateNotFoundError(f"world template does not exist: {name}") from error


def _resource_files(spec: _TemplateSpec) -> dict[str, bytes]:
    root = resources.files("grass.worlds").joinpath(_RESOURCE_DIRECTORY, spec.name)
    loaded: dict[str, bytes] = {}
    try:
        for relative_path in spec.files:
            loaded[relative_path] = root.joinpath(*PurePosixPath(relative_path).parts).read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise WorldTemplateIntegrityError(
            f"bundled world template material is missing or unreadable: {spec.name}"
        ) from error
    return loaded


def _write_files(root: Path, files: dict[str, bytes]) -> None:
    for relative_path, content in files.items():
        target = root.joinpath(*PurePosixPath(relative_path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)


def _directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        status = path.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(status.st_mode):
        return None
    return status.st_dev, status.st_ino


@dataclass(frozen=True, slots=True)
class _DestinationGuard:
    identity: tuple[int, int]
    marker_name: str
    marker_token: bytes


def _create_destination(path: Path) -> _DestinationGuard:
    path.mkdir()
    identity = _directory_identity(path)
    if identity is None:  # pragma: no cover - guarded by mkdir
        raise OSError("created template destination is not a directory")
    marker_name = f".grass-template-init-{secrets.token_hex(16)}"
    marker_token = secrets.token_bytes(32)
    try:
        with (path / marker_name).open("xb") as stream:
            stream.write(marker_token)
    except OSError:
        try:
            path.rmdir()
        except OSError:
            pass
        raise
    return _DestinationGuard(identity, marker_name, marker_token)


def _destination_is_guarded(path: Path, guard: _DestinationGuard) -> bool:
    if _directory_identity(path) != guard.identity:
        return False
    try:
        return (path / guard.marker_name).read_bytes() == guard.marker_token
    except OSError:
        return False


def _remove_created_directory(path: Path, guard: _DestinationGuard) -> None:
    if _destination_is_guarded(path, guard):
        shutil.rmtree(path, ignore_errors=True)


def _validate_materialized(spec: _TemplateSpec, files: dict[str, bytes]) -> WorldPackage:
    try:
        with TemporaryDirectory(prefix="grass-template-") as temporary:
            root = Path(temporary) / spec.name
            root.mkdir()
            _write_files(root, files)
            package = load_world_package(root)
            OccurrenceRuntimeComposer().validate(
                package.world_definition,
                SimulationRunConfig(package.world_definition.ref),
            )
            return package
    except (OSError, WorldPackageError, WorldCompositionError) as error:
        raise WorldTemplateIntegrityError(
            f"bundled world template is invalid: {spec.name}"
        ) from error


def _validated_template(
    spec: _TemplateSpec,
) -> tuple[WorldTemplateInfo, dict[str, bytes], WorldPackage]:
    files = _resource_files(spec)
    package = _validate_materialized(spec, files)
    definition = package.world_definition
    return (
        WorldTemplateInfo(
            spec.name,
            spec.description,
            package.manifest.package_version,
            definition.ref,
            definition.schema_version,
            spec.files,
        ),
        files,
        package,
    )


def list_world_templates() -> tuple[WorldTemplateInfo, ...]:
    """Return all trusted built-in templates in stable name order."""

    return tuple(_validated_template(spec)[0] for spec in _SPECS)


def get_world_template(name: str, /) -> WorldTemplateInfo:
    """Return validated metadata for one trusted built-in template."""

    return _validated_template(_spec(name))[0]


def _destination(destination: Path) -> Path:
    if not isinstance(destination, Path):
        raise TypeError("destination must be a Path")
    if _SAFE_SLUG.fullmatch(destination.name) is None:
        raise WorldTemplateDestinationError(
            "template destination basename must match [a-z0-9]+(?:-[a-z0-9]+)*"
        )
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise WorldTemplateDestinationError("template destination cannot be inspected") from error
    else:
        raise WorldTemplateDestinationExistsError(
            f"template destination already exists: {destination}"
        )
    try:
        parent_mode = destination.parent.stat().st_mode
    except OSError as error:
        raise WorldTemplateDestinationError(
            "template destination parent is not accessible"
        ) from error
    if not stat.S_ISDIR(parent_mode):
        raise WorldTemplateDestinationError("template destination parent must be a directory")
    return destination


def _rewrite_world_id(
    package: WorldPackage,
    files: dict[str, bytes],
    world_definition_id: str,
) -> dict[str, bytes]:
    world_path = package.manifest.world_definition
    try:
        document = json.loads(files[world_path].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:  # pragma: no cover
        raise WorldTemplateIntegrityError(
            "validated template world document cannot be read"
        ) from error
    if type(document) is not dict:  # pragma: no cover - normal package validation enforces this
        raise WorldTemplateIntegrityError("validated template world document is not an object")
    document["world_definition_id"] = world_definition_id
    rewritten = dict(files)
    rewritten[world_path] = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return rewritten


def initialize_world_template(name: str, destination: Path, /) -> WorldPackage:
    """Create and validate one editable ordinary WorldPackage without overwriting paths."""

    spec = _spec(name)
    _, files, package = _validated_template(spec)
    target = _destination(destination)
    initialized_files = _rewrite_world_id(package, files, target.name)
    destination_guard: _DestinationGuard | None = None
    succeeded = False
    try:
        with TemporaryDirectory(prefix="grass-template-init-") as temporary:
            staged = Path(temporary) / target.name
            staged.mkdir()
            _write_files(staged, initialized_files)
            initialized = load_world_package(staged)
            OccurrenceRuntimeComposer().validate(
                initialized.world_definition,
                SimulationRunConfig(initialized.world_definition.ref),
            )

            destination_guard = _create_destination(target)
            _write_files(target, initialized_files)
            if not _destination_is_guarded(target, destination_guard):
                raise OSError("template destination changed during initialization")
            (target / destination_guard.marker_name).unlink()
        succeeded = True
        return initialized
    except FileExistsError as error:
        if destination_guard is None:
            raise WorldTemplateDestinationExistsError(
                f"template destination already exists: {target}"
            ) from error
        raise WorldTemplateDestinationError(
            "template destination changed during initialization"
        ) from error
    except (OSError, WorldPackageError, WorldCompositionError) as error:
        raise WorldTemplateDestinationError("template initialization failed") from error
    finally:
        if destination_guard is not None and not succeeded:
            _remove_created_directory(target, destination_guard)
