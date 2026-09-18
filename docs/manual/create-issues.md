# `create-issues`

```yaml
create-issues: 'true'
issue-labels: 'dependencies'   # optional
```

```yaml
permissions:
  issues: write   # required
```

Opt-in (default `false`): files a durable, trackable GitHub issue per failing package instead of (or in addition to) the PR report, which only ever reflects the latest run. Runs after the PR is created/edited (so the issue can link to it) and requires `issues: write` on the token — see [Token and permissions](token-and-permissions.md).

## One issue per package, never per run

An issue is filed for every top-level package whose outcome this run is `failed`, or that has a held-back [`allow-major`](allow-major.md) attempt (`beyond_constraint_failure_kind` set). A package that is both (the beyond-constraint attempt *and* the in-range fallback both failed) gets one issue about the plain failure, not two.

## Identity: all three markers required

- a hidden marker in the issue body, `<!-- test-gated-updates:pkg=<name> -->` (`<name>` is the PEP 503 normalized package name) — **never the title**, which is free to change between runs;
- a second hidden marker, `<!-- test-gated-updates:state=<version>|<kind> -->`, recording what the last run reported;
- a footer line stating the issue is managed automatically.

Requiring all three (rather than the pkg marker alone) rules out, for example, a documentation issue that merely quotes the marker syntax as an example being mistaken for a managed one. The one edge case this cannot rule out: copy-pasting a managed issue's entire body verbatim into an unrelated issue would make that issue managed too — accepted as out of scope.

## Every run, per package that needs an issue

| Situation | Action |
|---|---|
| No existing open managed issue | **Create** one: title `<pkg>: update to <attempted> fails (<kind>)` (or the held-back-attempt variant), truncated to 256 characters if needed. Body: the pkg marker, current → attempted version, failure kind, captured output tail, a link to the workflow run, a link to the PR if one exists this run, a "last seen" note, and the managed-issue footer. Labels from `issue-labels` — **the label must already exist**, this action never creates one. |
| An existing open managed issue | **Update** its body to the current state. A **comment is added only if** the attempted version or failure kind changed since the state marker's last recorded value. |
| An existing open managed issue whose package is *not* failed/held-back this run | **Close** it, with a comment linking to the run (and the PR, if any). |
| More than one open managed issue for the same package | The **lowest-numbered** one is canonical; every other one is **closed** with a "Duplicate of #\<n\>" comment. |
| An open issue missing any of the three identity signals | **Never touched.** |

## Finding existing managed issues

Always starts from a plain, unfiltered `gh issue list --state open --json number,body --limit 200` — GitHub's issue *search* index is only eventually consistent, so it's never the primary source: relying on it first could miss an issue this same run (or a concurrent one) just created, and file a duplicate. Only if that plain listing comes back at exactly its `--limit` (there may be more than 200 open issues) does a second, search-narrowed call additionally run, merged in by issue number. Either way, every candidate's identity is always re-confirmed locally before it's trusted.

## Aborted runs

If the update loop itself aborts, issue management is skipped entirely and a `::notice::` is printed — the outcome list for an aborted run is only partial, and treating a package missing from it as "no longer failing" would incorrectly close its issue.

## `dry-run`

Performs no `gh` writes at all — only the read-only listing(s) run, so the plan can still be computed against real repository state. The planned actions are printed and exposed in `issue-actions` (`[]` when `create-issues` is off), e.g.:

```json
[{"package": "idna", "action": "create", "issue": null}]
```

A compact one-line summary is also appended to the job summary.

## Failures are isolated

Each package's `gh` call(s) are isolated — if one issue can no longer be commented on, every other package's create/update/close for this run still goes ahead. The failed action still shows up in `issue-actions` with an additive `error` field. **Failures never fail the run**: once the PR has been created/edited, it's this action's primary product, so `create-issues` failures never turn into a non-zero exit code.

## `update-transitive` interaction

A failed [`update-transitive`](update-transitive.md) step files one managed issue, keyed by the reserved package name `transitive-dependencies`, and closes it automatically once the step later passes (or is unchanged) again. If `update-transitive` is later turned back off while an issue for it is still open, it's still closed, but with a close comment explaining the feature is disabled rather than the usual "no longer failing" claim — that wouldn't be true, since nothing was actually checked this run.
