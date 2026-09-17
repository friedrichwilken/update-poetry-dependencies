from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .backend import Backend
from .errors import UpdateAborted
from .git_repo import GitRepo
from .runner import CommandRunner
from .textcap import capture_tail

# Kept as small string literals rather than a full enum class on purpose:
# a Literal is trivially extended by adding another string to the union at
# the call site.
Status = Literal["updated", "failed", "skipped"]
FailureKind = Literal["resolution", "test"] | None
Bump = Literal["major"] | None


@dataclass
class PackageOutcome:
    """One top-level package's result for a single run.

    `old_version`/`new_version` are read straight from the lock file
    (`Backend.locked_version`), not the installed environment. For a
    failed package, `new_version` is the version that was attempted (read
    right after the update, before the reset). `output_tail` is only ever
    populated for a failed package - the tail of whichever output is
    relevant to `failure_kind` (resolver output for "resolution", test
    command output for "test").

    The `bump`/`major_*` fields are additive, only ever set when
    `allow-major` is enabled (issue #21), and otherwise stay at their
    default (falsy) values - `report.py` relies on that to keep
    `report-json`'s shape byte-identical to before the feature existed
    when it is not in use:

    - `bump` is `"major"` when this outcome's own update *is* a major
      bump (`status` is "updated", `new_version` is the major release).
    - `major_attempted_version`/`major_failure_kind`/`major_output_tail`
      are set when a major bump was attempted but held back (resolution
      or test failure), regardless of what `status` ended up being for
      the (possibly still successful) in-range update alongside it.
    - `major_skip_reason` is set when `allow-major` is enabled but no
      major attempt could be made at all, for a package whose declared
      constraint has an upper bound but whose declaration shape is not
      one this feature can safely rewrite (git/path/url source, an
      environment marker, an exact pin, ...).
    """

    name: str
    status: Status
    old_version: str | None = None
    new_version: str | None = None
    failure_kind: FailureKind = None
    output_tail: str = ""
    bump: Bump = None
    major_attempted_version: str | None = None
    major_failure_kind: FailureKind = None
    major_output_tail: str = ""
    major_skip_reason: str | None = None

    @property
    def held_back_major(self) -> bool:
        return self.major_attempted_version is not None or self.major_failure_kind is not None


@dataclass
class UpdateResult:
    outcomes: list[PackageOutcome] = field(default_factory=list)

    # Convenient accessors kept for byte-compatibility with the existing
    # `passed-packages`/`failed-packages`/`skipped-packages` outputs, which
    # are just comma separated package names.
    @property
    def passed(self) -> list[str]:
        return [o.name for o in self.outcomes if o.status == "updated"]

    @property
    def failed(self) -> list[str]:
        return [o.name for o in self.outcomes if o.status == "failed"]

    @property
    def skipped(self) -> list[str]:
        return [o.name for o in self.outcomes if o.status == "skipped"]

    @property
    def held_back(self) -> list[str]:
        return [o.name for o in self.outcomes if o.held_back_major]


def _fmt_version(version: str | None) -> str:
    return version if version else "unknown"


def _reset_and_resync(
    backend: Backend, git: GitRepo, files: list[str], package: str, result: UpdateResult
) -> None:
    """Discard the lock file change for `package` and re-sync the
    environment to it. If the re-sync itself fails, the environment is left
    in an unknown state and it is not safe to keep testing later packages
    against it, so this aborts the whole run (packages already committed
    stay committed) - raising `UpdateAborted` rather than a bare
    `ActionError` so the partial `result` built so far is not lost."""
    git.reset_files(files)
    sync_result = backend.sync()
    print(sync_result.stdout)
    print(sync_result.stderr)
    if not sync_result.ok:
        raise UpdateAborted(
            f"failed to re-sync the environment to the lock file after "
            f"{package}; aborting to avoid testing later packages against a "
            f"broken environment",
            result,
        )


def _run_test_command(
    runner: CommandRunner, test_command: str, directory: str, package: str
) -> tuple[object, bool]:
    if not test_command:
        return None, True
    print(f"running test command for {package}: {test_command}")
    test_result = runner.run_shell(test_command, cwd=directory)
    return test_result, test_result.ok


def _in_range_update(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    package: str,
    test_command: str,
    directory: str,
    old_version: str | None,
    files: list[str],
) -> tuple[PackageOutcome, bool]:
    """The plain, in-constraint update for one package - today's whole
    behaviour, unchanged. Returns the outcome and whether the caller still
    needs to reset+resync `files` afterwards (true for either failure
    kind, false for "updated"/"skipped")."""
    update_result = backend.update_package(package)
    print(update_result.stdout)
    print(update_result.stderr)

    if not update_result.ok:
        print(f"update failed for {package}, discarding changes")
        attempted_version = backend.locked_version(package)
        outcome = PackageOutcome(
            name=package,
            status="failed",
            old_version=old_version,
            new_version=attempted_version,
            failure_kind="resolution",
            output_tail=capture_tail(update_result.stdout + "\n" + update_result.stderr),
        )
        return outcome, True

    if not git.diff_changed(files):
        print(f"no update available for {package}")
        outcome = PackageOutcome(
            name=package, status="skipped", old_version=old_version, new_version=old_version
        )
        return outcome, False

    new_version = backend.locked_version(package)
    test_result, test_passed = _run_test_command(runner, test_command, directory, package)

    if test_passed:
        print(f"update for {package} passed")
        git.stage(files)
        git.commit(f"Update {package} {_fmt_version(old_version)} -> {_fmt_version(new_version)}")
        outcome = PackageOutcome(
            name=package, status="updated", old_version=old_version, new_version=new_version
        )
        return outcome, False

    print(f"test failed for {package}, discarding changes")
    outcome = PackageOutcome(
        name=package,
        status="failed",
        old_version=old_version,
        new_version=new_version,
        failure_kind="test",
        output_tail=capture_tail(test_result.stdout + "\n" + test_result.stderr),
    )
    return outcome, True


