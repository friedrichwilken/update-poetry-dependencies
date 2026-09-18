from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .backend import Backend
from .errors import UpdateAborted
from .git_repo import GitRepo
from .pep440 import bump_kind as _bump_kind
from .runner import CommandRunner
from .textcap import capture_tail

# Kept as small string literals rather than a full enum class on purpose:
# a Literal is trivially extended by adding another string to the union at
# the call site.
Status = Literal["updated", "failed", "skipped"]
FailureKind = Literal["resolution", "test"] | None
Bump = Literal["major", "minor", "patch", "other"] | None


@dataclass
class PackageOutcome:
    """One top-level package's result for a single run.

    `old_version`/`new_version` are read straight from the lock file
    (`Backend.locked_version`), not the installed environment. For a
    failed package, `new_version` is the version that was attempted (read
    right after the update, before the reset). `output_tail` is only ever
    populated for a failed package - the tail of whichever output is
    relevant to `failure_kind` (resolver output for "resolution", test
    command output for "test").

    The `bump`/`constraint_raised`/`beyond_constraint_*` fields are
    additive, only ever set when `allow-major` is enabled (issue #21), and
    otherwise stay at their default (falsy) values - `report.py` relies on
    that to keep `report-json`'s shape byte-identical to before the
    feature existed when it is not in use:

    - `bump` is the actual release segment that changed between
      `old_version` and `new_version` for *any* "updated" outcome while
      `allow-major` is enabled (not just one that raised the constraint) -
      `"major"`, `"minor"`, `"patch"`, or `"other"` (see
      `pep440.bump_kind`). An update beyond the declared constraint is not
      necessarily a semver-major bump (`six >=1.10,<1.15` allowing
      `1.17.0` is a minor bump that merely exceeded the declared range),
      so this is never assumed - it is always computed from the actual
      version numbers.
    - `constraint_raised` is `True` exactly when this outcome's own commit
      raised the declared constraint itself (as opposed to a plain
      in-range update, which never touches the manifest).
    - `beyond_constraint_version`/`beyond_constraint_failure_kind`/
      `beyond_constraint_output_tail` are set when an attempt to go beyond
      the declared constraint was made but held back (resolution or test
      failure, or discarded - see `major.MajorAttempt` - both surface here
      as `failure_kind`), regardless of what `status` ended up being for
      the (possibly still successful) in-range update alongside it.
    - `beyond_constraint_skip_reason` is set when `allow-major` is enabled
      but no attempt could be made at all, for a package whose declared
      constraint has an upper bound but whose declaration shape is not one
      this feature can safely rewrite (git/path/url source, an
      environment marker, an exact pin, ...), or whose attempt succeeded
      but had to be discarded (changed more than the version constraint,
      or landed on an unwanted pre-release) - reported this way rather
      than as a failure_kind, since the tool itself did not fail.

    `strategy`/`tested_in_batch`/`batch_test_failed` are additive, only
    ever set when `strategy="batch-first"` (issue #23), and otherwise stay
    at their default (falsy) values - the default `strategy="per-package"`
    run renders/serializes byte-identically to before this feature
    existed:

    - `strategy` is `"batch-first"` on every outcome of a batch-first run,
      whichever path actually produced it (the batch's own one-shot test,
      a verification re-test after a sequential-replay divergence, or a
      per-package fallback) - it records what was *requested*, not
      necessarily what happened.
    - `tested_in_batch` is `True` for a package whose committed update was
      validated by one shared test run covering every package at once
      (the batch's own test, or - after a sequential-replay divergence -
      the one verification re-test of the replayed result) rather than by
      its own dedicated per-package test run.
    - `batch_test_failed` is `True` on every outcome when the batch's own
      one-shot test run failed and this run fell back to the ordinary
      per-package loop for everything.
    - `bundled_with` is set (to another package's name) when this
      package's own sequential-replay step produced no lock change of its
      own because it was already sitting at the batch's target version -
      pulled there as a side effect of an *earlier* package's own update
      in the same replay (most commonly a shared transitive dependency).
      It is still reported as `updated` (old -> the batch's target), but
      no separate commit exists for it - the change already lives in
      whichever package's commit `bundled_with` names (see
      `_replay_sequential`).
    """

    name: str
    status: Status
    old_version: str | None = None
    new_version: str | None = None
    failure_kind: FailureKind = None
    output_tail: str = ""
    bump: Bump = None
    constraint_raised: bool = False
    beyond_constraint_version: str | None = None
    beyond_constraint_failure_kind: FailureKind = None
    beyond_constraint_output_tail: str = ""
    beyond_constraint_skip_reason: str | None = None
    strategy: str | None = None
    tested_in_batch: bool = False
    batch_test_failed: bool = False
    bundled_with: str | None = None

    @property
    def held_back_beyond_constraint(self) -> bool:
        return (
            self.beyond_constraint_version is not None
            or self.beyond_constraint_failure_kind is not None
        )


