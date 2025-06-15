## Poetry Update GitHub Action

This GitHub Action is inspired by [gha-poetry-update](https://github.com/fuzzylabs/gha-poetry-update) but heavily modified. It updates your dependencies using [Poetry](https://python-poetry.org/), runs tests (optionally), and creates a pull request with the results.

### Features

1. Each updated package is committed separately.
2. Optionally test each update with a custom command—only successful updates are committed.
3. (TODO) Add labels to the created pull request.

### Inputs

| Name              | Description                                                        | Default     | Required   |
|-------------------|--------------------------------------------------------------------|-------------|------------|
| python-version    | The Python version to use with Poetry.                             | `3.12.00`   | no         |
| poetry-version    | The Poetry version to use.                                         | `2.0.0`     | no         |
| directory         | The directory of the project files.                                | `./`        | no         |
| pr-title-prefix   | A prefix for the PR title.                                         | `""`        | no         |
| pr-labels         | (TODO) Comma or newline separated list of labels for the PR.       | `""`        | no         |
| test-command      | A command to run tests after each update.                          | `""`        | no         |
| github_token      | GitHub token for PR creation.                                      |             | **yes**    |

### Usage Example

```yaml
- uses: friedrichwilken/update-poetry-dependencies@main
  with:
    python-version: '3.12.0'
    poetry-version: '2.0.0'
    directory: './'
    pr-title-prefix: '[Poetry Update] '
    # pr-labels: 'dependencies,automerge' # TODO: not yet implemented
    test-command: 'pytest'
    github_token: ${{ secrets.GITHUB_TOKEN }}
