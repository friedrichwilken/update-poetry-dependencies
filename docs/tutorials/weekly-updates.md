# Tutorial: a weekly dependency-update workflow

Let's build a workflow that bumps your dependencies once a week. Then we add the advanced features, one step at a time.

- Every step shows the **complete file**. Copy any step and it works.
- Lines marked `# <-` are new in that step.
- Using **Poetry**? Swap in the values marked `Poetry: '...'`. Everything else is identical.

## 1. A minimal weekly run

The action doesn't check out your repository itself, so `actions/checkout` comes first.

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'    # <- every Monday at 06:00 UTC (minute hour day month weekday)
  workflow_dispatch:       # <- adds a "Run workflow" button in the Actions tab

permissions:               # <- lets the action push a branch and open a PR
  contents: write
  pull-requests: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4   # <- clones your repo so the action can update it

      - uses: friedrichwilken/test-gated-python-updates@v2   # <- the action itself
        with:
          test-command: 'uv run pytest'   # <- runs after every single update. Poetry: 'poetry run pytest'
          github_token: ${{ secrets.GITHUB_TOKEN }}   # <- lets it push the branch and open the PR
```

**Before the first run:** turn on **Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests"**. It is off by default, and without it GitHub refuses the PR.

**What you should see:**

- A job named `update` runs: on Monday, or when you press "Run workflow".
- If any update passes your tests: a PR titled "Update and successfully test packages".

## 2. Try it safely first

Run it once with `dry-run: 'true'`: it does everything except push the branch or touch the PR.

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
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          dry-run: 'true'   # <- does everything except push and open the PR
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

Trigger it with `workflow_dispatch`, then open the run and scroll to its job summary — the same report a real run would put in the PR body is right there.

**What you should see:**

- The job summary shows the report: "✅ Updated", "🛑 Failed", "⏭ No update available".
- No branch is pushed and no PR appears.

More: [`dry-run`](../manual/dry-run.md), [the report](../manual/pr-report.md).

Once you're happy with what you see, remove the `dry-run: 'true'` line (or set it to `'false'`).

## 3. Get CI running on the PR

A PR opened with the default `GITHUB_TOKEN` triggers no `pull_request` workflows at all. Pass a fine-grained PAT or GitHub App token to **both** `actions/checkout` and the action itself to get normal CI on it.

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
        with:                                            # <- checkout needs the PAT too
          token: ${{ secrets.DEPS_UPDATE_TOKEN }}         # <- a PAT, so the PR triggers your CI

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}   # <- same PAT, for gh pr create/edit
```

To set it up:

1. Create a fine-grained PAT (or a GitHub App token) for this repo with **Contents** and **Pull requests** set to read and write.
2. Store it as the repository secret `DEPS_UPDATE_TOKEN`.

More: [token and permissions](../manual/token-and-permissions.md).

**What you should see:** your normal CI checks now run on the action's PR, like on any other PR.

## 4. Labels, title prefix, base branch, concurrency

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

concurrency:                        # <- stops two runs racing on the same branch
  group: ${{ github.workflow }}     # <- one slot per workflow
  cancel-in-progress: false         # <- let an in-flight run finish first

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.DEPS_UPDATE_TOKEN }}

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          pr-title-prefix: '[deps] '   # <- prepended to the PR title
          pr-labels: 'dependencies'   # <- label must already exist in the repo
          base-branch: 'main'   # <- rarely needed; defaults to the checked-out branch
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

`pr-labels` must already exist in the repository — this action never creates one (`gh label create dependencies ...` once, or via your repo settings).

**What you should see:** the PR title is prefixed `[deps] `, carries the `dependencies` label, and targets `main` explicitly.

## 5. Faster runs: `strategy: batch-first`

With many updatable packages, testing one at a time costs one test run per package. `batch-first` updates everything at once and tests once, falling back to the per-package loop only if that combined test fails.

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

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          pr-title-prefix: '[deps] '
          pr-labels: 'dependencies'
          base-branch: 'main'
          strategy: 'batch-first'   # <- update+test everything at once first
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

**What you should see:**

- One test run in the log instead of one per package, when everything passes together.
- The same PR report as before.

More: [`strategy`](../manual/strategies.md).

## 6. Beyond the declared constraint: `allow-major`

By default, a package whose constraint caps it below the latest release (`^1.2` when `2.0` exists) is never even attempted. `allow-major` opts in to also trying the raised constraint, falling back to the in-range update if it fails.

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

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          pr-title-prefix: '[deps] '
          pr-labels: 'dependencies'
          base-branch: 'main'
          strategy: 'batch-first'
          allow-major: 'true'   # <- also try updates beyond the declared constraint
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

**What you should see,** for a package with a capped constraint and a newer release:

- It is updated, with `(raised)` next to its bump. Or:
- It shows up in a new "⚠️ Held back" table, and the normal in-range update is applied instead.

More: [`allow-major`](../manual/allow-major.md).

## 7. Track what fails: `create-issues`

A failing package only ever shows up in the *latest* PR report. `create-issues` files one durable, auto-updating issue per failing package instead.

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  issues: write   # <- required by create-issues

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

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          pr-title-prefix: '[deps] '
          pr-labels: 'dependencies'
          base-branch: 'main'
          strategy: 'batch-first'
          allow-major: 'true'
          create-issues: 'true'   # <- one tracked issue per failing package
          issue-labels: 'dependencies'   # <- must already exist too
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

**What you should see:**

- The first time a package fails: a new issue, `<pkg>: update to <version> fails (...)`, with the `dependencies` label.
- While it keeps failing: the same issue is updated. No duplicates.
- Once it updates cleanly: the issue closes itself.

