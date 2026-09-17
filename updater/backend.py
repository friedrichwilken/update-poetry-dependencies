"""Backend abstraction over a dependency manager.

`PoetryBackend` and `UvBackend` both implement `Backend` below (list top
level packages, update one package, sync the environment to the lock file,
report which files to stage). The interface is kept narrow on purpose so
the update loop in `updater.py` never needs to know which one it is
driving.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .errors import ActionError
from .pyproject_deps import list_top_level_dependency_names
from .runner import CommandResult, CommandRunner
from .versions import version_at_least

if TYPE_CHECKING:
    from .config import Config

POETRY_LOCK_FILE = "poetry.lock"
UV_LOCK_FILE = "uv.lock"
PYPROJECT_FILE = "pyproject.toml"


class Backend(Protocol):
    name: str

    def lock_file_path(self) -> Path: ...

    def lock_exists(self) -> bool: ...

    def files_to_stage(self) -> list[str]:
        """Files that a successful update may change and that should be
        committed."""
        ...

    def install(self) -> CommandResult:
        """Install/sync the environment from the existing lock file
        without changing it."""
        ...

    def list_top_level_packages(self) -> list[str]: ...

    def update_package(self, package: str) -> CommandResult: ...

    def sync(self) -> CommandResult:
        """Re-sync the environment to whatever the lock file currently
        says, without changing the lock file itself."""
        ...


class PoetryBackend:
    name = "poetry"

    def __init__(self, runner: CommandRunner, directory: str, poetry_version: str):
        self.runner = runner
        self.directory = directory
        self.poetry_version = poetry_version

    def lock_file_path(self) -> Path:
        return Path(self.directory) / POETRY_LOCK_FILE

    def lock_exists(self) -> bool:
        return self.lock_file_path().is_file()

    def files_to_stage(self) -> list[str]:
        # Deliberately just the lock file for now; a major-bump mode will
        # also need pyproject.toml here.
        return [POETRY_LOCK_FILE]

    def install(self) -> CommandResult:
        return self.runner.run(["poetry", "install"], cwd=self.directory)

    def list_top_level_packages(self) -> list[str]:
        result = self.runner.run(["poetry", "show", "--top-level"], cwd=self.directory)
        if not result.ok:
            raise ActionError(f"poetry show --top-level failed: {result.stderr}")
        packages = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            packages.append(line.split()[0])
        return packages

    def update_package(self, package: str) -> CommandResult:
        return self.runner.run(
            ["poetry", "update", package, "--no-interaction"], cwd=self.directory
        )

    def sync(self) -> CommandResult:
        """Poetry >= 2 uses the dedicated `sync` command; 1.x needs
        `install --sync`."""
        if version_at_least(self.poetry_version, "2"):
            return self.runner.run(["poetry", "sync"], cwd=self.directory)
        return self.runner.run(["poetry", "install", "--sync"], cwd=self.directory)


class UvBackend:
    name = "uv"

    def __init__(self, runner: CommandRunner, directory: str, python_version: str):
        self.runner = runner
        self.directory = directory
        self.python_version = python_version

    def lock_file_path(self) -> Path:
        return Path(self.directory) / UV_LOCK_FILE

    def lock_exists(self) -> bool:
        return self.lock_file_path().is_file()

    def files_to_stage(self) -> list[str]:
        return [UV_LOCK_FILE]

    def _sync_args(self) -> list[str]:
        return [
            "uv",
            "sync",
            "--locked",
            "--all-groups",
            "--all-extras",
            "--python",
            self.python_version,
        ]

    def install(self) -> CommandResult:
        """`--locked` (used by `sync()`) makes uv fail loudly instead of
        silently rewriting uv.lock if it is out of date, so install never
        changes the lock."""
        return self.sync()

    def list_top_level_packages(self) -> list[str]:
        pyproject_path = Path(self.directory) / PYPROJECT_FILE
        if not pyproject_path.is_file():
            raise ActionError(f"{pyproject_path} not found; nothing to update")
        return list_top_level_dependency_names(pyproject_path)

    def update_package(self, package: str) -> CommandResult:
        lock_result = self.runner.run(
            ["uv", "lock", "--upgrade-package", package], cwd=self.directory
        )
        if not lock_result.ok:
            return lock_result
        return self.sync()

    def sync(self) -> CommandResult:
        return self.runner.run(self._sync_args(), cwd=self.directory)


def make_backend(package_manager: str, runner: CommandRunner, cfg: "Config") -> Backend:
    if package_manager == "poetry":
        return PoetryBackend(runner, cfg.directory, cfg.poetry_version)
    if package_manager == "uv":
        return UvBackend(runner, cfg.directory, cfg.python_version)
    raise ActionError(f"unknown package manager '{package_manager}'")
