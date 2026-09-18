# Dependency groups

```yaml
without-groups: 'dev'
```

`with-groups`, `without-groups` and `only-groups` (all default `""`) control which dependency **groups** a run considers, for two purposes: (1) which top-level packages get iterated by the update loop, and (2) what gets installed/synced so tests run against the intended set.

All three are comma/newline separated lists, parsed exactly like `pr-labels`. `with-groups` and `without-groups` may be combined; `only-groups` is mutually exclusive with both — combining it with either fails fast, as does naming a group that doesn't exist in the project's `pyproject.toml`, both checked before bootstrap/install, let alone the update loop itself.

`"main"` names the project's own ungrouped dependencies (`[project.dependencies]` / `[tool.poetry.dependencies]`) — never a real group in either backend's own vocabulary, but always a valid name here for symmetry with the named groups.

## Poetry

Maps straight onto `poetry show -T`/`install`/`sync`'s own `--with`/`--without`/`--only` flags (`"main"` is already a real group name to Poetry itself). With none of the three set, behavior is unchanged from before this feature existed.

A `[dependency-groups]` (PEP 735) name is only a valid group when `poetry-version` is `2.2` or later — naming such a group with an older `poetry-version` fails fast with a message saying so, rather than the generic "unknown group" error.

## uv

uv has no single built-in command that lists top-level dependency names the way `poetry show -T` does, so the listing side is filtered in Python against `"main"` (`[project.dependencies]`), `"dev"` (the legacy `[tool.uv.dev-dependencies]` list *or* a `dev` key inside `[dependency-groups]` — both mean the same thing), and every other `[dependency-groups]` (PEP 735) name — including following `{include-group = "..."}` entries *transitively* (cycle-safe), exactly like uv's own resolver does. Example: given `test = ["certifi"]` and `dev = [{include-group = "test"}, "six"]`:

- `only-groups: dev` includes both `six` and `certifi`
- `only-groups: test` includes only `certifi`
- `without-groups: test` still includes `certifi` (reachable through `dev`, which was never excluded)

`with-groups` has no effect on the listing side: with none of the three set, every group is already iterated (today's behavior, unchanged) — it only matters for what gets synced.

For `uv sync`, once any of the three is set, the selection switches from this action's own permissive default (`--all-groups --all-extras`, unchanged when none of the three are set) to uv's own native default group set (main plus whatever is a default group, most commonly just `dev`) adjusted by `--group`/`--no-group`/`--only-group` (which handle PEP 735 `include-group` transitivity natively — uv's own job, not this action's). Extras (`--all-extras`, or nothing under `tool.uv.conflicts` — see [Package managers](package-managers.md)) are a separate axis this feature does not touch.

### Known gap: `without-groups: main` cannot be honored for `uv sync`

`without-groups: main` is fully honored for *listing* (main-declared packages simply aren't iterated — a pure `pyproject.toml` parse, no uv flag needed) but **cannot** be honored for `uv sync`'s own selection — uv has no flag to exclude `[project.dependencies]` from `sync` while still installing other groups, so main is still installed either way; a `::warning::` is printed once when this applies.

### `uv-sync-args` always wins

`uv-sync-args`, when set, always wins for sync and replaces the selection outright, same as without this feature at all — `without-groups`/`only-groups` then only ever filter the listing side (`with-groups` still has no listing effect either way). See [Package managers](package-managers.md#uv).

**Note:** if `test-command` itself calls `uv run`, it re-syncs using uv's own default selection, ignoring this action's narrower one for the duration of that call — see [Package managers § uv run in test-command re-syncs](package-managers.md#uv-run-in-test-command-re-syncs).
