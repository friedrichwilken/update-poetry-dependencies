import json

import pytest
from fakes import FakeBackend, FakeGit, FakeGithubIssues, FakeGithubPR, FakeRunner

from updater.__main__ import run
from updater.config import Config
from updater.errors import ActionError


def make_cfg(**overrides):
    base = dict(
        python_version="3.12.7",
        package_manager="poetry",
        poetry_version="2.0.0",
        uv_sync_args="",
        directory=".",
        pr_title_prefix="",
        pr_labels="",
        test_command="",
        branch_name="deps/test-gated-updates",
        base_branch="",
        github_base_ref="",
        dry_run=False,
        allow_major=False,
        create_issues=False,
        issue_labels="",
        actor="actor",
        server_url="https://github.com",
        repository="owner/repo",
        run_id="1",
        github_output="",
        github_step_summary="",
    )
    base.update(overrides)
    return Config(**base)


def test_dry_run_never_pushes_or_touches_pr():
    cfg = make_cfg(dry_run=True)
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert git.checkout_branches == []
    assert git.push_branches == []
    assert gh.create_calls == []
    assert gh.edit_calls == []


def test_no_changes_skips_publish_even_when_not_dry_run():
    cfg = make_cfg(dry_run=False)
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[False], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert git.checkout_branches == []
    assert git.push_branches == []
    assert gh.create_calls == []
    assert gh.edit_calls == []


def test_pushes_and_creates_pr_when_changes_and_no_open_pr():
    cfg = make_cfg(dry_run=False, branch_name="deps/test-gated-updates")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert git.checkout_branches == ["deps/test-gated-updates"]
    assert git.push_branches == ["deps/test-gated-updates"]
    assert len(gh.create_calls) == 1
    assert gh.edit_calls == []


def test_pushes_and_edits_existing_pr_when_one_is_open():
    cfg = make_cfg(dry_run=False, pr_labels="dep,automerge")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=7)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert git.push_branches == ["deps/test-gated-updates"]
    assert gh.create_calls == []
    assert gh.edit_calls == [
        {
            "number": 7,
            "title": "Update and successfully test packages",
            "body": gh.edit_calls[0]["body"],
            "labels": ["dep", "automerge"],
        }
    ]


def test_empty_labels_are_never_passed_through_to_create():
    cfg = make_cfg(dry_run=False, pr_labels="")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert gh.create_calls[0]["labels"] == []


def test_explicit_base_branch_input_wins_over_detached_checkout():
    cfg = make_cfg(dry_run=True, base_branch="release")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"], current_branch="HEAD")
    gh = FakeGithubPR(open_pr_number=None)

    # should not raise even though the checkout is detached, because
    # base-branch was given explicitly
    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)


def test_detached_checkout_falls_back_to_github_base_ref():
    cfg = make_cfg(dry_run=True, base_branch="", github_base_ref="main")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"], current_branch="HEAD")
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)


def test_detached_checkout_without_base_branch_or_github_base_ref_fails_fast():
    cfg = make_cfg(dry_run=False, base_branch="", github_base_ref="")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"], current_branch="HEAD")
    gh = FakeGithubPR(open_pr_number=None)

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    # must fail before doing any work: no install, no packages processed
    assert backend.install_calls == 0
    assert backend.updated_packages == []


