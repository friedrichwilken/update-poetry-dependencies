from __future__ import annotations

import sys
import traceback

from .backend import make_backend
from .bootstrap import bootstrap
from .config import Config, check_versions, parse_labels, resolve_base_branch
from .detect import detect_package_manager
from .errors import ActionError, UpdateAborted
from .git_repo import GitRepo
from .github_pr import GithubPR, create_or_edit
from .report import MAX_SUMMARY_CHARS, render_body, write_outputs
from .runner import CommandRunner
from .updater import UpdateResult, run_updates


def run(cfg: Config, runner=None, backend=None, git=None, gh=None) -> int:
    # Guarantee the outputs are always set, even if something below fails
    # before a real UpdateResult exists. Any later write_outputs call below
    # overrides this with real (or partial) data.
    write_outputs(cfg.github_output, UpdateResult(), "")

    package_manager = detect_package_manager(cfg.directory, cfg.package_manager)
    check_versions(package_manager, cfg.python_version, cfg.poetry_version)

    runner = runner or CommandRunner()
    if backend is None:
        # Only for a real run (never in unit tests, which always inject a
        # fake backend): provision the project interpreter, and Poetry
        # itself if that is the selected backend, via uv.
        bootstrap(runner, package_manager, cfg.directory, cfg.python_version, cfg.poetry_version)
        backend = make_backend(package_manager, runner, cfg)
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
        raise ActionError(f"{package_manager} install failed")

    packages = backend.list_top_level_packages()
    print(f"top level packages: {', '.join(packages) or '(none)'}")

    git.configure_user(cfg.actor, f"{cfg.actor}@users.noreply.github.com")
    start_sha = git.head_sha()

    run_url = f"{cfg.server_url}/{cfg.repository}/actions/runs/{cfg.run_id}"

    try:
        result = run_updates(
            backend,
            git,
            runner,
            packages,
            cfg.test_command,
            cfg.directory,
            allow_major=cfg.allow_major,
        )
    except UpdateAborted as exc:
        # Some packages were already processed (and, for passing ones,
        # already committed) before the abort - report on that partial
        # result instead of losing it, but never push/PR it: the run
        # still failed, so re-raise once the report is written (the
        # already-made commits stay local/uncommitted-to-remote, exactly
        # like any other failure below the install step).
        partial_body = render_body(exc.result, run_url, aborted_reason=str(exc))
        partial_summary = render_body(
            exc.result,
            run_url,
            max_chars=MAX_SUMMARY_CHARS,
            aborted_reason=str(exc),
            include_major_skip_notes=True,
        )
        write_outputs(
            cfg.github_output,
            exc.result,
            partial_body,
            cfg.github_step_summary,
            summary_body=partial_summary,
        )
        print(partial_body)
        raise

    body = render_body(result, run_url)
    summary_body = render_body(
        result, run_url, max_chars=MAX_SUMMARY_CHARS, include_major_skip_notes=True
    )
    write_outputs(
        cfg.github_output, result, body, cfg.github_step_summary, summary_body=summary_body
    )
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

    existing_pr, pr_result = create_or_edit(gh, cfg.branch_name, title, body, base_branch, labels)
    print(f"updated existing PR #{existing_pr}" if existing_pr is not None else "created PR")

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
