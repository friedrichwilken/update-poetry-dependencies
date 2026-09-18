# Package managers

The action supports Poetry and uv projects; `package-manager` (default `auto`) detects which one from the lock file present in `directory` — `poetry.lock` or `uv.lock`. Set it explicitly (`poetry` or `uv`) if you'd rather not rely on detection.

## Poetry

Nothing extra to configure beyond `poetry-version` (default `2.4.3`). Top-level packages come from `poetry show -T`; groups map straight onto Poetry's own `--with`/`--without`/`--only` flags for `install`/`sync` (see [Dependency groups](dependency-groups.md)).

A `[dependency-groups]` (PEP 735) name is only a valid group when `poetry-version` is `2.2` or later — PEP 735 support was added in Poetry 2.2.0. Naming such a group with an older `poetry-version` fails fast with a message saying so.

## uv

`uv-sync-args` (default `""`) overrides the default `--all-groups --all-extras` selection passed to `uv sync` — parsed as shell arguments, e.g. `--extra cpu --group dev`.

### `tool.uv.conflicts`

If the project declares [`tool.uv.conflicts`](https://docs.astral.sh/uv/concepts/projects/dependencies/#conflicting-dependencies) (mutually exclusive extras/groups, e.g. a `cpu`/`gpu` extra pair), the default `--all-groups --all-extras` selection would try to install both sides at once and `uv sync` fails outright. When that's detected and `uv-sync-args` is not set, the action falls back to `uv sync` with no extras and only the default dependency groups, and prints a `::warning::`. Set `uv-sync-args` to choose what actually gets installed.

### Workspaces are not supported

Only the `pyproject.toml` in `directory` is read to find top-level dependencies. A `tool.uv.workspace` root's member projects are not iterated, and workspace `uv.lock` files live at the workspace root rather than in an individual member's directory.

### `uv run` in `test-command` re-syncs

If `test-command` itself invokes `uv run` (e.g. `uv run pytest`) together with `with-groups`/`without-groups`/`only-groups`, be aware that `uv run` re-syncs the environment on its own first, using **uv's own default group/extra selection** — not this action's narrower one (verified against real `uv==0.12.14`: a group this action's own sync correctly excluded gets silently reinstalled for the duration of that `uv run` invocation). This never affects which packages get iterated/reported, only what a test command that itself re-syncs actually sees installed while it runs. If a test genuinely depends on a group being absent, invoke `uv run --no-sync <command>` (or the venv's own interpreter directly, e.g. `.venv/bin/python -m pytest`) in `test-command` instead.

See [Dependency groups](dependency-groups.md) for the full group-selection semantics of both backends, and [How it works](how-it-works.md) for the bootstrap sequence common to both.
