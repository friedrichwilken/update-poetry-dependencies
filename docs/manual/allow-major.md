# `allow-major`

```yaml
allow-major: 'true'
```

Opt-in (default `false`): for a package whose declared constraint has an effective upper bound, also attempt an update beyond that bound (usually, but not always, a semver-major jump) before falling back to the plain in-range update.

## Why "beyond declared constraint" and not just "major"

`allow-major` is an opt-in, per-package extension of the same test-gated flow: for a package whose declared constraint has an effective upper bound (a caret/tilde/wildcard/`~=` Poetry constraint, or a PEP 508 specifier with `<`/`<=`/`~=`/`==x.*`), the ordinary in-range update never looks past that bound. Going beyond a declared constraint is not necessarily a semver-major jump — `six >=1.10,<1.15` allowing `1.17.0` is a minor bump that merely exceeded the declared range. `bump` in `report-json` always reports the real release segment that changed, computed from the actual version numbers, never assumed from the fact that a constraint was raised.

## What happens, per package

When an effective upper bound is found, before the plain in-range update:

1. **Attempt:** raise the declared constraint so the latest release is allowed (`poetry add "pkg[extras]@latest" --group <g>` / `--optional <extra>`, or for uv, rewrite just that requirement's specifier and re-lock with `uv add "pkg[extras]>=<bound>" --upgrade-package pkg`), then test exactly like an in-range update. If it passes, both `pyproject.toml` and the lock file are committed together (`Update <pkg> <old> -> <new> (constraint raised)`), tagged `constraint_raised: true` with `bump` set to the real delta, and the package is done — no separate in-range update runs for it.
2. **Fallback:** if raising the constraint fails to resolve, resolves but fails the test command, or resolves and passes but has to be discarded (see below), every touched file is reset and the environment re-synced, and the plain in-range update runs instead. Whichever outcome that produces also records the held-back attempt (`beyond_constraint_version`/`beyond_constraint_failure_kind`/`beyond_constraint_output_tail` in `report-json`; a `held-back-packages` output entry either way) or the discard reason (`beyond_constraint_skip_reason`) rather than a `failure_kind` — the tool itself did not fail, this action decided not to trust what it did.
3. If the in-range update fails too, the package is `failed` exactly as it would be without `allow-major`.

A package whose constraint has no effective upper bound needs no separate attempt — the in-range update already reaches the latest release — and is never double-tested.

## Declarations that are always skipped

Not every declaration shape can be safely rewritten without risking silently dropping information. These are always skipped rather than guessed at, reported via `beyond_constraint_skip_reason`:

- a git/path/url/workspace dependency, or a direct URL reference (`pkg @ ...`)
- more than one constraint entry for the package, or a Poetry `||` OR constraint where every alternative already has its own upper bound
- a dependency carrying `markers`/`python`/`platform`/`source`/`allow-prereleases` keys this feature cannot faithfully preserve
- an exact version pin (`==1.2.3`, or Poetry's bare `1.2.3`)
- a constraint/specifier this action's PEP 440-ish parser cannot parse
- a legacy Poetry `optional = true` dependency not listed in any `[tool.poetry.extras]` entry
- `python` itself

## Discarded after the tool call succeeds

Two more checks can still discard an otherwise-successful attempt (same effect as a failure — reset and fall back):

- the manifest is re-read and diffed against the original declaration; if anything other than the version constraint changed (extras dropped, moved to a different table, a marker appeared, ...), the change is discarded;
- if the attempted version is a pre-release and the original was not, it is discarded.

## In the report

The PR body gets a new "⚠️ Held back (update beyond declared constraint failed)" table (package, current, attempted, reason) once at least one package used it, and the "✅ Updated" table gains a `bump` column. With `allow-major` left at `false`, the rendered report and `report-json` are byte-identical to before this feature existed. See [The report](pr-report.md) and [outputs.md](outputs.md#report-json).

**Prerequisite:** like the lock file, `pyproject.toml` must have no uncommitted changes before this action runs — see [How it works](how-it-works.md#prerequisite-a-clean-manifestlock-file) — checked regardless of whether `allow-major` is enabled.
