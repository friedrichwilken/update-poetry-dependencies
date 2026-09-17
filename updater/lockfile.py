"""Reads a package's locked version(s) out of `poetry.lock` / `uv.lock`.

Both lock formats are TOML with a top-level array of `[[package]]` tables
carrying at least `name` and `version` keys, so a single stdlib-`tomllib`
based parser covers both backends - `Backend.locked_version()` (see
`backend.py`) is a thin wrapper around `locked_version()` below for both
`PoetryBackend` and `UvBackend`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .pyproject_deps import normalize_name


def locked_version(lock_path: Path | str, package: str) -> str | None:
    """The locked version of `package`, or None if the lock file is
    missing/unparsable or does not mention the package.

    A lock file can carry more than one `[[package]]` entry for the same
    normalized name - uv recording distinct forks/markers, or Poetry
    recording multiple marker-scoped entries for the same package - in
    which case every distinct version found is joined, comma-separated and
    sorted, rather than arbitrarily picking one.
    """
    path = Path(lock_path)
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError, OSError, UnicodeDecodeError:
        return None

    target = normalize_name(package)
    versions: set[str] = set()
    for entry in data.get("package") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        version = entry.get("version")
        if not name or not version:
            continue
        if normalize_name(name) == target:
            versions.add(str(version))

    if not versions:
        return None
    return ", ".join(sorted(versions))
