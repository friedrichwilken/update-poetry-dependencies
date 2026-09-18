import pytest
from fakes import FakeBackend, FakeGit, FakeRunner, result

from updater.errors import ActionError, UpdateAborted
from updater.major import MajorAttempt
from updater.updater import UpdateResult, run_transitive_update, run_updates


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


# --- strategy: batch-first (issue #23) -----------------------------------


def test_default_strategy_never_sets_batch_first_fields():
    """Byte-compat guard: leaving `strategy` at its default must never set
    any of the additive batch-first fields, on top of the existing
    default-off guard above for allow-major."""
    backend = FakeBackend(update_ok={"a": True}, versions={"a": ["1.0.0", "1.1.0"]})
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "", "dir")  # strategy omitted

    outcome = res.outcomes[0]
    assert outcome.strategy is None
    assert outcome.tested_in_batch is False
    assert outcome.batch_test_failed is False


def test_batch_first_pass_produces_per_package_commits_with_one_test_run():
    backend = FakeBackend(
        update_ok={"a": True, "b": True},
        versions={"a": ["1.0.0", "1.1.0"], "b": ["2.0.0", "2.1.0"]},
    )
    git = FakeGit(diff_results=[True, True, True])
    runner = FakeRunner(shell_results=[result(True)])

    res = run_updates(backend, git, runner, ["a", "b"], "pytest", "dir", strategy="batch-first")

    assert res.passed == ["a", "b"]
    assert res.failed == []
    assert res.skipped == []
    assert len(runner.shell_calls) == 1  # one shared test run, not one per package
    assert git.commit_messages == [
        "Update a 1.0.0 -> 1.1.0",
        "Update b 2.0.0 -> 2.1.0",
    ]

    outcomes = {o.name: o for o in res.outcomes}
    assert outcomes["a"].tested_in_batch is True
    assert outcomes["a"].strategy == "batch-first"
    assert outcomes["a"].batch_test_failed is False
    assert outcomes["b"].tested_in_batch is True
    assert outcomes["b"].strategy == "batch-first"


def test_batch_first_no_change_skips_everything_without_testing():
    backend = FakeBackend(update_ok={"a": True, "b": True})
    git = FakeGit(diff_results=[False])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a", "b"], "pytest", "dir", strategy="batch-first")

    assert res.skipped == ["a", "b"]
    assert res.passed == []
    assert res.failed == []
    assert runner.shell_calls == []
    assert git.commit_messages == []
    assert all(o.strategy == "batch-first" for o in res.outcomes)
    assert all(not o.tested_in_batch for o in res.outcomes)


def test_batch_first_resolution_failure_falls_back_to_per_package():
    backend = FakeBackend(update_ok={"a": False})
    backend.update_all = lambda packages: result(False, stderr="could not resolve the batch")
    git = FakeGit(diff_results=[])
    runner = FakeRunner()

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir", strategy="batch-first")

    assert res.failed == ["a"]
    assert runner.shell_calls == []  # the failing update never reaches the test stage
    outcome = res.outcomes[0]
    assert outcome.strategy == "batch-first"
    assert outcome.batch_test_failed is False  # the batch never even got to testing


def test_batch_first_test_failure_falls_back_to_per_package_with_n_plus_one_test_runs():
    backend = FakeBackend(update_ok={"a": True, "b": True})
    git = FakeGit(diff_results=[True, True, True])
    runner = FakeRunner(
        shell_results=[result(False, stderr="batch broke"), result(True), result(True)]
    )

    res = run_updates(backend, git, runner, ["a", "b"], "pytest", "dir", strategy="batch-first")

    # N=2 packages: 1 batch test run + 2 per-package fallback test runs = N+1
    assert len(runner.shell_calls) == 3
    assert res.passed == ["a", "b"]
    assert all(o.strategy == "batch-first" for o in res.outcomes)
    assert all(o.batch_test_failed for o in res.outcomes)
    assert all(not o.tested_in_batch for o in res.outcomes)


