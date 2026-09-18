# Versioning

```yaml
uses: friedrichwilken/test-gated-python-updates@v2
```

`v2` is a major-version tag: [`release.yml`](../../.github/workflows/release.yml) force-moves it to point at the latest `v2.x.y` release every time a `vX.Y.Z` tag is pushed, so pinning to `@v2` tracks new releases within the same major version automatically.

## Pinning by SHA

For a reproducible, supply-chain-hardened pin, use a full commit SHA instead:

```yaml
uses: friedrichwilken/test-gated-python-updates@<sha>  # v2.1.0
```

This is the same pattern this repo's own workflows use for third-party actions (see [`check_action.yml`](../../.github/workflows/check_action.yml) or [`update_dependencies.yml`](../../.github/workflows/update_dependencies.yml)) — a comment naming the version keeps the pin readable without giving up the exact-commit guarantee.

## `v1`

`v1`, the original bash-based action, is frozen at the `v1`/`v1.0.1` tags and unmaintained — it will never be moved or updated further; [`release.yml`](../../.github/workflows/release.yml) explicitly refuses to move it. See [Migrating from v1](migrating-from-v1.md) if you're still on it.
