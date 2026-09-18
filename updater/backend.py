"""Backend abstraction over a dependency manager.

`PoetryBackend` and `UvBackend` both implement `Backend` below (list top
level packages, update one package, sync the environment to the lock file,
report which files to stage). The interface is kept narrow on purpose so
the update loop in `updater.py` never needs to know which one it is
driving.
"""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .config import parse_labels
from .constraints import (
    all_clauses_parseable,
    pep508_has_upper_bound,
    pep508_is_exact_pin,
    pep508_parse_specifiers,
    pep508_strip_upper_bound,
    poetry_classify_constraint,
)
from .errors import ActionError
from .groups import MAIN_GROUP, poetry_group_args, uv_group_sync_args
from .lockfile import all_locked_versions as _all_locked_versions
from .lockfile import locked_version as _locked_version
from .major import MajorAttempt
from .pep440 import is_prerelease
from .poetry_manifest import (
    constraint_text,
    extras_of,
    find_extra_for_optional,
    find_poetry_table_declaration,
    is_optional,
    normalized_extra_fields,
    unsupported_key,
)
from .pyproject_deps import (
    find_pep_declaration,
    has_uv_conflicts,
    is_vcs_path_or_workspace_source,
    list_top_level_dependency_names,
    normalize_name,
)
from .runner import CommandResult, CommandRunner
from .versions import version_at_least

if TYPE_CHECKING:
    from .config import Config

POETRY_LOCK_FILE = "poetry.lock"
UV_LOCK_FILE = "uv.lock"
PYPROJECT_FILE = "pyproject.toml"


def _lands_on_new_prerelease(before_version: str | None, after_version: str | None) -> bool:
    """True if `after_version` is a pre-release but `before_version` was
    not. `poetry add pkg@latest` / `uv add ... --upgrade-package` are
    both expected to already exclude pre-releases by default, but a
    beyond-constraint attempt must never rely on that silently - this is
    the guarantee living in this action's own code. A comma-joined
    multi-version `locked_version()` result (see `lockfile.py`) never
    parses as a single PEP 440 version, so this conservatively treats it
    as "not a pre-release" rather than guessing."""
    return is_prerelease(after_version or "") and not is_prerelease(before_version or "")


class Backend(Protocol):
    name: str

    def lock_file_path(self) -> Path: ...

    def lock_exists(self) -> bool: ...

    def files_to_stage(self) -> list[str]:
        """Files that a successful in-range update may change and that
        should be committed."""
        ...

    def major_files_to_stage(self) -> list[str]:
        """Files that a successful major-bump attempt may change and that
        should be committed - the manifest in addition to whatever
        `files_to_stage()` already covers."""
        ...

    def try_major(self, package: str) -> MajorAttempt | None:
        """Attempt to raise `package`'s declared constraint so its latest
        release is allowed, and re-resolve/re-lock it (see `MajorAttempt`
        for the return contract). Only ever called when `allow-major` is
        enabled."""
        ...

    def install(self) -> CommandResult:
        """Install/sync the environment from the existing lock file
        without changing it."""
        ...

    def list_top_level_packages(self) -> list[str]: ...

    def update_package(self, package: str) -> CommandResult: ...

    def update_all(self, packages: list[str]) -> CommandResult:
        """Update every one of `packages` in a single lock/resolve call
        (used by the batch-first strategy - see `updater.run_updates`),
        rather than one `update_package()` call per package. Only ever
        called with names this backend's own `list_top_level_packages()`
        just returned, so a name unknown to the project is never passed
        in."""
        ...

    def sync(self) -> CommandResult:
        """Re-sync the environment to whatever the lock file currently
        says, without changing the lock file itself."""
        ...

    def update_transitive(self) -> CommandResult:
        """Refresh every dependency (top-level and transitive) that is
        still updatable within its declared constraint, in one final
        tested step run after the top-level loop (`update-transitive`,
        issue #24) - `poetry update --lock` / `uv lock --upgrade`,
        followed by a `sync()` so the environment matches - never touches
        `pyproject.toml`, only the lock file (verified against real
        poetry==2.4.3 and uv==0.12.14 - see `PoetryBackend.update_transitive`/
        `UvBackend.update_transitive`)."""
        ...

    def locked_version(self, package: str) -> str | None:
        """The version(s) `package` is currently locked at, read straight
        from the lock file (not the installed environment), or None if the
        lock file does not mention it."""
        ...

    def all_locked_versions(self) -> dict[str, str]:
        """Every package's locked version(s) in the current lock file,
        keyed by normalized name - see `lockfile.all_locked_versions()`.
        Used by the batch-first strategy to verify a sequential replay
        reproduces the same lock a one-shot batch update produced."""
        ...


