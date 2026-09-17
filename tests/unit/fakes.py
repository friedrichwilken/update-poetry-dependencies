"""Small duck-typed fakes used across the unit tests. They implement the
same method surface as the real backend/git/gh classes without touching a
shell, filesystem or network, so tests can assert what the orchestration
code decided to do."""

from __future__ import annotations

from poetry_update.runner import CommandResult


def result(ok: bool = True, stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult([], 0 if ok else 1, stdout, stderr)


class FakeBackend:
    def __init__(self, update_ok: dict | None = None, lock_exists: bool = True):
        self.update_ok = update_ok or {}
        self._lock_exists = lock_exists
        self.updated_packages: list[str] = []
        self.sync_calls = 0
        self.install_calls = 0

    def lock_exists(self) -> bool:
        return self._lock_exists

    def lock_file_path(self):
        return "poetry.lock"

    def files_to_stage(self) -> list[str]:
        return ["poetry.lock"]

    def install(self) -> CommandResult:
        self.install_calls += 1
        return result(True)

    def list_top_level_packages(self) -> list[str]:
        return list(self.update_ok.keys())

    def update_package(self, package: str) -> CommandResult:
        self.updated_packages.append(package)
        return result(self.update_ok.get(package, True))

    def sync(self) -> CommandResult:
        self.sync_calls += 1
        return result(True)


class FakeGit:
    def __init__(self, diff_results: list | None = None, head_shas: list | None = None):
        self._diff_results = list(diff_results or [])
        self._head_shas = list(head_shas or ["sha0"])
        self.reset_calls: list[list[str]] = []
        self.staged_calls: list[list[str]] = []
        self.commit_messages: list[str] = []
        self.checkout_branches: list[str] = []
        self.push_branches: list[str] = []
        self.configured = False

    def configure_user(self, name: str, email: str) -> None:
        self.configured = True

    def current_branch(self) -> str:
        return "main"

    def head_sha(self) -> str:
        if len(self._head_shas) > 1:
            return self._head_shas.pop(0)
        return self._head_shas[0]

    def diff_changed(self, paths: list[str]) -> bool:
        return self._diff_results.pop(0)

    def reset_files(self, paths: list[str]) -> None:
        self.reset_calls.append(list(paths))

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


class FakeRunner:
    """Only used where run_updates needs to execute the test command."""

    def __init__(self, shell_results: list | None = None):
        self._shell_results = list(shell_results or [])
        self.shell_calls: list[tuple] = []

    def run_shell(self, command: str, cwd=None) -> CommandResult:
        self.shell_calls.append((command, cwd))
        if self._shell_results:
            return self._shell_results.pop(0)
        return result(True)


class FakeGithubPR:
    def __init__(self, open_pr_number: int | None = None):
        self.open_pr_number = open_pr_number
        self.create_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    def find_open(self, head_branch: str):
        return self.open_pr_number

    def create(self, title, body, base, head, labels):
        self.create_calls.append(
            {"title": title, "body": body, "base": base, "head": head, "labels": labels}
        )
        return result(True)

    def edit(self, number, title, body):
        self.edit_calls.append({"number": number, "title": title, "body": body})
        return result(True)
