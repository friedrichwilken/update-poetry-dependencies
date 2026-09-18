"""Dependency-group selection (`with-groups`/`without-groups`/`only-groups`,
issue #4): which groups a run considers, for two purposes -

1. which top-level packages get iterated by the update loop at all
   (`Backend.list_top_level_packages()`);
2. what gets installed/synced, so the test command runs against the
   intended set (`Backend.install()`/`Backend.sync()`).

`"main"` names the project's own, ungrouped dependency set
(`[project.dependencies]` / `[tool.poetry.dependencies]`) - it is never a
real group in either backend's own vocabulary, but is always a valid name
to pass to `with-groups`/`without-groups`/`only-groups`, for symmetry with
the named groups. Poetry already treats `"main"` as a real group name for
its own `--with`/`--without`/`--only` flags (verified against real
poetry==2.4.3), so it needs no special-casing there. uv has no such
built-in name - see `uv_group_sync_args()` below for how it is emulated.

For uv, `"dev"` additionally covers the legacy `[tool.uv.dev-dependencies]`
list, on top of any `dev` key inside `[dependency-groups]` (PEP 735) - both
mean the same thing to uv's own `--group dev`/`--no-group dev` handling
(verified against real uv==0.12.14: `--only-group dev` behaves exactly like
the dedicated `--only-dev` flag, so this backend never needs the
dev-specific flags at all - `--group`/`--no-group`/`--only-group` cover
every case uniformly).

Validation happens once, before any work at all (fail fast, issue #4):
`check_group_selection` (pure, no I/O) enforces that `only-groups` is
mutually exclusive with `with-groups`/`without-groups`; `check_known_groups`
(reads `pyproject.toml`) enforces that every named group actually exists in
the project, for whichever backend is in play.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .errors import ActionError
from .versions import version_at_least

MAIN_GROUP = "main"

# PEP 735 `[dependency-groups]` support was added in Poetry 2.2.0 - "Add
# support for PEP 735 dependency groups" (poetry#10130),
# https://github.com/python-poetry/poetry/releases/tag/2.2.0. Verified
# empirically too: poetry==2.1.4 silently ignores the whole table (a
# package declared only there never even reaches the lock file, and
# `poetry show --only <name>` fails with "Group(s) not found"); poetry==2.2.0
# honors it exactly like a `[tool.poetry.group.<name>]` table. A name that
# only exists in `[dependency-groups]` is therefore not a real, selectable
# group for an older poetry-version - see `poetry_known_groups`.
MIN_POETRY_VERSION_FOR_DEPENDENCY_GROUPS = "2.2"


def check_group_selection(
    with_groups: list[str], without_groups: list[str], only_groups: list[str]
) -> None:
    """`only-groups` is mutually exclusive with `with-groups`/`without-groups`
    - pure, no I/O, so this can run before anything else (even before the
    package manager/backend is known)."""
    if only_groups and (with_groups or without_groups):
        raise ActionError(
            "only-groups is mutually exclusive with with-groups/without-groups; "
            "set only one of them"
        )


def poetry_known_groups(data: dict, poetry_version: str) -> set[str]:
    """Every group name valid for `--with`/`--without`/`--only` against this
    `pyproject.toml`, parsed with `tomllib` - `"main"`, every
    `[tool.poetry.group.<g>]` name, `"dev"` if `[tool.poetry.dev-dependencies]`
    is present, and, only when `poetry_version` actually supports it (see
    `MIN_POETRY_VERSION_FOR_DEPENDENCY_GROUPS` above), every
    `[dependency-groups]` (PEP 735) name too."""
    tool_poetry = (data.get("tool") or {}).get("poetry") or {}
    groups = {MAIN_GROUP}
    groups |= set((tool_poetry.get("group") or {}).keys())
    if tool_poetry.get("dev-dependencies"):
        groups.add("dev")
    if version_at_least(poetry_version, MIN_POETRY_VERSION_FOR_DEPENDENCY_GROUPS):
        groups |= set((data.get("dependency-groups") or {}).keys())
    return groups


def uv_known_groups(data: dict) -> set[str]:
    """Every group name valid for this action's own `with-groups`/
    `without-groups`/`only-groups` against this `pyproject.toml`: `"main"`
    (this action's own name for `[project.dependencies]`, uv has no such
    group of its own), every `[dependency-groups]` (PEP 735) name, and
    `"dev"` if the legacy `[tool.uv.dev-dependencies]` list is present."""
    groups = {MAIN_GROUP}
    groups |= set((data.get("dependency-groups") or {}).keys())
    tool_uv = (data.get("tool") or {}).get("uv") or {}
    if tool_uv.get("dev-dependencies"):
        groups.add("dev")
    return groups


def check_known_groups(
    package_manager: str,
    directory: str,
    with_groups: list[str],
    without_groups: list[str],
    only_groups: list[str],
    poetry_version: str = "",
) -> None:
    """Fails fast, before any work, if a requested group name does not
    exist in the project's `pyproject.toml` - never silently ignored.
    A no-op (and no file read at all) when no group input is set.
    `poetry_version` is only ever consulted for the poetry backend (see
    `poetry_known_groups`) - a `[dependency-groups]` (PEP 735) name gets
    its own, more specific error when it is right there in the file but
    invisible to this run's `poetry-version`, rather than being reported
    as if it did not exist at all."""
    requested = set(with_groups) | set(without_groups) | set(only_groups)
    if not requested:
        return

    pyproject_path = Path(directory) / "pyproject.toml"
    if not pyproject_path.is_file():
        # Let the ordinary "lock/manifest not found" checks later in run()
        # report this - not this function's job to duplicate that error.
        return
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ActionError(f"could not parse {pyproject_path}: {exc}") from None

    if package_manager == "poetry":
        known = poetry_known_groups(data, poetry_version)
        unknown = sorted(requested - known)
        if not unknown:
            return
        pep735_names = set((data.get("dependency-groups") or {}).keys())
        version_blocked = sorted(set(unknown) & pep735_names)
        if version_blocked and not version_at_least(
            poetry_version, MIN_POETRY_VERSION_FOR_DEPENDENCY_GROUPS
        ):
            raise ActionError(
                f"dependency group(s) {', '.join(version_blocked)} are declared in "
                f"[dependency-groups] in {pyproject_path}, but PEP 735 dependency groups "
                f"require poetry-version >= {MIN_POETRY_VERSION_FOR_DEPENDENCY_GROUPS} "
                f"(this run uses poetry-version {poetry_version or '(unset)'}); set "
                "poetry-version to a version that supports them, or select a different group"
            )
    else:
        known = uv_known_groups(data)
        unknown = sorted(requested - known)
        if not unknown:
            return

    raise ActionError(
        f"unknown dependency group(s) for the {package_manager} backend in "
        f"{pyproject_path}: {', '.join(unknown)}; known groups: "
        f"{', '.join(sorted(known)) or '(none)'}"
    )


def poetry_group_args(
    with_groups: list[str], without_groups: list[str], only_groups: list[str]
) -> list[str]:
    """`--with`/`--without`/`--only` flags for `poetry show -T`/`install`/
    `sync` (and the transitive-dependencies step's own `poetry update`).
    `[]` (Poetry's own, unchanged default) when no group input is set -
    this is what keeps a run with none of them set byte-for-byte identical
    to before this feature existed."""
    args: list[str] = []
    if only_groups:
        for group in only_groups:
            args += ["--only", group]
        return args
    for group in with_groups:
        args += ["--with", group]
    for group in without_groups:
        args += ["--without", group]
    return args


def uv_group_sync_args(
    with_groups: list[str], without_groups: list[str], only_groups: list[str]
) -> list[str] | None:
    """The uv counterpart of `poetry_group_args()`, for `uv sync`
    (`Backend.install()`/`sync()`). Returns `None` when no group input is
    set at all, so the caller falls back to its own pre-existing
    `--all-groups --all-extras` default (see `backend.UvBackend._selection_args`)
    - unlike Poetry, uv has no single flag meaning "everything, exactly like
    before this feature existed", so that fallback has to stay a caller
    concern.

    Once any group input *is* set, the selection switches from that
    permissive default to uv's own native default group set (main plus
    whatever `[tool.uv.default-groups]`/PEP 735 default already includes,
    most commonly just `dev`) adjusted by `with-groups`/`without-groups`/
    `only-groups` - mirroring `poetry show`/`install`'s own `--with`/
    `--without`/`--only` semantics as closely as uv's flag set allows (see
    the module docstring for verified real-uv flag behavior):

    - `only-groups`: uv's `--only-group <g>` already excludes `"main"` and
      every other group on its own (verified against real uv==0.12.14), so
      a plain custom-groups-only selection maps straight onto one
      `--only-group` per name. `"main"` in the selection needs a different
      pairing - there is no uv flag meaning "only main" - `--no-default-groups`
      (excludes uv's own default groups, e.g. `dev`) plus a `--group` for
      every other requested group reproduces it: main is always installed
      unless `--only-group` is used, so leaving it alone is exactly what is
      wanted, and `--no-default-groups` keeps a *default* group like `dev`
      from sneaking back in when it was not asked for.
    - `with-groups`/`without-groups`: `--group <g>`/`--no-group <g>` per
      name, on top of uv's own native default selection - `"main"` is
      skipped in `with-groups` (it is always included already, so this is
      a no-op) and, in `without-groups`, also skipped, but with a
      `::warning::` (see `backend.UvBackend._selection_args`) - uv has no
      flag to exclude the project's own `[project.dependencies]` from
      `sync` while still installing other groups, so `without-groups:
      main` cannot be honored for the *sync* selection here (it is still
      fully honored for which top-level packages get *iterated* - see
      `pyproject_deps.list_top_level_dependency_names`, which needs no uv
      flag at all to filter that).
    """
    if not (with_groups or without_groups or only_groups):
        return None

    if only_groups:
        custom = [g for g in only_groups if g != MAIN_GROUP]
        args: list[str] = []
        if MAIN_GROUP in only_groups:
            args.append("--no-default-groups")
            for group in custom:
                args += ["--group", group]
        else:
            for group in custom:
                args += ["--only-group", group]
        return args

    args = []
    for group in with_groups:
        if group != MAIN_GROUP:
            args += ["--group", group]
    for group in without_groups:
        if group != MAIN_GROUP:
            args += ["--no-group", group]
    return args
