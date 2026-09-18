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
from dataclasses import dataclass
from pathlib import Path

from .groups import uv_known_groups

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
_SOURCE_KEYS = {"git", "path", "url", "workspace"}

# name, then an optional bracketed extras list, then whatever is left
# (specifier text, possibly parenthesized, or a direct "@ ..." reference).
_NAME_EXTRAS_RE = re.compile(
    r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(\[\s*([^\]]*)\s*\])?\s*(.*)$"
)


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


def is_vcs_path_or_workspace_source(sources: dict, name: str) -> bool:
    entry = sources.get(name)
    if entry is None:
        return False
    entries = entry if isinstance(entry, list) else [entry]
    return any(isinstance(e, dict) and _SOURCE_KEYS & e.keys() for e in entries)


@dataclass(frozen=True)
class ParsedRequirement:
    """A PEP 508 requirement string, broken into the pieces the major-bump
    feature needs. `specifier_text` is the raw specifier set (whatever
    comes after the name/extras and before an environment marker), with a
    single pair of enclosing parentheses stripped if present (PEP 508
    allows `name (>=1,<2)` as well as `name>=1,<2`; Poetry's own
    `[project.dependencies]` output uses the parenthesized form)."""

    name: str
    extras: tuple[str, ...]
    specifier_text: str
    marker: str | None
    is_direct_reference: bool  # "name @ <url>" - cannot be version-bumped


def parse_requirement(requirement: str) -> ParsedRequirement | None:
    text = (requirement or "").strip()
    if not text:
        return None

    marker: str | None = None
    if ";" in text:
        text, marker = text.split(";", 1)
        text = text.strip()
        marker = marker.strip() or None

    match = _NAME_EXTRAS_RE.match(text)
    if not match:
        return None
    name = match.group(1)
    extras_raw = match.group(3) or ""
    extras = tuple(e.strip() for e in extras_raw.split(",") if e.strip())
    rest = match.group(4).strip()

    is_direct_reference = rest.startswith("@")
    specifier_text = ""
    if rest and not is_direct_reference:
        if rest.startswith("(") and rest.endswith(")"):
            rest = rest[1:-1].strip()
        specifier_text = rest

    return ParsedRequirement(
        name=name,
        extras=extras,
        specifier_text=specifier_text,
        marker=marker,
        is_direct_reference=is_direct_reference,
    )


@dataclass(frozen=True)
class PepDeclaration:
    """Where a package is declared in a PEP 621 (`[project.dependencies]`
    etc.) or PEP 735 (`[dependency-groups]`) table, or the legacy
    `[tool.uv.dev-dependencies]` list - the shape shared by uv's own
    dependencies and Poetry >= 2's PEP 621 tables."""

    # "dependencies" | "optional-dependencies" | "dependency-groups" | "tool.uv.dev-dependencies"
    table: str
    group: str | None  # extra/group name, None for the plain "dependencies" table
    index: int
    raw: str
    parsed: ParsedRequirement


def find_pep_declaration(data: dict, package: str) -> PepDeclaration | None:
    """Locate `package` (matched PEP 503 normalized) in any PEP
    621/735-style dependency table of an already-parsed `pyproject.toml`.
    Returns the first match; a `pyproject.toml` declaring the same
    top-level package in more than one of these tables at once is not a
    shape this action needs to handle specially."""
    target = normalize_name(package)

    def _scan(entries: list, table: str, group: str | None) -> PepDeclaration | None:
        for index, entry in enumerate(entries or []):
            if not isinstance(entry, str):
                continue  # e.g. a dependency-groups {"include-group": ...} entry
            parsed = parse_requirement(entry)
            if parsed and normalize_name(parsed.name) == target:
                return PepDeclaration(table, group, index, entry, parsed)
        return None

    project = data.get("project") or {}

    found = _scan(project.get("dependencies") or [], "dependencies", None)
    if found:
        return found

    for extra, entries in (project.get("optional-dependencies") or {}).items():
        found = _scan(entries, "optional-dependencies", extra)
        if found:
            return found

    for group, entries in (data.get("dependency-groups") or {}).items():
        found = _scan(entries, "dependency-groups", group)
        if found:
            return found

    tool_uv = (data.get("tool") or {}).get("uv") or {}
    found = _scan(tool_uv.get("dev-dependencies") or [], "tool.uv.dev-dependencies", None)
    if found:
        return found

    return None


