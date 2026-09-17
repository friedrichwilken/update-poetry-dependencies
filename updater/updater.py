from __future__ import annotations

from dataclasses import dataclass, field

from .backend import Backend
from .errors import ActionError
from .git_repo import GitRepo
from .runner import CommandRunner


@dataclass
class UpdateResult:
    passed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def _reset_and_resync(backend: Backend, git: GitRepo, files: list[str], package: str) -> None:
    """Discard the lock file change for `package` and re-sync the
    environment to it. If the re-sync itself fails, the environment is left
    in an unknown state and it is not safe to keep testing later packages
    against it, so this aborts the whole run (packages already committed
    stay committed)."""
    git.reset_files(files)
    sync_result = backend.sync()
    print(sync_result.stdout)
    print(sync_result.stderr)
    if not sync_result.ok:
        raise ActionError(
            f"failed to re-sync the environment to the lock file after "
            f"{package}; aborting to avoid testing later packages against a "
            f"broken environment"
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
    - failed if `poetry update` itself fails, or if it changes the lock file
      but the test command fails; either way the lock file is reset to HEAD
      and the environment is re-synced before moving on to the next package
    - passed if the lock file changed and the test command succeeded (or no
      test command was given); the lock file is committed
    """
    result = UpdateResult()
    files = backend.files_to_stage()

    for package in packages:
        print(f"::group::updating {package}")
        update_result = backend.update_package(package)
        print(update_result.stdout)
        print(update_result.stderr)

        if not update_result.ok:
            print(f"poetry update failed for {package}, discarding changes")
            result.failed.append(package)
            _reset_and_resync(backend, git, files, package)
            print("::endgroup::")
            continue

        if not git.diff_changed(files):
            print(f"no update available for {package}")
            result.skipped.append(package)
            print("::endgroup::")
            continue

        if test_command:
            print(f"running test command for {package}: {test_command}")
            test_result = runner.run_shell(test_command, cwd=directory)
            print(test_result.stdout)
            print(test_result.stderr)
            test_passed = test_result.ok
        else:
            test_passed = True

        if test_passed:
            print(f"update for {package} passed")
            git.stage(files)
            git.commit(f"Update and successfully test {package}")
            result.passed.append(package)
        else:
            print(f"test failed for {package}, discarding changes")
            result.failed.append(package)
            _reset_and_resync(backend, git, files, package)

        print("::endgroup::")

    return result