More: [`create-issues`](../manual/create-issues.md).

## 8. Keep the rest fresh: `update-transitive`

Every step so far only ever touches your *top-level* dependencies. `update-transitive` adds one final step that refreshes everything else too, still within already-declared constraints. This step also excludes the `dev` group from the top-level loop.

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  issues: write

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

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          pr-title-prefix: '[deps] '
          pr-labels: 'dependencies'
          base-branch: 'main'
          strategy: 'batch-first'
          allow-major: 'true'
          create-issues: 'true'
          issue-labels: 'dependencies'
          update-transitive: 'true'   # <- also refresh transitive dependencies
          without-groups: 'dev'   # <- exclude the dev group from the top-level loop
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

**uv note:** `"dev"` covers both a `dev` key in `[dependency-groups]` and uv's legacy `[tool.uv.dev-dependencies]`. **Poetry note:** the group name must be one you've actually declared (e.g. `[tool.poetry.group.dev]`) — there's no built-in `dev` group. Either way, see [Dependency groups](../manual/dependency-groups.md).

**Re-sync note:** if `test-command` itself runs `uv run ...`, it re-syncs the environment first using **uv's own** default group selection, not this action's narrower `without-groups` one. If a test genuinely depends on the group being absent, use `uv run --no-sync ...` or `.venv/bin/python` directly instead. See [Package managers § `uv run` in `test-command` re-syncs](../manual/package-managers.md#uv-run-in-test-command-re-syncs).

**What you should see:**

- An extra commit, `Update transitive dependencies`, whenever something transitive could move.
- With `without-groups: dev`: packages that live only in `dev` are left alone and are not in the report.

## 9. Hands-off: auto-merge the PR when CI is green

There's no `pr-number`/`pr-url` output on this action today, so key a separate, `pull_request`-triggered workflow off the fixed branch name this action always uses instead — the same pattern this repo uses for its own Dependabot PRs.

Add a second workflow file, `.github/workflows/automerge-deps.yml`:

```yaml
name: auto-merge dependency updates
on:
  pull_request:                     # <- fires when the update PR is opened/updated
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  automerge:
    if: |                           # <- only this action's own PR, never a fork
      github.head_ref == 'deps/test-gated-updates' &&
      github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    steps:
      - name: Enable auto-merge
        env:
          GH_TOKEN: ${{ secrets.DEPS_UPDATE_TOKEN }}       # <- same PAT as the update workflow
          PR_URL: ${{ github.event.pull_request.html_url }}
        run: gh pr merge --auto --squash "$PR_URL"         # <- merges once required checks pass
```

This only fires on a real `pull_request` event, which needs the PAT from step 3 (`GITHUB_TOKEN` PRs never trigger it). It also needs **Settings → General → Pull Requests → "Allow auto-merge"** on, and at least one required status check in branch protection — otherwise `gh pr merge --auto` has nothing to wait for and merges immediately.

A PR from a fork never receives this workflow's secrets, so `gh pr merge` could not authenticate even if the branch-name check above matched one — the extra repository-owner condition just makes that explicit rather than relying on it implicitly.

**What you should see:** once the required checks pass, the PR merges itself. If "Allow auto-merge" is off, the step fails loudly instead: turn the setting on and re-run.

## 10. The final workflow

Two files, together:

```yaml
name: update dependencies
on:
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  issues: write

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

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          pr-title-prefix: '[deps] '
          pr-labels: 'dependencies'
          base-branch: 'main'
          strategy: 'batch-first'
          allow-major: 'true'
          create-issues: 'true'
          issue-labels: 'dependencies'
          update-transitive: 'true'
          without-groups: 'dev'
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

```yaml
name: auto-merge dependency updates
on:
  pull_request:
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  automerge:
    if: |
      github.head_ref == 'deps/test-gated-updates' &&
      github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    steps:
      - name: Enable auto-merge
        env:
          GH_TOKEN: ${{ secrets.DEPS_UPDATE_TOKEN }}
          PR_URL: ${{ github.event.pull_request.html_url }}
        run: gh pr merge --auto --squash "$PR_URL"
```

Every input above, in the manual:

- `test-command`, `github_token`, `directory`, `python-version`, `package-manager` — [inputs.md § Core](../manual/inputs.md#core)
- `pr-title-prefix`, `pr-labels`, `base-branch`, `branch-name` — [inputs.md § Pull request](../manual/inputs.md#pull-request)
- `strategy` — [strategies.md](../manual/strategies.md)
- `allow-major` — [allow-major.md](../manual/allow-major.md)
- `create-issues`, `issue-labels` — [create-issues.md](../manual/create-issues.md)
- `update-transitive` — [update-transitive.md](../manual/update-transitive.md)
- `without-groups` (and `with-groups`/`only-groups`) — [dependency-groups.md](../manual/dependency-groups.md)
- `poetry-version`, `uv-sync-args` — optional, backend-specific; not needed above unless you pin a Poetry release or work around `tool.uv.conflicts` — see [package-managers.md](../manual/package-managers.md)
- tokens and the `permissions:`/`issues: write` blocks — [token-and-permissions.md](../manual/token-and-permissions.md)
- how the loop, the fixed branch and the PR itself behave — [how-it-works.md](../manual/how-it-works.md)
- the PR body / job summary this produces — [pr-report.md](../manual/pr-report.md)

This repository runs this same workflow on itself every week — see [`update_dependencies.yml`](../../.github/workflows/update_dependencies.yml) for a complete, currently-running example.