def _dependency_group_includes(data: dict) -> dict[str, set[str]]:
    """`group name -> set of group names it includes`, one level - every
    `{"include-group": "..."}` table entry directly inside a
    `[dependency-groups]` (PEP 735) group. `_group_closure` below follows
    this transitively. Never raises on a reference to a group that turns
    out not to exist (uv itself would refuse to lock such a project) -
    `_group_closure` simply finds nothing more to add for it."""
    includes: dict[str, set[str]] = {}
    for group_name, group_entries in (data.get("dependency-groups") or {}).items():
        for entry in group_entries or []:
            if isinstance(entry, dict) and isinstance(entry.get("include-group"), str):
                includes.setdefault(group_name, set()).add(entry["include-group"])
    return includes


def _group_closure(group: str, includes: dict[str, set[str]]) -> set[str]:
    """Every group reachable from `group` by following `include-group`
    edges, `group` itself always included - cycle-safe (a real
    `include-group` cycle is rejected by uv itself at lock time, verified
    against real uv==0.12.14: "Detected a cycle in `dependency-groups`" -
    but this never assumes that; a group already visited is simply never
    revisited, so a cycle just makes the closure stop growing rather than
    looping forever)."""
    seen: set[str] = set()
    stack = [group]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(includes.get(current, ()))
    return seen


def _active_reachable_groups(
    data: dict,
    without_groups: tuple[str, ...],
    only_groups: tuple[str, ...],
) -> set[str]:
    """Every group name a requirement's own *declaring* group may match
    against to still be considered active this run - the transitive
    `include-group` closure (PEP 735) of whichever groups are themselves
    active, mirroring uv's own semantics (verified against real
    uv==0.12.14): `--no-group x` deactivates `x` as a root, but a package
    declared under `x` is still installed if some *other* still-active
    group's own `include-group` chain reaches `x` - e.g. given `test =
    ["certifi"]` and `dev = [{include-group = "test"}, "six"]`, `uv sync
    --no-group test` still installs certifi via `dev`, and `--only-group
    dev` installs both six and certifi, while `--only-group test` installs
    only certifi (dev does not reach test the other way around).

    With none of `with_groups`/`without_groups`/`only_groups` set, every
    known group is already a root (today's "list everything" default -
    see `list_top_level_dependency_names`), so the closure computation
    changes nothing in that case - it only matters once `without_groups`/
    `only_groups` actually narrows the active roots."""
    includes = _dependency_group_includes(data)
    roots = set(only_groups) if only_groups else uv_known_groups(data) - set(without_groups)
    reachable: set[str] = set()
    for root in roots:
        reachable |= _group_closure(root, includes)
    return reachable


def _group_included(group: str | None, reachable_groups: set[str]) -> bool:
    """Whether a requirement tagged with `group` (see
    `list_top_level_dependency_names`) should be iterated at all. `group`
    is `None` for an optional-dependencies (extras) entry, which is
    always included - extras are a separate axis `with-groups`/
    `without-groups`/`only-groups` (issue #4) does not touch.
    `reachable_groups` already folds in with/without/only *and* PEP 735
    `include-group` transitivity - see `_active_reachable_groups`."""
    if group is None:
        return True
    return group in reachable_groups


