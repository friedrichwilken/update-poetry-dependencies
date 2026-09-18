import pytest
from fakes import FakeBackend, FakeGit, FakeRunner, result

from updater.errors import ActionError, UpdateAborted
from updater.major import MajorAttempt
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


def test_failed_resync_raises_update_aborted_carrying_the_partial_result():
    """The abort must not lose the outcomes already recorded (here: a's
    resolution failure) - it is raised as an UpdateAborted carrying the
    partial UpdateResult, not a bare ActionError, precisely so the caller
    can still report on it."""
    backend = FakeBackend(update_ok={"a": False, "b": True}, sync_ok=False)
    git = FakeGit(diff_results=[])
    runner = FakeRunner()

    with pytest.raises(UpdateAborted) as excinfo:
        run_updates(backend, git, runner, ["a", "b"], "pytest", "dir")

    partial = excinfo.value.result
    assert [o.name for o in partial.outcomes] == ["a"]
    assert partial.outcomes[0].status == "failed"
    assert partial.outcomes[0].failure_kind == "resolution"
    # b was never reached, so it must not appear in the partial result
    assert "b" not in [o.name for o in partial.outcomes]


def test_failed_resync_after_a_passing_package_keeps_that_commit_in_the_partial_result():
    """a passes and is committed; b then fails to re-sync. The partial
    result must still include a's successful outcome - its commit was
    already made and stays made, only the run as a whole is aborted."""
    backend = FakeBackend(
        update_ok={"a": True, "b": False},
        sync_ok=False,
        versions={"a": ["1.0.0", "1.1.0"]},
    )
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    with pytest.raises(UpdateAborted) as excinfo:
        run_updates(backend, git, runner, ["a", "b"], "", "dir")

    partial = excinfo.value.result
    names_and_status = [(o.name, o.status) for o in partial.outcomes]
    assert names_and_status == [("a", "updated"), ("b", "failed")]
    assert git.commit_messages == ["Update a 1.0.0 -> 1.1.0"]


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


# --- allow_major state machine (issue #21) ------------------------------


def test_default_off_byte_compat_never_touches_major_machinery():
    """With allow_major left at its default (False), try_major() and
    major_files_to_stage() must never even be called - the manifest is
    never read or touched at all."""
    backend = FakeBackend(update_ok={"a": True}, versions={"a": ["1.0.0", "1.1.0"]})
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir")

    assert res.passed == ["a"]
    assert backend.try_major_calls == []
    assert backend.major_files_to_stage_calls == 0
    outcome = res.outcomes[0]
    assert outcome.bump is None
    assert outcome.constraint_raised is False
    assert outcome.beyond_constraint_version is None
    assert outcome.beyond_constraint_skip_reason is None


def test_beyond_constraint_attempt_passes_and_is_committed_without_an_in_range_update():
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "3.0.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(True))},
    )
    git = FakeGit(diff_results=[])  # never consulted: no in-range update runs
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    assert res.passed == ["a"]
    assert backend.updated_packages == []  # the plain in-range path never ran
    assert git.commit_messages == ["Update a 1.0.0 -> 3.0.0 (constraint raised)"]
    assert git.staged_calls == [["pyproject.toml", "poetry.lock"]]

    outcome = res.outcomes[0]
    assert outcome.status == "updated"
    assert outcome.bump == "major"  # 1.0.0 -> 3.0.0 really is a major bump here
    assert outcome.constraint_raised is True
    assert outcome.old_version == "1.0.0"
    assert outcome.new_version == "3.0.0"
    assert outcome.beyond_constraint_version is None
    assert outcome.beyond_constraint_skip_reason is None


def test_beyond_constraint_bump_reflects_the_actual_version_delta_not_always_major():
    """A capped constraint like `six >=1.10,<1.15` allowing 1.17.0 is a
    minor bump that merely exceeded the declared range - `bump` must never
    just assume "major" because the constraint itself was raised."""
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.10.0", "1.17.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(True))},
    )
    git = FakeGit(diff_results=[])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    outcome = res.outcomes[0]
    assert outcome.constraint_raised is True
    assert outcome.bump == "minor"


def test_beyond_constraint_attempt_runs_test_command_before_committing():
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "3.0.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(True))},
    )
    git = FakeGit()
    runner = FakeRunner(shell_results=[result(True)])

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir", allow_major=True)

    assert runner.shell_calls == [("pytest", "dir")]
    assert res.outcomes[0].bump == "major"


