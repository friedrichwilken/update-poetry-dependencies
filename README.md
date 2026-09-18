# Test-gated Python updates

A GitHub Action that updates your Poetry or uv dependencies one package at a time, running your tests after each one, and opens a single pull request with the results.

- **Tested per package** — only updates that pass your test command are kept; the rest are dropped, not forced on you.
- **One pull request, not fifteen** — reused and updated every run instead of piling up duplicates.
- **Failures are reported, not blocking** — a report table (and, optionally, a tracked issue), never a broken build.

## Quick start (uv)

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'
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
          test-command: 'uv run pytest'
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

Using Poetry? Change `test-command` to `'poetry run pytest'` — everything else auto-detects. Full walkthrough: [tutorial](docs/tutorials/weekly-updates.md).

The default `GITHUB_TOKEN` above won't trigger your CI on the PR it opens — see [token and permissions](docs/manual/token-and-permissions.md) for why, and for a PAT that fixes it.

## What you get

A pull request with a report, e.g.:

| Package | Result | Detail |
|---|---|---|
| six | updated | 1.16.0 → 1.17.0 |
| idna | failed | test failed at 3.7 |

## Going further

- [`allow-major`](docs/manual/allow-major.md) — attempt updates beyond the declared constraint.
- [`strategy: batch-first`](docs/manual/strategies.md) — cut N test runs down to about 1.
- [`create-issues`](docs/manual/create-issues.md) — track failures as durable GitHub issues.
- [`update-transitive`](docs/manual/update-transitive.md) — refresh transitive dependencies too.
- [Dependency groups](docs/manual/dependency-groups.md) — `with-groups`/`without-groups`/`only-groups`.
- [`dry-run` and outputs](docs/manual/dry-run.md) — preview a run, or consume `report-json` yourself.
- [Token and permissions](docs/manual/token-and-permissions.md) — get real CI running on the PR.

## Learn more

- [Tutorial: a weekly dependency-update workflow](docs/tutorials/weekly-updates.md)
- [Manual](docs/manual/README.md) — full reference for every input and output.
- [Migrating from v1](docs/manual/migrating-from-v1.md)
- [This repo's own weekly workflow](.github/workflows/update_dependencies.yml) — a live example.
