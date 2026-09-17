"""Locates a package's declaration in Poetry's own dependency tables
(`[tool.poetry.dependencies]`, `[tool.poetry.group.<g>.dependencies]`, and
the legacy `[tool.poetry.dev-dependencies]`) - the counterpart to
`pyproject_deps.find_pep_declaration`, which covers the PEP 621/735 tables
Poetry >= 2 also supports (`[project.dependencies]` etc).

Kept separate from `pyproject_deps.py` because the *shape* of an entry
here is entirely different: a plain string or an inline table using
Poetry's own keys (`version`, `extras`, `optional`, `git`, `path`, `url`,
`source`, `markers`, `python`, `platform`, ...), never a PEP 508
requirement string.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pyproject_deps import normalize_name

# Any of these present on a dependency's table entry means "this is not a
# plain registry dependency behind a version constraint" - the major-bump
# feature has no faithful way to preserve it, so a package declared with
# one of these is always skipped rather than risking silently dropping it.
_UNSUPPORTED_KEYS = {
    "git",
    "path",
    "url",
    "source",
    "markers",
    "python",
    "platform",
    "branch",
    "tag",
    "rev",
    "allow-prereleases",
}


@dataclass(frozen=True)
class PoetryTableDeclaration:
    # "tool.poetry.dependencies" | "tool.poetry.group.dependencies" | "tool.poetry.dev-dependencies"
    table: str
    group: str | None  # the group name for "tool.poetry.group.dependencies", else None
    name: str  # key exactly as written in the table
    value: object  # raw TOML value for that key: str | dict | list


def find_poetry_table_declaration(data: dict, package: str) -> PoetryTableDeclaration | None:
    target = normalize_name(package)
    tool_poetry = (data.get("tool") or {}).get("poetry") or {}

    for name, value in (tool_poetry.get("dependencies") or {}).items():
        if normalize_name(name) == target:
            return PoetryTableDeclaration("tool.poetry.dependencies", None, name, value)

    for group_name, group_table in (tool_poetry.get("group") or {}).items():
        for name, value in ((group_table or {}).get("dependencies") or {}).items():
            if normalize_name(name) == target:
                return PoetryTableDeclaration(
                    "tool.poetry.group.dependencies", group_name, name, value
                )

    for name, value in (tool_poetry.get("dev-dependencies") or {}).items():
        if normalize_name(name) == target:
            return PoetryTableDeclaration("tool.poetry.dev-dependencies", "dev", name, value)

    return None


def find_extra_for_optional(data: dict, name: str) -> str | None:
    """The `[tool.poetry.extras]` entry (if any) that lists `name` -
    Poetry's legacy way of exposing an `optional = true` dependency as an
    installable extra."""
    target = normalize_name(name)
    extras = ((data.get("tool") or {}).get("poetry") or {}).get("extras") or {}
    for extra, members in extras.items():
        if any(normalize_name(m) == target for m in members or []):
            return extra
    return None


def unsupported_key(value: object) -> str | None:
    """The first key in `value` (a table-form dependency entry) that makes
    it unsafe for the major-bump feature to touch, or None if it looks
    like a plain version-constrained dependency."""
    if not isinstance(value, dict):
        return None
    for key in _UNSUPPORTED_KEYS:
        if key in value:
            return key
    return None


def constraint_text(value: object) -> str | None:
    """The version constraint string of a dependency entry, whichever
    shape it is written in - a bare string, or a table's `version` key
    (which may itself be absent, e.g. a source-only override; the caller
    is expected to have already rejected those via `unsupported_key`)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        version = value.get("version")
        return version if isinstance(version, str) else None
    return None


def extras_of(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(value.get("extras") or [])
    return ()


def is_optional(value: object) -> bool:
    return isinstance(value, dict) and bool(value.get("optional"))


def normalized_extra_fields(value: object) -> tuple:
    """A coarse fingerprint of everything about a dependency entry other
    than its version constraint: extras (order independent), the optional
    flag, and every other key/value pair. Used to detect whether `poetry
    add` changed anything besides the version constraint it was asked to
    raise - if this differs before vs. after, the change is treated as
    unsupported rather than silently kept."""
    if isinstance(value, str):
        return ((), False, ())
    if isinstance(value, dict):
        extras = tuple(sorted(value.get("extras") or []))
        optional = bool(value.get("optional", False))
        other = tuple(
            sorted(
                (key, repr(val))
                for key, val in value.items()
                if key not in ("version", "extras", "optional")
            )
        )
        return (extras, optional, other)
    return None
