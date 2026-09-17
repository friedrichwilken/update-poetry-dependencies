"""Backend abstraction over a dependency manager.

`PoetryBackend` is the only implementation today, but the interface (list top
level packages, update one package, sync the environment to the lock file,
report which files to stage) is kept narrow on purpose so a `uv` backend can
be added later without touching the updater loop.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ActionError
from .runner import CommandResult, CommandRunner
from .versions import version_at_least

LOCK_FILE = "poetry.lock"


class PoetryBackend:
    name = "poetry"

    def __init__(self, runner: CommandRunner, directory: str, poetry_version: str):
        self.runner = runner
        self.directory = directory
        self.poetry_version = poetry_version

    def lock_file_path(self) -> Path:
        return Path(self.directory) / LOCK_FILE

    def lock_exists(self) -> bool:
        return self.lock_file_path().is_file()

    def files_to_stage(self) -> list[str]:
        """Files that a successful update may change and that should be
        committed. Deliberately just the lock file for now; a major-bump mode
        will also need pyproject.toml here."""
        return [LOCK_FILE]

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
        """Re-sync the virtualenv with the lock file. Poetry >= 2 uses the
        dedicated `sync` command; 1.x needs `install --sync`."""
        if version_at_least(self.poetry_version, "2"):
            return self.runner.run(["poetry", "sync"], cwd=self.directory)
        return self.runner.run(["poetry", "install", "--sync"], cwd=self.directory)
