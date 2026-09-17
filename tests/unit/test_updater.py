import pytest
from fakes import FakeBackend, FakeGit, FakeRunner, result

from updater.errors import ActionError
from updater.updater import run_updates


def test_package_passes_when_lock_changes_and_test_succeeds():
    backend = FakeBackend(update_ok={"a": True, "b": True})
    git = FakeGit(diff_results=[True, True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a", "b"], "", "dir")

    assert res.passed == ["a", "b"]
    assert res.failed == []
    assert res.skipped == []
    assert git.commit_messages == [
        "Update and successfully test a",
        "Update and successfully test b",
    ]
    assert backend.sync_calls == 0
    assert runner.shell_calls == []


def test_package_skipped_when_lock_does_not_change():
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[False])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir")

    assert res.skipped == ["a"]
    assert res.passed == []
    assert res.failed == []
    # no test should have run for a package with nothing to test
    assert runner.shell_calls == []
    assert git.commit_messages == []


def test_updater_failure_counts_as_failed_and_resyncs():
    backend = FakeBackend(update_ok={"a": False})
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


def test_failed_test_resyncs_and_does_not_stop_later_packages():
    backend = FakeBackend(update_ok={"a": True, "b": False, "c": True})
    git = FakeGit(diff_results=[True, True])  # only for a and c; b fails before diff check
    runner = FakeRunner(shell_results=[result(True), result(False)])

    res = run_updates(backend, git, runner, ["a", "b", "c"], "pytest", "dir")

    assert res.passed == ["a"]
    assert res.failed == ["b", "c"]
    assert res.skipped == []
    assert backend.sync_calls == 2  # for b (update failure) and c (test failure)
    assert git.reset_calls == [["poetry.lock"], ["poetry.lock"]]
    assert len(runner.shell_calls) == 2  # only a and c reach the test stage


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


def test_test_command_runs_in_project_directory():
    backend = FakeBackend(update_ok={"a": True})
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    run_updates(backend, git, runner, ["a"], "pytest", "some/project/dir")

    assert runner.shell_calls == [("pytest", "some/project/dir")]