class PoetryBackend:
    name = "poetry"

    def __init__(
        self,
        runner: CommandRunner,
        directory: str,
        poetry_version: str,
        with_groups: list[str] | None = None,
        without_groups: list[str] | None = None,
        only_groups: list[str] | None = None,
    ):
        self.runner = runner
        self.directory = directory
        self.poetry_version = poetry_version
        self.with_groups = with_groups or []
        self.without_groups = without_groups or []
        self.only_groups = only_groups or []

    def _group_args(self) -> list[str]:
        """`--with`/`--without`/`--only` flags derived from `with-groups`/
        `without-groups`/`only-groups` (issue #4) - `[]` (Poetry's own,
        unchanged default) when none of them are set. Shared by every
        command whose scope those inputs are documented to control:
        `list_top_level_packages()`, `install()`, `sync()`, and the
        transitive-dependencies step's own `poetry update` - deliberately
        *not* `update_package()`/`update_all()`/`try_major()`, which target
        one already-known package name directly and need no group
        filtering of their own (verified against real poetry==2.4.3:
        `poetry update <pkg>` resolves a named package regardless of which
        group it belongs to)."""
        return poetry_group_args(self.with_groups, self.without_groups, self.only_groups)

    def lock_file_path(self) -> Path:
        return Path(self.directory) / POETRY_LOCK_FILE

    def lock_exists(self) -> bool:
        return self.lock_file_path().is_file()

    def files_to_stage(self) -> list[str]:
        return [POETRY_LOCK_FILE]

    def major_files_to_stage(self) -> list[str]:
        return [PYPROJECT_FILE, POETRY_LOCK_FILE]

    def _pyproject_path(self) -> Path:
        return Path(self.directory) / PYPROJECT_FILE

    def try_major(self, package: str) -> MajorAttempt | None:
        if normalize_name(package) == "python":
            return MajorAttempt(skip_reason="python itself is never bumped")

        pyproject_path = self._pyproject_path()
        if not pyproject_path.is_file():
            return MajorAttempt(skip_reason="pyproject.toml not found")
        before_text = pyproject_path.read_text(encoding="utf-8")
        before_data = tomllib.loads(before_text)

        plan = _plan_poetry_major(before_data, package)
        if plan is None or isinstance(plan, str):
            return None if plan is None else MajorAttempt(skip_reason=plan)

        before_version = self.locked_version(package)

        # --lock: review fix, verified against real poetry==2.4.3 - a
        # plain `poetry add` (no --lock) implicitly installs afterward
        # using Poetry's own default group selection, which would
        # silently reinstall a package `install()`'s own group-aware sync
        # had correctly left out (the exact bug `update_package()` above
        # has its own, longer comment about - found by an e2e test
        # actually invoking the synced venv's own interpreter). The
        # explicit `self.sync()` call below - which *does* respect
        # `with-groups`/`without-groups`/`only-groups` - replaces it, only
        # once the attempt is known to be worth keeping (a discarded
        # attempt is reset+resynced by the caller instead, and --lock
        # means nothing was ever installed for it to begin with).
        args = ["poetry", "add", plan.requirement, "-n", "--lock", *plan.extra_args]
        result = self.runner.run(args, cwd=self.directory)

        if not result.ok:
            return MajorAttempt(resolve_result=result)

        after_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        if not _poetry_only_version_changed(before_data, after_data, plan):
            return MajorAttempt(
                resolve_result=result,
                discarded_reason="manifest changed beyond the version constraint",
            )

        after_version = self.locked_version(package)
        if _lands_on_new_prerelease(before_version, after_version):
            return MajorAttempt(
                resolve_result=result,
                discarded_reason="attempted version is a pre-release",
            )

        sync_result = self.sync()
        combined = CommandResult(
            result.args + sync_result.args,
            sync_result.returncode,
            result.stdout + "\n" + sync_result.stdout,
            result.stderr + "\n" + sync_result.stderr,
        )
        # A failing sync here (unlikely, but see UvBackend.try_major's own
        # identical pattern) surfaces as an ordinary resolution failure -
        # combined.ok being False is exactly what a real resolve failure
        # looks like to every caller of try_major(), so no separate
        # discarded_reason branch is needed for it.
        return MajorAttempt(resolve_result=combined)

    def install(self) -> CommandResult:
        return self.runner.run(["poetry", "install", *self._group_args()], cwd=self.directory)

    def list_top_level_packages(self) -> list[str]:
        result = self.runner.run(
            ["poetry", "show", "--top-level", *self._group_args()], cwd=self.directory
        )
        if not result.ok:
            raise ActionError(f"poetry show --top-level failed: {result.stderr}")
        packages = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            packages.append(line.split()[0])
        return packages

    def update_package(self, package: str) -> CommandResult:
        # `_group_args()` here (unlike try_major()'s own `poetry add`,
        # which never needs it): `poetry update <pkg>` still resolves and
        # updates the named package regardless of which group it belongs
        # to (see `_group_args()`'s own docstring), but - review fix,
        # verified against real poetry==2.4.3 - it *also* implicitly syncs
        # the environment afterward using Poetry's own default group
        # selection unless told otherwise, which would silently reinstall
        # a package `install()`'s own group-aware sync had correctly left
        # out (found by an e2e test actually invoking the synced venv's
        # own interpreter after a per-package update, not just checking
        # report-json). Passing the same flags here keeps that implicit
        # sync in line with everything else.
        return self.runner.run(
            ["poetry", "update", package, "--no-interaction", *self._group_args()],
            cwd=self.directory,
        )

    def update_all(self, packages: list[str]) -> CommandResult:
        # Verified against real poetry==2.4.3: `poetry update a b --no-interaction`
        # resolves and updates every listed package in one call, exactly
        # like a plain `poetry update` restricted to those names - it
        # never touches a package left out of the list. A name that is
        # not a dependency of the project makes the whole call fail
        # outright ("The following packages are not dependencies of this
        # project"), but `update_all` is only ever called with names this
        # backend's own `list_top_level_packages()` just returned, so that
        # never happens here. `_group_args()` guards its own implicit sync
        # the same way `update_package()` does - see its comment above.
        return self.runner.run(
            ["poetry", "update", *packages, "--no-interaction", *self._group_args()],
            cwd=self.directory,
        )

    def sync(self) -> CommandResult:
        """Poetry >= 2 uses the dedicated `sync` command; 1.x needs
        `install --sync`."""
        if version_at_least(self.poetry_version, "2"):
            return self.runner.run(["poetry", "sync", *self._group_args()], cwd=self.directory)
        return self.runner.run(
            ["poetry", "install", "--sync", *self._group_args()], cwd=self.directory
        )

    def update_transitive(self) -> CommandResult:
        # `--lock`: only refresh the lock file, never install/sync as a
        # side effect (verified against real poetry==2.4.3: plain `poetry
        # update` without `--lock` installs into the environment too,
        # using its own default group selection rather than this backend's
        # `with-groups`/`without-groups`/`only-groups`-derived one) - the
        # sync() call below does that instead, so it goes through the same
        # group selection as every other install/sync. Deliberately no
        # `_group_args()` here (see its own docstring) - this refreshes
        # the whole lock file within its existing constraints, same as a
        # plain `poetry update` would, regardless of which groups are
        # selected for listing/installing.
        update_result = self.runner.run(
            ["poetry", "update", "--lock", "--no-interaction"], cwd=self.directory
        )
        if not update_result.ok:
            return update_result
        sync_result = self.sync()
        return CommandResult(
            update_result.args + sync_result.args,
            sync_result.returncode,
            update_result.stdout + "\n" + sync_result.stdout,
            update_result.stderr + "\n" + sync_result.stderr,
        )

    def locked_version(self, package: str) -> str | None:
        return _locked_version(self.lock_file_path(), package)

    def all_locked_versions(self) -> dict[str, str]:
        return _all_locked_versions(self.lock_file_path())


