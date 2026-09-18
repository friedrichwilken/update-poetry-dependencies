from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .errors import ActionError
from .versions import version_at_least

# The minimum *project* python-version accepted for each backend. Poetry's
# floor tracks poetry-core's own support window; uv supports much older
# interpreters, so a uv project should not be blocked on Poetry's minimum.
MIN_PROJECT_PYTHON_VERSION = {
    "poetry": "3.10",
    "uv": "3.9",
}
MIN_POETRY_VERSION = "1.2"

_TRUE_VALUES = {"true", "1", "yes"}


def parse_bool(value: str) -> bool:
    return value.strip().lower() in _TRUE_VALUES


def parse_labels(raw: str) -> list[str]:
    """Split a comma and/or newline separated label list, trim, drop empties."""
    if not raw:
        return []
    parts = re.split(r"[,\n]", raw)
    return [p.strip() for p in parts if p.strip()]


def check_versions(package_manager: str, python_version: str, poetry_version: str) -> None:
    # package_manager is expected to already be resolved to "poetry" or
    # "uv" by detect_package_manager() before this is called.
    minimum = MIN_PROJECT_PYTHON_VERSION[package_manager]
    if not version_at_least(python_version, minimum):
        raise ActionError(
            f"python-version {python_version} is below the minimum required "
            f"version {minimum} for the {package_manager} backend"
        )
    if package_manager == "poetry" and not version_at_least(poetry_version, MIN_POETRY_VERSION):
        raise ActionError(
            f"poetry-version {poetry_version} is below the minimum required "
            f"version {MIN_POETRY_VERSION}"
        )


def resolve_base_branch(explicit: str, current_branch: str, github_base_ref: str) -> str:
    """Decide which branch the update PR should target.

    `git rev-parse --abbrev-ref HEAD` returns the literal string "HEAD" on a
    detached checkout, which happens on pull_request/tag/explicit-SHA
    checkouts. Falling back to that would push a branch and then fail (or
    worse, succeed) with `--base HEAD`. Preference order: the explicit
    `base-branch` input, then the checked-out branch if it is not detached,
    then `GITHUB_BASE_REF` (set by Actions on pull_request events), else
    fail loudly so the caller sets `base-branch` explicitly.
    """
    if explicit:
        return explicit
    if current_branch and current_branch != "HEAD":
        return current_branch
    if github_base_ref:
        return github_base_ref
    raise ActionError(
        "could not determine the base branch: the checkout is in a detached "
        "HEAD state and GITHUB_BASE_REF is not set; pass the base-branch "
        "input explicitly"
    )


@dataclass
class Config:
    python_version: str
    package_manager: str
    poetry_version: str
    uv_sync_args: str
    directory: str
    pr_title_prefix: str
    pr_labels: str
    test_command: str
    branch_name: str
    base_branch: str
    github_base_ref: str
    dry_run: bool
    allow_major: bool
    create_issues: bool
    issue_labels: str
    actor: str
    server_url: str
    repository: str
    run_id: str
    github_output: str
    github_step_summary: str = ""

    @classmethod
    def from_env(cls, env: dict | None = None) -> Config:
        env = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            return env.get(name, default)

        return cls(
            python_version=get("PYTHON_VERSION"),
            package_manager=get("PACKAGE_MANAGER", "auto"),
            poetry_version=get("POETRY_VERSION"),
            uv_sync_args=get("UV_SYNC_ARGS"),
            directory=get("DIRECTORY", "./"),
            pr_title_prefix=get("PR_TITLE_PREFIX"),
            pr_labels=get("PR_LABELS"),
            test_command=get("TEST_COMMAND"),
            branch_name=get("BRANCH_NAME", "deps/test-gated-updates"),
            base_branch=get("BASE_BRANCH"),
            github_base_ref=get("GITHUB_BASE_REF", ""),
            dry_run=parse_bool(get("DRY_RUN", "false")),
            allow_major=parse_bool(get("ALLOW_MAJOR", "false")),
            create_issues=parse_bool(get("CREATE_ISSUES", "false")),
            issue_labels=get("ISSUE_LABELS"),
            actor=get("GITHUB_ACTOR", "github-actions[bot]"),
            server_url=get("GITHUB_SERVER_URL", "https://github.com"),
            repository=get("GITHUB_REPOSITORY", ""),
            run_id=get("GITHUB_RUN_ID", ""),
            github_output=get("GITHUB_OUTPUT", ""),
            github_step_summary=get("GITHUB_STEP_SUMMARY", ""),
        )