TransitiveStatus = Literal["updated", "failed", "unchanged"]


@dataclass
class ChangedTransitivePackage:
    """One package's before/after version in a passing/failing
    `TransitiveOutcome` - never just a name, so the report can show what
    actually moved even when the step's own commit was discarded."""

    name: str
    old: str | None
    new: str | None


@dataclass
class TransitiveOutcome:
    """The result of the one, final `update-transitive` step (issue #24) -
    run once per run, after the top-level loop (and any beyond-constraint
    attempts) - never a `PackageOutcome`: it has no single old/new version
    of its own, only a set of packages the lock-wide refresh touched, so it
    gets its own shape and its own `transitive-report` output/PR-body
    section instead of a synthetic entry in `report-json`'s per-package
    array (see `report.py`).

    - `"unchanged"`: the refresh (`poetry update --lock` / `uv lock
      --upgrade`) found nothing left to update within existing constraints
      - no test ran, nothing was committed.
    - `"updated"`: the lock changed and the test command passed (or none
      was given) - committed as `Update transitive dependencies`.
      `changed_packages` lists every package the lock's own before/after
      snapshot (`Backend.all_locked_versions()`) differed on, not just
      those this step's own resolution step directly targeted - exactly
      like any other lock refresh, moving one package can move others.
    - `"failed"`: the lock changed but the test command failed (`test`) or
      the refresh command itself failed to resolve (`resolution`) - the
      lock file is reset back to its pre-step state and the environment
      re-synced; `changed_packages` still lists what *would* have changed
      (empty for a `"resolution"` failure_kind, before anything to diff
      existed), and `output_tail` carries the tail of whichever output is
      relevant (see `PackageOutcome.output_tail`'s own docstring for the
      same convention).
    """

    status: TransitiveStatus
    changed_packages: list[ChangedTransitivePackage] = field(default_factory=list)
    failure_kind: FailureKind = None
    output_tail: str = ""


@dataclass
class UpdateResult:
    outcomes: list[PackageOutcome] = field(default_factory=list)
    # None until the update-transitive step actually runs (feature off, or
    # not yet reached - e.g. an abort during the top-level loop) - see
    # TransitiveOutcome and run_transitive_update().
    transitive: TransitiveOutcome | None = None

    # Convenient accessors kept for byte-compatibility with the existing
    # `passed-packages`/`failed-packages`/`skipped-packages` outputs, which
    # are just comma separated package names.
    @property
    def passed(self) -> list[str]:
        return [o.name for o in self.outcomes if o.status == "updated"]

    @property
    def failed(self) -> list[str]:
        return [o.name for o in self.outcomes if o.status == "failed"]

    @property
    def skipped(self) -> list[str]:
        return [o.name for o in self.outcomes if o.status == "skipped"]

    @property
    def held_back(self) -> list[str]:
        return [o.name for o in self.outcomes if o.held_back_beyond_constraint]


def _fmt_version(version: str | None) -> str:
    return version if version else "unknown"


def _reset_and_resync(
    backend: Backend, git: GitRepo, files: list[str], package: str, result: UpdateResult
) -> None:
    """Discard the lock file change for `package` and re-sync the
    environment to it. If the re-sync itself fails, the environment is left
    in an unknown state and it is not safe to keep testing later packages
    against it, so this aborts the whole run (packages already committed
    stay committed) - raising `UpdateAborted` rather than a bare
    `ActionError` so the partial `result` built so far is not lost."""
    git.reset_files(files)
    sync_result = backend.sync()
    print(sync_result.stdout)
    print(sync_result.stderr)
    if not sync_result.ok:
        raise UpdateAborted(
            f"failed to re-sync the environment to the lock file after "
            f"{package}; aborting to avoid testing later packages against a "
            f"broken environment",
            result,
        )


def _run_test_command(
    runner: CommandRunner, test_command: str, directory: str, package: str
) -> tuple[object, bool]:
    if not test_command:
        return None, True
    print(f"running test command for {package}: {test_command}")
    test_result = runner.run_shell(test_command, cwd=directory)
    return test_result, test_result.ok


