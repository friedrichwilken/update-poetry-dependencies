from __future__ import annotations

import sys
import traceback

from .backend import PoetryBackend
from .config import Config, check_versions, parse_labels, resolve_base_branch
from .errors import ActionError
from .git_repo import GitRepo
from .github_pr import GithubPR, create_or_edit
from .report import render_body, write_outputs
from .runner import CommandRunner
from .updater import UpdateResult, run_updates


def run(cfg: Config, runner=None, backend=None, git=None, gh=None) -> int:
    # Guarantee the outputs are always set, even if something below fails
    # before a real UpdateResult exists. Any later write_outputs call below
    # overrides this with real (or partial) data.
    write_outputs(cfg.github_output, UpdateResult(), "")

    check_versions(cfg.python_version, cfg.poetry_version)

    runner = runner or CommandRunner()
    backend = backend or PoetryBackend(runner, cfg.directory, cfg.poetry_version)
    git = git or GitRepo(runner, cfg.directory)

    # Resolve and validate the base branch before doing any work: a
    # misconfigured/detached checkout should fail fast, not after packages
    # have already been updated, committed and pushed.
    base_branch = resolve_base_branch(cfg.base_branch, git.current_branch(), cfg.github_base_ref)

    if not backend.lock_exists():
        raise ActionError(f"{backend.lock_file_path()} not found; nothing to update")

    print("::group::installing dependencies")
    install_result = backend.install()
    print(install_result.stdout)
    print(install_result.stderr)
    print("::endgroup::")
    if not install_result.ok:
        raise ActionError("poetry install failed")

    packages = backend.list_top_level_packages()
    print(f"top level packages: {', '.join(packages) or '(none)'}")

    git.configure_user(cfg.actor, f"{cfg.actor}@users.noreply.github.com")
    start_sha = git.head_sha()

    result = run_updates(backend, git, runner, packages, cfg.test_command, cfg.directory)

    run_url = f"{cfg.server_url}/{cfg.repository}/actions/runs/{cfg.run_id}"
    body = render_body(result, run_url)
    write_outputs(cfg.github_output, result, body)
    print(body)

    if cfg.dry_run:
        print("dry-run: skipping push and PR create/edit")
        return 0

    if git.head_sha() == start_sha:
        print("no packages updated, nothing to push")
        return 0

    git.checkout_new_branch(cfg.branch_name)
    push_result = git.push(cfg.branch_name)
    if not push_result.ok:
        raise ActionError(f"git push failed: {push_result.stderr}")

    gh = gh or GithubPR(runner, cfg.directory)
    title = f"{cfg.pr_title_prefix}Update and successfully test packages"
    labels = parse_labels(cfg.pr_labels)

    existing_pr, pr_result = create_or_edit(
        gh, cfg.branch_name, title, body, base_branch, labels
    )
    print(
        f"updated existing PR #{existing_pr}" if existing_pr is not None else "created PR"
    )

    if not pr_result.ok:
        raise ActionError(f"gh pr create/edit failed: {pr_result.stderr}")

    return 0


def main() -> int:
    cfg = Config.from_env()
    try:
        return run(cfg)
    except ActionError as exc:
        print(f"::error::{exc}")
        return 1
    except Exception as exc:  # last-resort: still fail with ::error:: and a clean exit code
        traceback.print_exc()
        print(f"::error::unexpected failure: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
