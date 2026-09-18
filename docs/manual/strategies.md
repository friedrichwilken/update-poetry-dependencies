# `strategy`

```yaml
strategy: 'batch-first'
```

`strategy` (default `per-package`) picks how the update loop spends test runs.

## Test-run cost

| Strategy | Happy path (every package updates cleanly) | If something fails |
|---|---|---|
| `per-package` (default) | N test runs (one per package) | N test runs, as usual |
| `batch-first` | 1 test run | up to N+1 test runs (falls back to `per-package`) |

## `per-package`

Today's behavior, unchanged: update, test and commit one top-level package at a time.

## `batch-first`

An opt-in alternative that costs only 1 test run in the happy path:

1. **Batch:** update every top-level package at once (`poetry update <pkgs...>` / `uv lock --upgrade-package <pkg> ...` repeated once per package plus one `uv sync`) — in-range only. If nothing changed in the lock, every package is reported `skipped` and nothing is tested.
2. **Test once**, against the whole batch.
   - **Fails:** reset the lock/manifest to before the batch ran, re-sync, and run the ordinary `per-package` loop for every package instead — worst case N+1 test runs total, same final result `per-package` would have produced. `report-json` marks every outcome `batch_test_failed: true`.
   - **Passes:** reset to before the batch again, then replay each changed package's own update and commit it on its own, in sequence, *without* testing in between — so the git history and PR report look exactly like a `per-package` run would have produced, just without paying for N-1 extra test runs. Once every package has been replayed, compare against the batch's own lock file:
     - **Matches:** done. Every replayed package is reported `updated` with `tested_in_batch: true`. A package that produces no lock change of its own — because an earlier package's replay already pulled it to the batch's target version, most commonly a shared transitive dependency — needs no separate commit: it's still reported `updated`, tagged `bundled_with: "<other package>"` naming whichever commit the change actually lives in.
     - **Diverges:** one more test run, against the diverged sequential result. Passes → keep it (still `tested_in_batch: true`). Fails → discard every replay commit and fall back to `per-package` for everything (this path does not set `batch_test_failed` — the batch's own test genuinely passed; it's the replay that couldn't be trusted).

A re-sync failure at any point aborts the whole run, exactly like `per-package` — see [How it works](how-it-works.md#reset-and-re-sync).

## Interaction with `allow-major`

The batch step itself only ever performs in-range updates, even when `allow-major` is enabled. Once the batch (or its replay) has landed, `allow-major`'s beyond-constraint attempts still run exactly as they do without `batch-first`: one at a time, per package, each with its own test run. A package that gets both an in-range update from the batch *and* a further beyond-constraint attempt ends up with two commits instead of one, but is still reported as a single outcome spanning the whole journey. `batch-first` only ever saves test runs on the in-range portion of the work; `allow-major`'s own test-per-attempt cost is unchanged either way. See [`allow-major`](allow-major.md).

`report-json` marks every outcome of a `batch-first` run with `strategy: "batch-first"`, additionally to `tested_in_batch`/`batch_test_failed`/`bundled_with`. With `strategy` left at `per-package`, the rendered report, job summary and `report-json` are byte-identical to before this feature existed. See [outputs.md](outputs.md#report-json).