def _attempt_major(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    package: str,
    test_command: str,
    directory: str,
    old_version: str | None,
    result: UpdateResult,
) -> tuple[PackageOutcome | None, tuple[str | None, str, str] | None, str | None]:
    """Try to raise `package` to its latest release (issue #21). Returns a
    3-tuple:

    - a finished `PackageOutcome` if the major bump itself passed and was
      committed (the caller should record it and move on to the next
      package without an in-range update at all);
    - else, a `(attempted_version, failure_kind, output_tail)` "held back"
      tuple if an attempt was made but failed (resolution or test) - the
      manifest/lock have already been reset+resynced, and the caller
      should still run the plain in-range update and attach this to
      whatever outcome that produces;
    - else, a skip reason string if `allow-major` is enabled but no
      attempt could be made for this package at all (or None if none of
      the above apply - no major attempt was needed in the first place).
    """
    major = backend.try_major(package)
    if major is None:
        return None, None, None
    if major.skip_reason is not None:
        return None, None, major.skip_reason

    resolve_result = major.resolve_result
    print(resolve_result.stdout)
    print(resolve_result.stderr)
    major_files = backend.major_files_to_stage()

    if resolve_result.ok:
        attempted_version = backend.locked_version(package)
        test_result, test_passed = _run_test_command(runner, test_command, directory, package)
        if test_passed:
            print(f"major update for {package} passed")
            git.stage(major_files)
            git.commit(
                f"Update {package} {_fmt_version(old_version)} -> "
                f"{_fmt_version(attempted_version)} (major)"
            )
            outcome = PackageOutcome(
                name=package,
                status="updated",
                old_version=old_version,
                new_version=attempted_version,
                bump="major",
            )
            return outcome, None, None
        held_back = (
            attempted_version,
            "test",
            capture_tail(test_result.stdout + "\n" + test_result.stderr),
        )
    else:
        attempted_version = backend.locked_version(package)
        held_back = (
            attempted_version,
            "resolution",
            capture_tail(resolve_result.stdout + "\n" + resolve_result.stderr),
        )

    print(f"major update for {package} held back, falling back to the in-range update")
    _reset_and_resync(backend, git, major_files, package, result)
    return None, held_back, None


def run_updates(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    packages: list[str],
    test_command: str,
    directory: str,
    allow_major: bool = False,
) -> UpdateResult:
    """Update each top-level package one by one. A package is:

    - skipped if `poetry update` succeeds but the lock file does not change
    - failed if `poetry update` itself fails (failure_kind "resolution"), or
      if it changes the lock file but the test command fails (failure_kind
      "test"); either way the lock file is reset to HEAD and the
      environment is re-synced before moving on to the next package
    - passed if the lock file changed and the test command succeeded (or no
      test command was given); the lock file is committed

    When `allow_major` is true (issue #21), each package is first offered a
    major-bump attempt (`Backend.try_major`): raise its declared constraint
    so the latest release is allowed, re-lock just that package, and test
    it exactly like an in-range update. A passing attempt is committed on
    its own (tagged `bump="major"`) and the package is done - no separate
    in-range update runs for it. A failing attempt (resolution or test) is
    reset and reported as "held back" on whatever outcome the ordinary
    in-range update produces instead, which still runs normally. When
    `allow_major` is false, `pyproject.toml` is never read or touched by
    this loop at all.
    """
    result = UpdateResult()
    files = backend.files_to_stage()

    for package in packages:
        print(f"::group::updating {package}")
        old_version = backend.locked_version(package)

        held_back = None
        major_skip_reason = None
        if allow_major:
            major_outcome, held_back, major_skip_reason = _attempt_major(
                backend, git, runner, package, test_command, directory, old_version, result
            )
            if major_outcome is not None:
                result.outcomes.append(major_outcome)
                print("::endgroup::")
                continue

        outcome, needs_reset = _in_range_update(
            backend, git, runner, package, test_command, directory, old_version, files
        )
        if held_back is not None:
            (
                outcome.major_attempted_version,
                outcome.major_failure_kind,
                outcome.major_output_tail,
            ) = held_back
        if major_skip_reason is not None:
            outcome.major_skip_reason = major_skip_reason
        result.outcomes.append(outcome)
        if needs_reset:
            _reset_and_resync(backend, git, files, package, result)

        print("::endgroup::")

    return result
