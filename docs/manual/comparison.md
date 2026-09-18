# How is this different from Dependabot / Renovate?

Dependabot and Renovate cover many ecosystems, open PRs for security advisories, and can group updates into one PR — but a grouped PR is all-or-nothing: if one package in the group breaks your tests, the whole PR is red and you're back to untangling it by hand. This action only ever does Poetry/uv, but tests every package individually first: what passes ships in one green PR, what fails is dropped and reported (or filed as an issue), and nothing you'd have to untangle ever lands in the PR in the first place.

## The trade-offs, factually

| | This action | Dependabot / Renovate |
|---|---|---|
| Ecosystem coverage | Poetry and uv only | Dozens of ecosystems ([Dependabot's supported list](https://docs.github.com/en/code-security/dependabot/ecosystems-supported-by-dependabot), [Renovate's supported managers](https://docs.renovatebot.com/modules/manager/)) |
| Security advisories | No — this is an update runner, not a vulnerability scanner | Yes — both can open dedicated security-update PRs from advisory data |
| Grouped updates | Every top-level package is tested on its own by default; a failing one is dropped, not merged into the group ([`strategy: batch-first`](strategies.md) trades some of that isolation back for speed, with an automatic fallback to per-package on failure) | Both support grouping ([Dependabot groups](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuring-dependabot-version-updates#grouping-dependency-updates), [Renovate groups](https://docs.renovatebot.com/configuration-options/#groupname)) — but a group PR lives or dies together; one failing package fails the whole group's CI run |
| Failures | Reported in the PR body, and optionally [tracked as a durable issue per package](create-issues.md) | Surface as a red check on the (possibly grouped) PR; no separate per-package tracking |
| Where it runs | Your own GitHub Actions minutes ([how it works](how-it-works.md)) | Dependabot: GitHub-hosted, no minutes charged. Renovate: self-hosted or the hosted app, depending on setup |

## When Dependabot or Renovate is the better choice

If you need security-advisory coverage, ecosystems beyond Poetry/uv, or don't run a test suite this action could gate on in the first place, Dependabot or Renovate is the better (and in the security-advisory case, the only) choice. This action is narrower on purpose: it assumes you already have tests, and trades ecosystem breadth for testing every package before it ever reaches your PR.