def test_beyond_constraint_resolution_failure_falls_back_and_reports_held_back():
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "1.5.0", "1.0.1"]},
        major_attempts={
            "a": MajorAttempt(resolve_result=result(False, stderr="could not resolve pkg>=3"))
        },
    )
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    # beyond-constraint files were reset+resynced once, before the
    # in-range update ran
    assert git.reset_calls == [["pyproject.toml", "poetry.lock"]]
    assert backend.sync_calls == 1
    # the in-range update then ran normally and passed
    assert res.passed == ["a"]
    assert git.staged_calls == [["poetry.lock"]]

    outcome = res.outcomes[0]
    assert outcome.status == "updated"
    assert outcome.constraint_raised is False
    assert outcome.bump == "patch"  # the in-range fallback's own actual delta
    assert outcome.beyond_constraint_version == "1.5.0"
    assert outcome.beyond_constraint_failure_kind == "resolution"
    assert "could not resolve pkg>=3" in outcome.beyond_constraint_output_tail
    assert outcome.old_version == "1.0.0"
    assert outcome.new_version == "1.0.1"


def test_beyond_constraint_test_failure_falls_back_and_reports_held_back():
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "3.0.0", "1.1.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(True))},
    )
    git = FakeGit(diff_results=[True])
    # first run_shell call (for the beyond-constraint attempt) fails; second (in-range) passes
    runner = FakeRunner(shell_results=[result(False, stderr="tests failed hard"), result(True)])

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir", allow_major=True)

    assert git.reset_calls == [["pyproject.toml", "poetry.lock"]]
    assert res.passed == ["a"]

    outcome = res.outcomes[0]
    assert outcome.constraint_raised is False
    assert outcome.beyond_constraint_version == "3.0.0"
    assert outcome.beyond_constraint_failure_kind == "test"
    assert "tests failed hard" in outcome.beyond_constraint_output_tail
    assert outcome.new_version == "1.1.0"


def test_beyond_constraint_discarded_reports_a_skip_reason_not_a_failure_kind():
    """A tool call that succeeded but had to be discarded (manifest diff
    guard, or a pre-release landing) must never be reported as if the
    tool itself had failed."""
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "1.5.0", "1.1.0"]},
        major_attempts={
            "a": MajorAttempt(
                resolve_result=result(True),
                discarded_reason="manifest changed beyond the version constraint",
            )
        },
    )
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    assert git.reset_calls == [["pyproject.toml", "poetry.lock"]]
    assert res.passed == ["a"]

    outcome = res.outcomes[0]
    assert outcome.beyond_constraint_skip_reason == "manifest changed beyond the version constraint"
    assert outcome.beyond_constraint_version is None
    assert outcome.beyond_constraint_failure_kind is None
    assert outcome.failure_kind is None


def test_beyond_constraint_and_in_range_both_fail_reports_failed_with_held_back_info():
    backend = FakeBackend(
        update_ok={"a": False},
        versions={"a": ["1.0.0", "3.0.0", "1.0.0", "1.0.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(True))},
    )
    git = FakeGit(diff_results=[])
    runner = FakeRunner(shell_results=[result(False, stderr="beyond-constraint test failed")])

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir", allow_major=True)

    assert res.failed == ["a"]
    outcome = res.outcomes[0]
    assert outcome.status == "failed"
    assert outcome.failure_kind == "resolution"  # the in-range update's own failure
    assert outcome.beyond_constraint_version == "3.0.0"
    assert outcome.beyond_constraint_failure_kind == "test"
    # both resets happened: once for the held-back attempt, once for the
    # in-range resolution failure
    assert git.reset_calls == [["pyproject.toml", "poetry.lock"], ["poetry.lock"]]


def test_beyond_constraint_fails_and_nothing_in_range_is_still_reported_skipped_with_held_back():
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "3.0.0", "1.0.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(True))},
    )
    git = FakeGit(diff_results=[False])  # in-range update has nothing to do
    runner = FakeRunner(shell_results=[result(False, stderr="beyond-constraint test failed")])

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir", allow_major=True)

    assert res.skipped == ["a"]
    outcome = res.outcomes[0]
    assert outcome.status == "skipped"
    assert outcome.beyond_constraint_version == "3.0.0"
    assert outcome.beyond_constraint_failure_kind == "test"


def test_beyond_constraint_skip_reason_is_recorded_and_in_range_update_still_runs():
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "1.1.0"]},
        major_attempts={"a": MajorAttempt(skip_reason="exact version pin")},
    )
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    assert res.passed == ["a"]
    outcome = res.outcomes[0]
    assert outcome.beyond_constraint_skip_reason == "exact version pin"
    assert outcome.beyond_constraint_version is None
    assert outcome.constraint_raised is False