def _in_range_update(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    package: str,
    test_command: str,
    directory: str,
    old_version: str | None,
    files: list[str],
) -> tuple[PackageOutcome, bool]:
    """The plain, in-constraint update for one package - today's whole
    behaviour, unchanged. Returns the outcome and whether the caller still
    needs to reset+resync `files` afterwards (true for either failure
    kind, false for "updated"/"skipped")."""
    update_result = backend.update_package(package)
    print(update_result.stdout)
    print(update_result.stderr)

    if not update_result.ok:
        print(f"update failed for {package}, discarding changes")
        attempted_version = backend.locked_version(package)
        outcome = PackageOutcome(
            name=package,
            status="failed",
            old_version=old_version,
            new_version=attempted_version,
            failure_kind="resolution",
            output_tail=capture_tail(update_result.stdout + "\n" + update_result.stderr),
        )
        return outcome, True

    if not git.diff_changed(files):
        print(f"no update available for {package}")
        outcome = PackageOutcome(
            name=package, status="skipped", old_version=old_version, new_version=old_version
        )
        return outcome, False

    new_version = backend.locked_version(package)
    test_result, test_passed = _run_test_command(runner, test_command, directory, package)

    if test_passed:
        print(f"update for {package} passed")
        git.stage(files)
        git.commit(f"Update {package} {_fmt_version(old_version)} -> {_fmt_version(new_version)}")
        outcome = PackageOutcome(
            name=package, status="updated", old_version=old_version, new_version=new_version
        )
        return outcome, False

    print(f"test failed for {package}, discarding changes")
    outcome = PackageOutcome(
        name=package,
        status="failed",
        old_version=old_version,
        new_version=new_version,
        failure_kind="test",
        output_tail=capture_tail(test_result.stdout + "\n" + test_result.stderr),
    )
    return outcome, True


def _reset_beyond_constraint_or_abort_with_outcome(
    backend: Backend,
    git: GitRepo,
    beyond_files: list[str],
    package: str,
    result: UpdateResult,
    old_version: str | None,
    attempted_version: str | None,
    failure_kind: str,
    output_tail: str,
) -> None:
    """Reset+resync the beyond-constraint attempt's files. The plain
    in-range failure paths already append their outcome to
    `result.outcomes` *before* resetting, so an abort there never drops
    the package it happened on - but at this point in the
    beyond-constraint flow no outcome for `package` exists yet (it is
    normally attached to whatever the in-range fallback produces
    afterwards). If the reset itself aborts the run, record a `failed`
    outcome for `package` first so the partial result does not silently
    drop it."""
    try:
        _reset_and_resync(backend, git, beyond_files, package, result)
    except UpdateAborted as exc:
        result.outcomes.append(
            PackageOutcome(
                name=package,
                status="failed",
                old_version=old_version,
                new_version=attempted_version,
                failure_kind=failure_kind,
                output_tail=capture_tail(f"{output_tail}\n{exc}"),
            )
        )
        raise


def _attempt_beyond_constraint(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    package: str,
    test_command: str,
    directory: str,
    old_version: str | None,
    result: UpdateResult,
) -> tuple[PackageOutcome | None, tuple[str | None, str, str] | None, str | None]:
    """Try to raise `package`'s declared constraint beyond its current
    upper bound (issue #21). Returns a 3-tuple:

    - a finished `PackageOutcome` if the attempt itself passed and was
      committed (the caller should record it and move on to the next
      package without an in-range update at all);
    - else, a `(attempted_version, failure_kind, output_tail)` "held back"
      tuple if an attempt was made but failed, or had to be discarded -
      the manifest/lock have already been reset+resynced, and the caller
      should still run the plain in-range update and attach this to
      whatever outcome that produces;
    - else, a skip reason string if `allow-major` is enabled but no
      attempt could be made for this package at all, or its
      otherwise-successful attempt had to be discarded (or None if none
      of the above apply - no attempt was needed in the first place).
    """
    attempt = backend.try_major(package)
    if attempt is None:
        return None, None, None
    if attempt.skip_reason is not None:
        return None, None, attempt.skip_reason

    resolve_result = attempt.resolve_result
    print(resolve_result.stdout)
    print(resolve_result.stderr)
    beyond_files = backend.major_files_to_stage()

    if attempt.discarded_reason is not None:
        attempted_version = backend.locked_version(package)
        print(f"beyond-constraint update for {package} discarded: {attempt.discarded_reason}")
        _reset_beyond_constraint_or_abort_with_outcome(
            backend,
            git,
            beyond_files,
            package,
            result,
            old_version,
            attempted_version,
            "resolution",
            capture_tail(resolve_result.stdout + "\n" + resolve_result.stderr),
        )
        return None, None, attempt.discarded_reason

    if resolve_result.ok:
        attempted_version = backend.locked_version(package)
        test_result, test_passed = _run_test_command(runner, test_command, directory, package)
        if test_passed:
            print(f"beyond-constraint update for {package} passed")
            git.stage(beyond_files)
            git.commit(
                f"Update {package} {_fmt_version(old_version)} -> "
                f"{_fmt_version(attempted_version)} (constraint raised)"
            )
            outcome = PackageOutcome(
                name=package,
                status="updated",
                old_version=old_version,
                new_version=attempted_version,
                bump=_bump_kind(old_version, attempted_version),
                constraint_raised=True,
            )
            return outcome, None, None
        held_back = (
            attempted_version,
            "test",
            capture_tail(test_result.stdout + "\n" + test_result.stderr),
        )
    else:
        attempted_version = backend.locked_version(package)
        held_back = (
            attempted_version,
            "resolution",
            capture_tail(resolve_result.stdout + "\n" + resolve_result.stderr),
        )

    print(f"beyond-constraint update for {package} held back, falling back to the in-range update")
    _reset_beyond_constraint_or_abort_with_outcome(
        backend, git, beyond_files, package, result, old_version, *held_back
    )
    return None, held_back, None


