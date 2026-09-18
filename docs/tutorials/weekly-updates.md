# Tutorial: a weekly dependency-update workflow

This tutorial builds one GitHub Actions workflow step by step, starting from the smallest thing that works and adding one capability at a time. Every step shows the complete workflow file so far — copy-paste any step and it works on its own. New or changed lines are marked `# new`.

All the workflows below are **uv** projects. **Using Poetry?** Everything below works unchanged — the package manager is auto-detected from your lock file (`uv.lock` vs. `poetry.lock`). The only lines that differ are marked `# Poetry: '...'` — swap in that value and you have a working Poetry workflow.

Each step ends with what you should see when it runs. Every input used is linked to its [manual](../manual/README.md) page — read this tutorial to learn the shape of things, and the manual when you want the full detail on one of them.

## 1. A minimal weekly run

The action doesn't check out your repository itself, so `actions/checkout` comes first. `permissions:` is needed because the repository default for `GITHUB_TOKEN` is often read-only.

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
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

`workflow_dispatch` lets you trigger a run by hand from the Actions tab instead of waiting for Monday. `test-command` runs in `directory` via `bash -c` — see [inputs.md](../manual/inputs.md).

**What you should see:** on the next scheduled run (or a manual `workflow_dispatch`), a job named `update` runs, and — if any of your top-level packages have updates that pass `test-command` — a pull request titled "Update and successfully test packages" against your default branch, opened with the built-in `GITHUB_TOKEN`.

## 2. Try it safely first

Before trusting this against your real project, run it with `dry-run: 'true'`: it does everything — updates, tests, local commits — except pushing the branch or touching the PR. Read the result from the job summary instead.

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
          dry-run: 'true'   # new
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

Trigger it once with `workflow_dispatch`, then open the run in the Actions tab and scroll to its job summary — the same report a real run would put in the PR body is right there.

**What you should see:** the job summary shows the "✅ Updated" / "❌ Failed" / skipped tables, but no branch is pushed and no PR appears — `git status` in the job is clean the whole time. See [`dry-run`](../manual/dry-run.md).

Once you're happy with what you see, remove the `dry-run: 'true'` line (or set it to `'false'`) — the rest of this tutorial builds on the real thing.

## 3. Get CI running on the PR

A PR opened with the default `GITHUB_TOKEN` triggers no `pull_request` workflows at all — that's a deliberate GitHub Actions restriction. If you want your normal CI to run against the PR this action opens, pass a fine-grained PAT or GitHub App token to **both** `actions/checkout` and the action itself.

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
        with:
          token: ${{ secrets.DEPS_UPDATE_TOKEN }}   # new

      - uses: friedrichwilken/test-gated-python-updates@v2
        with:
          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}   # new