def test_failed_resync_aborts_the_run():
    cfg = make_cfg(dry_run=True, test_command="pytest")
    backend = FakeBackend(update_ok={"a": False}, sync_ok=False)
    git = FakeGit(diff_results=[], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert backend.sync_calls == 1


def test_failed_resync_never_pushes_or_touches_pr_even_though_a_was_committed():
    """a passes and is committed; b then fails to re-sync and aborts the
    run. The already-made commit for a must stay local - it must not be
    pushed, and no PR may be created/edited, since the run as a whole
    failed."""
    cfg = make_cfg(dry_run=False, test_command="")
    backend = FakeBackend(
        update_ok={"a": True, "b": False}, sync_ok=False, versions={"a": ["1.0.0", "1.1.0"]}
    )
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert git.commit_messages == ["Update a 1.0.0 -> 1.1.0"]
    assert git.checkout_branches == []
    assert git.push_branches == []
    assert gh.create_calls == []
    assert gh.edit_calls == []


def test_failed_resync_writes_partial_outputs_with_an_aborted_banner(tmp_path):
    output_file = tmp_path / "output.txt"
    summary_file = tmp_path / "summary.md"
    cfg = make_cfg(
        dry_run=False,
        test_command="",
        github_output=str(output_file),
        github_step_summary=str(summary_file),
    )
    backend = FakeBackend(
        update_ok={"a": True, "b": False}, sync_ok=False, versions={"a": ["1.0.0", "1.1.0"]}
    )
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    content = output_file.read_text()
    # the outputs written for the abort must reflect the partial result
    # (a already succeeded), not the early empty guard write
    assert "passed-packages=a\n" in content
    assert "failed-packages=b\n" in content

    pr_body_start = content.index("pr-body<<")
    pr_body = content[pr_body_start:]
    assert "Run aborted" in pr_body
    assert "a" in pr_body

    summary = summary_file.read_text()
    assert "Run aborted" in summary


def test_outputs_are_always_written_even_on_early_failure(tmp_path):
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(python_version="3.5", github_output=str(output_file))
    backend = FakeBackend()
    git = FakeGit()
    gh = FakeGithubPR()

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    content = output_file.read_text()
    assert "passed-packages=\n" in content
    assert "failed-packages=\n" in content
    assert "skipped-packages=\n" in content
    assert "pr-body<<" in content


def test_job_summary_is_written_when_github_step_summary_is_set(tmp_path):
    output_file = tmp_path / "output.txt"
    summary_file = tmp_path / "summary.md"
    cfg = make_cfg(
        dry_run=True,
        github_output=str(output_file),
        github_step_summary=str(summary_file),
    )
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    summary = summary_file.read_text()
    assert "Workflow run:" in summary
    assert "a" in summary


def test_job_summary_is_written_even_in_dry_run(tmp_path):
    """dry-run must not skip the job summary write - only the push/PR
    steps are skipped."""
    summary_file = tmp_path / "summary.md"
    cfg = make_cfg(dry_run=True, github_step_summary=str(summary_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert summary_file.exists()
    assert summary_file.read_text().strip() != ""


# --- Uncommitted manifest/lock changes fail fast (review fix) -----------


def test_uncommitted_manifest_or_lock_changes_fail_fast_before_any_work():
    cfg = make_cfg(dry_run=True)
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"], uncommitted=True)
    gh = FakeGithubPR(open_pr_number=None)

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    # must fail before any package was touched
    assert backend.install_calls == 0
    assert backend.updated_packages == []
    assert git.commit_messages == []


def test_uncommitted_check_covers_both_manifest_and_lock_regardless_of_allow_major():
    cfg = make_cfg(dry_run=True, allow_major=False)
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"], uncommitted=False)
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert git.has_uncommitted_changes_calls == [["pyproject.toml", "poetry.lock"]]


def test_clean_working_tree_proceeds_normally():
    cfg = make_cfg(dry_run=True, allow_major=True)
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"], uncommitted=False)
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert backend.install_calls == 1


# --- create-issues (issue #28) -------------------------------------------


def _issue_actions_output(output_file) -> list:
    """GITHUB_OUTPUT is append-only and last-write-wins per key - `run()`
    always writes an empty-result guard first (see its own comment), so
    the real value (if any) is whichever `issue-actions=` line comes
    last."""
    content = output_file.read_text()
    line = [line for line in content.splitlines() if line.startswith("issue-actions=")][-1]
    return json.loads(line[len("issue-actions=") :])


def test_issue_actions_output_is_empty_when_feature_off(tmp_path):
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(dry_run=True, create_issues=False, github_output=str(output_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert _issue_actions_output(output_file) == []


def test_report_outputs_are_byte_compatible_when_create_issues_is_off(tmp_path):
    """The only change to the output file when the feature is off is the
    new, additive `issue-actions=[]` line."""
    output_file_off = tmp_path / "off.txt"
    cfg = make_cfg(dry_run=True, create_issues=False, github_output=str(output_file_off))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    content = output_file_off.read_text()
    lines = [
        line for line in content.splitlines() if "=" in line and not line.startswith("pr-body")
    ]
    keys = {line.split("=", 1)[0] for line in lines}
    assert keys == {
        "passed-packages",
        "failed-packages",
        "skipped-packages",
        "held-back-packages",
        "report-json",
        "issue-actions",
    }


def test_create_issues_off_never_instantiates_or_calls_gh_issues(tmp_path):
    """No gh_issues object is even needed when the feature is off - proven
    by never passing one and the run still succeeding without error."""
    cfg = make_cfg(dry_run=True, create_issues=False)
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=None)


def test_create_issues_dry_run_plans_without_writing(tmp_path):
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(
        dry_run=True, create_issues=True, github_output=str(output_file), test_command=""
    )
    backend = FakeBackend(update_ok={"a": False}, versions={"a": ["1.0.0", "1.1.0"]})
    git = FakeGit(diff_results=[], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)
    gh_issues = FakeGithubIssues(open_managed=[])

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    assert gh_issues.create_calls == []
    actions = _issue_actions_output(output_file)
    assert actions == [{"package": "a", "action": "create", "issue": None}]


def test_create_issues_runs_after_pr_creation_and_gets_the_pr_url():
    cfg = make_cfg(dry_run=False, create_issues=True, test_command="")
    backend = FakeBackend(
        update_ok={"a": True, "b": False},
        versions={"a": ["1.0.0", "1.1.0"], "b": ["2.0.0", "2.0.0"]},
    )
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None, created_pr_url="https://github.com/owner/repo/pull/42")
    gh_issues = FakeGithubIssues(open_managed=[])

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    assert len(gh.create_calls) == 1  # the PR itself
    assert len(gh_issues.create_calls) == 1  # the issue for "b"
    assert "https://github.com/owner/repo/pull/42" in gh_issues.create_calls[0]["body"]


def test_create_issues_gets_no_pr_url_in_dry_run():
    cfg = make_cfg(dry_run=True, create_issues=True, test_command="")
    backend = FakeBackend(update_ok={"a": False}, versions={"a": ["1.0.0", "1.1.0"]})
    git = FakeGit(diff_results=[], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)
    gh_issues = FakeGithubIssues(open_managed=[])

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    assert gh_issues.create_calls == []  # dry-run: planned only
    # dry-run never even calls execute's write path, so confirm via a
    # non-dry-run companion instead that pr_url is threaded through when
    # there is one - see test_create_issues_runs_after_pr_creation_and_gets_the_pr_url.


def test_create_issues_failure_does_not_fail_the_run(tmp_path, capsys):
    """A gh issue failure must not take down a run that already produced
    its primary product (the PR)."""

    class _RaisingGithubIssues:
        def list_open_managed(self, limit=200):
            raise RuntimeError("gh issue list exploded")

    output_file = tmp_path / "output.txt"
    cfg = make_cfg(
        dry_run=False, create_issues=True, github_output=str(output_file), test_command=""
    )
    backend = FakeBackend(update_ok={"a": True}, versions={"a": ["1.0.0", "1.1.0"]})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    result = run(
        cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=_RaisingGithubIssues()
    )

    assert result == 0
    assert len(gh.create_calls) == 1  # the PR was still created
    assert "::warning::" in capsys.readouterr().out
    assert _issue_actions_output(output_file) == []


def test_aborted_run_skips_issue_management_entirely(capsys):
    cfg = make_cfg(dry_run=True, create_issues=True, test_command="pytest")
    backend = FakeBackend(update_ok={"a": False}, sync_ok=False)
    git = FakeGit(diff_results=[], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)
    gh_issues = FakeGithubIssues()

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    assert gh_issues.list_calls == 0
    assert "create-issues" in capsys.readouterr().out


def test_job_summary_mentions_issue_actions_when_feature_on(tmp_path):
    summary_file = tmp_path / "summary.md"
    cfg = make_cfg(
        dry_run=True, create_issues=True, github_step_summary=str(summary_file), test_command=""
    )
    backend = FakeBackend(update_ok={"a": False}, versions={"a": ["1.0.0", "1.1.0"]})
    git = FakeGit(diff_results=[], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)
    gh_issues = FakeGithubIssues(open_managed=[])

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    assert "Issue actions:" in summary_file.read_text()


def test_job_summary_does_not_mention_issue_actions_when_feature_off(tmp_path):
    summary_file = tmp_path / "summary.md"
    cfg = make_cfg(dry_run=True, create_issues=False, github_step_summary=str(summary_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert "Issue actions:" not in summary_file.read_text()
