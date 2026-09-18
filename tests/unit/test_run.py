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
        strategy="per-package",
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


# --- pr-number / pr-url outputs (issue #43) -------------------------------


def _output_value(output_file, key: str) -> str:
    """GITHUB_OUTPUT is append-only and last-write-wins per key - `run()`
    always writes an empty-result guard first (see its own comment), so the
    real value (if any) is whichever `<key>=` line comes last."""
    content = output_file.read_text()
    lines = [line for line in content.splitlines() if line.startswith(f"{key}=")]
    return lines[-1][len(key) + 1 :]


def test_pr_number_and_pr_url_outputs_on_create(tmp_path):
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(dry_run=False, github_output=str(output_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None, created_pr_url="https://github.com/owner/repo/pull/42")

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert _output_value(output_file, "pr-number") == "42"
    assert _output_value(output_file, "pr-url") == "https://github.com/owner/repo/pull/42"


def test_pr_number_and_pr_url_outputs_on_edit(tmp_path):
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(dry_run=False, github_output=str(output_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=7)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert _output_value(output_file, "pr-number") == "7"
    assert _output_value(output_file, "pr-url") == "https://github.com/owner/repo/pull/7"


def test_pr_number_and_pr_url_outputs_empty_in_dry_run(tmp_path):
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(dry_run=True, github_output=str(output_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert _output_value(output_file, "pr-number") == ""
    assert _output_value(output_file, "pr-url") == ""


def test_pr_number_and_pr_url_outputs_empty_when_nothing_to_push(tmp_path):
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(dry_run=False, github_output=str(output_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[False], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert _output_value(output_file, "pr-number") == ""
    assert _output_value(output_file, "pr-url") == ""


def test_pr_number_and_pr_url_outputs_empty_with_warning_when_create_output_unparsable(
    tmp_path, capsys
):
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(dry_run=False, github_output=str(output_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None, created_pr_url="no PR URL in this output")

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert _output_value(output_file, "pr-number") == ""
    assert _output_value(output_file, "pr-url") == ""
    assert "::warning::" in capsys.readouterr().out


def test_pr_number_and_pr_url_outputs_empty_when_run_aborts_before_pr_step(tmp_path):
    """a passes (and is committed) before b fails to re-sync and aborts the
    run - the PR step is never reached, so both outputs stay empty even
    though a commit was made locally."""
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(dry_run=False, test_command="", github_output=str(output_file))
    backend = FakeBackend(
        update_ok={"a": True, "b": False}, sync_ok=False, versions={"a": ["1.0.0", "1.1.0"]}
    )
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert _output_value(output_file, "pr-number") == ""
    assert _output_value(output_file, "pr-url") == ""


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
    """The only change to the output file when create-issues/update-transitive
    are off is the new, additive `issue-actions=[]`/`transitive-report=null`
    lines (and `pr-number`/`pr-url`, issue #43 - always written, unrelated
    to create-issues)."""
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
        "transitive-report",
        "pr-number",
        "pr-url",
    }

    transitive_line = next(line for line in lines if line.startswith("transitive-report="))
    assert transitive_line == "transitive-report=null"


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


def test_create_issues_one_failing_action_does_not_lose_the_others(tmp_path, capsys):
    """Item 2 of the follow-up review, exercised through the full run():
    three packages fail this run (three planned "create" actions); the
    second package's gh issue create call fails. The first and third are
    still executed, the run still exits 0, and issue-actions reports all
    three - the second with an error."""
    output_file = tmp_path / "output.txt"
    cfg = make_cfg(
        dry_run=False, create_issues=True, github_output=str(output_file), test_command=""
    )
    backend = FakeBackend(
        update_ok={"a": False, "b": False, "c": False},
        versions={"a": ["1.0.0", "1.1.0"], "b": ["1.0.0", "1.1.0"], "c": ["1.0.0", "1.1.0"]},
    )
    git = FakeGit(diff_results=[], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)
    gh_issues = FakeGithubIssues(open_managed=[], fail_create_for={"b"})

    result = run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    assert result == 0
    assert len(gh_issues.create_calls) == 3  # all three were attempted

    warnings = [line for line in capsys.readouterr().out.splitlines() if "::warning::" in line]
    assert len(warnings) == 1
    assert "b" in warnings[0]

    actions = _issue_actions_output(output_file)
    by_pkg = {a["package"]: a for a in actions}
    assert set(by_pkg) == {"a", "b", "c"}
    assert "error" not in by_pkg["a"]
    assert by_pkg["a"]["issue"] is not None
    assert "error" in by_pkg["b"]
    assert by_pkg["b"]["issue"] is None
    assert "error" not in by_pkg["c"]
    assert by_pkg["c"]["issue"] is not None


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


# --- strategy (issue #23) -------------------------------------------------


def test_invalid_strategy_fails_fast_before_any_work():
    cfg = make_cfg(dry_run=True, strategy="bogus")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert backend.install_calls == 0
    assert backend.updated_packages == []


def test_job_summary_does_not_mention_issue_actions_when_feature_off(tmp_path):
    summary_file = tmp_path / "summary.md"
    cfg = make_cfg(dry_run=True, create_issues=False, github_step_summary=str(summary_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert "Issue actions:" not in summary_file.read_text()


# --- update-transitive wiring (issue #24) ------------------------------------


def test_update_transitive_disabled_by_default_never_calls_backend(tmp_path):
    output_file = tmp_path / "out.txt"
    cfg = make_cfg(dry_run=True, github_output=str(output_file))
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert backend.update_transitive_calls == 0
    assert "transitive-report=null" in output_file.read_text()


def test_update_transitive_enabled_runs_after_the_top_level_loop_and_commits(tmp_path):
    output_file = tmp_path / "out.txt"
    cfg = make_cfg(dry_run=True, update_transitive=True, github_output=str(output_file))
    backend = FakeBackend(
        update_ok={"a": True},
        lock_snapshots=[{"a": "1.0.0"}, {"a": "1.0.0", "b": "2.1.0"}],
    )
    git = FakeGit(diff_results=[True, True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert backend.update_transitive_calls == 1
    assert git.commit_messages[-1] == "Update transitive dependencies"
    content = output_file.read_text()
    assert '"status": "updated"' in content
    assert '"name": "b"' in content


def test_update_transitive_failure_creates_a_managed_issue(tmp_path):
    output_file = tmp_path / "out.txt"
    cfg = make_cfg(
        dry_run=False,
        create_issues=True,
        update_transitive=True,
        github_output=str(output_file),
    )
    backend = FakeBackend(update_ok={}, update_transitive_ok=False, update_transitive_stderr="boom")
    git = FakeGit(diff_results=[], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)
    gh_issues = FakeGithubIssues(open_managed=[])

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    assert len(gh_issues.create_calls) == 1
    assert (
        gh_issues.create_calls[0]["title"]
        == "transitive dependencies: lock-wide refresh fails (resolution)"
    )
    assert "boom" in gh_issues.create_calls[0]["body"]
    content = output_file.read_text()
    assert '"status": "failed"' in content


def test_update_transitive_recovery_closes_the_managed_issue():
    from updater.github_issues import ManagedIssue

    cfg = make_cfg(dry_run=False, create_issues=True, update_transitive=True)
    backend = FakeBackend(update_ok={})  # update_transitive_ok=True by default
    git = FakeGit(diff_results=[False], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)
    gh_issues = FakeGithubIssues(
        open_managed=[
            ManagedIssue(
                number=7, package="transitive-dependencies", last_version="", last_kind="test"
            )
        ]
    )

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    assert len(gh_issues.close_calls) == 1
    assert gh_issues.close_calls[0]["number"] == 7


def test_update_transitive_never_files_an_issue_for_a_normal_package_failure():
    """The synthetic transitive-dependencies package must never leak into
    create-issues when the feature never ran (update-transitive off)."""
    cfg = make_cfg(dry_run=False, create_issues=True, update_transitive=False)
    backend = FakeBackend(update_ok={"a": False}, versions={"a": ["1.0.0", "1.0.0"]})
    git = FakeGit(diff_results=[], head_shas=["sha0", "sha0"])
    gh = FakeGithubPR(open_pr_number=None)
    gh_issues = FakeGithubIssues(open_managed=[])

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh, gh_issues=gh_issues)

    titles = [c["title"] for c in gh_issues.create_calls]
    assert titles == ["a: update to 1.0.0 fails (resolution)"]
    assert not any(t.startswith("transitive-dependencies") for t in titles)


# --- with-groups/without-groups/only-groups fail-fast (issue #4) -------------


def test_group_selection_mutual_exclusivity_fails_fast_before_any_work():
    cfg = make_cfg(with_groups="docs", only_groups="dev")
    backend = FakeBackend(update_ok={"a": True})

    with pytest.raises(ActionError):
        run(cfg, runner=FakeRunner(), backend=backend, git=FakeGit(), gh=FakeGithubPR())

    assert backend.install_calls == 0


def test_unknown_group_name_fails_fast_before_any_work(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = []\n')
    cfg = make_cfg(directory=str(tmp_path), only_groups="doesnotexist")
    backend = FakeBackend(update_ok={"a": True})

    with pytest.raises(ActionError, match="unknown dependency group"):
        run(cfg, runner=FakeRunner(), backend=backend, git=FakeGit(), gh=FakeGithubPR())

    assert backend.install_calls == 0


def test_known_group_names_pass_validation_and_the_run_proceeds(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "x"
        dependencies = []

        [tool.poetry.group.dev.dependencies]
        idna = "*"
        """
    )
    cfg = make_cfg(directory=str(tmp_path), dry_run=True, without_groups="dev")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=FakeGithubPR())

    assert backend.install_calls == 1


def test_pep735_group_rejected_when_poetry_version_too_old(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "x"
        dependencies = []

        [dependency-groups]
        test = ["pytest"]
        """
    )
    cfg = make_cfg(directory=str(tmp_path), poetry_version="2.1.4", only_groups="test")
    backend = FakeBackend(update_ok={"a": True})

    with pytest.raises(ActionError, match="poetry-version >= 2.2"):
        run(cfg, runner=FakeRunner(), backend=backend, git=FakeGit(), gh=FakeGithubPR())

    assert backend.install_calls == 0


def test_pep735_group_accepted_when_poetry_version_new_enough(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "x"
        dependencies = []

        [dependency-groups]
        test = ["pytest"]
        """
    )
    cfg = make_cfg(
        directory=str(tmp_path),
        dry_run=True,
        poetry_version="2.4.3",
        only_groups="test",
    )
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=FakeGithubPR())

    assert backend.install_calls == 1
