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

# run_updates() calls locked_version() twice per package against the same
# lock file, so re-parsing the whole file from scratch every time is
# wasted work on a project with many packages. A single-entry cache keyed
# by (path, mtime_ns, size) is enough: within one run the lock file is
# only ever read (never concurrently written), and clearing it whenever a
# different key shows up keeps memory bounded to at most one parsed file
# at a time.
_cache_key: tuple[str, int, int] | None = None
_cache_data: dict | None = None


def _load(path: Path) -> dict:
    global _cache_key, _cache_data

    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key == _cache_key and _cache_data is not None:
        return _cache_data

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    _cache_key, _cache_data = key, data
    return data


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
        data = _load(path)
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
