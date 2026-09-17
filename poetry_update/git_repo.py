from __future__ import annotations

from .runner import CommandResult, CommandRunner


class GitRepo:
    """Thin wrapper around the git commands the action needs, all scoped to
    `directory` (or the repository root for branch/push operations that git
    resolves relative to .git regardless of cwd)."""

    def __init__(self, runner: CommandRunner, directory: str):
        self.runner = runner
        self.directory = directory

    def configure_user(self, name: str, email: str) -> None:
        self.runner.run(["git", "config", "user.name", name], cwd=self.directory)
        self.runner.run(["git", "config", "user.email", email], cwd=self.directory)

    def current_branch(self) -> str:
        result = self.runner.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.directory
        )
        return result.stdout.strip()

    def head_sha(self) -> str:
        result = self.runner.run(["git", "rev-parse", "HEAD"], cwd=self.directory)
        return result.stdout.strip()

    def diff_changed(self, paths: list[str]) -> bool:
        """True if any of `paths` differ from what is committed."""
        result = self.runner.run(
            ["git", "diff", "--quiet", "--"] + paths, cwd=self.directory
        )
        return result.returncode != 0

    def reset_files(self, paths: list[str]) -> None:
        """Discard uncommitted changes to `paths` only (tracked files, never
        touches anything untracked such as a .venv)."""
        self.runner.run(["git", "checkout", "--", *paths], cwd=self.directory)

    def stage(self, paths: list[str]) -> None:
        self.runner.run(["git", "add", "--", *paths], cwd=self.directory)

    def commit(self, message: str) -> CommandResult:
        return self.runner.run(["git", "commit", "-m", message], cwd=self.directory)

    def checkout_new_branch(self, branch: str) -> CommandResult:
        return self.runner.run(["git", "checkout", "-B", branch], cwd=self.directory)

    def push(self, branch: str) -> CommandResult:
        return self.runner.run(
            ["git", "push", "--force", "origin", branch], cwd=self.directory
        )
