from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .backend import Backend
from .errors import UpdateAborted
from .git_repo import GitRepo
from .runner import CommandRunner
from .textcap import capture_tail

# Kept as small string literals rather than a full enum class on purpose:
# issue #21 ("try major bump, fall back to in-constraint update") wants to
# add a further outcome ("major held back") without changing this shape,
# and a Literal is trivially extended by adding another string to the
# union at the call site.
Status = Literal["updated", "failed", "skipped"]
FailureKind = Literal["resolution", "test"] | None


@dataclass
class PackageOutcome:
    """One top-level package's result for a single run.

    `old_version`/`new_version` are read straight from the lock file
    (`Backend.locked_version`), not the installed environment. For a
    failed package, `new_version` is the version that was attempted (read
    right after the update, before the reset). `output_tail` is only ever
    populated for a failed package - the tail of whichever output is
    relevant to `failure_kind` (resolver output for "resolution", test
    command output for "test")."""

    name: str
    status: Status
    old_version: str | None = None
    new_version: str | None = None
    failure_kind: FailureKind = None
    output_tail: str = ""


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


def run_updates(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    packages: list[str],
    test_command: str,
    directory: str,
) -> UpdateResult:
    """Update each top-level package one by one. A package is:

    - skipped if `poetry update` succeeds but the lock file does not change
    - failed if `poetry update` itself fails (failure_kind "resolution"), or
      if it changes the lock file but the test command fails (failure_kind
      "test"); either way the lock file is reset to HEAD and the
      environment is re-synced before moving on to the next package
    - passed if the lock file changed and the test command succeeded (or no
      test command was given); the lock file is committed
    """
    result = UpdateResult()
    files = backend.files_to_stage()

    for package in packages:
        print(f"::group::updating {package}")
        old_version = backend.locked_version(package)
        update_result = backend.update_package(package)
        print(update_result.stdout)
        print(update_result.stderr)

        if not update_result.ok:
            print(f"update failed for {package}, discarding changes")
            attempted_version = backend.locked_version(package)
            result.outcomes.append(
                PackageOutcome(
                    name=package,
                    status="failed",
                    old_version=old_version,
                    new_version=attempted_version,
                    failure_kind="resolution",
                    output_tail=capture_tail(update_result.stdout + "\n" + update_result.stderr),
                )
            )
            _reset_and_resync(backend, git, files, package, result)
            print("::endgroup::")
            continue

        if not git.diff_changed(files):
            print(f"no update available for {package}")
            result.outcomes.append(
                PackageOutcome(
                    name=package,
                    status="skipped",
                    old_version=old_version,
                    new_version=old_version,
                )
            )
            print("::endgroup::")
            continue

        new_version = backend.locked_version(package)

        if test_command:
            print(f"running test command for {package}: {test_command}")
            test_result = runner.run_shell(test_command, cwd=directory)
            test_passed = test_result.ok
        else:
            test_result = None
            test_passed = True

        if test_passed:
            print(f"update for {package} passed")
            git.stage(files)
            git.commit(
                f"Update {package} {_fmt_version(old_version)} -> {_fmt_version(new_version)}"
            )
            result.outcomes.append(
                PackageOutcome(
                    name=package,
                    status="updated",
                    old_version=old_version,
                    new_version=new_version,
                )
            )
        else:
            print(f"test failed for {package}, discarding changes")
            result.outcomes.append(
                PackageOutcome(
                    name=package,
                    status="failed",
                    old_version=old_version,
                    new_version=new_version,
                    failure_kind="test",
                    output_tail=capture_tail(test_result.stdout + "\n" + test_result.stderr),
                )
            )
            _reset_and_resync(backend, git, files, package, result)

        print("::endgroup::")

    return result
