# Token and permissions

A PR opened with the default `GITHUB_TOKEN` gets no CI checks. If you want checks on the PR this action opens, use a fine-grained PAT or a GitHub App installation token instead, passed to **both** `actions/checkout` and this action.

## Why `GITHUB_TOKEN` isn't enough

A pull request opened with the default, ephemeral `GITHUB_TOKEN` does **not** trigger other `pull_request` (or `pull_request_target`) workflows — this is a deliberate GitHub Actions restriction to stop workflows from recursively triggering themselves. If you rely on CI checks running against the PR this action opens, `GITHUB_TOKEN` alone will leave it with no checks at all.

## Use a PAT or App token

To get normal CI on the resulting PR, use a fine-grained personal access token or a GitHub App installation token, with at least:

- `contents: write` (push the update branch)
- `pull-requests: write` (create/edit the PR, add labels)
- `issues: write` too, only if you enable [`create-issues`](create-issues.md) — it also covers the read-only `gh issue list` lookup `create-issues` needs, so no separate `issues: read` is needed

## Pass it in two places

That token has to go to **both** places, because two different things authenticate independently:

```yaml
- uses: actions/checkout@v4
  with:
    token: ${{ secrets.DEPS_UPDATE_TOKEN }}

- uses: friedrichwilken/test-gated-python-updates@v2
  with:
    github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

1. `actions/checkout`'s `token:` input — `actions/checkout` persists this as the git credential for the checkout, and this action's own `git push` relies entirely on those persisted credentials; it never receives or handles a token itself for the push.
2. This action's `github_token` input — used for `gh pr create`/`gh pr edit` and, when `create-issues` is enabled, `gh issue list`/`create`/`edit`/`comment`/`close`, which all shell out to the `gh` CLI authenticated via `GH_TOKEN`.

## Sticking with `GITHUB_TOKEN`

If you'd rather stick with `GITHUB_TOKEN` (accepting that the PR gets no automatic checks, or that you trigger checks another way, e.g. `workflow_run`), the calling workflow must still declare the permissions explicitly — the repository default for `GITHUB_TOKEN` is often read-only:

```yaml
permissions:
  contents: write
  pull-requests: write
  # issues: write   # only if create-issues is enabled
```

## The repository setting

Either way, **Settings → Actions → General → Workflow permissions → "Allow GitHub Actions to create and approve pull requests"** must be enabled, or PR creation is rejected outright regardless of which token is used.
