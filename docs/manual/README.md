# Manual

Reference documentation: what's there, precisely. Looking for a guided walkthrough instead? See the [tutorial](../tutorials/weekly-updates.md).

- [Inputs](inputs.md) — every `with:` key, grouped by topic.
- [Outputs](outputs.md) — every output, including the `report-json`, `issue-actions` and `transitive-report` JSON schemas.
- [How it works](how-it-works.md) — the update loop, the clean-tree prerequisite, the fixed branch/PR, and how the action bootstraps itself with `uv`.
- [Token and permissions](token-and-permissions.md) — `GITHUB_TOKEN` vs. a PAT/App token, the `permissions:` block, and the repo setting you need.
- [Package managers](package-managers.md) — auto-detection, and Poetry/uv specifics.
- [`allow-major`](allow-major.md) — attempting updates beyond the declared constraint.
- [`strategy`](strategies.md) — `per-package` vs. `batch-first`.
- [`create-issues`](create-issues.md) — filing one tracked issue per failing package.
- [`update-transitive`](update-transitive.md) — refreshing transitive dependencies.
- [Dependency groups](dependency-groups.md) — `with-groups` / `without-groups` / `only-groups`.
- [`dry-run`](dry-run.md) — previewing a run without pushing anything.
- [The report](output-rendering.md) — how the PR body and job summary are rendered and budgeted.
- [Migrating from v1](migrating-from-v1.md) — the breaking changes from the old bash action.
- [Versioning](versioning.md) — tags, pinning, and the release process.
- [Maintaining this repo](maintaining.md) — dev setup, tests, and how the maintainer releases new versions.
