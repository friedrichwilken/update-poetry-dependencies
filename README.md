# Test-gated Python updates

A GitHub Action that updates your **Poetry** or **uv** dependencies one package at a time, running your tests after each one, and opens a single pull request with the results.

## Why

A bulk dependency bump that turns CI red tells you *something* broke, but not *what*. In Python, breaking API changes often only show up when the tests run, so you end up untangling the PR by hand. Bumping one dependency per PR avoids that, but costs a CI run and a review for every package.

This action does the untangling for you. Everything that passes your tests lands in **one green PR**. The packages that break your app are **named, with the test output**, so you (or an agent) can fix exactly those.

## Quick start (uv)

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'   # <- every Monday at 06:00 UTC
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # <- runs after every update
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

Using Poetry? Change `test-command` to `'poetry run pytest'` — everything else auto-detects. Full walkthrough: [tutorial](docs/tutorials/weekly-updates.md).

Before the first run:
- Turn on **Settings → Actions → General → Allow GitHub Actions to create and approve pull requests** (off by default).
- Want your CI to run on the PR by itself? With the default `GITHUB_TOKEN`, GitHub holds those runs for manual approval: [use a PAT](docs/manual/token-and-permissions.md).

## What you get: one PR with a report

> **✅ Updated**
>
> | package | old | new |
> | --- | --- | --- |
> | six | 1.16.0 | 1.17.0 |
>
> **🛑 Failed**
>
> | package | current | attempted | reason |
> | --- | --- | --- | --- |
> | idna | 3.6 | 3.7 | tests failed |

## Going further
- [`allow-major`](docs/manual/allow-major.md) — updates beyond the declared constraint.
- [`strategy: batch-first`](docs/manual/strategies.md) — cut N test runs to about 1.
- [`create-issues`](docs/manual/create-issues.md) — track failures as durable issues.
- [`update-transitive`](docs/manual/update-transitive.md) — refresh transitive deps too.
- [Dependency groups](docs/manual/dependency-groups.md) — with/without/only-groups.
- [`dry-run` and outputs](docs/manual/dry-run.md) — preview a run, or consume `report-json`.

## Learn more
- [Tutorial: a weekly dependency-update workflow](docs/tutorials/weekly-updates.md)
- [Manual](docs/manual/README.md) — full reference for every input and output.
- [How is this different from Dependabot / Renovate?](docs/manual/comparison.md)
- [Migrating from v1](docs/manual/migrating-from-v1.md)