def _run_per_package(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    packages: list[str],
    test_command: str,
    directory: str,
    allow_major: bool = False,
) -> UpdateResult:
    """Update each top-level package one by one. A package is:

    - skipped if `poetry update` succeeds but the lock file does not change
    - failed if `poetry update` itself fails (failure_kind "resolution"), or
      if it changes the lock file but the test command fails (failure_kind
      "test"); either way the lock file is reset to HEAD and the
      environment is re-synced before moving on to the next package
    - passed if the lock file changed and the test command succeeded (or no
      test command was given); the lock file is committed

    When `allow_major` is true (issue #21), each package is first offered
    an attempt to go beyond its declared constraint (`Backend.try_major`):
    raise it so the latest release is allowed, re-lock just that package,
    and test it exactly like an in-range update. A passing attempt is
    committed on its own (`constraint_raised=True`, `bump` set to whatever
    release segment actually changed - not necessarily "major") and the
    package is done - no separate in-range update runs for it. A failing
    attempt (resolution or test, or one that had to be discarded) is reset
    and reported as "held back" on whatever outcome the ordinary in-range
    update produces instead, which still runs normally; when that in-range
    outcome is itself "updated", it also gets its own `bump` computed, so
    every "updated" outcome in an `allow_major` run reports a truthful
    `bump` regardless of which path produced it. When `allow_major` is
    false, `pyproject.toml` is never read or touched by this loop at all.
    """
    result = UpdateResult()
    files = backend.files_to_stage()

    for package in packages:
        print(f"::group::updating {package}")
        old_version = backend.locked_version(package)

        held_back = None
        beyond_constraint_skip_reason = None
        if allow_major:
            beyond_outcome, held_back, beyond_constraint_skip_reason = _attempt_beyond_constraint(
                backend, git, runner, package, test_command, directory, old_version, result
            )
            if beyond_outcome is not None:
                result.outcomes.append(beyond_outcome)
                print("::endgroup::")
                continue

        outcome, needs_reset = _in_range_update(
            backend, git, runner, package, test_command, directory, old_version, files
        )
        if held_back is not None:
            (
                outcome.beyond_constraint_version,
                outcome.beyond_constraint_failure_kind,
                outcome.beyond_constraint_output_tail,
            ) = held_back
        if beyond_constraint_skip_reason is not None:
            outcome.beyond_constraint_skip_reason = beyond_constraint_skip_reason
        if allow_major and outcome.status == "updated":
            outcome.bump = _bump_kind(outcome.old_version, outcome.new_version)
        result.outcomes.append(outcome)
        if needs_reset:
            _reset_and_resync(backend, git, files, package, result)

        print("::endgroup::")

    return result