def test_batch_first_resync_failure_after_batch_test_failure_aborts_with_partial_result():
    backend = FakeBackend(update_ok={"a": True}, sync_ok=False)
    git = FakeGit(diff_results=[True])
    runner = FakeRunner(shell_results=[result(False, stderr="batch broke")])

    with pytest.raises(UpdateAborted) as excinfo:
        run_updates(backend, git, runner, ["a"], "pytest", "dir", strategy="batch-first")

    assert excinfo.value.result.outcomes == []


def test_batch_first_sequential_replay_divergence_runs_one_verification_test_and_keeps_it():
    """The batch's own lock and the sequential replay's lock disagree (a
    resolver can be order-sensitive) - one extra verification test run
    against the replayed result, and it passes, so the replay is kept."""
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "1.1.0"]},
        lock_snapshots=[{"a": "mid"}, {"a": "final-different"}],
    )
    git = FakeGit(diff_results=[True, True])
    runner = FakeRunner(shell_results=[result(True), result(True)])

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir", strategy="batch-first")

    assert len(runner.shell_calls) == 2  # the batch test + one verification test
    assert res.passed == ["a"]
    assert res.outcomes[0].tested_in_batch is True
    assert res.outcomes[0].strategy == "batch-first"
    assert res.outcomes[0].batch_test_failed is False
    assert git.commit_messages == ["Update a 1.0.0 -> 1.1.0"]
    assert git.hard_reset_calls == []  # kept, never discarded


def test_batch_first_sequential_replay_divergence_failed_verification_falls_back():
    """Same divergence as above, but the verification test fails - the
    replay's commits are discarded (hard-reset) and every package goes
    through the ordinary per-package loop instead."""
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "1.1.0"]},
        lock_snapshots=[{"a": "mid"}, {"a": "final-different"}],
    )
    git = FakeGit(diff_results=[True, True, True], head_shas=["start-sha"])
    runner = FakeRunner(shell_results=[result(True), result(False), result(True)])

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir", strategy="batch-first")

    assert git.hard_reset_calls == ["start-sha"]
    assert len(runner.shell_calls) == 3  # batch test + failed verification + fallback's own test
    assert res.passed == ["a"]  # the per-package fallback's own attempt succeeds
    outcome = res.outcomes[0]
    assert outcome.strategy == "batch-first"
    assert outcome.tested_in_batch is False
    assert outcome.batch_test_failed is False  # the batch's own test genuinely passed


def test_batch_first_replay_update_itself_failing_discards_and_falls_back_immediately():
    """A replay step's own `update_package()` call failing outright (not
    just landing on a differently-resolved lock) skips the
    verification-test grace period entirely - there is no coherent
    replayed state left to verify."""
    backend = FakeBackend(
        update_ok={"a": False, "b": True},
        update_all_ok=True,  # the batch itself still resolves fine
        versions={"a": ["1.0.0", "1.1.0"], "b": ["2.0.0", "2.1.0"]},
    )
    git = FakeGit(diff_results=[True, True], head_shas=["start-sha"])
    runner = FakeRunner(shell_results=[result(True), result(True)])

    res = run_updates(backend, git, runner, ["a", "b"], "pytest", "dir", strategy="batch-first")

    assert git.hard_reset_calls == ["start-sha"]
    # a's own update fails again in the fresh per-package fallback too
    # (same update_ok); b still succeeds
    assert res.failed == ["a"]
    assert res.passed == ["b"]
    assert all(o.strategy == "batch-first" for o in res.outcomes)
    assert all(not o.tested_in_batch for o in res.outcomes)


def test_batch_first_replay_no_diff_and_not_at_target_is_a_real_failure():
    """Review fix: a replay step producing no lock change of its own is
    only ever excused (see the "already achieved" test below) when it
    landed exactly on the batch's own target version for that package - a
    genuine mismatch (no change, and not at the target either) is still
    a real replay failure, discarded and falling back to per-package."""
    backend = FakeBackend(
        update_ok={"a": True, "b": True},
        versions={"a": ["1.0.0", "1.1.0"], "b": ["2.0.0", "2.5.0", "2.0.0"]},
    )
    git = FakeGit(
        # batch check; a's own replay diff; b's own replay diff (false -
        # no change, and not at its 2.5.0 target either); then the fresh
        # per-package fallback loop's own diff check for a and for b
        diff_results=[True, True, False, True, True],
        head_shas=["start-sha"],
    )
    runner = FakeRunner(shell_results=[result(True), result(True), result(True)])

    res = run_updates(backend, git, runner, ["a", "b"], "pytest", "dir", strategy="batch-first")

    assert git.hard_reset_calls == ["start-sha"]
    assert res.passed == ["a", "b"]
    assert all(o.strategy == "batch-first" for o in res.outcomes)
    assert all(not o.tested_in_batch for o in res.outcomes)
    assert all(o.bundled_with is None for o in res.outcomes)


