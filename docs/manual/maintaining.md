# Maintaining this repo

```sh
uv sync --locked
uv run pytest tests/unit -q
uv run ruff check .
uv run ruff format --check .
```

Notes for whoever maintains `friedrichwilken/test-gated-python-updates` itself — not relevant to consumers of the action.

## Dev setup

The dev tooling is itself a `uv` project (`pyproject.toml` at the repo root, name `update-poetry-dependencies-dev`) — it only pins `pytest`/`ruff` for local dev and CI; it is not a distributable package. The action itself is a stdlib-only script run via `uv run --no-project` (see `action.yml`).

```sh
uv sync --locked
```

## Tests

```sh
uv run pytest tests/unit -q
```

`tests/unit` is the fast, hermetic suite (fakes for git/gh/backends — see `tests/unit/fakes.py`); `check_action.yml`'s `e2e` job additionally runs the action against real fixture projects under `tests/fixture/` (both Poetry and uv, several scenarios: basic, major, batch, groups) in `dry-run`, using `uses: ./`.

## Linting

```sh
uv run ruff check .
uv run ruff format --check .
```

`check_action.yml`'s `actionlint` job also lints every workflow file and `action.yml` itself with `raven-actions/actionlint`.

## Docs validation

The `docs` CI job renders every complete workflow example from `README.md`/`docs/**/*.md` against `./` (the local `action.yml`) and runs actionlint on the result, so a documented `with:` key that doesn't exist (or a value actionlint would reject) fails CI. `tests/unit/test_readme_sync.py` separately keeps the input/output tables in [`inputs.md`](inputs.md)/[`outputs.md`](outputs.md) honest against `action.yml`.

**`uv run pytest tests/unit` does not exercise the Poetry rendition of the tutorial.** `tests/unit/test_docs_examples.py` checks the `with:` keys of every documented example exactly as written (uv), never the mechanically generated Poetry variant (applying each `# Poetry: ...` comment) - only `python3 .github/scripts/lint_docs_workflows.py` (the same script the `docs` CI job runs; needs `actionlint` on `PATH`) renders and lints both. Run it locally after touching the tutorial's Poetry-only lines.

## Why the e2e fixtures pin old versions

`tests/fixture/*` deliberately lock **old** (even vulnerable) versions of a handful of small packages, so the action has something to update when the e2e job runs it in `dry-run`. Dependabot would otherwise keep opening security-update PRs against those exact fixture files and break them — [`dependabot.yml`](../../.github/dependabot.yml) sets `open-pull-requests-limit: 0` and ignores every dependency under `tests/fixture/*` for both the `pip` and `uv` ecosystems to stop that.

## Dependabot + auto-merge

[`dependabot.yml`](../../.github/dependabot.yml) keeps GitHub Actions dependencies (grouped into one PR) and this repo's own dev dependencies up to date on a weekly schedule. [`dependabot_automerge.yml`](../../.github/workflows/dependabot_automerge.yml) auto-merges a non-major Dependabot PR once its checks pass, but only actually enables auto-merge if the repository setting **Settings → General → Pull Requests → "Allow auto-merge"** is on; if it's off, the workflow prints a `::warning::` and exits cleanly instead of failing.

## This repo's own dependency updates

[`update_dependencies.yml`](../../.github/workflows/update_dependencies.yml) dogfoods the action on itself (`uses: ./`, uv backend) and needs a `DEPS_UPDATE_TOKEN` secret (see [Token and permissions](token-and-permissions.md)) to get CI running on the PRs it opens; it falls back to `github.token` otherwise.

## Release process

[`release.yml`](../../.github/workflows/release.yml) only reacts to a pushed `vX.Y.Z` tag and only ever force-moves the major tag matching that same `X` (e.g. pushing `v2.3.0` moves `v2`) — it can never touch `v1`, the legacy bash action, and explicitly refuses to if a `v1.x.y` tag is ever pushed by mistake. See [Versioning](versioning.md).
