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

### How it bootstraps

The action installs [`astral-sh/setup-uv`](https://github.com/astral-sh/setup-uv) and uses `uv` for everything else: it runs itself on a fixed `uv`-managed interpreter, installs the project's `python-version` with `uv python install`, and — for Poetry projects — installs Poetry itself with `uv tool install poetry==<poetry-version>` and creates its in-project virtualenv directly with `uv venv`, pinned to that interpreter (Poetry then picks up the existing virtualenv automatically). You do not need `actions/setup-python`, `snok/install-poetry`, or a preinstalled `uv`/`poetry` in your workflow; just check out the repository first.

Every run rebuilds `.venv` from scratch (`uv venv --clear`), so restoring `.venv` itself from a CI cache does nothing useful. If you want faster syncs, cache `uv`'s own package cache (e.g. `~/.cache/uv` on Linux/macOS, or `actions/cache` with `path: ~/.cache/uv` / the output of `uv cache dir`) instead.

### uv backend: scope and limits

- Only the `pyproject.toml` in `directory` is read to find top-level dependencies. A `tool.uv.workspace` root's member projects are not iterated, and workspace `uv.lock` files live at the workspace root rather than in an individual member's directory — [uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/) are not supported yet.
- If the project declares [`tool.uv.conflicts`](https://docs.astral.sh/uv/concepts/projects/dependencies/#conflicting-dependencies) (mutually exclusive extras/groups, e.g. a `cpu`/`gpu` extra pair), the default `uv sync --all-groups --all-extras` selection would try to install both sides at once and `uv sync` fails outright. When that is detected and `uv-sync-args` is not set, the action falls back to `uv sync` with no extras and only the default dependency groups, and prints a `::warning::`. Set `uv-sync-args` to choose what actually gets installed, e.g. `uv-sync-args: '--extra cpu --group dev'`.

### Inputs

| Name              | Description                                                                                   | Default                       | Required |
|-------------------|-----------------------------------------------------------------------------------------------|--------------------------------|----------|
| python-version    | The Python version to use for the project.                                                    | `3.12.7`                       | no       |
| package-manager   | Which package manager the project uses: `auto` (detected from the lock file in `directory`), `poetry`, or `uv`. | `auto`                          | no       |
| poetry-version    | The Poetry version to use. Only used when the poetry backend is selected.                     | `2.1.3`                        | no       |
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

### Usage Example

The action no longer checks out the repository itself — do that in the calling workflow before using it. `package-manager` defaults to `auto`, so it usually does not need to be set explicitly.

#### Poetry project

```yaml
- uses: actions/checkout@v4

- uses: friedrichwilken/update-poetry-dependencies@main
  with:
    python-version: '3.12.7'
    poetry-version: '2.1.3'
    directory: './'
    pr-title-prefix: '[Poetry Update] '
    pr-labels: 'bug,needs review,high priority'
    test-command: 'pytest'
    branch-name: 'deps/test-gated-updates'
    github_token: ${{ secrets.GITHUB_TOKEN }}
```

#### uv project

```yaml
- uses: actions/checkout@v4

- uses: friedrichwilken/update-poetry-dependencies@main
  with:
    python-version: '3.12.7'
    package-manager: 'uv'
    directory: './'
    pr-title-prefix: '[uv Update] '
    pr-labels: 'bug,needs review,high priority'
    test-command: 'uv run pytest'
    branch-name: 'deps/test-gated-updates'
    github_token: ${{ secrets.GITHUB_TOKEN }}
```
