"""Extracts top-level dependency package names from a `pyproject.toml`, the
uv-backend equivalent of `poetry show --top-level`.

uv has no single command that lists top-level dependency names the way
`poetry show --top-level` does, so this parses `[project.dependencies]`,
`[project.optional-dependencies]`, `[dependency-groups]` (PEP 735) and the
legacy `[tool.uv.dev-dependencies]` table directly, using the stdlib
`tomllib` parser (available since Python 3.11; the updater always runs on a
pinned 3.14 interpreter regardless of the project's own python-version, see
`bootstrap.py`).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
_SOURCE_KEYS = {"git", "path", "url", "workspace"}


def normalize_name(name: str) -> str:
    """PEP 503 normalization: case-fold and collapse runs of `-`, `_`, `.`
    into a single `-`."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str | None:
    """Extract and normalize the package name from a PEP 508 requirement
    string. Returns None for direct URL/path requirements (`name @ ...`),
    which cannot be resolved/upgraded through the normal registry
    resolution `uv lock --upgrade-package` relies on."""
    req = requirement.split(";", 1)[0].strip()  # drop the environment marker
    if "@" in req:
        return None
    match = _NAME_RE.match(req)
    if not match:
        return None
    return normalize_name(match.group(1))


def _is_vcs_path_or_workspace_source(sources: dict, name: str) -> bool:
    entry = sources.get(name)
    if entry is None:
        return False
    entries = entry if isinstance(entry, list) else [entry]
    return any(isinstance(e, dict) and _SOURCE_KEYS & e.keys() for e in entries)


def has_uv_conflicts(pyproject_path: Path) -> bool:
    """True if `[tool.uv.conflicts]` declares at least one conflict set.

    A non-empty `tool.uv.conflicts` means some extras/groups are mutually
    exclusive, so unconditionally selecting all of them (`uv sync
    --all-groups --all-extras`) fails outright - see `UvBackend`."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    conflicts = ((data.get("tool") or {}).get("uv") or {}).get("conflicts") or []
    return bool(conflicts)


def list_top_level_dependency_names(pyproject_path: Path) -> list[str]:
    """Return the sorted, deduplicated, PEP-503-normalized names of every
    top-level dependency declared anywhere in `pyproject_path`: base
    dependencies, every optional-dependencies extra, every dependency
    group, and the legacy `tool.uv.dev-dependencies` list. Direct URL/path
    requirements and anything pinned to a git/path/url/workspace source in
    `[tool.uv.sources]` are skipped, since `uv lock --upgrade-package`
    cannot meaningfully bump those."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    requirements: list[str] = []

    project = data.get("project") or {}
    requirements.extend(project.get("dependencies") or [])
    for extra_deps in (project.get("optional-dependencies") or {}).values():
        requirements.extend(extra_deps or [])

    for group_entries in (data.get("dependency-groups") or {}).values():
        for entry in group_entries or []:
            if isinstance(entry, str):
                requirements.append(entry)
            # Table entries such as {"include-group": "..."} name no
            # package of their own; the group they point at is walked via
            # its own key in the same loop, so nothing is lost by skipping
            # them here.

    tool_uv = (data.get("tool") or {}).get("uv") or {}
    requirements.extend(tool_uv.get("dev-dependencies") or [])

    sources = {normalize_name(k): v for k, v in (tool_uv.get("sources") or {}).items()}

    names = set()
    for requirement in requirements:
        name = _requirement_name(requirement)
        if name is None:
            continue
        if _is_vcs_path_or_workspace_source(sources, name):
            continue
        names.add(name)

    return sorted(names)
