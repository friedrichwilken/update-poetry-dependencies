import pytest
from fakes import FakeBackend, FakeGit, FakeGithubPR, FakeRunner

from updater.__main__ import run
from updater.config import Config
from updater.errors import ActionError


def make_cfg(**overrides):
    base = dict(
        python_version="3.12.7",
        poetry_version="2.0.0",
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
