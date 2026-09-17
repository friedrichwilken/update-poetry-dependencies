import pytest
from fakes import FakeBackend, FakeGit, FakeGithubPR, FakeRunner

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
