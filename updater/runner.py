"""Thin subprocess wrapper.

Every external command (poetry, git, gh, and the user's test command) goes
through a single injectable object so unit tests can fake it instead of
touching the real filesystem or network.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# How many trailing lines of a run_shell command's stdout/stderr to keep in
# memory. Generously above what textcap.capture_tail actually needs (its
# own cap is the last ~40 lines), so this never meaningfully changes what
# ends up in a failure report while still bounding memory for a command
# that logs a huge amount of output.
CAPTURED_LINES = 2000

# How long to wait for the output-pumping threads to finish once the
# command itself has exited, before giving up on them and moving on. A
# backgrounded grandchild process (e.g. `sleep 30 &`) inherits our
# stdout/stderr pipes and can keep them open long after the command we
# actually ran has exited, which would otherwise block these threads (and
# this call) until the grandchild itself finishes too - joining with a
# timeout means run_shell always returns once the command we ran is done,
# at the cost of possibly missing trailing output from an orphaned
# background process.
PUMP_JOIN_TIMEOUT = 1.0

# How many times in a row reading from a pipe may raise before the pump
# gives up on it instead of retrying forever.
MAX_CONSECUTIVE_READ_ERRORS = 100


@dataclass
class CommandResult:
    args: list
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _pump(source: TextIO, sink: TextIO, collected: deque) -> None:
    """Copy `source` to `sink` line by line as it arrives (so the job log
    shows output live) while also collecting a bounded tail of it, so the
    caller still gets something back once the process exits.

    Never stops draining early: any exception raised while handling a
    line (decoding, writing to `sink`, ...) is swallowed and the loop
    keeps going until the source actually hits EOF. If this thread died
    instead on the first bad line, the pipe would be left undrained and
    the child could block forever the next time it tries to write to it.
    """
    read_errors = 0
    while True:
        try:
            line = source.readline()
        except Exception:
            # Not expected in practice - the pipe is opened with
            # errors="replace" (see run_shell), so decoding should not
            # raise - but if it ever does, keep looping rather than
            # abandoning the pipe undrained. A persistent error (closed or
            # broken pipe) would make this spin forever, so give up after
            # a few consecutive failures.
            read_errors += 1
            if read_errors >= MAX_CONSECUTIVE_READ_ERRORS:
                break
            continue
        read_errors = 0
        if line == "":
            break
        try:
            collected.append(line)
            sink.write(line)
            sink.flush()
        except Exception:
            pass
    try:
        source.close()
    except Exception:
        pass


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
        log as it happens) while also capturing a bounded tail of it, so a
        failure report can later embed it. Two threads pump stdout/stderr
        concurrently so a command that only writes to one of them (or
        writes lopsidedly) never stalls behind the other.

        Decoding uses errors="replace" so a single non-UTF-8 byte can
        never raise inside the pump loop (which used to kill the thread,
        leave the pipe undrained, and hang the whole call once the
        child's stdout buffer filled up). stdin is /dev/null so the
        command can never block waiting for input.
        """
        proc = subprocess.Popen(
            ["bash", "-c", command],
            cwd=str(cwd) if cwd is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        stdout_lines: deque = deque(maxlen=CAPTURED_LINES)
        stderr_lines: deque = deque(maxlen=CAPTURED_LINES)
        threads = [
            threading.Thread(
                target=_pump, args=(proc.stdout, sys.stdout, stdout_lines), daemon=True
            ),
            threading.Thread(
                target=_pump, args=(proc.stderr, sys.stderr, stderr_lines), daemon=True
            ),
        ]
        for thread in threads:
            thread.start()

        returncode = proc.wait()

        # The command itself has exited; do not wait unboundedly for the
        # pump threads to see EOF too, in case a backgrounded grandchild
        # is still holding a pipe open (see PUMP_JOIN_TIMEOUT above).
        for thread in threads:
            thread.join(timeout=PUMP_JOIN_TIMEOUT)

        return CommandResult([command], returncode, "".join(stdout_lines), "".join(stderr_lines))