```

Create a fine-grained PAT (or a GitHub App installation token) with `contents: write` and `pull-requests: write`, and store it as the `DEPS_UPDATE_TOKEN` repository secret. Either way — this token or the plain `GITHUB_TOKEN` — the repository setting **Settings → Actions → General → Workflow permissions → "Allow GitHub Actions to create and approve pull requests"** must also be on, or PR creation is rejected outright. Full detail: [Token and permissions](../manual/token-and-permissions.md).

**What you should see:** the next PR this action opens (or updates) now also shows your repository's normal required checks running against it, the way any other PR would.

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

concurrency:   # new
  group: ${{ github.workflow }}   # new
  cancel-in-progress: false   # new

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
          pr-title-prefix: '[deps] '   # new
          pr-labels: 'dependencies'   # new
          base-branch: 'main'   # new
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

`pr-labels` must already exist in the repository — this action never creates one (`gh label create dependencies ...` once, or via your repo settings). `base-branch` is rarely needed (it already defaults to whichever branch is checked out) — set it explicitly if your checkout step ever lands on something other than the branch you want the PR opened against. `concurrency` stops two runs from racing to push the same fixed branch if a manual `workflow_dispatch` overlaps a scheduled run.

**What you should see:** the PR title is prefixed `[deps] `, carries the `dependencies` label, and targets `main` explicitly.

## 5. Faster runs: `strategy: batch-first`

With many updatable packages, testing one at a time costs one test run per package. `strategy: batch-first` updates everything at once and tests once, falling back to the per-package loop only if that combined test fails.

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
          strategy: 'batch-first'   # new
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

**What you should see:** if your project has several updatable packages and they all still pass together, the run's log shows exactly one test invocation instead of one per package — the PR report is identical either way, plus `tested_in_batch: true` in `report-json`. See [`strategy`](../manual/strategies.md).

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
          allow-major: 'true'   # new
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

**What you should see:** for a package with a capped constraint and a newer release available, the PR now either shows it updated with `(raised)` next to its bump, or — if the raised attempt failed its tests — a new "⚠️ Held back" table naming it, with the plain in-range update applied instead. See [`allow-major`](../manual/allow-major.md).

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
  issues: write   # new

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
          create-issues: 'true'   # new
          issue-labels: 'dependencies'   # new
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

`issue-labels` must already exist too, same rule as `pr-labels`. `issues: write` on the token is required — it also covers the read-only issue lookup this feature needs, so no separate `issues: read` is necessary.

**What you should see:** the first time a package fails, a new issue titled `<pkg>: update to <version> fails (...)`, carrying a hidden identity marker and the `dependencies` label. It gets updated silently on later still-failing runs, and closes itself automatically once the package updates cleanly. See [`create-issues`](../manual/create-issues.md).

## 8. Keep the rest fresh: `update-transitive`

Every step so far only ever touches your *top-level* dependencies. `update-transitive` adds one final step that refreshes everything else too, still within already-declared constraints. Paired here with `without-groups` to show excluding a group from the top-level loop entirely.

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
          update-transitive: 'true'   # new
          without-groups: 'dev'   # new
          github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

**uv note:** `"dev"` covers both a `dev` key in `[dependency-groups]` and uv's legacy `[tool.uv.dev-dependencies]`. **Poetry note:** the group name must be one you've actually declared (e.g. `[tool.poetry.group.dev]`) — there's no built-in `dev` group. Either way, see [Dependency groups](../manual/dependency-groups.md).

**Re-sync note:** if `test-command` itself runs `uv run ...`, be aware it re-syncs the environment first using **uv's own** default group selection, not this action's narrower `without-groups` one — a test that must not see the excluded group needs `uv run --no-sync ...` or `.venv/bin/python` directly instead. See [Package managers § `uv run` in `test-command` re-syncs](../manual/package-managers.md#uv-run-in-test-command-re-syncs).

**What you should see:** an extra commit, `Update transitive dependencies`, when anything transitive had room to move — and, once `without-groups: dev` is set, any package that lives only in your `dev` group no longer appears in `report-json` at all.

## 9. Hands-off: auto-merge the PR when CI is green

There's no `pr-number`/`pr-url` output on this action today, so the auto-merge step can't target "the PR this run just touched" directly. Instead, key a separate, `pull_request`-triggered workflow off the fixed branch name this action always uses (`deps/test-gated-updates`, or your own `branch-name` if you changed it) — the same pattern this repo uses for its own Dependabot PRs.

Add a second workflow file, `.github/workflows/automerge-deps.yml`:

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
    if: github.head_ref == 'deps/test-gated-updates'
    runs-on: ubuntu-latest
    steps:
      - name: Enable auto-merge
        env:
          GH_TOKEN: ${{ secrets.DEPS_UPDATE_TOKEN }}
          PR_URL: ${{ github.event.pull_request.html_url }}
        run: gh pr merge --auto --squash "$PR_URL"
```

This only fires on a real `pull_request` event, which needs the PAT from step 3 (`GITHUB_TOKEN` PRs never trigger it). It also needs the repository setting **Settings → General → Pull Requests → "Allow auto-merge"** on, and at least one required status check configured in branch protection — otherwise `gh pr merge --auto` has nothing to wait for and merges immediately.

**What you should see:** once your required checks pass on the update PR, it merges itself — no click required. If "Allow auto-merge" is off, `gh pr merge --auto` fails loudly instead of merging early; turn the setting on and re-run.

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
    if: github.head_ref == 'deps/test-gated-updates'
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
- the PR body / job summary this produces — [output-rendering.md](../manual/output-rendering.md)

This repository dogfoods a version of this same workflow on itself — see [`update_dependencies.yml`](../../.github/workflows/update_dependencies.yml) for a complete, currently-running example.
