# How it works

One top-level package at a time: update it, test it, keep it if the test passes, discard it if not — then push one branch and open (or update) one pull request with a report of everything that happened.

## The loop

1. List the project's top-level dependencies (`poetry show -T`, or this action's own `pyproject.toml` parse for uv — see [Package managers](package-managers.md)).
2. For each package: update just that one, then run `test-command` (if set) against the result.
   - Passes (or no `test-command` given): commit the change (`Update <pkg> <old> -> <new>`).
   - Fails: discard the change and reset the environment.
3. Once every package has been through the loop, render the report and push one branch, creating or updating one PR.

`strategy: batch-first` changes *how* the loop spends test runs (update everything, test once, replay as separate commits) without changing what gets committed or reported — see [`strategy`](strategies.md).

## Reset and re-sync

A discarded update (failed resolution or failed test) resets `pyproject.toml` and the lock file back to the last good commit and re-syncs the environment (`.venv`) before moving on to the next package, so one package's failed attempt can never leak into the next package's test run. If a re-sync itself fails, the whole run aborts: the report still covers everything processed so far (already-made commits for passing packages stay made locally), but nothing is pushed and no PR is created or edited — the run starts its report with a "Run aborted: `<reason>`" banner instead.

## Prerequisite: a clean manifest/lock file

Before doing anything else, the action fails fast if `pyproject.toml` or the lock file in `directory` already have uncommitted changes (staged or not) — the loop resets and commits exactly these files itself, and running it against a dirty working tree would otherwise either discard that uncommitted work (on a discarded update) or silently absorb it into one of this run's own commits. This is checked unconditionally, not just when `allow-major` is enabled. Commit or stash those changes before this action runs.

## Fixed branch, one PR

The action never checks out the repository itself — do that first with `actions/checkout`. It reuses a fixed `branch-name` (default `deps/test-gated-updates`), force-pushed on every run, and creates the PR the first time, editing it on every later run — so scheduled runs never pile up duplicate PRs. If nothing changed (`git` HEAD is unchanged after the loop), nothing is pushed and no PR is touched at all.

`base-branch` defaults to whichever branch is currently checked out; on a detached checkout (e.g. a `pull_request`-triggered run) it falls back to `GITHUB_BASE_REF`, and fails fast if neither is available, before any work happens.

## Bootstrap: everything through `uv`

The action installs [`astral-sh/setup-uv`](https://github.com/astral-sh/setup-uv) and uses `uv` for everything else: it runs its own Python (the updater tool itself) on a fixed, pinned interpreter — independent of your project's `python-version` — then installs your project's `python-version` with `uv python install`, and, for Poetry projects, installs Poetry itself with `uv tool install poetry==<poetry-version>` and creates the project's in-project virtualenv directly with `uv venv --clear`, pinned to that interpreter (Poetry then picks up the existing virtualenv automatically). You do not need `actions/setup-python`, `snok/install-poetry`, or a preinstalled `uv`/`poetry` in your workflow — just check out the repository first.

**The action's own Python is not your project's Python.** The updater always runs on its own fixed interpreter (currently 3.14) so its stdlib tooling is always available; your project gets exactly the `python-version` you asked for, provisioned separately.

**`.venv` is rebuilt every run** (`uv venv --clear`), so restoring `.venv` itself from a CI cache does nothing useful. If you want faster syncs, cache `uv`'s own package cache instead (e.g. `actions/cache` with `path: ~/.cache/uv`, or the platform-appropriate `uv cache dir`).

See [Package managers](package-managers.md) for backend-specific detail, and [The report](pr-report.md) for how the PR body/job summary are produced.
