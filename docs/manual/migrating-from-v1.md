# Migrating from v1

```yaml
- uses: actions/checkout@v4      # new: v2 no longer checks itself out
  with:
    token: ${{ secrets.DEPS_UPDATE_TOKEN }}

- uses: friedrichwilken/test-gated-python-updates@v2
  with:
    github_token: ${{ secrets.DEPS_UPDATE_TOKEN }}
```

`v2` is a breaking rewrite: Python instead of bash, `uv`-based bootstrapping, and some input/output changes.

`v1` is the original bash-based action. It is frozen at the `v1`/`v1.0.1` tags and unmaintained — it will not be moved or updated further.

To migrate:

1. Add an explicit `actions/checkout` step before this action in your workflow — v1 checked out the repository itself; v2 does not.
2. Pass your token to **both** `actions/checkout`'s `token:` input and this action's `github_token` input (see [Token and permissions](token-and-permissions.md)) — v1 only needed `github_token`.
3. Check [Inputs](inputs.md) and [Outputs](outputs.md) against your existing `with:` block — some defaults changed (e.g. `poetry-version` now defaults to a Poetry 2.x release) and `package-manager` is new (for uv support; defaults to `auto`-detecting from the lock file).
4. Drop any `actions/setup-python` / `snok/install-poetry` steps you had before this action — v2's `uv`-based bootstrap replaces them entirely; see [How it works § Bootstrap](how-it-works.md#bootstrap-everything-through-uv).

See [Versioning](versioning.md) for how v2 tags move, and how to pin more strictly if you want to.
