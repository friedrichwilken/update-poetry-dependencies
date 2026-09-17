## Poetry Update GitHub Action

A GitHub Action to update Poetry dependencies, that ensures to not break anything by running tests after each package update.

This GitHub Action is inspired by [gha-poetry-update](https://github.com/fuzzylabs/gha-poetry-update) but heavily modified. It updates your dependencies using [Poetry](https://python-poetry.org/), runs tests (optionally), and creates a pull request with the results.

### Features

1. Each updated package is committed separately.
2. Optionally test each update with a custom command —only successful updates are committed.
3. Add labels and PR title prefixes to resulting pull request, to integrate with your CI/CD workflows.
4. Reuses a fixed branch/PR across runs instead of piling up duplicate PRs.
5. `dry-run` mode to see what would happen without pushing anything.

### Inputs

| Name              | Description                                                                                   | Default                       | Required |
|-------------------|-----------------------------------------------------------------------------------------------|--------------------------------|----------|
| python-version    | The Python version to use with Poetry.                                                        | `3.12.7`                       | no       |
| poetry-version    | The Poetry version to use.                                                                     | `2.1.3`                        | no       |
| directory         | The directory of the project files.                                                            | `./`                            | no       |
| pr-title-prefix   | A prefix for the PR title.                                                                     | `""`                            | no       |
| pr-labels         | A comma or newline separated list of labels for the PR.                                        | `""`                            | no       |
| test-command      | A command to run tests after each update. Runs in `directory` via `bash -c`.                   | `""`                            | no       |
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

The action no longer checks out the repository itself — do that in the calling workflow before using it:

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
