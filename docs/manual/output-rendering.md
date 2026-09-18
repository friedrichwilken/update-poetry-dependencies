# The report

```json
{"passed-packages": "six", "failed-packages": "idna"}
```

Per package, the rendered report shows: for an update, the old and new locked version; for a failure, the current and attempted version, whether it was a dependency-resolution failure or a test failure, and a collapsed block with the tail of the relevant output (resolver output for a resolution failure, test command output for a test failure). Package names, versions and failure reasons are escaped so they can never break the table formatting or be interpreted as markup.

The same rendering drives the PR body (`pr-body` output), the job summary (`GITHUB_STEP_SUMMARY`, written even in [`dry-run`](dry-run.md)), and `report-json` (the machine-readable form — see [outputs.md](outputs.md#report-json)).

## Sections

- Updated — every package that got a new version this run, with a `bump` column once [`allow-major`](allow-major.md) produced at least one.
- Failed
- Held back (update beyond declared constraint failed) — only when `allow-major` produced at least one, see [`allow-major`](allow-major.md).
- Transitive dependencies — only when [`update-transitive`](update-transitive.md) actually ran this run.
- Skipped packages (compact, one line)

## Size budgets

The rendering happens under an explicit character budget: well under GitHub's 65536 character PR body limit (`MAX_BODY_CHARS = 60000`), and a larger (but still bounded, `MAX_SUMMARY_CHARS = 900000`) budget for the job summary — so the job summary can carry more detail than the PR body for the same run. At either size, table rows and per-package output blocks are dropped (with a "N more, see `report-json`/job summary" note) as needed to stay under the budget — the guarantee holds regardless of how many packages or how much output there is.

`report-json`'s total size is capped independently (`MAX_REPORT_JSON_BYTES = 256 * 1024`, ~256 KiB): if needed, `output_tail` is dropped (in favor of `output_truncated: true`) from the packages with the largest captured output first, until it fits — every package still gets a record.

## Aborted runs

If the update loop has to abort early (currently only when re-syncing the environment after a discarded update itself fails), the rendered output still covers everything processed before the abort — already-made commits for packages that passed stay made locally, but the run is not pushed and no PR is created/edited — and starts with a "Run aborted: `<reason>`" banner. See [How it works § Reset and re-sync](how-it-works.md#reset-and-re-sync).