def _discard_commits_since(
    backend: Backend, git: GitRepo, start_sha: str, context: str, result: UpdateResult
) -> None:
    """Hard-reset away any commits (and any leftover uncommitted change)
    made since `start_sha`, then re-sync the environment to match. Only
    used by the batch-first strategy to undo its own not-yet-pushed
    sequential-replay commits when they turn out not to be trustworthy
    (see `_run_batch_first`) - mirrors `_reset_and_resync`'s
    abort-on-resync-failure contract, just for a whole run of commits
    instead of one file reset."""
    git.reset_hard(start_sha)
    sync_result = backend.sync()
    print(sync_result.stdout)
    print(sync_result.stderr)
    if not sync_result.ok:
        raise UpdateAborted(
            f"failed to re-sync the environment after discarding {context}; aborting",
            result,
        )


def _fall_back_to_per_package(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    packages: list[str],
    test_command: str,
    directory: str,
    allow_major: bool,
    batch_test_failed: bool,
) -> UpdateResult:
    """Runs the plain per-package loop (shared, unchanged - see
    `_run_per_package`) and tags every outcome it produces with
    `strategy="batch-first"` (this run still requested batch-first, even
    though every package ended up going through the per-package path) and,
    when the batch's own test is what triggered the fallback,
    `batch_test_failed=True`.

    Also tags an `UpdateAborted` raised *by* `_run_per_package` itself (a
    re-sync failure partway through the fallback loop) - its carried
    partial result is real, already-committed outcomes, and must not be
    reported as if they came from a plain, untagged per-package run just
    because the tagging loop below never got to run on them."""
    try:
        result = _run_per_package(
            backend, git, runner, packages, test_command, directory, allow_major
        )
    except UpdateAborted as exc:
        for outcome in exc.result.outcomes:
            outcome.strategy = "batch-first"
            if batch_test_failed:
                outcome.batch_test_failed = True
        raise
    for outcome in result.outcomes:
        outcome.strategy = "batch-first"
        if batch_test_failed:
            outcome.batch_test_failed = True
    return result


def _finish_batch_first(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    packages: list[str],
    outcomes_by_name: dict[str, PackageOutcome],
    old_versions: dict[str, str | None],
    test_command: str,
    directory: str,
    allow_major: bool,
) -> UpdateResult:
    """Common tail end of a successful batch-first run (the batch's lock
    change tested clean, and the sequential per-package replay either
    matched it exactly or was itself re-verified - see `_run_batch_first`):
    optionally layer the beyond-constraint attempts on top (issue #21's
    `allow-major`, "keep it simple" per the batch-first design - the batch
    step itself only ever does in-range updates; beyond-constraint attempts
    always run per-package, each tested on its own, same as they would
    without batch-first at all), then return the outcomes in `packages`
    order.

    A beyond-constraint attempt that succeeds replaces whatever outcome the
    batch/replay produced for that package outright (its own commit lands
    on top of the replay's, and the reported old/new/bump span the whole
    journey from before the batch ran); one that is held back or skipped
    just attaches its `beyond_constraint_*`/`beyond_constraint_skip_reason`
    fields onto that outcome, exactly like the per-package loop does."""
    if allow_major:
        # _attempt_beyond_constraint's own abort-with-outcome helper needs
        # an UpdateResult to attach a failed outcome to and carry along in
        # UpdateAborted - reuse whatever has been decided so far, in
        # `packages` order, so an abort here reports on exactly what is
        # really committed at that point.
        running_result = UpdateResult(
            outcomes=[outcomes_by_name[p] for p in packages if p in outcomes_by_name]
        )
        for package in packages:
            old_version = old_versions[package]
            beyond_outcome, held_back, beyond_constraint_skip_reason = _attempt_beyond_constraint(
                backend, git, runner, package, test_command, directory, old_version, running_result
            )
            if beyond_outcome is not None:
                beyond_outcome.strategy = "batch-first"
                outcomes_by_name[package] = beyond_outcome
                continue

            outcome = outcomes_by_name.get(package)
            if outcome is None:
                continue
            if held_back is not None:
                (
                    outcome.beyond_constraint_version,
                    outcome.beyond_constraint_failure_kind,
                    outcome.beyond_constraint_output_tail,
                ) = held_back
            if beyond_constraint_skip_reason is not None:
                outcome.beyond_constraint_skip_reason = beyond_constraint_skip_reason
            if outcome.status == "updated":
                outcome.bump = _bump_kind(outcome.old_version, outcome.new_version)

    return UpdateResult(outcomes=[outcomes_by_name[p] for p in packages if p in outcomes_by_name])


