from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .errors import ActionError
from .versions import version_at_least

MIN_PYTHON_VERSION = "3.10"
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


def check_versions(python_version: str, poetry_version: str) -> None:
    if not version_at_least(python_version, MIN_PYTHON_VERSION):
        raise ActionError(
            f"python-version {python_version} is below the minimum required "
            f"version {MIN_PYTHON_VERSION}"
        )
    if not version_at_least(poetry_version, MIN_POETRY_VERSION):
        raise ActionError(
            f"poetry-version {poetry_version} is below the minimum required "
            f"version {MIN_POETRY_VERSION}"
        )


@dataclass
class Config:
    python_version: str
    poetry_version: str
    directory: str
    pr_title_prefix: str
    pr_labels: str
    test_command: str
    github_token: str
    branch_name: str
    base_branch: str
    dry_run: bool
    actor: str
    server_url: str
    repository: str
    run_id: str
    github_output: str

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            return env.get(name, default)

        return cls(
            python_version=get("PYTHON_VERSION"),
            poetry_version=get("POETRY_VERSION"),
            directory=get("DIRECTORY", "./"),
            pr_title_prefix=get("PR_TITLE_PREFIX"),
            pr_labels=get("PR_LABELS"),
            test_command=get("TEST_COMMAND"),
            github_token=get("GITHUB_TOKEN_INPUT"),
            branch_name=get("BRANCH_NAME", "deps/test-gated-updates"),
            base_branch=get("BASE_BRANCH"),
            dry_run=parse_bool(get("DRY_RUN", "false")),
            actor=get("GITHUB_ACTOR", "github-actions[bot]"),
            server_url=get("GITHUB_SERVER_URL", "https://github.com"),
            repository=get("GITHUB_REPOSITORY", ""),
            run_id=get("GITHUB_RUN_ID", ""),
            github_output=get("GITHUB_OUTPUT", ""),
        )
