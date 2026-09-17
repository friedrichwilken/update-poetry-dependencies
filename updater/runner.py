"""Thin subprocess wrapper.

Every external command (poetry, git, gh, and the user's test command) goes
through a single injectable object so unit tests can fake it instead of
touching the real filesystem or network.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass
class CommandResult:
    args: list
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _pump(source: TextIO, sink: TextIO, collected: list[str]) -> None:
    """Copy `source` to `sink` line by line as it arrives (so the job log
    shows output live) while also collecting it, so the caller still gets
    the full text back once the process exits."""
    for line in iter(source.readline, ""):
        collected.append(line)
        sink.write(line)
        sink.flush()
    source.close()


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
        """Runs `command` through bash, streaming its stdout/stderr to this
        process' own stdout/stderr live (so it still shows up in the job
        log as it happens) while also capturing it, so failure reports can
        later embed a tail of it. Two threads pump stdout/stderr
        concurrently so a command that only writes to one of them (or
        writes lopsidedly) never stalls behind the other."""
        proc = subprocess.Popen(
            ["bash", "-c", command],
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        threads = [
            threading.Thread(target=_pump, args=(proc.stdout, sys.stdout, stdout_lines)),
            threading.Thread(target=_pump, args=(proc.stderr, sys.stderr, stderr_lines)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        returncode = proc.wait()
        return CommandResult([command], returncode, "".join(stdout_lines), "".join(stderr_lines))
