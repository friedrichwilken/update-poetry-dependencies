"""Small duck-typed fakes used across the unit tests. They implement the
same method surface as the real backend/git/gh classes without touching a
shell, filesystem or network, so tests can assert what the orchestration
code decided to do."""

from __future__ import annotations

import sys

from updater.runner import CommandResult


def result(ok: bool = True, stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult([], 0 if ok else 1, stdout, stderr)


class FakeBackend:
    """Duck-typed stand-in for any `Backend` (Poetry or uv). The lock file
    name defaults to poetry.lock but is overridable so tests can prove the
    update loop in `updater.py` never special-cases either backend."""

    def __init__(
        self,
        update_ok: dict | None = None,
        lock_exists: bool = True,
        sync_ok: bool = True,
        lock_file: str = "poetry.lock",
        versions: dict | None = None,
        major_attempts: dict | None = None,
        manifest_file: str = "pyproject.toml",
        update_all_ok: bool | None = None,
        lock_snapshots: list | None = None,
    ):
        self.update_ok = update_ok or {}
        self._lock_exists = lock_exists
        self._sync_ok = sync_ok
        self.lock_file = lock_file
        self.manifest_file = manifest_file
        self.updated_packages: list[str] = []
        self.sync_calls = 0
        self.install_calls = 0
        # versions[package] is a list of versions returned by successive
        # locked_version(package) calls (typically [old, new/attempted]);
        # once exhausted the last value keeps being returned. Defaults to
        # a fixed version so tests that do not care about version numbers
        # do not need to supply any.
        self._versions = {k: list(v) for k, v in (versions or {}).items()}
        self.locked_version_calls: list[str] = []
        # major_attempts[package] is a `MajorAttempt | None` (or a
        # zero-arg callable returning one, for a test that wants to
        # observe state at call time) returned by try_major(package).
        # Packages not present in the map get None (no attempt needed) -
        # this also means a test that never enables allow_major never
        # needs to populate this at all.
        self._major_attempts = major_attempts or {}
        self.try_major_calls: list[str] = []
        self.major_files_to_stage_calls = 0
        # update_all_ok controls update_all()'s result independently of
        # update_ok (which drives the per-package update_package() path):
        # None (default) derives it from update_ok - ok unless any package
        # passed to update_all() is itself mapped to a failing
        # update_ok - so a batch-first test that never cares about a
        # resolution failure does not need to set this explicitly.
        self._update_all_ok = update_all_ok
        self.update_all_calls: list[list[str]] = []
        # lock_snapshots is a list of dicts returned by successive
        # all_locked_versions() calls (batch-first's replay-vs-batch lock
        # comparison); once exhausted the last value keeps being returned.
        # Defaults to a single {} so two calls compare equal (no
        # divergence) unless a test deliberately sets differing snapshots.
        self._lock_snapshots = list(lock_snapshots) if lock_snapshots is not None else [{}]
        self.all_locked_versions_calls = 0

    def lock_exists(self) -> bool:
        return self._lock_exists

    def lock_file_path(self):
        return self.lock_file

    def files_to_stage(self) -> list[str]:
        return [self.lock_file]

    def major_files_to_stage(self) -> list[str]:
        self.major_files_to_stage_calls += 1
        return [self.manifest_file, self.lock_file]

    def try_major(self, package: str):
        self.try_major_calls.append(package)
        attempt = self._major_attempts.get(package)
        return attempt() if callable(attempt) else attempt

    def install(self) -> CommandResult:
        self.install_calls += 1
        return result(True)

    def list_top_level_packages(self) -> list[str]:
        return list(self.update_ok.keys())

    def update_package(self, package: str) -> CommandResult:
        self.updated_packages.append(package)
        return result(self.update_ok.get(package, True))

    def update_all(self, packages: list[str]) -> CommandResult:
        self.update_all_calls.append(list(packages))
        if self._update_all_ok is not None:
            ok = self._update_all_ok
        else:
            ok = all(self.update_ok.get(p, True) for p in packages)
        return result(ok, stderr="" if ok else "batch update failed")

    def sync(self) -> CommandResult:
        self.sync_calls += 1
        return result(self._sync_ok)

    def locked_version(self, package: str) -> str | None:
        self.locked_version_calls.append(package)
        seq = self._versions.get(package)
        if not seq:
            return "1.0.0"
        if len(seq) > 1:
            return seq.pop(0)
        return seq[0]

    def all_locked_versions(self) -> dict:
        self.all_locked_versions_calls += 1
        if len(self._lock_snapshots) > 1:
            return self._lock_snapshots.pop(0)
        return self._lock_snapshots[0]


class FakeGit:
    def __init__(
        self,
        diff_results: list | None = None,
        head_shas: list | None = None,
        current_branch: str = "main",
        uncommitted: bool = False,
    ):
        self._diff_results = list(diff_results or [])
        self._head_shas = list(head_shas or ["sha0"])
        self._current_branch = current_branch
        self._uncommitted = uncommitted
        self.reset_calls: list[list[str]] = []
        self.hard_reset_calls: list[str] = []
        self.staged_calls: list[list[str]] = []
        self.commit_messages: list[str] = []
        self.checkout_branches: list[str] = []
        self.push_branches: list[str] = []
        self.configured = False
        self.has_uncommitted_changes_calls: list[list[str]] = []

    def configure_user(self, name: str, email: str) -> None:
        self.configured = True

    def current_branch(self) -> str:
        return self._current_branch

    def head_sha(self) -> str:
        if len(self._head_shas) > 1:
            return self._head_shas.pop(0)
        return self._head_shas[0]

    def diff_changed(self, paths: list[str]) -> bool:
        return self._diff_results.pop(0)

    def has_uncommitted_changes(self, paths: list[str]) -> bool:
        self.has_uncommitted_changes_calls.append(list(paths))
        return self._uncommitted

    def reset_files(self, paths: list[str]) -> None:
        self.reset_calls.append(list(paths))

    def reset_hard(self, sha: str) -> CommandResult:
        self.hard_reset_calls.append(sha)
        return result(True)

    def stage(self, paths: list[str]) -> None:
        self.staged_calls.append(list(paths))

    def commit(self, message: str) -> CommandResult:
        self.commit_messages.append(message)
        return result(True)

    def checkout_new_branch(self, branch: str) -> CommandResult:
        self.checkout_branches.append(branch)
        return result(True)

    def push(self, branch: str) -> CommandResult:
        self.push_branches.append(branch)
        return result(True)


class FakeCommandRunner:
    """General purpose fake for `CommandRunner.run()`, used wherever a test
    exercises something other than the update loop's shell test-command
    (bootstrap, a backend's own commands). Results are consumed in call
    order; once exhausted, a successful empty result is returned."""

    def __init__(self, results: list | None = None):
        self._results = list(results or [])
        self.calls: list[dict] = []

    def run(self, args: list, cwd=None) -> CommandResult:
        self.calls.append({"args": list(args), "cwd": cwd})
        if self._results:
            return self._results.pop(0)
        return result(True)


class FakeRunner:
    """Only used where run_updates needs to execute the test command.

    Mirrors `CommandRunner.run_shell`'s contract of printing its captured
    stdout/stderr as it "streams" them (here: all at once, since there is
    no real subprocess) in addition to returning them on the
    `CommandResult`, so callers cannot tell the two apart from the outside."""

    def __init__(self, shell_results: list | None = None):
        self._shell_results = list(shell_results or [])
        self.shell_calls: list[tuple] = []

    def run_shell(self, command: str, cwd=None) -> CommandResult:
        self.shell_calls.append((command, cwd))
        res = self._shell_results.pop(0) if self._shell_results else result(True)
        if res.stdout:
            print(res.stdout, end="")
        if res.stderr:
            print(res.stderr, end="", file=sys.stderr)
        return res


class FakeGithubPR:
    def __init__(
        self,
        open_pr_number: int | None = None,
        created_pr_url: str = "https://github.com/owner/repo/pull/123",
    ):
        self.open_pr_number = open_pr_number
        self.created_pr_url = created_pr_url
        self.create_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    def find_open(self, head_branch: str):
        return self.open_pr_number

    def create(self, title, body, base, head, labels):
        self.create_calls.append(
            {"title": title, "body": body, "base": base, "head": head, "labels": labels}
        )
        # Mirrors the real `gh pr create`, which prints the new PR's URL as
        # its only stdout line on success (see github_pr.parse_created_pr_number).
        return result(True, stdout=self.created_pr_url)

    def edit(self, number, title, body, labels=None):
        self.edit_calls.append(
            {"number": number, "title": title, "body": body, "labels": labels or []}
        )
        return result(True)


class FakeGithubIssues:
    """Duck-typed stand-in for `GithubIssues`. `open_managed` is whatever
    `list_open_managed()` should return - a list of `ManagedIssue`
    instances the test constructs directly. `fail_numbers` makes
    edit/comment/close return a failing result for that issue number (used
    to test execute_issue_actions' per-action isolation); `fail_create`
    does the same for every create, and `fail_create_for` for just the
    creates whose title starts with one of the given (unnormalized)
    package names (there is no issue number yet to key off of for a
    "create" - see render_issue_title for the "<package>: ..." shape)."""

    def __init__(
        self,
        open_managed: list | None = None,
        created_issue_number: int = 501,
        fail_numbers: set | None = None,
        fail_create: bool = False,
        fail_create_for: set | None = None,
    ):
        self._open_managed = list(open_managed or [])
        self.created_issue_number = created_issue_number
        self._fail_numbers = set(fail_numbers or [])
        self._fail_create = fail_create
        self._fail_create_for = set(fail_create_for or [])
        self.list_calls = 0
        self.create_calls: list[dict] = []
        self.edit_calls: list[dict] = []
        self.comment_calls: list[dict] = []
        self.close_calls: list[dict] = []

    def list_open_managed(self, limit: int = 200):
        self.list_calls += 1
        return list(self._open_managed)

    def create(self, title, body, labels):
        self.create_calls.append({"title": title, "body": body, "labels": labels})
        package = title.split(":", 1)[0]
        if self._fail_create or package in self._fail_create_for:
            return result(False, stderr="fake create failure")
        url = f"https://github.com/owner/repo/issues/{self.created_issue_number}"
        return result(True, stdout=url)

    def edit(self, number, body):
        self.edit_calls.append({"number": number, "body": body})
        if number in self._fail_numbers:
            return result(False, stderr="fake edit failure")
        return result(True)

    def comment(self, number, body):
        self.comment_calls.append({"number": number, "body": body})
        if number in self._fail_numbers:
            return result(False, stderr="fake comment failure")
        return result(True)

    def close(self, number, comment):
        self.close_calls.append({"number": number, "comment": comment})
        if number in self._fail_numbers:
            return result(False, stderr="fake close failure")
        return result(True)
