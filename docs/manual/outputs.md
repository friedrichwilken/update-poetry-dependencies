# Outputs

Every output this action sets. Generated from `action.yml`.

| Name | Description |
|---|---|
| `passed-packages` | Comma separated list of packages that were updated and passed the test command. |
| `failed-packages` | Comma separated list of packages whose update or test failed and were discarded. |
| `skipped-packages` | Comma separated list of packages that had nothing to update. |
| `held-back-packages` | Comma separated list of packages where an update beyond the declared constraint was attempted (`allow-major`) but held back — the package may still show up in `passed-packages`/`failed-packages`/`skipped-packages` for the in-range update that ran instead. |
| `pr-body` | The rendered report / PR body. |
| `report-json` | JSON array of per-package update records. Schema below. |
| `issue-actions` | JSON array of planned/performed `create-issues` actions. Schema below. |
| `transitive-report` | A single JSON object reporting the `update-transitive` step, or the JSON literal `null`. Schema below. |

The same report is also written to the job summary (`GITHUB_STEP_SUMMARY`), including in `dry-run`. See [The report](output-rendering.md) for how `pr-body` and the job summary are rendered and budgeted.

## `report-json`

One object per top-level package processed this run.

```json
[
  {"name": "idna", "status": "updated", "old_version": "3.6", "new_version": "3.7", "failure_kind": null, "output_tail": ""}
]
```

| Field | Type | Description |
|---|---|---|
| `name` | string | The top-level package name. |
| `status` | string | One of `updated`, `failed`, `skipped`. |
| `old_version` | string \| null | The version locked before this run touched the package, or `null` if unknown. |
| `new_version` | string \| null | For `updated`/`skipped`: the resulting locked version. For `failed`: the version that was attempted before the change was reverted. `null` if unknown. |
| `failure_kind` | string \| null | `resolution` (the update/lock step itself failed), `test` (the test command failed), or `null` for a non-failure. |
| `output_tail` | string | Tail of the relevant captured output for a failure (empty otherwise), ANSI escape codes stripped. |
| `output_truncated` | boolean | Only present (`true`) when `output_tail` was dropped to keep `report-json` under its ~256 KiB size cap; absent otherwise. |

Additive fields, only present when the corresponding feature produced them:

| Field | Feature | Description |
|---|---|---|
| `bump` | [`allow-major`](allow-major.md) | Only on an `updated` outcome: the real release segment that changed — `major`, `minor`, `patch`, or `other` — regardless of whether this was an in-range update or one that raised the constraint. |
| `constraint_raised` | `allow-major` | Only present (`true`) when this outcome's own commit raised the declared constraint itself. |
| `beyond_constraint_version` | `allow-major` | The version a held-back beyond-constraint attempt tried. |
| `beyond_constraint_failure_kind` | `allow-major` | `resolution` or `test`, same meaning as `failure_kind` but for the held-back attempt. |
| `beyond_constraint_output_tail` | `allow-major` | Tail of the held-back attempt's captured output. |
| `beyond_constraint_output_truncated` | `allow-major` | Only present (`true`) when output was dropped to keep `report-json` under its size cap. |
| `beyond_constraint_skip_reason` | `allow-major` | Only present when `allow-major` is enabled but no attempt could be made for this package at all (e.g. a git/path dependency, an exact pin, an unparsable constraint). |
| `strategy` | [`strategy`](strategies.md) | Only present (`"batch-first"`) when `strategy: batch-first` was requested for this run. |
| `tested_in_batch` | `strategy` | Only present (`true`) on an outcome validated by the shared batch test run rather than its own dedicated test run. |
| `batch_test_failed` | `strategy` | Only present (`true`) on every outcome when the batch's own one-shot test failed and the run fell back to `per-package` for everything. |
| `bundled_with` | `strategy` | Only present on a `batch-first` outcome whose own replay step produced no lock change of its own because an earlier package's replay already pulled it to the batch's target version. Names that other package. |

## `issue-actions`

One object per package `create-issues` acted on this run; `[]` when `create-issues` is off.

```json
[{"package": "idna", "action": "create", "issue": null}]
```

| Field | Type | Description |
|---|---|---|
| `package` | string | The affected package name (or the reserved `transitive-dependencies`). |
| `action` | string | `create`, `update`, or `close`. |
| `issue` | number \| null | The existing/created issue number, or `null` for a not-yet-created issue (always `null` in `dry-run`, and for a failed create). |
| `error` | string | Additive: only present when this specific action's own `gh` call failed. |

See [`create-issues`](create-issues.md) for the identity rules and decision table behind this.

## `transitive-report`

A single JSON object, or the JSON literal `null` when `update-transitive` is off (the default) or the run aborted before the step ran.

```json
{"status": "updated", "changed_packages": [{"name": "certifi", "old": "2024.2.2", "new": "2024.7.4"}], "failure_kind": null, "output_tail": ""}
```

| Field | Type | Description |
|---|---|---|
| `status` | string | `updated`, `failed`, or `unchanged`. |
| `changed_packages` | array | `{name, old, new}` for every package the lock's before/after snapshot differed on — not just the package(s) the refresh command directly targeted. Present even for a discarded `failed` attempt. |
| `failure_kind` | string | Only present when `status` is `failed`: `resolution` or `test`, same meaning as `report-json`'s field. |
| `output_tail` | string | Only present when `status` is `failed`. |

See [`update-transitive`](update-transitive.md).
