from __future__ import annotations

import json
import re

from .errors import ActionError
from .runner import CommandRunner

_PR_URL_RE = re.compile(r"/pull/(\d+)")


def parse_created_pr_number(stdout: str) -> int | None:
    """`gh pr create` prints the new PR's URL on success, normally as its
    only stdout line - but this scans the whole output for a `/pull/<n>`
    URL rather than assuming that, so a stray leading line (a warning, a
    notice) before the URL still parses, and it works unchanged against a
    GitHub Enterprise Server host, whose URL has a different domain but
    the same `/pull/<n>` path. `None` if no such URL is found anywhere in
    `stdout`. Used by `run()` to learn the PR number for a newly created PR
    without an extra `gh` call (an edited PR's number is already known -
    it is whatever `find_open` returned)."""
    match = _PR_URL_RE.search(stdout)
    return int(match.group(1)) if match else None


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


def create_or_edit(gh: GithubPR, branch: str, title: str, body: str, base: str, labels: list[str]):
    """Update the existing open PR for `branch` if there is one, else create
    a new one. Kept as a standalone function so the decision is unit
    testable without going through the full `run()` orchestration."""
    existing = gh.find_open(branch)
    if existing is not None:
        return existing, gh.edit(existing, title, body, labels)
    return None, gh.create(title, body, base=base, head=branch, labels=labels)
