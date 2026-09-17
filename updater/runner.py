"""Thin subprocess wrapper.

Every external command (poetry, git, gh, and the user's test command) goes
through a single injectable object so unit tests can fake it instead of
touching the real filesystem or network.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    args: list
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    """Runs real subprocesses. Argument lists only, never shell=True.

    The one exception is `run_shell`, used exclusively for the user-supplied
    test-command, which is intentionally a shell command.
    """

    def run(self, args: list, cwd: str | Path | None = None) -> CommandResult:
        proc = subprocess.run(
            [str(a) for a in args],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
        )
        return CommandResult(list(args), proc.returncode, proc.stdout, proc.stderr)

    def run_shell(self, command: str, cwd: str | Path | None = None) -> CommandResult:
        proc = subprocess.run(
            ["bash", "-c", command],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
        )
        return CommandResult([command], proc.returncode, proc.stdout, proc.stderr)
