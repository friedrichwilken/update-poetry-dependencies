from fakes import FakeBackend, FakeGit, FakeGithubPR, FakeRunner

from poetry_update.__main__ import run
from poetry_update.config import Config


def make_cfg(**overrides):
    base = dict(
        python_version="3.12.7",
        poetry_version="2.0.0",
        directory=".",
        pr_title_prefix="",
        pr_labels="",
        test_command="",
        github_token="token",
        branch_name="deps/test-gated-updates",
        base_branch="",
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
    cfg = make_cfg(dry_run=False)
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
        }
    ]


def test_empty_labels_are_never_passed_through_to_create():
    cfg = make_cfg(dry_run=False, pr_labels="")
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True], head_shas=["sha0", "sha1"])
    gh = FakeGithubPR(open_pr_number=None)

    run(cfg, runner=FakeRunner(), backend=backend, git=git, gh=gh)

    assert gh.create_calls[0]["labels"] == []
