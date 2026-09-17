"""Resolves the `package-manager` input ('auto' | 'poetry' | 'uv') to a
concrete backend name."""

from __future__ import annotations

from pathlib import Path

from .errors import ActionError

UV_LOCK_FILE = "uv.lock"
POETRY_LOCK_FILE = "poetry.lock"

_KNOWN = {"poetry", "uv"}


def detect_package_manager(directory: str, requested: str) -> str:
    """`requested` is the raw `package-manager` input. An explicit
    'poetry'/'uv' is returned as-is without touching the filesystem, so
    callers never pay for (or need to fake) a directory lookup unless
    auto-detection is actually in play. 'auto' (or an empty string) looks
    at which lock file is present in `directory`."""
    choice = (requested or "auto").strip().lower()
    if choice in _KNOWN:
        return choice
    if choice != "auto":
        raise ActionError(
            f"invalid package-manager '{requested}'; expected 'auto', 'poetry', or 'uv'"
        )

    has_uv = (Path(directory) / UV_LOCK_FILE).is_file()
    has_poetry = (Path(directory) / POETRY_LOCK_FILE).is_file()

    if has_uv and has_poetry:
        raise ActionError(
            f"both {UV_LOCK_FILE} and {POETRY_LOCK_FILE} found in {directory}; "
            "set package-manager to 'poetry' or 'uv' explicitly"
        )
    if has_uv:
        return "uv"
    if has_poetry:
        return "poetry"
    raise ActionError(
        f"neither {UV_LOCK_FILE} nor {POETRY_LOCK_FILE} found in {directory}; nothing to update"
    )
