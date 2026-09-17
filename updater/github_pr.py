from __future__ import annotations

import json

from .errors import ActionError
from .runner import CommandRunner


class GithubPR:
    """Wraps the `gh` CLI. Relies on GH_TOKEN being present in the
    environment (set by the composite action step), so no token is passed on
    the command line."""

    def __init__(self, runner: CommandRunner, directory: str):
        self.runner = runner
        self.directory = directory

    def find_open(self, head_branch: str) -> int | None:
        result = self.runner.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                head_branch,
                "--state",
                "open",
                "--json",
                "number",
            ],
            cwd=self.directory,
        )
        if not result.ok:
            raise ActionError(f"gh pr list failed: {result.stderr}")
        data = json.loads(result.stdout or "[]")
        if not data:
            return None
        return data[0]["number"]

    def create(self, title: str, body: str, base: str, head: str, labels: list[str]):
        args = [
            "gh",
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--base",
            base,
            "--head",
            head,
        ]
        for label in labels:
            args += ["--label", label]
        return self.runner.run(args, cwd=self.directory)

    def edit(self, number: int, title: str, body: str, labels: list[str] | None = None):
        args = ["gh", "pr", "edit", str(number), "--title", title, "--body", body]
        for label in labels or []:
            args += ["--add-label", label]
        return self.runner.run(args, cwd=self.directory)


def create_or_edit(gh: "GithubPR", branch: str, title: str, body: str, base: str, labels: list[str]):
    """Update the existing open PR for `branch` if there is one, else create
    a new one. Kept as a standalone function so the decision is unit
    testable without going through the full `run()` orchestration."""
    existing = gh.find_open(branch)
    if existing is not None:
        return existing, gh.edit(existing, title, body, labels)
    return None, gh.create(title, body, base=base, head=branch, labels=labels)
