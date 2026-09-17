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
| github_token      | GitHub token for PR creation.                                                                   |                                  | **yes**  |

### Outputs

| Name              | Description                                                                 |
|-------------------|------------------------------------------------------------------------------|
| passed-packages   | Comma separated list of packages that were updated and passed the test command. |
| failed-packages   | Comma separated list of packages whose update or test failed and were discarded. |
| skipped-packages  | Comma separated list of packages that had nothing to update.                |
| pr-body           | The rendered report / PR body.                                              |

### Token and permissions

A pull request opened with the default, ephemeral `GITHUB_TOKEN` does **not** trigger other `pull_request` (or `pull_request_target`) workflows — this is a deliberate GitHub Actions restriction to stop workflows from recursively triggering themselves. If you rely on CI checks running against the PR this action opens, `GITHUB_TOKEN` alone will leave it with no checks at all.

To get normal CI on the resulting PR, use a fine-grained personal access token or a GitHub App installation token instead, with at least:

- `contents: write` (push the update branch)
- `pull-requests: write` (create/edit the PR, add labels)
- `issues: write` too, only if you later use features that create/label issues

That token has to be passed in **two** places, because two different things authenticate independently:

1. `actions/checkout`'s `token:` input — `actions/checkout` persists this as the git credential for the checkout, and this action's own `git push` (see `updater/git_repo.py`) relies entirely on those persisted credentials; it never receives or handles a token itself for the push.
2. This action's `github_token` input — used for `gh pr create`/`gh pr edit` (see `updater/github_pr.py`), which shells out to the `gh` CLI authenticated via `GH_TOKEN`.

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