def has_uv_conflicts(pyproject_path: Path) -> bool:
    """True if `[tool.uv.conflicts]` declares at least one conflict set.

    A non-empty `tool.uv.conflicts` means some extras/groups are mutually
    exclusive, so unconditionally selecting all of them (`uv sync
    --all-groups --all-extras`) fails outright - see `UvBackend`."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    conflicts = ((data.get("tool") or {}).get("uv") or {}).get("conflicts") or []
    return bool(conflicts)


def list_top_level_dependency_names(
    pyproject_path: Path,
    with_groups: tuple[str, ...] = (),
    without_groups: tuple[str, ...] = (),
    only_groups: tuple[str, ...] = (),
) -> list[str]:
    """Return the sorted, deduplicated, PEP-503-normalized names of every
    top-level dependency declared anywhere in `pyproject_path`: base
    dependencies, every optional-dependencies extra, every dependency
    group, and the legacy `tool.uv.dev-dependencies` list. Direct URL/path
    requirements and anything pinned to a git/path/url/workspace source in
    `[tool.uv.sources]` are skipped, since `uv lock --upgrade-package`
    cannot meaningfully bump those.

    `with_groups`/`without_groups`/`only_groups` (issue #4) filter which
    dependency GROUPS are iterated - `"main"` for `[project.dependencies]`,
    `"dev"` for the legacy `[tool.uv.dev-dependencies]` list, and each
    `[dependency-groups]` (PEP 735) key by its own name (see `groups.py`
    for the full picture, including how these also drive `uv sync`'s
    selection). `with_groups` has no effect *here*: with none of the three
    set, every group is already iterated (today's behavior, unchanged),
    so there is nothing left for `with_groups` to add back - it only ever
    matters for `UvBackend.sync()`'s own selection (see
    `groups.uv_group_sync_args`). An optional-dependencies extra is always
    iterated regardless of any of the three - extras are a separate axis
    this feature does not touch.

    A requirement's own *declaring* group is not the only way it can be
    reached: PEP 735's `{"include-group": "..."}` entries mean a group can
    pull in another group's members wholesale, transitively, and uv honors
    that when deciding what `--only-group`/`--no-group` actually select
    (verified against real uv==0.12.14 - see `_active_reachable_groups`'s
    own docstring for the exact semantics, including the surprising one:
    `without_groups` naming a group that is still reachable through some
    other active group does not remove its members)."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    # (requirement, group) pairs; group is None for an extra (always
    # included - see _group_included), "main" for a plain dependency, the
    # dependency-groups/tool.uv.dev-dependencies group name otherwise -
    # each requirement's own *declaring* group, before include-group
    # transitivity (_active_reachable_groups, applied below) decides
    # whether that declaring group is actually reachable this run.
    requirements: list[tuple[str, str | None]] = []

    project = data.get("project") or {}
    requirements += [(r, "main") for r in (project.get("dependencies") or [])]
    for extra_deps in (project.get("optional-dependencies") or {}).values():
        requirements += [(r, None) for r in (extra_deps or [])]

    for group_name, group_entries in (data.get("dependency-groups") or {}).items():
        for entry in group_entries or []:
            if isinstance(entry, str):
                requirements.append((entry, group_name))
            # Table entries such as {"include-group": "..."} name no
            # package of their own; the group they point at is walked via
            # its own key in the same loop, so nothing is lost by skipping
            # them here.

    tool_uv = (data.get("tool") or {}).get("uv") or {}
    requirements += [(r, "dev") for r in (tool_uv.get("dev-dependencies") or [])]

    sources = {normalize_name(k): v for k, v in (tool_uv.get("sources") or {}).items()}
    reachable_groups = _active_reachable_groups(data, tuple(without_groups), tuple(only_groups))

    names = set()
    for requirement, group in requirements:
        if not _group_included(group, reachable_groups):
            continue
        name = _requirement_name(requirement)
        if name is None:
            continue
        if is_vcs_path_or_workspace_source(sources, name):
            continue
        names.add(name)

    return sorted(names)