def _replay_sequential(
    backend: Backend,
    git: GitRepo,
    files: list[str],
    old_versions: dict[str, str | None],
    new_versions: dict[str, str | None],
    changed_packages: list[str],
) -> tuple[dict[str, PackageOutcome], bool]:
    """Replays each of `changed_packages`' own update, committed on its
    own, without testing in between (the sequential-replay half of
    `_run_batch_first`'s happy path). Returns `(outcomes_by_name,
    replay_step_failed)`:

    - `outcomes_by_name` only ever covers `changed_packages` - the caller
      fills in "skipped" outcomes for the rest.
    - `replay_step_failed` is `True` when a replay step itself could not
      be trusted (its own `update_package()` call failed, or it produced
      neither a lock change nor landed on the batch's own target version
      for that package) - the caller discards everything and falls back
      in that case, never attempting the verification-test grace period:
      unlike a *complete* replay simply landing on a different (but
      internally consistent) lock than the batch did - which the caller
      handles separately, by comparing `Backend.all_locked_versions()` -
      this leaves nothing coherent left to verify.

    Two corrections on top of the batch's own precomputed `new_versions`,
    both because a resolver can behave differently resolving one package
    alone (in the replay) than as part of the larger batch:

    - a package's own commit message/outcome always use its version as
      read fresh right after its own `update_package()` call, never the
      batch's precomputed value, which can already be stale by the time
      this package's own replay step actually runs (issue #23 review: a
      commit claiming one version while the lock actually holds another);
    - a package that produces no lock change of its own but is already
      sitting at the batch's target version was pulled there as a side
      effect of an *earlier* package's own update in this same replay - a
      shared transitive dependency, most commonly (issue #23 review: e.g.
      updating jsonschema alone already pulls in the attrs version the
      batch wanted, so attrs's own replay step has nothing left to do).
      That is not a failure: it is reported as `updated` anyway (old ->
      the batch's target) with no separate commit of its own - the change
      already lives in whichever package's commit `bundled_with` names
      (`None` only if that is somehow the very first replay step, which
      should not happen: the start state was just reset to, so the first
      changed package cannot already be at its target).

    After every changed package has been processed, every outcome's
    `new_version` is refreshed once more straight from the lock, in case
    a *later* package's own update further changed an *earlier*,
    already-committed package's version - the already-written commit
    message cannot be retroactively fixed, but the reported outcome
    always reflects the true final state.
    """
    outcomes_by_name: dict[str, PackageOutcome] = {}
    last_committed_package: str | None = None

    for package in changed_packages:
        update_result = backend.update_package(package)
        print(update_result.stdout)
        print(update_result.stderr)
        if not update_result.ok:
            return outcomes_by_name, True

        if not git.diff_changed(files):
            already_at_target = backend.locked_version(package) == new_versions[package]
            if not already_at_target:
                # A real mismatch: this package's own replay neither
                # changed anything nor landed on what the batch achieved
                # for it - nothing coherent left to verify.
                return outcomes_by_name, True
            outcomes_by_name[package] = PackageOutcome(
                name=package,
                status="updated",
                old_version=old_versions[package],
                new_version=new_versions[package],
                strategy="batch-first",
                tested_in_batch=True,
                bundled_with=last_committed_package,
            )
            continue

        actual_new_version = backend.locked_version(package)
        git.stage(files)
        git.commit(
            f"Update {package} {_fmt_version(old_versions[package])} -> "
            f"{_fmt_version(actual_new_version)}"
        )
        last_committed_package = package
        outcomes_by_name[package] = PackageOutcome(
            name=package,
            status="updated",
            old_version=old_versions[package],
            new_version=actual_new_version,
            strategy="batch-first",
            tested_in_batch=True,
        )

    for package in changed_packages:
        outcomes_by_name[package].new_version = backend.locked_version(package)

    return outcomes_by_name, False


