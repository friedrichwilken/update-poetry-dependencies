"""Turns raw subprocess output into a short, safe tail suitable for
embedding in a failure report: ANSI escape codes stripped, capped to the
last ~40 lines and a total character budget so a runaway resolver/test
command can never blow up the PR body or the GITHUB_OUTPUT payload."""

from __future__ import annotations

import re

# Matches ANSI CSI sequences (colors, cursor movement, ...), which is the
# vast majority of what a test runner or resolver prints in a CI log.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

TAIL_LINES = 40
TAIL_CHARS = 4000


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def capture_tail(text: str, max_lines: int = TAIL_LINES, max_chars: int = TAIL_CHARS) -> str:
    """The last `max_lines` lines of `text` (ANSI stripped), additionally
    capped to the last `max_chars` characters in case a handful of lines
    are themselves huge."""
    cleaned = strip_ansi(text).strip("\n")
    if not cleaned:
        return ""
    lines = cleaned.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[-max_chars:]
    return result
