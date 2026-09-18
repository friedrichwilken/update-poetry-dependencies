# Inputs

Every `with:` key this action accepts. Generated from `action.yml` — defaults and descriptions here must always match it. Grouped by topic; each group links to the page that explains it in full.

## Core

| Name | Default | Description |
|---|---|---|
| `python-version` | `3.12.14` | The Python version to use for the project. |
| `package-manager` | `auto` | Which package manager the project uses: `auto` (detected from the lock file present in `directory`), `poetry`, or `uv`. See [Package managers](package-managers.md). |
| `directory` | `./` | The directory of the project files. |
| `test-command` | `""` | A command for a test to run after updating every package. |
| `github_token` | *(none — required)* | GitHub token for the PR creation. See [Token and permissions](token-and-permissions.md). |

## Package manager specifics

See [Package managers](package-managers.md).

| Name | Default | Description |
|---|---|---|
| `poetry-version` | `2.4.3` | The Poetry version to use. Only used when the poetry backend is selected. |
| `uv-sync-args` | `""` | Only used when the uv backend is selected. Overrides the default `--all-groups --all-extras` group/extra selection passed to `uv sync` (parsed as shell arguments, e.g. `--extra cpu --group dev`). Needed when the project declares `tool.uv.conflicts`. |

## Pull request

See [How it works](how-it-works.md) and [The report](pr-report.md).

| Name | Default | Description |
|---|---|---|
| `pr-title-prefix` | `""` | A prefix that gets prepended to the PR title. |
| `pr-labels` | `""` | A comma or newline separated list of labels added to the PR. |
| `branch-name` | `deps/test-gated-updates` | Fixed branch name used for the update PR. Reused (and force-pushed) on every run instead of creating a new PR each time. |
| `base-branch` | `""` (the checked-out branch) | Base branch for the PR. Defaults to the branch that is currently checked out. |

## Run behavior

| Name | Default | Description |
|---|---|---|
| `dry-run` | `false` | Run the full update loop but skip pushing the branch and creating/updating the PR. See [`dry-run`](dry-run.md). |
| `allow-major` | `false` | Opt-in: for each package whose declared constraint would exclude its latest release, also attempt an update beyond the declared constraint before falling back to the plain in-range update on failure. See [`allow-major`](allow-major.md). |
| `strategy` | `per-package` | `per-package`: update, test and commit one top-level package at a time. `batch-first`: update every package at once and test once, replaying as per-package commits on success. See [`strategy`](strategies.md). |

## `create-issues`

See [`create-issues`](create-issues.md).

| Name | Default | Description |
|---|---|---|
| `create-issues` | `false` | Opt-in: file one GitHub issue per top-level package that fails (or has a held-back beyond-constraint attempt), updated across runs and closed automatically once it no longer applies. Requires `issues: write` on the token. |
| `issue-labels` | `""` | A comma or newline separated list of labels added to an issue created by `create-issues`. Labels must already exist in the repository. |

## `update-transitive`

See [`update-transitive`](update-transitive.md).

| Name | Default | Description |
|---|---|---|
| `update-transitive` | `false` | Opt-in: after the top-level loop (and any `allow-major` beyond-constraint attempts) finish, run one final tested step that refreshes every dependency — transitive included — still updatable within its existing constraints, committed separately as `Update transitive dependencies`. |

## Dependency groups

See [Dependency groups](dependency-groups.md).

| Name | Default | Description |
|---|---|---|
| `with-groups` | `""` | A comma or newline separated list of dependency groups to additionally include when selecting what gets installed/synced. `main` names the project's own ungrouped dependencies. May be combined with `without-groups`; mutually exclusive with `only-groups`. |
| `without-groups` | `""` | A comma or newline separated list of dependency groups to exclude. `main` names the project's own ungrouped dependencies (`dev` additionally covers uv's legacy `tool.uv.dev-dependencies`). May be combined with `with-groups`; mutually exclusive with `only-groups`. |
| `only-groups` | `""` | A comma or newline separated list of dependency groups to exclusively include, dropping every other group (`main` included). Mutually exclusive with `with-groups`/`without-groups`. |
