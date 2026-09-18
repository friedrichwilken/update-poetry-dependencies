# `update-transitive`

```yaml
update-transitive: 'true'
```

Opt-in (default `false`), run-level (not per-package) final step: after the top-level loop (either [`strategy`](strategies.md)) and any [`allow-major`](allow-major.md) beyond-constraint attempts have both finished, it refreshes *everything* — transitive dependencies included, and any top-level package `with-groups`/`without-groups`/`only-groups` left out of this run's own iteration — that is still updatable within its already-declared constraints.

Every other feature only ever touches *top-level* packages (`poetry show -T` / this action's own uv equivalent); this is the one step that reaches transitive dependencies at all.

## What it does

1. **Refresh:** `poetry update --lock --no-interaction` / `uv lock --upgrade`, then a sync — verified to only ever change the lock file, never `pyproject.toml`. If the lock doesn't change, nothing further happens (reported `"unchanged"`).
2. **Test once**, against the refreshed lock — exactly like every other tested step in this action.
   - **Passes:** committed as its own commit, `Update transitive dependencies`.
   - **Fails**, or the refresh command itself fails to resolve: the lock file is reset to its pre-step state and the environment re-synced; nothing is committed.

## Its own output

Unlike a per-package update, one lock-wide refresh has no single old/new version of its own, so it's **not** folded into `report-json`'s per-package array — it gets its own `transitive-report` output: `{status, changed_packages, failure_kind, output_tail}`. `changed_packages` lists every package the lock's before/after snapshot differed on, not just whichever package(s) the refresh command directly targeted (moving one package can move others) — present even for a discarded `"failed"` attempt, to show what would have changed. See [outputs.md](outputs.md#transitive-report) for the full schema.

The PR body / job summary get a new "🔁 Transitive dependencies" section (only rendered when the step actually ran) listing every changed package's old → new version, or, on failure, the same collapsed output block used everywhere else in the report.

## `create-issues` interaction

A failed step files one managed issue, keyed by the reserved package name `transitive-dependencies`, closed automatically once the step later passes (or is unchanged) again. See [`create-issues`](create-issues.md#update-transitive-interaction).

## Aborted runs

If the run aborts — whether during the top-level loop or during this step's own re-sync — the report still reflects whatever `transitive-report` state exists at that point (the step's own `"failed"` outcome if the abort happened while discarding it, otherwise `null`), the same "partial, not pushed" handling described in [How it works](how-it-works.md#reset-and-re-sync).