def _run_batch_first(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    packages: list[str],
    test_command: str,
    directory: str,
    allow_major: bool,
) -> UpdateResult:
    """Update every top-level package in one go and test once, instead of
    once per package (issue #23) - cuts N test runs down to close to 1 in
    the happy path:

    1. `Backend.update_all(packages)` (in-range only; `allow-major`'s
       beyond-constraint attempts are always layered on afterwards,
       per-package - see `_finish_batch_first`). If the lock does not
       change at all, every package is reported "skipped" and nothing is
       tested.
    2. Otherwise, the test command runs once against the whole batch.
       - Fails -> reset+re-sync to the start state and fall back to the
         ordinary per-package loop for every package (worst case: N+1 test
         runs total) - `batch_test_failed=True` on every outcome.
       - Passes -> reset to the start state again, then replay each
         changed package's own `update_package()` + commit, in sequence,
         *without* testing in between (see `_replay_sequential` for two
         corrections this applies on top of the batch's own precomputed
         versions - a package's commit/outcome always uses its version as
         read fresh right after its own replay step, and a package
         already pulled to its target by an *earlier* package's replay
         step - e.g. a shared transitive dependency - needs no separate
         commit of its own), so the git history looks the same as a
         per-package run would have produced. Once every package has been
         replayed, its result is compared against the batch's own lock
         (`Backend.all_locked_versions()`) - a resolver can be
         order-sensitive for transitive dependencies, so a replayed
         package-by-package resolution is not guaranteed to reproduce the
         exact same lock the all-at-once batch update did.
         - Matches -> done; every replayed package is reported "updated"
           with `tested_in_batch=True` (validated by the batch's one test
           run, not its own).
         - Diverges (or a replay step itself could not be trusted at all -
           see `_replay_sequential`) -> one more test run, against the
           diverged sequential result. Passes -> keep it (still
           `tested_in_batch=True` - validated by this one verification run
           covering everything). Fails -> hard-reset away every replay
           commit and fall back to the ordinary per-package loop for every
           package instead (this path never sets `batch_test_failed` - the
           batch's own test did pass; it is the replay that could not be
           trusted).

    A re-sync failure at any point aborts the whole run with whatever
    partial result exists at that point, exactly like the per-package
    loop (`UpdateAborted`, carrying the partial `UpdateResult`)."""
    if not packages:
        return UpdateResult()

    files = backend.files_to_stage()
    start_sha = git.head_sha()
    old_versions = {package: backend.locked_version(package) for package in packages}

    print("::group::batch update")
    batch_result = backend.update_all(packages)
    print(batch_result.stdout)
    print(batch_result.stderr)

    if not batch_result.ok:
        print("batch update failed to resolve; falling back to the per-package loop")
        print("::endgroup::")
        abort_result = UpdateResult()
        _reset_and_resync(backend, git, files, "batch update", abort_result)
        return _fall_back_to_per_package(
            backend, git, runner, packages, test_command, directory, allow_major, False
        )

    if not git.diff_changed(files):
        print("nothing to update in the batch")
        print("::endgroup::")
        return UpdateResult(
            outcomes=[
                PackageOutcome(
                    name=package,
                    status="skipped",
                    old_version=old_versions[package],
                    new_version=old_versions[package],
                    strategy="batch-first",
                )
                for package in packages
            ]
        )

    new_versions = {package: backend.locked_version(package) for package in packages}
    changed_packages = [p for p in packages if new_versions[p] != old_versions[p]]
    batch_snapshot = backend.all_locked_versions()

    _, test_passed = _run_test_command(runner, test_command, directory, "batch update")
    print("::endgroup::")

    if not test_passed:
        print("batch update failed the test command; falling back to the per-package loop")
        abort_result = UpdateResult()
        _reset_and_resync(backend, git, files, "batch update", abort_result)
        return _fall_back_to_per_package(
            backend, git, runner, packages, test_command, directory, allow_major, True
        )

    # The batch passed - reset to the start state and replay each changed
    # package's own update, committed on its own, without testing again.
    abort_result = UpdateResult()
    _reset_and_resync(backend, git, files, "batch update", abort_result)

    outcomes_by_name, replay_step_failed = _replay_sequential(
        backend, git, files, old_versions, new_versions, changed_packages
    )

    if replay_step_failed:
        print(
            "batch-first sequential replay itself failed partway through; "
            "discarding it and falling back to the per-package loop"
        )
        discard_result = UpdateResult()
        _discard_commits_since(
            backend, git, start_sha, "the batch-first sequential replay", discard_result
        )
        return _fall_back_to_per_package(
            backend, git, runner, packages, test_command, directory, allow_major, False
        )

    for package in packages:
        if package not in changed_packages:
            outcomes_by_name[package] = PackageOutcome(
                name=package,
                status="skipped",
                old_version=old_versions[package],
                new_version=old_versions[package],
                strategy="batch-first",
            )

    if backend.all_locked_versions() == batch_snapshot:
        return _finish_batch_first(
            backend,
            git,
            runner,
            packages,
            outcomes_by_name,
            old_versions,
            test_command,
            directory,
            allow_major,
        )

    print(
        "sequential replay does not match the batch lock; running one "
        "final verification test before trusting it"
    )
    _, verify_passed = _run_test_command(
        runner, test_command, directory, "batch replay verification"
    )
    if verify_passed:
        print("sequential replay verified; keeping it")
        return _finish_batch_first(
            backend,
            git,
            runner,
            packages,
            outcomes_by_name,
            old_versions,
            test_command,
            directory,
            allow_major,
        )

    print(
        "sequential replay failed verification; discarding it and falling back "
        "to the per-package loop"
    )
    discard_result = UpdateResult()
    _discard_commits_since(
        backend, git, start_sha, "the batch-first sequential replay", discard_result
    )
    return _fall_back_to_per_package(
        backend, git, runner, packages, test_command, directory, allow_major, False
    )


