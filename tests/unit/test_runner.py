"""Exercises CommandRunner.run_shell against real subprocesses (no fakes) -
this is the one place the action does non-trivial process/thread plumbing
(live-streaming while capturing a bounded tail), so it is worth the extra
cost of spawning real children to catch hangs/regressions a fake could
never reproduce.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from updater.runner import CommandRunner


def _call_with_hang_guard(fn, timeout=10.0):
    """Runs `fn` (no args) on a background thread and fails the test
    explicitly if it has not returned within `timeout` seconds, instead of
    letting a regression hang the whole test run (and CI) forever."""
    box: dict = {}

    def target():
        box["result"] = fn()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        pytest.fail(f"call did not return within {timeout}s - suspected hang")
    return box["result"]


def test_run_shell_captures_stdout_and_stderr_separately():
    runner = CommandRunner()

    result = _call_with_hang_guard(lambda: runner.run_shell("echo out; echo err >&2"))

    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert result.ok


def test_run_shell_captures_nonzero_exit_code():
    runner = CommandRunner()

    result = _call_with_hang_guard(lambda: runner.run_shell("exit 3"))

    assert result.returncode == 3
    assert not result.ok


def test_run_shell_streams_output_live_to_this_process_stdout_and_stderr(capsys):
    runner = CommandRunner()

    result = _call_with_hang_guard(lambda: runner.run_shell("echo hello; echo world >&2"))

    captured = capsys.readouterr()
    # the output must appear on this process' real stdout/stderr (streamed
    # to the job log), not just be returned on the CommandResult
    assert "hello" in captured.out
    assert "world" in captured.err
    assert result.stdout == "hello\n"
    assert result.stderr == "world\n"


def test_run_shell_runs_in_given_cwd(tmp_path):
    runner = CommandRunner()

    result = _call_with_hang_guard(lambda: runner.run_shell("pwd", cwd=tmp_path))

    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


def test_run_shell_captures_a_partial_final_line_without_trailing_newline():
    runner = CommandRunner()

    result = _call_with_hang_guard(lambda: runner.run_shell("printf 'no newline at the end'"))

    assert result.stdout == "no newline at the end"
    assert result.ok


def test_run_shell_survives_non_utf8_bytes_and_keeps_capturing_afterwards(tmp_path):
    """A single invalid byte must not stop the output pump: strict
    decoding used to raise inside the pump thread, killing it and leaving
    the pipe undrained - which could hang the whole call forever once the
    child's stdout buffer filled up on a large enough write."""
    script = tmp_path / "bad_bytes.py"
    script.write_text(
        "import sys\n"
        "sys.stdout.buffer.write(b'before \\xff\\xfe bad bytes\\n')\n"
        "sys.stdout.buffer.flush()\n"
        "for i in range(20000):\n"
        "    print('line', i)\n"
    )
    runner = CommandRunner()

    result = _call_with_hang_guard(
        lambda: runner.run_shell(f"{sys.executable} {script}"), timeout=15.0
    )

    assert result.returncode == 0
    assert "line 19999" in result.stdout


def test_run_shell_handles_50k_lines_on_both_streams_and_bounds_memory(tmp_path):
    script = tmp_path / "chatty.py"
    script.write_text(
        "import sys\n"
        "for i in range(50000):\n"
        "    print('out', i)\n"
        "    print('err', i, file=sys.stderr)\n"
    )
    runner = CommandRunner()

    result = _call_with_hang_guard(
        lambda: runner.run_shell(f"{sys.executable} {script}"), timeout=30.0
    )

    assert result.returncode == 0
    assert "out 49999" in result.stdout
    assert "err 49999" in result.stderr
    # captured output is bounded (a trailing tail), not the full 50k lines
    stdout_lines = result.stdout.splitlines()
    assert len(stdout_lines) < 50000
    assert stdout_lines[0] != "out 0"


def test_run_shell_returns_once_the_shell_exits_even_with_a_backgrounded_grandchild():
    """A backgrounded grandchild (`sleep 5 &`) inherits our stdout/stderr
    pipes; as long as it keeps them open, reading those pipes to EOF would
    block forever without a join timeout. The call must return once the
    shell itself is done, not after the grandchild."""
    runner = CommandRunner()

    start = time.monotonic()
    result = _call_with_hang_guard(lambda: runner.run_shell("echo hi; sleep 5 &"), timeout=10.0)
    elapsed = time.monotonic() - start

    assert result.ok
    assert "hi" in result.stdout
    assert elapsed < 3.0