def test_beyond_constraint_not_needed_returns_none_and_behaves_like_default_off():
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "1.0.1"]},
        major_attempts={"a": None},
    )
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    assert backend.try_major_calls == ["a"]
    outcome = res.outcomes[0]
    assert outcome.status == "updated"
    assert outcome.bump == "patch"
    assert outcome.constraint_raised is False
    assert outcome.beyond_constraint_skip_reason is None


def test_beyond_constraint_reset_resync_failure_aborts_with_partial_results():
    backend = FakeBackend(
        update_ok={"a": True, "b": True},
        sync_ok=False,
        versions={"a": ["1.0.0", "1.1.0"]},
        major_attempts={"b": MajorAttempt(resolve_result=result(False, stderr="boom"))},
    )
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    with pytest.raises(UpdateAborted) as excinfo:
        run_updates(backend, git, runner, ["a", "b"], "", "dir", allow_major=True)

    partial = excinfo.value.result
    # a completed and was committed normally before b's beyond-constraint
    # attempt blew up the environment - and b itself is still recorded
    # (review fix: an abort during the held-back reset must not silently
    # drop the in-progress package from the partial result)
    assert [(o.name, o.status) for o in partial.outcomes] == [("a", "updated"), ("b", "failed")]
    assert git.commit_messages == ["Update a 1.0.0 -> 1.1.0"]
    assert partial.outcomes[1].failure_kind == "resolution"
    assert "boom" in partial.outcomes[1].output_tail


def test_beyond_constraint_reset_restores_both_manifest_and_lock():
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "1.0.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(False, stderr="boom"))},
    )
    git = FakeGit(diff_results=[False])
    runner = FakeRunner()

    run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    assert git.reset_calls == [["pyproject.toml", "poetry.lock"]]


def test_beyond_constraint_commit_stages_manifest_and_lock_but_in_range_stages_lock_only():
    backend = FakeBackend(
        update_ok={"a": True, "b": True},
        versions={"a": ["1.0.0", "2.0.0"], "b": ["1.0.0", "1.1.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(True))},
    )
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    run_updates(backend, git, runner, ["a", "b"], "", "dir", allow_major=True)

    assert git.staged_calls == [["pyproject.toml", "poetry.lock"], ["poetry.lock"]]


# --- Review fix: aborting during a held-back beyond-constraint attempt --
# must not silently drop the in-progress package from the partial result.


def test_beyond_constraint_abort_during_the_held_back_reset_still_records_the_package():
    """`a`'s beyond-constraint attempt fails resolution; the reset+resync
    that should follow it fails too, aborting the run. Unlike a plain
    resync failure (covered above, which happens *after* an outcome for
    `a` already exists), this abort happens *before* `a`'s in-range
    fallback ever runs - so no outcome for `a` exists yet unless the abort
    path itself creates one."""
    backend = FakeBackend(
        update_ok={"a": True},
        sync_ok=False,
        versions={"a": ["1.0.0", "1.5.0"]},
        major_attempts={
            "a": MajorAttempt(resolve_result=result(False, stderr="could not resolve pkg>=3"))
        },
    )
    git = FakeGit(diff_results=[])
    runner = FakeRunner()

    with pytest.raises(UpdateAborted) as excinfo:
        run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    partial = excinfo.value.result
    assert [o.name for o in partial.outcomes] == ["a"]
    outcome = partial.outcomes[0]
    assert outcome.status == "failed"
    assert outcome.old_version == "1.0.0"
    assert outcome.new_version == "1.5.0"
    assert outcome.failure_kind == "resolution"
    assert "could not resolve pkg>=3" in outcome.output_tail
    # the resync failure itself is also captured in the tail
    assert "re-sync" in outcome.output_tail or "resync" in outcome.output_tail.lower()


def test_beyond_constraint_abort_during_discarded_reset_still_records_the_package():
    backend = FakeBackend(
        update_ok={"a": True},
        sync_ok=False,
        versions={"a": ["1.0.0", "1.5.0"]},
        major_attempts={
            "a": MajorAttempt(
                resolve_result=result(True),
                discarded_reason="manifest changed beyond the version constraint",
            )
        },
    )
    git = FakeGit(diff_results=[])
    runner = FakeRunner()

    with pytest.raises(UpdateAborted) as excinfo:
        run_updates(backend, git, runner, ["a"], "", "dir", allow_major=True)

    partial = excinfo.value.result
    assert [o.name for o in partial.outcomes] == ["a"]
    assert partial.outcomes[0].status == "failed"