def run_updates(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    packages: list[str],
    test_command: str,
    directory: str,
    allow_major: bool = False,
    strategy: str = "per-package",
) -> UpdateResult:
    """Entry point: dispatches to `_run_batch_first` (issue #23) when
    `strategy` is `"batch-first"`, else `_run_per_package` (today's
    behavior, the default - see its own docstring). Every other input has
    the exact same meaning either way; see `_run_batch_first`'s docstring
    for how it cuts down the number of test runs and when/how it falls
    back to the per-package loop."""
    if strategy == "batch-first":
        return _run_batch_first(
            backend, git, runner, packages, test_command, directory, allow_major
        )
    return _run_per_package(backend, git, runner, packages, test_command, directory, allow_major)


def _diff_locked_versions(
    before: dict[str, str], after: dict[str, str]
) -> list[ChangedTransitivePackage]:
    names = sorted(set(before) | set(after))
    return [
        ChangedTransitivePackage(name=name, old=before.get(name), new=after.get(name))
        for name in names
        if before.get(name) != after.get(name)
    ]


def run_transitive_update(
    backend: Backend,
    git: GitRepo,
    runner: CommandRunner,
    test_command: str,
    directory: str,
    result: UpdateResult,
) -> None:
    """The final, opt-in `update-transitive` step (`update-transitive`,
    default `false`, issue #24) - called once, after the top-level loop
    (`run_updates`, either strategy) and any `allow-major` beyond-constraint
    attempts have both finished, to catch up everything else still
    updatable within its existing constraints: a transitive dependency,
    but also any top-level package `with-groups`/`without-groups`/
    `only-groups` (issue #4) left out of this run's own iteration.

    Always sets `result.transitive` (see `TransitiveOutcome`) before
    returning normally. Like every other reset path in this module, a
    re-sync failure raises `UpdateAborted` instead (carrying `result`,
    with `result.transitive` already set to the `"failed"` outcome that
    triggered it - mirroring `_in_range_update`/`_attempt_beyond_constraint`,
    which always append/attach their own outcome before a reset that might
    itself abort), so the caller never loses this step's own outcome even
    on that failure path.

    Deliberately never touches `pyproject.toml`: `Backend.update_transitive()`
    is documented to only ever change the lock file (verified against real
    poetry==2.4.3/uv==0.12.14 - see the backends' own `update_transitive`
    docstrings), so this only stages/resets the lock file, same as
    `_in_range_update`."""
    files = backend.files_to_stage()
    before = backend.all_locked_versions()

    print("::group::transitive dependencies")
    update_result = backend.update_transitive()
    print(update_result.stdout)
    print(update_result.stderr)

    if not update_result.ok:
        print("transitive dependencies update failed to resolve, discarding changes")
        result.transitive = TransitiveOutcome(
            status="failed",
            failure_kind="resolution",
            output_tail=capture_tail(update_result.stdout + "\n" + update_result.stderr),
        )
        _reset_and_resync(backend, git, files, "transitive dependencies", result)
        print("::endgroup::")
        return

    if not git.diff_changed(files):
        print("no transitive updates available")
        result.transitive = TransitiveOutcome(status="unchanged")
        print("::endgroup::")
        return

    after = backend.all_locked_versions()
    changed_packages = _diff_locked_versions(before, after)

    test_result, test_passed = _run_test_command(
        runner, test_command, directory, "transitive dependencies"
    )

    if test_passed:
        print("transitive dependencies update passed")
        git.stage(files)
        git.commit("Update transitive dependencies")
        result.transitive = TransitiveOutcome(status="updated", changed_packages=changed_packages)
        print("::endgroup::")
        return

    print("transitive dependencies update failed tests, discarding changes")
    result.transitive = TransitiveOutcome(
        status="failed",
        changed_packages=changed_packages,
        failure_kind="test",
        output_tail=capture_tail(test_result.stdout + "\n" + test_result.stderr),
    )
    _reset_and_resync(backend, git, files, "transitive dependencies", result)
    print("::endgroup::")