def test_batch_first_replay_package_already_at_target_needs_no_separate_commit():
    """Review fix: a package whose own replay step produces no lock
    change because an *earlier* package's own update already pulled it
    to the batch's target (a shared transitive dependency, most
    commonly - reproduced for real locally with jsonschema+attrs on both
    uv and Poetry) must not be treated as a replay failure - it is
    reported as updated (old -> the batch's target) with no separate
    commit of its own."""
    backend = FakeBackend(
        update_ok={"a": True, "b": True},
        versions={"a": ["1.0.0", "1.1.0"], "b": ["2.0.0", "2.5.0", "2.5.0"]},
    )
    # batch check; a's own replay diff; b's own replay diff (false - no
    # change of its own, because a's update already pulled it to 2.5.0)
    git = FakeGit(diff_results=[True, True, False])
    runner = FakeRunner(shell_results=[result(True)])

    res = run_updates(backend, git, runner, ["a", "b"], "pytest", "dir", strategy="batch-first")

    assert res.passed == ["a", "b"]
    assert len(runner.shell_calls) == 1  # still only the one batch test run
    # only one commit was made - for a; b's change is bundled into it
    assert git.commit_messages == ["Update a 1.0.0 -> 1.1.0"]

    outcomes = {o.name: o for o in res.outcomes}
    assert outcomes["a"].bundled_with is None
    assert outcomes["b"].old_version == "2.0.0"
    assert outcomes["b"].new_version == "2.5.0"
    assert outcomes["b"].bundled_with == "a"
    assert outcomes["b"].tested_in_batch is True
    assert outcomes["b"].strategy == "batch-first"


def test_batch_first_replay_commit_and_outcome_use_the_actual_replayed_version():
    """Review fix (blocker): the batch's own precomputed locked_version()
    read must never be trusted for the replay's own commit
    message/outcome once a resolver genuinely resolves this package to a
    different version alone (in the replay) than it did as part of the
    larger batch - re-read right after this package's own
    `update_package()` call instead. Reproduced by the reviewer as
    "commit says 1.1.0, lock has 1.1.9"."""
    backend = FakeBackend(
        update_ok={"a": True},
        versions={"a": ["1.0.0", "1.1.0", "1.1.9"]},
        lock_snapshots=[{"a": "mid"}, {"a": "final-different"}],
    )
    git = FakeGit(diff_results=[True, True])
    runner = FakeRunner(shell_results=[result(True), result(True)])

    res = run_updates(backend, git, runner, ["a"], "pytest", "dir", strategy="batch-first")

    assert res.passed == ["a"]
    assert git.commit_messages == ["Update a 1.0.0 -> 1.1.9"]
    assert res.outcomes[0].new_version == "1.1.9"


def test_batch_first_fallback_tags_outcomes_even_when_the_fallback_itself_aborts():
    """Review fix: a re-sync failure *inside* the per-package fallback
    loop (after the batch itself fell back to it) must still carry
    strategy/batch_test_failed on the partial outcomes in the raised
    UpdateAborted - not just on a result that never gets returned because
    the run raised instead of returning normally."""
    sync_call_count = {"n": 0}

    def flaky_sync():
        sync_call_count["n"] += 1
        # 1st call: the reset back to the start state before the
        # per-package fallback loop begins - must succeed, or the
        # fallback never even gets a chance to run. Every call after that
        # (inside the fallback loop itself, for b's own failure) fails.
        return result(sync_call_count["n"] == 1)

    backend = FakeBackend(update_ok={"a": True, "b": False}, update_all_ok=True)
    backend.sync = flaky_sync
    git = FakeGit(diff_results=[True, True])
    runner = FakeRunner(shell_results=[result(False, stderr="batch broke"), result(True)])

    with pytest.raises(UpdateAborted) as excinfo:
        run_updates(backend, git, runner, ["a", "b"], "pytest", "dir", strategy="batch-first")

    partial = excinfo.value.result
    assert [o.name for o in partial.outcomes] == ["a", "b"]
    assert all(o.strategy == "batch-first" for o in partial.outcomes)
    assert all(o.batch_test_failed for o in partial.outcomes)


