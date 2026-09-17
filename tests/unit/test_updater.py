import pytest
from fakes import FakeBackend, FakeGit, FakeRunner, result

from updater.errors import ActionError
from updater.updater import run_updates


def test_package_passes_when_lock_changes_and_test_succeeds():
    backend = FakeBackend(
        update_ok={"a": True, "b": True},
        versions={"a": ["1.0.0", "1.1.0"], "b": ["2.0.0", "2.1.0"]},
    )
    git = FakeGit(diff_results=[True, True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a", "b"], "", "dir")

    assert res.passed == ["a", "b"]
    assert res.failed == []
    assert res.skipped == []
    assert git.commit_messages == [
        "Update a 1.0.0 -> 1.1.0",
        "Update b 2.0.0 -> 2.1.0",
    ]
    assert backend.sync_calls == 0
    assert runner.shell_calls == []

    outcomes = {o.name: o for o in res.outcomes}
    assert outcomes["a"].status == "updated"
    assert outcomes["a"].old_version == "1.0.0"
    assert outcomes["a"].new_version == "1.1.0"
    assert outcomes["a"].failure_kind is None
    assert outcomes["a"].output_tail == ""


def test_package_skipped_when_lock_does_not_change():
    backend = FakeBackend(update_ok={"a": True}, versions={"a": ["1.0.0"]})
    git = FakeGit(diff_results=[False])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir")

    assert res.skipped == ["a"]
    assert res.passed == []
    assert res.failed == []
    # no test should have run for a package with nothing to test
    assert runner.shell_calls == []
    assert git.commit_messages == []

    outcome = res.outcomes[0]
    assert outcome.status == "skipped"
    assert outcome.old_version == "1.0.0"
    assert outcome.new_version == "1.0.0"


def test_updater_failure_counts_as_failed_and_resyncs():
    backend = FakeBackend(update_ok={"a": False}, versions={"a": ["1.0.0", "1.0.0"]})
    git = FakeGit(diff_results=[])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir")

    assert res.failed == ["a"]
    assert res.passed == []
    assert res.skipped == []
    assert git.reset_calls == [["poetry.lock"]]
    assert backend.sync_calls == 1
    # the test command never runs for a package whose update itself failed
    assert runner.shell_calls == []

    outcome = res.outcomes[0]
    assert outcome.status == "failed"
    assert outcome.failure_kind == "resolution"
    assert outcome.old_version == "1.0.0"
    assert outcome.new_version == "1.0.0"


def test_resolution_failure_captures_output_tail():
    backend = FakeBackend(update_ok={"a": False})
    backend.update_package = lambda package: result(
        False, stdout="line1\nline2\n", stderr="resolver blew up\n"
    )
    git = FakeGit(diff_results=[])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir")

    outcome = res.outcomes[0]
    assert "line1" in outcome.output_tail
    assert "resolver blew up" in outcome.output_tail


def test_failed_test_resyncs_and_does_not_stop_later_packages():
    backend = FakeBackend(
        update_ok={"a": True, "b": False, "c": True},
        versions={"a": ["1.0.0", "1.1.0"], "c": ["3.0.0", "3.1.0"]},
    )
    git = FakeGit(diff_results=[True, True])  # only for a and c; b fails before diff check
    runner = FakeRunner(shell_results=[result(True), result(False, stderr="assertion failed")])

    res = run_updates(backend, git, runner, ["a", "b", "c"], "pytest", "dir")

    assert res.passed == ["a"]
    assert res.failed == ["b", "c"]
    assert res.skipped == []
    assert backend.sync_calls == 2  # for b (update failure) and c (test failure)
    assert git.reset_calls == [["poetry.lock"], ["poetry.lock"]]
    assert len(runner.shell_calls) == 2  # only a and c reach the test stage

    outcomes = {o.name: o for o in res.outcomes}
    assert outcomes["b"].failure_kind == "resolution"
    assert outcomes["c"].failure_kind == "test"
    assert "assertion failed" in outcomes["c"].output_tail
    assert outcomes["c"].old_version == "3.0.0"
    assert outcomes["c"].new_version == "3.1.0"


def test_only_lock_file_is_staged():
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    run_updates(backend, git, runner, ["a"], "", "dir")

    assert git.staged_calls == [["poetry.lock"]]


def test_failed_resync_after_update_failure_aborts_the_run():
    backend = FakeBackend(update_ok={"a": False, "b": True}, sync_ok=False)
    git = FakeGit(diff_results=[])
    runner = FakeRunner()

    with pytest.raises(ActionError):
        run_updates(backend, git, runner, ["a", "b"], "pytest", "dir")

    # a is recorded as failed before the resync is attempted and found broken
    assert backend.sync_calls == 1
    # b is never touched once the environment is known to be broken
    assert backend.updated_packages == ["a"]


def test_failed_resync_after_test_failure_aborts_the_run():
    backend = FakeBackend(update_ok={"a": True, "b": True}, sync_ok=False)
    git = FakeGit(diff_results=[True])
    runner = FakeRunner(shell_results=[result(False)])

    with pytest.raises(ActionError):
        run_updates(backend, git, runner, ["a", "b"], "pytest", "dir")

    assert backend.sync_calls == 1
    assert backend.updated_packages == ["a"]


def test_run_updates_is_backend_agnostic_and_stages_whatever_lock_file_the_backend_reports():
    """The update loop must not know or care which backend it is driving:
    a uv-flavoured backend (uv.lock instead of poetry.lock) goes through
    exactly the same path as the Poetry one."""
    backend = FakeBackend(update_ok={"idna": True}, lock_file="uv.lock")
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["idna"], "", "dir")

    assert res.passed == ["idna"]
    assert git.staged_calls == [["uv.lock"]]


def test_test_command_runs_in_project_directory():
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    run_updates(backend, git, runner, ["a"], "pytest", "some/project/dir")

    assert runner.shell_calls == [("pytest", "some/project/dir")]


def test_locked_version_is_read_before_and_after_the_update_attempt():
    backend = FakeBackend(update_ok={"a": True}, versions={"a": ["1.0.0", "1.1.0"]})
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    run_updates(backend, git, runner, ["a"], "", "dir")

    assert backend.locked_version_calls == ["a", "a"]
