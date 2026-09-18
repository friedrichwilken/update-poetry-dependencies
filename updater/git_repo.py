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
        result = self.runner.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.directory)
        return result.stdout.strip()

    def head_sha(self) -> str:
        result = self.runner.run(["git", "rev-parse", "HEAD"], cwd=self.directory)
        return result.stdout.strip()

    def diff_changed(self, paths: list[str]) -> bool:
        """True if any of `paths` differ from what is committed."""
        result = self.runner.run(["git", "diff", "--quiet", "--"] + paths, cwd=self.directory)
        return result.returncode != 0

    def has_uncommitted_changes(self, paths: list[str]) -> bool:
        """True if any of `paths` differ from HEAD in either the working
        tree or the index (staged or unstaged) - unlike `diff_changed`
        (working tree vs. index only), this also catches changes that are
        already staged but not committed. Used to fail fast before this
        action's own update loop would otherwise either destroy a caller's
        uncommitted edit to the manifest/lock file (`reset_files` discards
        it) or silently sweep it into one of this run's own commits."""
        result = self.runner.run(["git", "status", "--porcelain", "--"] + paths, cwd=self.directory)
        return bool(result.stdout.strip())

    def reset_files(self, paths: list[str]) -> None:
        """Discard uncommitted changes to `paths` only (tracked files, never
        touches anything untracked such as a .venv)."""
        self.runner.run(["git", "checkout", "--", *paths], cwd=self.directory)

    def reset_hard(self, sha: str) -> CommandResult:
        """Discard commits made since `sha` (and any uncommitted changes)
        by hard-resetting to it. Only used by the batch-first strategy
        (see `updater._discard_commits_since`) to undo its own
        not-yet-pushed sequential replay commits when they turn out not to
        be trustworthy - never touches anything that was already pushed."""
        return self.runner.run(["git", "reset", "--hard", sha], cwd=self.directory)

    def stage(self, paths: list[str]) -> None:
        self.runner.run(["git", "add", "--", *paths], cwd=self.directory)

    def commit(self, message: str) -> CommandResult:
        return self.runner.run(["git", "commit", "-m", message], cwd=self.directory)

    def checkout_new_branch(self, branch: str) -> CommandResult:
        return self.runner.run(["git", "checkout", "-B", branch], cwd=self.directory)

    def push(self, branch: str) -> CommandResult:
        return self.runner.run(["git", "push", "--force", "origin", branch], cwd=self.directory)