class _PoetryMajorPlan:
    """What `PoetryBackend.try_major()` decided to run, plus enough about
    where the dependency was declared to check afterwards that `poetry
    add` only touched the version constraint."""

    __slots__ = ("requirement", "extra_args", "is_pep", "table", "group", "name", "extras")

    def __init__(self, requirement, extra_args, is_pep, table, group, name, extras):
        self.requirement = requirement
        self.extra_args = extra_args
        self.is_pep = is_pep
        self.table = table
        self.group = group
        self.name = name
        self.extras = extras


def _plan_poetry_major(data: dict, package: str) -> _PoetryMajorPlan | str | None:
    """Returns a `_PoetryMajorPlan` ready to execute, a string skip reason,
    or None (no attempt needed - the constraint already has no effective
    upper bound). Poetry's own tables are checked first: a package
    declared via `[project.dependencies]` but overridden with a
    git/path/url/source in `[tool.poetry.dependencies]` must be skipped
    based on that override, not the plain PEP 508 entry."""
    table_decl = find_poetry_table_declaration(data, package)
    if table_decl is not None:
        bad_key = unsupported_key(table_decl.value)
        if bad_key:
            return f"{bad_key} dependency"
        if isinstance(table_decl.value, list):
            return "multiple constraint entries (per-python/platform markers)"

        raw_constraint = constraint_text(table_decl.value)
        if raw_constraint is None:
            return "no version constraint to raise"
        needed, reason = poetry_classify_constraint(raw_constraint)
        if reason is not None:
            return reason
        if not needed:
            return None

        extra_args = []
        if table_decl.table == "tool.poetry.group.dependencies":
            extra_args += ["--group", table_decl.group]
        elif table_decl.table == "tool.poetry.dev-dependencies":
            extra_args += ["--group", "dev"]

        # `poetry add` drops an existing `optional = true` unless told
        # which extra it belongs to (verified against poetry==2.4.3: the
        # entry loses its `optional` key entirely otherwise, which the
        # before/after diff guard below would then correctly - but
        # wastefully - discard on every single run).
        if is_optional(table_decl.value):
            extra = find_extra_for_optional(data, table_decl.name)
            if extra is None:
                return "optional dependency not listed in any [tool.poetry.extras] entry"
            extra_args += ["--optional", extra]

        extras = extras_of(table_decl.value)
        extras_part = f"[{','.join(extras)}]" if extras else ""
        requirement = f"{table_decl.name}{extras_part}@latest"

        return _PoetryMajorPlan(
            requirement,
            extra_args,
            False,
            table_decl.table,
            table_decl.group,
            table_decl.name,
            extras,
        )

    pep_decl = find_pep_declaration(data, package)
    if pep_decl is not None:
        parsed = pep_decl.parsed
        if parsed.is_direct_reference:
            return "direct URL/path requirement"
        if parsed.marker:
            return "environment marker"

        clauses = pep508_parse_specifiers(parsed.specifier_text)
        if clauses is None:
            return "unparsable version specifier"
        if not all_clauses_parseable(clauses):
            return "unparsable version specifier"
        if pep508_is_exact_pin(clauses):
            return "exact version pin"
        if not pep508_has_upper_bound(clauses):
            return None

        extras_part = f"[{','.join(parsed.extras)}]" if parsed.extras else ""
        requirement = f"{parsed.name}{extras_part}@latest"

        extra_args = []
        if pep_decl.table == "optional-dependencies":
            extra_args += ["--optional", pep_decl.group]
        elif pep_decl.table == "dependency-groups" and pep_decl.group:
            extra_args += ["--group", pep_decl.group]

        return _PoetryMajorPlan(
            requirement,
            extra_args,
            True,
            pep_decl.table,
            pep_decl.group,
            parsed.name,
            parsed.extras,
        )

    return "could not locate the dependency declaration"


