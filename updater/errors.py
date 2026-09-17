from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .updater import UpdateResult


class ActionError(Exception):
    """Raised for any condition that should fail the action with ::error::."""


class UpdateAborted(ActionError):
    """Raised when the update loop has to stop early - currently only when
    a re-sync after a discarded update itself fails, leaving the
    environment in an unknown state that is not safe to keep testing later
    packages against (see `updater._reset_and_resync`).

    Some packages may already have been processed - and, for passing ones,
    already committed - before the abort, so this carries the partial
    `UpdateResult` built so far, letting the caller still report on it
    (PR body / job summary / outputs) instead of losing it outright.
    """

    def __init__(self, message: str, result: UpdateResult):
        super().__init__(message)
        self.result = result
