"""Shared result type for `Backend.try_major()` (issue #21: opt-in
`allow-major` support). Kept in its own module (rather than `backend.py`)
so `updater.py`'s state machine can depend on the shape without importing
the backends themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from .runner import CommandResult


@dataclass
class MajorAttempt:
    """The outcome of `Backend.try_major(package)`.

    `try_major` itself returns `None` (not even this type) when no attempt
    is needed at all - the package's declared constraint already allows
    the latest release, so the ordinary in-range update already reaches it
    and a separate major attempt would just double-test the same change.

    Otherwise it returns a `MajorAttempt`:

    - `skip_reason` set: the declaration has a shape the feature does not
      support (git/path/url source, multiple marker-scoped constraints, an
      environment marker, an exact pin, ...). No files were touched.
      Reported quietly (`report-json` plus a compact job-summary line),
      never as PR-body noise.
    - `skip_reason` is `None`: an attempt was actually made - the manifest
      and lock file were rewritten to raise the constraint and re-resolve.
      `resolve_result.ok` says whether that succeeded; either way it is
      `updater.run_updates`'s job to test/commit on success or reset and
      fall back to the plain in-range update on failure.
    """

    skip_reason: str | None = None
    resolve_result: CommandResult | None = None
