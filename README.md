## Update Python Dependencies GitHub Action

A GitHub Action to update your Poetry or uv dependencies, that ensures to not break anything by running tests after each package update.

This GitHub Action is inspired by [gha-poetry-update](https://github.com/fuzzylabs/gha-poetry-update) but heavily modified. It updates your dependencies one top-level package at a time using [Poetry](https://python-poetry.org/) or [uv](https://docs.astral.sh/uv/), runs tests (optionally), and creates a pull request with the results.

### Features

1. Supports both Poetry and uv projects; auto-detected from the lock file present, or selected explicitly with `package-manager`.
2. Each updated package is committed separately.
3. Optionally test each update with a custom command — only successful updates are committed.
4. Add labels and PR title prefixes to resulting pull request, to integrate with your CI/CD workflows.
5. Reuses a fixed branch/PR across runs instead of piling up duplicate PRs.
6. `dry-run` mode to see what would happen without pushing anything.

### Versions

- **`v2`** (this branch/version) is a breaking Python rewrite with uv support, a new bootstrap (see below), and new inputs/outputs. It is **not released yet**: the `v2`/`v2.0.0` tags only start existing once the maintainer pushes the first `v2.0.0` tag (see [`release.yml`](.github/workflows/release.yml)). Until then, pin to `@main` (moves with the default branch) or, for a reproducible/supply-chain-hardened pin, a full commit SHA — `friedrichwilken/update-poetry-dependencies@<sha>  # describe the commit`, the same pattern this repo's own workflows use for third-party actions.
- **`v1`** is the original bash-based action. It is frozen at the `v1`/`v1.0.1` tags and unmaintained — it will not be moved or updated further. If you're still using it, see "Migrating from v1" below.

### Migrating from v1

`v2` is a breaking rewrite: Python instead of bash, `uv`-based bootstrapping, and some input/output changes. To migrate:

1. Add an explicit `actions/checkout` step before this action in your workflow — v1 checked out the repository itself; v2 does not.
2. Pass your token to **both** `actions/checkout`'s `token:` input and this action's `github_token` input (see "Token and permissions" below) — v1 only needed `github_token`.
3. Check the [Inputs](#inputs) and [Outputs](#outputs) tables against your existing `with:` block — some defaults changed (e.g. `poetry-version` now defaults to a Poetry 2.x release) and `package-manager` is new (for uv support; defaults to `auto`-detecting from the lock file).
4. Drop any `actions/setup-python` / `snok/install-poetry` steps you had before this action — v2's `uv`-based bootstrap replaces them entirely; see "How it bootstraps" below.

### How it bootstraps

The action installs [`astral-sh/setup-uv`](https://github.com/astral-sh/setup-uv) and uses `uv` for everything else: it runs itself on a fixed `uv`-managed interpreter, installs the project's `python-version` with `uv python install`, and — for Poetry projects — installs Poetry itself with `uv tool install poetry==<poetry-version>` and creates its in-project virtualenv directly with `uv venv`, pinned to that interpreter (Poetry then picks up the existing virtualenv automatically). You do not need `actions/setup-python`, `snok/install-poetry`, or a preinstalled `uv`/`poetry` in your workflow; just check out the repository first.

Every run rebuilds `.venv` from scratch (`uv venv --clear`), so restoring `.venv` itself from a CI cache does nothing useful. If you want faster syncs, cache `uv`'s own package cache (e.g. `~/.cache/uv` on Linux/macOS, or `actions/cache` with `path: ~/.cache/uv` / the output of `uv cache dir`) instead.

**Prerequisite: a clean manifest/lock file.** Before doing anything else, the action fails fast if `pyproject.toml` or the lock file in `directory` already have uncommitted changes (staged or not) — the update loop resets and commits exactly these files itself, and running it against a dirty working tree would otherwise either discard that uncommitted work (on a discarded update) or silently absorb it into one of this run's own commits. This is checked unconditionally, not just when `allow-major` is enabled. Commit or stash those changes before this action runs.

### uv backend: scope and limits

- Only the `pyproject.toml` in `directory` is read to find top-level dependencies. A `tool.uv.workspace` root's member projects are not iterated, and workspace `uv.lock` files live at the workspace root rather than in an individual member's directory — [uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/) are not supported yet.
- If the project declares [`tool.uv.conflicts`](https://docs.astral.sh/uv/concepts/projects/dependencies/#conflicting-dependencies) (mutually exclusive extras/groups, e.g. a `cpu`/`gpu` extra pair), the default `uv sync --all-groups --all-extras` selection would try to install both sides at once and `uv sync` fails outright. When that is detected and `uv-sync-args` is not set, the action falls back to `uv sync` with no extras and only the default dependency groups, and prints a `::warning::`. Set `uv-sync-args` to choose what actually gets installed, e.g. `uv-sync-args: '--extra cpu --group dev'`.

### Inputs

| Name              | Description                                                                                   | Default                       | Required |
|-------------------|-----------------------------------------------------------------------------------------------|--------------------------------|----------|
| python-version    | The Python version to use for the project.                                                    | `3.12.14`                      | no       |
| package-manager   | Which package manager the project uses: `auto` (detected from the lock file in `directory`), `poetry`, or `uv`. | `auto`                          | no       |
| poetry-version    | The Poetry version to use. Only used when the poetry backend is selected.                     | `2.4.3`                        | no       |
| uv-sync-args      | Only used when the uv backend is selected. Overrides the default `--all-groups --all-extras` selection passed to `uv sync` (parsed as shell arguments, e.g. `--extra cpu --group dev`). Needed when the project declares `tool.uv.conflicts`. | `""`                            | no       |
| directory         | The directory of the project files.                                                            | `./`                            | no       |
| pr-title-prefix   | A prefix for the PR title.                                                                     | `""`                            | no       |
| pr-labels         | A comma or newline separated list of labels for the PR.                                        | `""`                            | no       |
| test-command      | A command to run tests after each update. Runs in `directory` via `bash -c` (e.g. `pytest` for Poetry, `uv run pytest` for uv). | `""`                            | no       |
| branch-name       | Fixed branch name used for the update PR. Force-pushed on every run.                            | `deps/test-gated-updates`       | no       |
| base-branch       | Base branch for the PR. If the checkout is detached (e.g. `pull_request` events), falls back to `GITHUB_BASE_REF`; if neither is available the action fails fast, before doing any work. | the currently checked out branch | no |
| dry-run           | Run the full update loop but skip pushing the branch and creating/updating the PR.               | `false`                         | no       |
| allow-major       | Opt-in: also attempt an update beyond the declared constraint (raising it) for a package whose constraint would otherwise exclude its latest release, falling back to the plain in-range update if that attempt fails. Despite the name, this is not always a semver-major bump. See "Beyond-constraint update attempts" below. | `false` | no |
| create-issues     | Opt-in: file one GitHub issue per top-level package that fails (or has a held-back beyond-constraint attempt), kept up to date and closed automatically across runs. Requires `issues: write` on the token. See "`create-issues`: filing issues for failures" below. | `false` | no |
| issue-labels      | A comma or newline separated list of labels added to an issue created by `create-issues`. Labels must already exist in the repository - this action never creates one. | `""` | no |
| github_token      | GitHub token for PR creation.                                                                   |                                  | **yes**  |

### Outputs

| Name              | Description                                                                 |
|-------------------|------------------------------------------------------------------------------|
| passed-packages   | Comma separated list of packages that were updated and passed the test command. |
| failed-packages   | Comma separated list of packages whose update or test failed and were discarded. |
| skipped-packages  | Comma separated list of packages that had nothing to update.                |
| held-back-packages | Comma separated list of packages where an update beyond the declared constraint was attempted (`allow-major`) but held back; see "Beyond-constraint update attempts" below. |
| pr-body           | The rendered report / PR body.                                              |
| report-json       | JSON array of per-package records; see "Report" below for the field reference. |
| issue-actions     | JSON array of planned/performed `create-issues` actions, one object per affected package: `{package, action, issue}`. `action` is `create`, `update`, or `close`; `issue` is the existing/created issue number, or `null` for a not-yet-created issue (always `null` in `dry-run`, since nothing is actually created). `[]` when `create-issues` is not enabled. See "`create-issues`: filing issues for failures" below. |

The same report is also written to the job summary (`GITHUB_STEP_SUMMARY`), including in `dry-run`.

### Report

The PR body / job summary reports, per package: for an update, the old and new locked version; for a failure, the current and attempted version, whether it was a dependency-resolution failure or a test failure, and a collapsed block with the tail of the relevant output (resolver output for a resolution failure, test command output for a test failure). Package names, versions and failure reasons are escaped so they can never break the report's table formatting or be interpreted as markup.

The report is rendered under an explicit character budget: well under GitHub's 65536 character PR body limit for `pr-body`, and a larger (but still bounded, ~900000 character) budget for the job summary, so the job summary can carry more detail than the PR body for the same run. At either size, table rows and per-package output blocks are dropped (with a "N more, see `report-json`/job summary" note) as needed to stay under the budget - the guarantee holds regardless of how many packages or how much output there is.

If the update loop has to abort early (currently only when re-syncing the environment after a discarded update itself fails), the report still covers everything processed before the abort - already-made commits for packages that passed stay made locally, but the run is not pushed and no PR is created/edited - and starts with a "Run aborted: `<reason>`" banner.

`report-json` carries the same per-package data as a stable, machine-readable array, one object per top-level package. Its total size is capped independently (~256 KiB): if needed, `output_tail` is dropped (in favor of `output_truncated: true`) from the packages with the largest captured output first, until it fits - every package still gets a record.

| Field             | Type            | Description                                                                 |
|-------------------|-----------------|-------------------------------------------------------------------------------|
| name              | string          | The top-level package name.                                                 |
| status            | string          | One of `updated`, `failed`, `skipped`.                                      |
| old_version       | string \| null  | The version locked before this run touched the package, or `null` if unknown. |
| new_version       | string \| null  | For `updated`/`skipped`: the resulting locked version. For `failed`: the version that was attempted before the change was reverted. `null` if unknown. |
| failure_kind      | string \| null  | `resolution` (the update/lock step itself failed), `test` (the test command failed), or `null` for a non-failure. |
| output_tail       | string          | Tail of the relevant captured output for a failure (empty otherwise), ANSI escape codes stripped. |
| output_truncated  | boolean         | Only present (`true`) when `output_tail` was dropped to keep `report-json` under its size cap; absent otherwise. |
| bump              | string          | Only present on an `updated` outcome produced while `allow-major` is enabled: the actual release segment that changed between `old_version` and `new_version` - `major`, `minor`, `patch`, or `other` (see below) - regardless of whether this was an in-range update or one that raised the constraint. |
| constraint_raised | boolean         | Only present (`true`) when this outcome's own commit raised the declared constraint itself, as opposed to a plain in-range update (which never touches the manifest). |
| beyond_constraint_version | string \| null | Only present when an update beyond the declared constraint was attempted for this package but held back (see "Beyond-constraint update attempts" below): the version the attempt tried. |
| beyond_constraint_failure_kind | string \| null | Only present alongside `beyond_constraint_version`: `resolution` or `test`, same meaning as `failure_kind` but for the held-back attempt. |
| beyond_constraint_output_tail | string | Only present alongside `beyond_constraint_version`: tail of the held-back attempt's captured output. |
| beyond_constraint_output_truncated | boolean | Only present (`true`) when `output_tail`/`beyond_constraint_output_tail` were dropped together to keep `report-json` under its size cap. |
| beyond_constraint_skip_reason | string | Only present when `allow-major` is enabled but no attempt to go beyond the declared constraint could be made for this package at all (e.g. a git/path dependency, an exact pin, an environment marker, an unparsable constraint, or an otherwise-successful attempt that had to be discarded). |

### Beyond-constraint update attempts (`allow-major`)

`allow-major` (default `false`) is an opt-in, per-package extension of the same test-gated flow: for a package whose *declared constraint* has an effective upper bound (a caret/tilde/wildcard/`~=` Poetry constraint, or a PEP 508 specifier with `<`/`<=`/`~=`/`==x.*`), it is not enough to know a newer release exists - the ordinary in-range update never looks past that bound. Despite the input's name, going beyond a declared constraint is not necessarily a semver-major jump (`six >=1.10,<1.15` allowing `1.17.0` is a minor bump that merely exceeded the declared range) - `bump` always reports the real release segment that changed, computed from the actual version numbers, never assumed from the fact that a constraint was raised. When an effective upper bound is found, before the plain in-range update:

1. **Attempt:** raise the declared constraint so the latest release is allowed (`poetry add "pkg[extras]@latest" --group <g>` / `--optional <extra>`, or for uv, rewrite just that requirement's specifier and re-lock with `uv add "pkg[extras]>=<bound>" --upgrade-package pkg`), then test exactly like an in-range update. If it passes, both `pyproject.toml` and the lock file are committed together (`Update <pkg> <old> -> <new> (constraint raised)`), tagged `constraint_raised: true` with `bump` set to the real delta, and the package is done - no separate in-range update runs for it.
2. **Fallback:** if raising the constraint fails to resolve, resolves but fails the test command, or resolves and passes but has to be discarded (see below), every touched file (manifest *and* lock) is reset and the environment re-synced, and the plain in-range update (today's behavior) runs instead. Whichever outcome that produces - updated, failed, or "no update available" - also records the held-back attempt (`beyond_constraint_version`/`beyond_constraint_failure_kind`/`beyond_constraint_output_tail` in `report-json`; a `held-back-packages` output entry either way) or the discard reason (`beyond_constraint_skip_reason`) rather than a `failure_kind` - the tool itself did not fail, this action decided not to trust what it did.
3. If the in-range update fails too, the package is `failed` exactly as it would be without `allow-major` - the held-back attempt's details are kept alongside it.

A package whose constraint has no effective upper bound needs no separate attempt at all - the in-range update already reaches the latest release - and is never double-tested.

Not every declaration shape can be safely rewritten without risking silently dropping information (an extra, a marker, an environment-specific source, ...). These are always skipped rather than guessed at, and reported via `beyond_constraint_skip_reason` (plus a compact line in the job summary - not the PR body, to keep it free of noise) rather than silently ignored:

- a git/path/url/workspace dependency, or a direct URL reference (`pkg @ ...`)
- more than one constraint entry for the package (e.g. per-Python-version marker-scoped table entries), or a Poetry `||` OR constraint where every alternative already has its own upper bound (unbounded if *any* alternative is open-ended - the union is then already unbounded and no attempt is needed)
- a dependency carrying `markers`/`python`/`platform`/`source`/`allow-prereleases` keys this feature cannot faithfully preserve
- an exact version pin (`==1.2.3`, or Poetry's bare `1.2.3`) - pinned on purpose, never touched
- a constraint/specifier this action's PEP 440-ish parser cannot parse (including a version literal that fails to parse even when the operator syntax looks fine, e.g. `^abc`)
- a legacy Poetry `optional = true` dependency not listed in any `[tool.poetry.extras]` entry (there is no extra name to pass `poetry add --optional` for it)
- `python` itself

After an attempt's tool call succeeds, two more checks can still discard it (same effect as a failure: reset and fall back to the in-range update, reported via `beyond_constraint_skip_reason`, not `failure_kind`):

- the manifest is re-read and diffed against the original declaration; if anything other than the version constraint changed (extras dropped, moved to a different table, a marker appeared, ...), the change is discarded rather than kept - this action never keeps a change it cannot fully account for;
- if the attempted version is a pre-release and the original was not, it is discarded - both Poetry and uv are expected to already exclude pre-releases by default, but this action never relies on that silently.

The PR body gets a new "⚠️ Held back (update beyond declared constraint failed)" table (package, current, attempted, reason) with the same collapsed per-package output blocks as the "Failed" section, and the "✅ Updated" table gains a `bump` column (with a "(raised)" suffix on a row where the constraint itself was rewritten) once at least one package in the run used it. All of this is additive: with `allow-major` left at its default `false`, the rendered report and `report-json` are byte-identical to before this feature existed.

**Prerequisite:** like the lock file, `pyproject.toml` must have no uncommitted changes before this action runs (see the "Prerequisite: a clean manifest/lock file" note above) - checked regardless of whether `allow-major` is enabled.

### `create-issues`: filing issues for failures

`create-issues` (default `false`) is an opt-in extension that hands failures off to a durable, trackable GitHub issue instead of (or in addition to) the PR report, which only ever reflects the latest run. It runs after the PR is created/edited (so the issue can link to it) and requires `issues: write` on the token (see "Token and permissions" below).

**One issue per package, never per run.** An issue is filed for every top-level package whose outcome this run is `failed`, or that has a held-back beyond-constraint attempt (`beyond_constraint_failure_kind` set - see "Beyond-constraint update attempts" above); a package that is both (the beyond-constraint attempt *and* the in-range fallback both failed) gets one issue about the plain failure, not two. Identity is a hidden marker in the issue body, `<!-- test-gated-updates:pkg=<name> -->` (`<name>` is the PEP 503 normalized package name) - **never the title**, which is free to change between runs and is never matched on. A second hidden marker, `<!-- test-gated-updates:state=<version>|<kind> -->`, records what the last run reported, so the action can tell whether anything actually changed without an extra `gh` call.

Every run, for every package that needs an issue this way:

| Situation | Action |
|---|---|
| No existing open managed issue for the package | **Create** one: title `<pkg>: update to <attempted> fails (<kind>)`, or for a held-back attempt, `<pkg>: update beyond declared constraint to <version> fails (<kind>)`. Body: the pkg marker, current -> attempted version, failure kind, the tail of the relevant captured output (the same safe, fenced rendering as the PR body/job summary - see `report.py`), a link to the workflow run, a link to the PR if one was created/edited this run (`null`/omitted in `dry-run`, since none is), a "last seen" note, and a footer explaining the issue is managed automatically. Labels come from `issue-labels`, exactly like `pr-labels` (only passed with `--label` when non-empty) - **the label must already exist**, this action never creates one. |
| An existing open managed issue for the package | **Update** its body to the current state (the pkg marker is kept as-is). A **comment is added only if** the attempted version or failure kind changed since the state marker's last recorded value - an unchanged, still-failing package is updated silently, not re-commented on every run. |
| An existing open managed issue whose package is *not* failed/held-back in this run's outcomes | **Close** it, with a comment linking to the run (and the PR, if any) - the package either updated successfully, had nothing to update, or is no longer a top-level dependency at all. |
| An open issue with no pkg marker at all | **Never touched.** Only issues this action itself created are ever edited or closed. |

Finding existing managed issues is a single `gh issue list --state open --search '"test-gated-updates:pkg=" in:body' --json number,body --limit 200` call (falling back to a plain, unfiltered open-issue listing if `--search` itself fails) - either way, the pkg marker is always re-confirmed locally in each candidate's body before it is trusted, never taken from the search match alone.

**Aborted runs:** if the update loop itself aborts (`UpdateAborted` - see "Report" above), issue management is skipped entirely and a `::notice::` is printed - the outcome list for an aborted run is only partial, and treating a package missing from it as "no longer failing" would incorrectly close its issue.

**Dry-run:** performs no `gh` writes at all (no create/update/comment/close calls) - only the read-only listing above runs, so the plan can still be computed against real repository state. The planned actions are printed and exposed in the `issue-actions` output (`[]` when `create-issues` is off, always) as `{package, action, issue}` objects, e.g.:

```json
[{"package": "idna", "action": "create", "issue": null}]
```

A compact one-line summary (e.g. `Issue actions: 1 created, 0 updated (0 commented), 0 closed (dry-run: planned only, no writes performed).`) is also appended to the job summary.

**Failures never fail the run.** Once the PR has been created/edited, it is this action's primary product - a `gh issue` failure (rate limit, missing label, missing permission, ...) is caught, printed as a `::warning::`, and the run still succeeds.

### Token and permissions

A pull request opened with the default, ephemeral `GITHUB_TOKEN` does **not** trigger other `pull_request` (or `pull_request_target`) workflows — this is a deliberate GitHub Actions restriction to stop workflows from recursively triggering themselves. If you rely on CI checks running against the PR this action opens, `GITHUB_TOKEN` alone will leave it with no checks at all.

To get normal CI on the resulting PR, use a fine-grained personal access token or a GitHub App installation token instead, with at least:

- `contents: write` (push the update branch)
- `pull-requests: write` (create/edit the PR, add labels)
- `issues: write` too, only if you enable `create-issues` (see above) - it also covers the read-only `gh issue list` lookup `create-issues` needs, so no separate `issues: read` is needed

That token has to be passed in **two** places, because two different things authenticate independently:

1. `actions/checkout`'s `token:` input — `actions/checkout` persists this as the git credential for the checkout, and this action's own `git push` (see `updater/git_repo.py`) relies entirely on those persisted credentials; it never receives or handles a token itself for the push.
2. This action's `github_token` input — used for `gh pr create`/`gh pr edit` (see `updater/github_pr.py`) and, when `create-issues` is enabled, `gh issue list`/`create`/`edit`/`comment`/`close` (see `updater/github_issues.py`), which all shell out to the `gh` CLI authenticated via `GH_TOKEN`.

```yaml
- uses: actions/checkout@v4
  with:
    token: ${{ secrets.DEPS_UPDATE_TOKEN }}

- uses: friedrichwilken/update-poetry-dependencies@v2 # see "Versions" above - not released yet, pin to @main or a SHA until v2.0.0 exists
  with:
    github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
    # ... other inputs
```

If you'd rather stick with `GITHUB_TOKEN` (accepting that the PR gets no automatic checks, or that you trigger checks another way, e.g. `workflow_run`), the calling workflow must still declare the permissions explicitly — the repository default for `GITHUB_TOKEN` is often read-only:

```yaml
permissions:
  contents: write
  pull-requests: write
```

Either way, the repository setting **Settings → Actions → General → Workflow permissions → "Allow GitHub Actions to create and approve pull requests"** must be enabled, or PR creation is rejected outright regardless of which token is used.

### Usage Example

The action no longer checks out the repository itself — do that in the calling workflow before using it. `package-manager` defaults to `auto`, so it usually does not need to be set explicitly.

These examples pin to the `v2` major tag, which the [release workflow](.github/workflows/release.yml) will move to point at the latest `v2.x.y` release — **but see "Versions" above: `v2` does not exist yet.** Until the first `v2.0.0` tag is pushed, pin to `@main` or a full commit SHA instead (`friedrichwilken/update-poetry-dependencies@<sha>  # describe the commit`) — see how this repo's own workflows pin their third-party actions for the pattern.

This repository dogfoods the action on itself; see [`.github/workflows/update_dependencies.yml`](.github/workflows/update_dependencies.yml) for a complete, currently-running example (uv backend).

#### Poetry project

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

concurrency:
  group: ${{ github.workflow }}
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.DEPS_UPDATE_TOKEN }}

      - uses: friedrichwilken/update-poetry-dependencies@v2 # not released yet - pin to @main or a SHA, see "Versions" above
        with:
          python-version: '3.12.14'
          poetry-version: '2.4.3'
          directory: './'
          pr-title-prefix: '[Poetry Update] '
          pr-labels: 'dependencies'
          test-command: 'pytest'
          branch-name: 'deps/test-gated-updates'
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

#### uv project

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

concurrency:
  group: ${{ github.workflow }}
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.DEPS_UPDATE_TOKEN }}

      - uses: friedrichwilken/update-poetry-dependencies@v2 # not released yet - pin to @main or a SHA, see "Versions" above
        with:
          python-version: '3.12.14'
          package-manager: 'uv'
          directory: './'
          pr-title-prefix: '[uv Update] '
          pr-labels: 'dependencies'
          test-command: 'uv run pytest'
          branch-name: 'deps/test-gated-updates'
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

### Maintaining this repo

Notes for whoever maintains `friedrichwilken/update-poetry-dependencies` itself (not relevant to consumers of the action):

- [`dependabot_automerge.yml`](.github/workflows/dependabot_automerge.yml) only actually enables auto-merge on a Dependabot PR if the repository setting **Settings → General → Pull Requests → "Allow auto-merge"** is on; if it's off, the workflow prints a `::warning::` and exits cleanly instead of failing.
- [`update_dependencies.yml`](.github/workflows/update_dependencies.yml) needs a `DEPS_UPDATE_TOKEN` secret (see "Token and permissions" above) to get CI running on the PRs it opens; it falls back to `github.token` otherwise.
- [`release.yml`](.github/workflows/release.yml) only reacts to a pushed `vX.Y.Z` tag and only ever force-moves the major tag matching that same `X` — pushing a `v2.0.0` tag is what turns on `v2` for the first time.