def test_batch_first_no_packages_returns_empty_result():
    backend = FakeBackend()
    git = FakeGit()
    runner = FakeRunner()

    res = run_updates(backend, git, runner, [], "pytest", "dir", strategy="batch-first")

    assert res.outcomes == []


def test_batch_first_allow_major_layers_beyond_constraint_attempt_on_top_after_batch():
    """allow-major's beyond-constraint attempt always runs per-package, on
    top of a successful batch, each with its own test run - a package that
    gets both ends up with two commits but one outcome spanning the whole
    journey (issue #23's documented interaction with allow-major)."""
    backend = FakeBackend(
        update_ok={"a": True},
        # calls, in order: old, batch-new (unused for the commit itself
        # any more - see the replay-uses-actual-version fix), the
        # replay's own fresh read (2.0.0, no divergence intended here),
        # the post-replay correction read (2.0.0, unchanged), then the
        # beyond-constraint attempt's own attempted-version read (3.0.0)
        versions={"a": ["1.0.0", "2.0.0", "2.0.0", "2.0.0", "3.0.0"]},
        major_attempts={"a": MajorAttempt(resolve_result=result(True))},
    )
    git = FakeGit(diff_results=[True, True])
    runner = FakeRunner(shell_results=[result(True), result(True)])

    res = run_updates(
        backend, git, runner, ["a"], "pytest", "dir", allow_major=True, strategy="batch-first"
    )

    # one test for the batch, one for the beyond-constraint attempt on top
    assert len(runner.shell_calls) == 2
    assert git.commit_messages == [
        "Update a 1.0.0 -> 2.0.0",
        "Update a 1.0.0 -> 3.0.0 (constraint raised)",
    ]
    outcome = res.outcomes[0]
    assert outcome.status == "updated"
    assert outcome.old_version == "1.0.0"
    assert outcome.new_version == "3.0.0"
    assert outcome.constraint_raised is True
    assert outcome.bump == "major"
    assert outcome.strategy == "batch-first"


def test_batch_first_allow_major_held_back_attaches_to_the_batch_outcome():
    backend = FakeBackend(
        update_ok={"a": True},
        # same call shape as the test above: old, batch-new, the replay's
        # own read (2.0.0, kept - no divergence here), the post-replay
        # correction read (2.0.0), then the held-back beyond-constraint
        # attempt's own attempted-version read (2.5.0)
        versions={"a": ["1.0.0", "2.0.0", "2.0.0", "2.0.0", "2.5.0"]},
        major_attempts={
            "a": MajorAttempt(resolve_result=result(False, stderr="could not resolve"))
        },
    )
    git = FakeGit(diff_results=[True, True])
    runner = FakeRunner()

    res = run_updates(
        backend, git, runner, ["a"], "", "dir", allow_major=True, strategy="batch-first"
    )

    outcome = res.outcomes[0]
    assert outcome.status == "updated"
    assert outcome.old_version == "1.0.0"
    assert outcome.new_version == "2.0.0"  # the batch's own in-range result, kept
    assert outcome.beyond_constraint_version == "2.5.0"
    assert outcome.beyond_constraint_failure_kind == "resolution"
    assert outcome.strategy == "batch-first"


# --- run_transitive_update (update-transitive, issue #24) -------------------


def test_transitive_update_unchanged_when_lock_does_not_change():
    backend = FakeBackend()
    git = FakeGit(diff_results=[False])
    runner = FakeRunner()
    res = UpdateResult()

    run_transitive_update(backend, git, runner, "pytest", "dir", res)

    assert res.transitive.status == "unchanged"
    assert res.transitive.changed_packages == []
    assert res.transitive.failure_kind is None
    assert git.commit_messages == []
    assert git.reset_calls == []
    assert runner.shell_calls == []
    assert backend.update_transitive_calls == 1


