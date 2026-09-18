from __future__ import annotations

import sys
import traceback

from .backend import make_backend
from .bootstrap import bootstrap
from .config import Config, check_versions, parse_labels, resolve_base_branch
from .detect import detect_package_manager
from .errors import ActionError, UpdateAborted
from .git_repo import GitRepo
from .github_issues import issue_actions_to_json, run_issue_management, summarize_issue_actions
from .github_pr import GithubPR, create_or_edit, parse_created_pr_number
from .report import MAX_SUMMARY_CHARS, render_body, write_outputs
from .runner import CommandRunner
from .updater import UpdateResult, run_updates


def run(cfg: Config, runner=None, backend=None, git=None, gh=None, gh_issues=None) -> int:
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

    # Fail fast, before anything else, if the manifest/lock file already
    # have uncommitted changes: the update loop's `reset_files` would
    # otherwise discard them on a discarded update, or `stage`/`commit`
    # would silently sweep them into one of this run's own commits.
    # Checked regardless of allow-major - the lock file is always at risk
    # even when the manifest itself is never touched.
    tracked_files = backend.major_files_to_stage()
    if git.has_uncommitted_changes(tracked_files):
        raise ActionError(
            f"{cfg.directory} has uncommitted changes to {', '.join(tracked_files)}; "
            "commit or stash them before running this action - the update loop "
            "resets and commits these files itself and would otherwise either "
            "discard or absorb those changes"
        )

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
        #
        # create-issues is skipped entirely here (never just for the
        # missing packages) - exc.result is a partial outcome list, and
        # treating whatever is missing from it as "no longer failing"
        # would incorrectly close issues for packages this run never even
        # got to process.
        if cfg.create_issues:
            print(
                "::notice::create-issues: skipped issue management for this run - "
                "it aborted before completing, so the outcome list is only partial"
            )
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
    print(body)

    # Push/PR and (after it - see the README "create-issues" section)
    # issue management both run under one `finally` so the report is
    # still written even if either of them raises: the report is this
    # action's primary product and must not be lost just because a later
    # step failed.
    pr_url: str | None = None
    issue_actions: list = []
    try:
        if cfg.dry_run:
            print("dry-run: skipping push and PR create/edit")
        elif git.head_sha() == start_sha:
            print("no packages updated, nothing to push")
        else:
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

            pr_number = existing_pr
            if pr_number is None:
                pr_number = parse_created_pr_number(pr_result.stdout)
            if pr_number is not None:
                pr_url = f"{cfg.server_url}/{cfg.repository}/pull/{pr_number}"

        # Runs after the PR create/edit above (pr_url is known by now, or
        # deliberately still None for dry-run - see the README) and
        # before returning. A failure here must never fail a run that
        # already produced its primary product (the PR / the report) - a
        # single action's own gh failure is isolated by
        # execute_issue_actions and surfaces as one of `issue_errors`
        # below (each printed as its own ::warning::, without losing the
        # other actions that did succeed); run_issue_management itself can
        # still raise outright (e.g. the initial issue listing failing),
        # which is caught the same broad way as everywhere else this
        # action treats a create-issues failure as non-fatal.
        if cfg.create_issues:
            try:
                issue_actions, issue_errors = run_issue_management(
                    cfg, runner, result.outcomes, run_url, pr_url, gh_issues=gh_issues
                )
            except Exception as exc:  # deliberately broad - see the comment above
                print(f"::warning::create-issues: failed to manage issues: {exc}")
                issue_actions, issue_errors = [], []
            for issue_error in issue_errors:
                print(f"::warning::create-issues: {issue_error}")
            summary_body = (
                f"{summary_body}\n\n{summarize_issue_actions(issue_actions, cfg.dry_run)}\n"
            )
    finally:
        write_outputs(
            cfg.github_output,
            result,
            body,
            cfg.github_step_summary,
            summary_body=summary_body,
            issue_actions_json=issue_actions_to_json(issue_actions),
        )

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
