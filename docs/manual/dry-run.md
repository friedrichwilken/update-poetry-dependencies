# `dry-run`

```yaml
dry-run: 'true'
```

Runs the full update loop — updating, testing, committing locally — but skips pushing the branch and creating/updating the PR (default `false`). Nothing on GitHub changes.

Everything else still happens: packages are updated and tested exactly as in a real run, commits are made locally, and the report is still rendered and written to the job summary (`GITHUB_STEP_SUMMARY`) and the `pr-body`/`report-json` outputs — so you can read the report from the job summary, or consume the outputs in a later step, without anything being pushed.

If [`create-issues`](create-issues.md) is also enabled, no `gh` writes happen either — only the read-only issue listing runs, so the plan is still computed against real repository state and exposed via `issue-actions`, with every `issue` field `null` (nothing was actually created).

Use this to try a new configuration (a new `test-command`, `allow-major`, a stricter `strategy`) against your real project before trusting it to open a PR.
