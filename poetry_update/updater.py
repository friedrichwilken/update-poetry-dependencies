from __future__ import annotations

from dataclasses import dataclass, field

from .backend import PoetryBackend
from .git_repo import GitRepo
from .runner import CommandRunner


@dataclass
class UpdateResult:
    passed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def run_updates(
    backend: PoetryBackend,
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
            git.reset_files(files)
            backend.sync()
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
            git.reset_files(files)
            backend.sync()

        print("::endgroup::")

    return result