def _poetry_only_version_changed(before: dict, after: dict, plan: _PoetryMajorPlan) -> bool:
    """True if, comparing the same declaration before/after `poetry add`,
    nothing but the version constraint itself changed - same table, same
    group/extra, same extras/optional/other keys. Anything else (moved
    table, dropped extras, a newly introduced marker, ...) means `poetry
    add` did something this feature cannot faithfully preserve, and the
    attempt must be discarded rather than silently kept."""
    if plan.is_pep:
        after_decl = find_pep_declaration(after, plan.name)
        if after_decl is None:
            return False
        return (
            after_decl.table == plan.table
            and after_decl.group == plan.group
            and tuple(sorted(after_decl.parsed.extras)) == tuple(sorted(plan.extras))
            and not after_decl.parsed.marker
            and not after_decl.parsed.is_direct_reference
        )

    before_decl = find_poetry_table_declaration(before, plan.name)
    after_decl = find_poetry_table_declaration(after, plan.name)
    if before_decl is None or after_decl is None:
        return False
    if after_decl.table != plan.table or after_decl.group != plan.group:
        return False
    return normalized_extra_fields(before_decl.value) == normalized_extra_fields(after_decl.value)


class UvBackend:
    name = "uv"

    def __init__(
        self,
        runner: CommandRunner,
        directory: str,
        python_version: str,
        uv_sync_args: str = "",
        with_groups: list[str] | None = None,
        without_groups: list[str] | None = None,
        only_groups: list[str] | None = None,
    ):
        self.runner = runner
        self.directory = directory
        self.python_version = python_version
        self.uv_sync_args = uv_sync_args
        self.with_groups = with_groups or []
        self.without_groups = without_groups or []
        self.only_groups = only_groups or []
        # sync() (and therefore _selection_args()) runs once per package in
        # the update loop; without these, a project with tool.uv.conflicts,
        # or a `without-groups` selection that includes "main", would print
        # the same ::warning:: dozens of times over one run.
        self._conflicts_warned = False
        self._without_main_warned = False

    def lock_file_path(self) -> Path:
        return Path(self.directory) / UV_LOCK_FILE

    def lock_exists(self) -> bool:
        return self.lock_file_path().is_file()

    def files_to_stage(self) -> list[str]:
        return [UV_LOCK_FILE]

    def major_files_to_stage(self) -> list[str]:
        return [PYPROJECT_FILE, UV_LOCK_FILE]

    def _pyproject_path(self) -> Path:
        return Path(self.directory) / PYPROJECT_FILE

    def try_major(self, package: str) -> MajorAttempt | None:
        if normalize_name(package) == "python":
            return MajorAttempt(skip_reason="python itself is never bumped")

        pyproject_path = self._pyproject_path()
        if not pyproject_path.is_file():
            return MajorAttempt(skip_reason="pyproject.toml not found")
        before_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        decl = find_pep_declaration(before_data, package)
        if decl is None:
            return MajorAttempt(skip_reason="could not locate the dependency declaration")
        parsed = decl.parsed

        if parsed.is_direct_reference:
            return MajorAttempt(skip_reason="direct URL/path requirement")
        if parsed.marker:
            return MajorAttempt(skip_reason="environment marker")

        tool_uv = (before_data.get("tool") or {}).get("uv") or {}
        sources = {normalize_name(k): v for k, v in (tool_uv.get("sources") or {}).items()}
        if is_vcs_path_or_workspace_source(sources, normalize_name(parsed.name)):
            return MajorAttempt(skip_reason="git/path/url/workspace source")

        clauses = pep508_parse_specifiers(parsed.specifier_text)
        if clauses is None:
            return MajorAttempt(skip_reason="unparsable version specifier")
        if not all_clauses_parseable(clauses):
            return MajorAttempt(skip_reason="unparsable version specifier")
        if pep508_is_exact_pin(clauses):
            return MajorAttempt(skip_reason="exact version pin")
        if not pep508_has_upper_bound(clauses):
            return None

        before_version = self.locked_version(package)

        new_spec = pep508_strip_upper_bound(clauses)
        extras_part = f"[{','.join(parsed.extras)}]" if parsed.extras else ""
        requirement = f"{parsed.name}{extras_part}{new_spec}"

        # --no-sync: `uv add` would otherwise sync the environment itself,
        # using its own default group/extra selection and interpreter
        # discovery rather than this project's (`_sync_args()`, matching
        # `python-version`/`uv-sync-args`) - do that explicitly below
        # instead, exactly like `update_package()` does for an in-range
        # update, so a major attempt leaves the environment in the same
        # shape either way.
        args = ["uv", "add", requirement, "--upgrade-package", parsed.name, "--no-sync"]
        if decl.table == "optional-dependencies":
            args += ["--optional", decl.group]
        elif decl.table == "dependency-groups":
            args += ["--group", decl.group]
        elif decl.table == "tool.uv.dev-dependencies":
            args += ["--dev"]

        add_result = self.runner.run(args, cwd=self.directory)

        if not add_result.ok:
            return MajorAttempt(resolve_result=add_result)

        after_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        after_decl = find_pep_declaration(after_data, package)
        same_shape = (
            after_decl is not None
            and after_decl.table == decl.table
            and after_decl.group == decl.group
            and tuple(sorted(after_decl.parsed.extras)) == tuple(sorted(parsed.extras))
            and not after_decl.parsed.marker
            and not after_decl.parsed.is_direct_reference
        )
        if not same_shape:
            return MajorAttempt(
                resolve_result=add_result,
                discarded_reason="manifest changed beyond the version constraint",
            )

        sync_result = self.sync()
        combined = CommandResult(
            add_result.args + sync_result.args,
            sync_result.returncode,
            add_result.stdout + "\n" + sync_result.stdout,
            add_result.stderr + "\n" + sync_result.stderr,
        )
        if not combined.ok:
            return MajorAttempt(resolve_result=combined)

        after_version = self.locked_version(package)
        if _lands_on_new_prerelease(before_version, after_version):
            return MajorAttempt(
                resolve_result=combined,
                discarded_reason="attempted version is a pre-release",
            )

        return MajorAttempt(resolve_result=combined)

    def _selection_args(self) -> list[str]:
        """Which groups/extras `uv sync` should install.

        `uv-sync-args`, when given, always wins and replaces the default
        selection outright (parsed as shell arguments, e.g. `--extra cpu
        --group dev`) - `with-groups`/`without-groups`/`only-groups` then
        only ever filter which top-level packages get *iterated*
        (`list_top_level_packages()`), never what gets synced (documented
        in the README).

        Otherwise, with none of `with-groups`/`without-groups`/`only-groups`
        set either, the default is `--all-groups --all-extras` (unchanged
        from before issue #4) - unless the project declares
        `[tool.uv.conflicts]`, in which case `--all-groups --all-extras`
        would unconditionally select mutually exclusive extras/groups and
        uv would simply refuse to sync ("Extras `cpu` and `gpu` are
        incompatible with the declared conflicts"). There is no
        generically correct subset to pick automatically, so this falls
        back to no selection flags at all (uv's own default: the
        project's default dependency groups, no optional extras) and warns
        that `uv-sync-args` is how to select what actually gets installed.

        With one of `with-groups`/`without-groups`/`only-groups` set, the
        group portion of the selection switches to `uv_group_sync_args()`
        (see its own docstring: uv's own native default group set,
        adjusted by those inputs) instead of `--all-groups` - the extras
        portion (`--all-extras`, or nothing under `tool.uv.conflicts`) is
        unaffected either way, since extras are a separate axis this
        feature does not touch.
        """
        if self.uv_sync_args:
            return shlex.split(self.uv_sync_args)

        pyproject_path = self._pyproject_path()
        conflicts = pyproject_path.is_file() and has_uv_conflicts(pyproject_path)
        if conflicts and not self._conflicts_warned:
            print(
                "::warning::tool.uv.conflicts detected in "
                f"{pyproject_path}: some extras/groups are declared "
                "mutually exclusive, so `uv sync --all-extras` would fail. "
                "Falling back to `uv sync` with no extras selected (group "
                "selection unaffected). Set the uv-sync-args input to "
                "select what to install, e.g. '--extra cpu --group dev'."
            )
            self._conflicts_warned = True
        extras_args = [] if conflicts else ["--all-extras"]

        group_args = uv_group_sync_args(self.with_groups, self.without_groups, self.only_groups)
        if group_args is None:
            if conflicts:
                # Matches the pre-issue-#4 conflict fallback exactly: no
                # selection flags at all (uv's own default group set, no
                # extras), not just no extras.
                return []
            group_args = ["--all-groups"]
        elif MAIN_GROUP in self.without_groups and not self._without_main_warned:
            print(
                "::warning::without-groups includes 'main', but uv has no "
                "flag to exclude the project's own [project.dependencies] "
                "from `uv sync` while still installing other groups - main "
                "is still installed. This only affects `uv sync`; the "
                "top-level packages iterated by this run correctly exclude "
                "'main' either way."
            )
            self._without_main_warned = True

        return group_args + extras_args

    def _sync_args(self) -> list[str]:
        return [
            "uv",
            "sync",
            "--locked",
            *self._selection_args(),
            "--python",
            self.python_version,
        ]

    def install(self) -> CommandResult:
        """`--locked` (used by `sync()`) makes uv fail loudly instead of
        silently rewriting uv.lock if it is out of date, so install never
        changes the lock."""
        return self.sync()

    def list_top_level_packages(self) -> list[str]:
        pyproject_path = self._pyproject_path()
        if not pyproject_path.is_file():
            raise ActionError(f"{pyproject_path} not found; nothing to update")
        return list_top_level_dependency_names(
            pyproject_path,
            with_groups=self.with_groups,
            without_groups=self.without_groups,
            only_groups=self.only_groups,
        )

    def update_package(self, package: str) -> CommandResult:
        lock_result = self.runner.run(
            ["uv", "lock", "--upgrade-package", package, "--python", self.python_version],
            cwd=self.directory,
        )
        if not lock_result.ok:
            return lock_result
        return self.sync()

    def update_all(self, packages: list[str]) -> CommandResult:
        # Verified against real uv==0.12.14: repeating `--upgrade-package`
        # once per name and re-locking once is the safest one-call
        # equivalent of updating a list of top-level packages - it only
        # touches the packages named (any other top-level/transitive
        # package moves only if the resolver needs it to satisfy those
        # upgrades), and a name that is not a dependency of the project is
        # silently accepted as a no-op rather than failing the whole lock
        # (unlike Poetry's `update` - see `PoetryBackend.update_all`).
        # `update_all` is only ever called with names this backend's own
        # `list_top_level_packages()` just returned, so that tolerance is
        # never actually relied on here.
        args = ["uv", "lock"]
        for package in packages:
            args += ["--upgrade-package", package]
        args += ["--python", self.python_version]
        lock_result = self.runner.run(args, cwd=self.directory)
        if not lock_result.ok:
            return lock_result
        return self.sync()

    def sync(self) -> CommandResult:
        return self.runner.run(self._sync_args(), cwd=self.directory)

    def update_transitive(self) -> CommandResult:
        # Deliberately no --upgrade-package/--upgrade-group restriction and
        # no group-selection args here (see PoetryBackend.update_transitive's
        # comment - the same reasoning applies): this refreshes the whole
        # lock file within its existing constraints, same scope as a plain
        # `uv lock --upgrade` would cover. sync() below is what applies
        # with-groups/without-groups/only-groups, same as every other
        # install/sync.
        lock_result = self.runner.run(
            ["uv", "lock", "--upgrade", "--python", self.python_version], cwd=self.directory
        )
        if not lock_result.ok:
            return lock_result
        return self.sync()

    def locked_version(self, package: str) -> str | None:
        return _locked_version(self.lock_file_path(), package)

    def all_locked_versions(self) -> dict[str, str]:
        return _all_locked_versions(self.lock_file_path())


def make_backend(package_manager: str, runner: CommandRunner, cfg: Config) -> Backend:
    with_groups = parse_labels(cfg.with_groups)
    without_groups = parse_labels(cfg.without_groups)
    only_groups = parse_labels(cfg.only_groups)
    if package_manager == "poetry":
        return PoetryBackend(
            runner,
            cfg.directory,
            cfg.poetry_version,
            with_groups=with_groups,
            without_groups=without_groups,
            only_groups=only_groups,
        )
    if package_manager == "uv":
        return UvBackend(
            runner,
            cfg.directory,
            cfg.python_version,
            cfg.uv_sync_args,
            with_groups=with_groups,
            without_groups=without_groups,
            only_groups=only_groups,
        )
    raise ActionError(f"unknown package manager '{package_manager}'")