def test_transitive_update_passes_and_commits_changed_packages():
    backend = FakeBackend(
        lock_snapshots=[
            {"a": "1.0.0", "b": "2.0.0"},
            {"a": "1.1.0", "b": "2.0.0", "c": "3.0.0"},
        ]
    )
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()
    res = UpdateResult()

    run_transitive_update(backend, git, runner, "pytest", "dir", res)

    assert res.transitive.status == "updated"
    assert res.transitive.failure_kind is None
    changed = {p.name: (p.old, p.new) for p in res.transitive.changed_packages}
    assert changed == {"a": ("1.0.0", "1.1.0"), "c": (None, "3.0.0")}
    assert git.commit_messages == ["Update transitive dependencies"]
    assert git.staged_calls == [[backend.lock_file]]
    assert git.reset_calls == []
    assert runner.shell_calls == [("pytest", "dir")]


def test_transitive_update_skips_test_when_no_test_command_given():
    backend = FakeBackend(lock_snapshots=[{"a": "1.0.0"}, {"a": "1.1.0"}])
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()
    res = UpdateResult()

    run_transitive_update(backend, git, runner, "", "dir", res)

    assert res.transitive.status == "updated"
    assert runner.shell_calls == []
    assert git.commit_messages == ["Update transitive dependencies"]


def test_transitive_update_test_failure_resets_and_reports():
    backend = FakeBackend(lock_snapshots=[{"a": "1.0.0"}, {"a": "1.1.0"}])
    git = FakeGit(diff_results=[True])
    runner = FakeRunner(shell_results=[result(False, stdout="boom", stderr="err")])
    res = UpdateResult()

    run_transitive_update(backend, git, runner, "pytest", "dir", res)

    assert res.transitive.status == "failed"
    assert res.transitive.failure_kind == "test"
    assert "boom" in res.transitive.output_tail
    assert [p.name for p in res.transitive.changed_packages] == ["a"]
    assert git.commit_messages == []
    assert git.reset_calls == [[backend.lock_file]]
    assert backend.sync_calls == 1


def test_transitive_update_resolution_failure_resets_and_reports():
    backend = FakeBackend(update_transitive_ok=False, update_transitive_stderr="could not resolve")
    git = FakeGit(diff_results=[])
    runner = FakeRunner()
    res = UpdateResult()

    run_transitive_update(backend, git, runner, "pytest", "dir", res)

    assert res.transitive.status == "failed"
    assert res.transitive.failure_kind == "resolution"
    assert "could not resolve" in res.transitive.output_tail
    assert res.transitive.changed_packages == []
    assert git.commit_messages == []
    assert git.reset_calls == [[backend.lock_file]]
    assert runner.shell_calls == []


def test_transitive_update_resync_failure_aborts_but_keeps_the_outcome():
    backend = FakeBackend(sync_ok=False, lock_snapshots=[{"a": "1.0.0"}, {"a": "1.1.0"}])
    git = FakeGit(diff_results=[True])
    runner = FakeRunner(shell_results=[result(False, stdout="fail")])
    res = UpdateResult()

    with pytest.raises(UpdateAborted) as exc_info:
        run_transitive_update(backend, git, runner, "pytest", "dir", res)

    # The failed outcome is set before the reset+resync is even attempted,
    # so it survives on both the original result object and the one the
    # abort carries.
    assert res.transitive.status == "failed"
    assert exc_info.value.result is res


def test_transitive_update_never_touches_the_manifest():
    """Backend.update_transitive() is documented to only ever change the
    lock file - files_to_stage() (lock only), not major_files_to_stage()
    (lock + manifest), is what gets staged/reset."""
    backend = FakeBackend(lock_snapshots=[{"a": "1.0.0"}, {"a": "1.1.0"}])
    git = FakeGit(diff_results=[True])
    runner = FakeRunner()
    res = UpdateResult()

    run_transitive_update(backend, git, runner, "", "dir", res)

    assert backend.major_files_to_stage_calls == 0
    assert git.staged_calls == [[backend.lock_file]]
