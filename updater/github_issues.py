"""Opt-in (`create-issues`): one GitHub issue per top-level package that is
either `failed` or has a held-back beyond-constraint attempt
(`beyond_constraint_failure_kind` set - see `updater.py`/issue #21),
created/updated/closed across runs instead of piling up noise.

Identity requires *all three* of: a hidden pkg marker in the issue body,
`<!-- test-gated-updates:pkg=<normalized name> -->` (never the title, which
is free to change); a state marker,
`<!-- test-gated-updates:state=<version>|<kind> -->`, which records what the
last run reported for that package so `plan_issue_actions` can tell whether
a comment is warranted without an extra `gh` call; and the managed-by
footer text (`_MANAGED_BY_FOOTER`). Every issue this action itself creates
always carries all three, so this is only ever a *stricter* check, never a
missed real one - see `parse_managed_issues`. Requiring all three (rather
than the pkg marker alone) rules out a document that merely quotes the pkg
marker syntax as an example (see the false positive noted on
`_VALID_NORMALIZED_NAME_RE` below) being mistaken for a managed issue. The
one edge case this cannot rule out: someone copy-pasting a managed issue's
entire body verbatim into an unrelated issue - accepted as out of scope
(see the README).

Finding existing managed issues (`GithubIssues.list_open_managed`) always
starts from a plain, unfiltered `gh issue list` - GitHub's issue *search*
index (`--search`) is only eventually consistent, so relying on it as the
primary source could miss an issue created moments earlier in the same
run/a concurrent run and create a duplicate. `--search` is only ever used
as a supplementary pass, and only when the plain listing comes back at
exactly its `--limit` (i.e. it may itself have been truncated) - its
results are merged into the plain listing by issue number rather than
trusted alone. Because both mechanisms are outside this action's control,
`plan_issue_actions` still has to cope with more than one open managed
issue turning up for the same package: it treats the lowest-numbered one
as canonical and plans to close every other one as a duplicate.

The module is split into three layers, in line with the rest of this
codebase's style (see `updater.py`/`github_pr.py`):

- `issue_target_for`/`plan_issue_actions`: pure decision logic, no `gh`
  calls, fully unit testable as a decision table.
- `render_issue_title`/`render_issue_body`: pure rendering, reusing
  `report.py`'s safe-cell/fence helpers so a package name or captured
  output can never break the issue body's markdown.
- `GithubIssues`/`execute_issue_actions`/`run_issue_management`: the `gh`
  CLI wrapper and the orchestration that actually calls it (or, in
  dry-run, does not). `execute_issue_actions` isolates each action's `gh`
  call(s): one failing action is recorded and skipped, never aborting the
  rest of the plan.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from .config import parse_labels
from .errors import ActionError
from .pyproject_deps import normalize_name
from .report import _REASON_LABELS, _cell, _detail_block
from .runner import CommandRunner
from .updater import ChangedTransitivePackage, PackageOutcome, TransitiveOutcome

IssueActionKind = Literal["create", "update", "close"]

# The reserved, already-normalized package name used for the
# update-transitive step's own managed issue (issue #24) - never a real
# top-level package, but a valid normalize_name() output
# (_VALID_NORMALIZED_NAME_RE below), so it is indistinguishable from a real
# one to the rest of this module's identity checks.
TRANSITIVE_ISSUE_PACKAGE = "transitive-dependencies"

# How many changed packages a transitive-dependencies issue body lists
# before capping with a "N more" note - mirrors report.py's own
# budgeted-list pattern, just with a fixed count instead of a character
# budget (an issue body has no comparably tight size limit to guard).
_MAX_CHANGED_PACKAGES_IN_ISSUE = 50

# GitHub's own limit is much higher, but a title this long has already lost
# any value as a title - see render_issue_title.
_MAX_TITLE_LENGTH = 256

# Marker regexes are intentionally permissive about surrounding whitespace
# (a human or a future version of this code could reformat the comment
# slightly) but always require the exact `key=` prefix, so they never
# accidentally match an unrelated HTML comment.
_PKG_MARKER_RE = re.compile(r"<!--\s*test-gated-updates:pkg=(\S+?)\s*-->")
_STATE_MARKER_RE = re.compile(r"<!--\s*test-gated-updates:state=(.*?)\|(.*?)\s*-->")

# A real pkg marker's payload is always normalize_name()'s output: lowercase
# letters, digits and single hyphens only. Found by testing list_open_managed
# against this repo's own issue #28, which - being the design issue for this
# very feature - literally quotes `<!-- test-gated-updates:pkg=<name> -->` as
# an example in its body; without this check that placeholder is picked up
# as a real marker (extracting the package name "<name>"), which would make
# an actual (non-dry-run) run try to close issue #28 itself as "no longer
# failing". Requiring the payload to look like a real normalized name is a
# cheap, effective guard against that whole class of false positive -
# documentation/discussion that merely mentions the marker syntax.
_VALID_NORMALIZED_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_MANAGED_BY_FOOTER = (
    "_This issue is managed automatically by the "
    "[test-gated-python-updates](https://github.com/friedrichwilken/test-gated-python-updates) "
    "action's `create-issues` feature: it is updated on every run while the "
    "package keeps failing or being held back, and closed automatically "
    "once it no longer is. It should not be edited by hand._"
)


@dataclass
class ManagedIssue:
    """One open issue this action already owns, as found via
    `GithubIssues.list_open_managed` - `package` and the `last_*` fields
    come straight from the markers in its body (see module docstring: all
    three of the pkg marker, the state marker and the managed-by footer are
    required for an issue to count as managed at all), confirmed locally
    rather than trusted from `gh`'s search results."""

    number: int
    package: str  # PEP 503 normalized, from the pkg marker
    last_version: str | None
    last_kind: str | None


@dataclass
class IssueTarget:
    """The failure/held-back data an issue should reflect for one package,
    computed once from a `PackageOutcome` (see `issue_target_for`) so the
    decision table and the renderers always agree on which of a package's
    two possible failure surfaces - its own `failed` outcome, or a
    held-back beyond-constraint attempt - an issue is about.

    `kind`/`changed_packages` are additive, only ever set (to `"transitive"`
    and the refresh's own changed-package list) for the one, reserved
    `TRANSITIVE_ISSUE_PACKAGE` target built by `transitive_issue_target()`
    (issue #24) rather than `issue_target_for()` - a failed `update-transitive`
    lock-wide refresh has no single old/new package version of its own
    (see `updater.TransitiveOutcome`), so it needs its own title/body shape
    (`render_issue_title`/`render_issue_body` branch on `kind`) instead of
    the generic per-package one. Every real package's target keeps the
    default `kind="package"`."""

    package: str  # original (display) name
    held_back: bool
    old_version: str | None
    attempted_version: str | None
    failure_kind: str | None
    output_tail: str
    kind: str = "package"  # "package" | "transitive"
    changed_packages: tuple[ChangedTransitivePackage, ...] = ()


@dataclass
class IssueAction:
    """One planned (and, unless dry-run, executed) action for one package.
    `package` is always PEP 503 normalized, matching the pkg marker.
    `target`/`comment`/`duplicate_of` carry the detail `execute_issue_actions`
    needs and (aside from `error`) are not part of the public `issue-actions`
    output (see `issue_actions_to_json`)."""

    package: str
    action: IssueActionKind
    issue: int | None
    target: IssueTarget | None = None  # None for "close"
    comment: bool = False  # only meaningful for "update"
    # Set only for a "close" action closing a non-canonical duplicate issue
    # for the same package (see plan_issue_actions) - the canonical issue's
    # number, so execute_issue_actions can comment "Duplicate of #<n>."
    # instead of the usual "no longer failing" close comment.
    duplicate_of: int | None = None
    # Set only for a "close" action whose package has no target this run
    # because the *feature that would have produced one is itself disabled*
    # (currently: update-transitive off - see plan_issue_actions'
    # disabled_reasons and __main__.run()) rather than because it is
    # genuinely no longer failing - overrides the usual "no longer failing"
    # close comment with this truthful one instead (never set together with
    # duplicate_of, which always wins when both could apply).
    close_reason: str | None = None
    # Set by execute_issue_actions when this action's own gh call(s) failed
    # - the action is still reported (in issue-actions, with this message),
    # just not counted as having actually happened.
    error: str | None = None


def issue_target_for(outcome: PackageOutcome) -> IssueTarget | None:
    """`None` if `outcome` needs no issue at all this run. When a package
    is both `failed` (its in-range/only update failed) and carries a
    held-back beyond-constraint attempt (the beyond-constraint attempt
    *and* the in-range fallback both failed), the plain failure wins - it
    is the run's final, more direct outcome for the package; the
    held-back detail is still visible in `report-json`/the PR body either
    way."""
    if outcome.status == "failed":
        return IssueTarget(
            package=outcome.name,
            held_back=False,
            old_version=outcome.old_version,
            attempted_version=outcome.new_version,
            failure_kind=outcome.failure_kind,
            output_tail=outcome.output_tail,
        )
    if outcome.held_back_beyond_constraint:
        return IssueTarget(
            package=outcome.name,
            held_back=True,
            old_version=outcome.old_version,
            attempted_version=outcome.beyond_constraint_version,
            failure_kind=outcome.beyond_constraint_failure_kind,
            output_tail=outcome.beyond_constraint_output_tail,
        )
    return None


def transitive_issue_target(transitive: TransitiveOutcome | None) -> IssueTarget | None:
    """The `IssueTarget` for the `update-transitive` step's own managed
    issue (issue #24), keyed by the reserved `TRANSITIVE_ISSUE_PACKAGE`
    name - built directly from a `TransitiveOutcome`, never routed through
    `issue_target_for()`/a synthetic `PackageOutcome` (see `IssueTarget`'s
    own docstring for why). `None` unless the step itself failed this run
    - `"updated"`/`"unchanged"` need no issue, exactly like a passing/
    skipped package never gets one from `issue_target_for()` either."""
    if transitive is None or transitive.status != "failed":
        return None
    return IssueTarget(
        package=TRANSITIVE_ISSUE_PACKAGE,
        held_back=False,
        old_version=None,
        attempted_version=None,
        failure_kind=transitive.failure_kind,
        output_tail=transitive.output_tail,
        kind="transitive",
        changed_packages=tuple(transitive.changed_packages),
    )


def parse_managed_issues(raw_issues: list[dict]) -> list[ManagedIssue]:
    """Confirms identity locally in each candidate's body - `gh`'s
    `--search` is never trusted on its own - and extracts the package plus
    whatever the state marker last recorded.

    An issue counts as managed only if its body has *all three* of: a pkg
    marker whose payload looks like a real normalized package name (see
    `_VALID_NORMALIZED_NAME_RE`; rules out e.g. a documentation placeholder
    such as this repo's own issue #28, which quotes the marker syntax as an
    example), a state marker, and the managed-by footer text
    (`_MANAGED_BY_FOOTER`) - see the module docstring for why all three are
    required. Anything short of that is silently dropped: it is not one
    this action manages, and must never be touched (this is what keeps
    `plan_issue_actions` from ever closing or editing an unrelated issue,
    regardless of what search query found it)."""
    managed = []
    for item in raw_issues:
        body = item.get("body") or ""
        pkg_match = _PKG_MARKER_RE.search(body)
        if not pkg_match:
            continue
        if not _VALID_NORMALIZED_NAME_RE.match(pkg_match.group(1)):
            # Looks like a marker but is not a real normalized package name
            # (e.g. a documentation placeholder) - see the comment on
            # _VALID_NORMALIZED_NAME_RE above.
            continue
        state_match = _STATE_MARKER_RE.search(body)
        if not state_match:
            continue
        if _MANAGED_BY_FOOTER not in body:
            continue
        managed.append(
            ManagedIssue(
                number=item["number"],
                package=pkg_match.group(1),
                last_version=state_match.group(1) or None,
                last_kind=state_match.group(2) or None,
            )
        )
    return managed


def plan_issue_actions(
    outcomes: list[PackageOutcome],
    open_managed_issues: list[ManagedIssue],
    extra_targets: dict[str, IssueTarget] | None = None,
    disabled_reasons: dict[str, str] | None = None,
) -> list[IssueAction]:
    """Pure decision table, no `gh` calls:

    - a package with an `IssueTarget` (failed, or held-back) this run and
      no existing managed issue -> `create`
    - a package with an `IssueTarget` this run and an existing managed
      issue -> `update`, always (the body is refreshed to the current
      state), with `comment=True` only when the attempted version or
      failure kind changed since the issue's last recorded state
    - an existing managed issue whose package has no `IssueTarget` this
      run (it updated, was skipped, or is no longer a top-level
      dependency at all) -> `close`, with a `close_reason` override (see
      `IssueAction.close_reason`) when `disabled_reasons` names that
      package - used for a marker package (e.g.
      `TRANSITIVE_ISSUE_PACKAGE`) whose *producing feature* is itself
      disabled this run, where the usual "no longer failing" close
      comment would be untrue (nothing was actually checked)
    - more than one open managed issue for the same package (possible
      because `list_open_managed`'s two lookup paths - and, in principle,
      overlapping runs - are outside this action's control; see the module
      docstring) -> the lowest-numbered one is treated as canonical for the
      rules above, and every other one is closed as a duplicate
      (`duplicate_of` set to the canonical number)
    - anything else (an open issue with no pkg marker at all, or missing
      the state marker/managed-by footer) is never returned here in the
      first place - see `parse_managed_issues`.

    `extra_targets` (already-normalized-name -> `IssueTarget`) merges in
    targets built some other way than `issue_target_for()`/a real
    `PackageOutcome` - currently only ever `transitive_issue_target()`'s
    result for `TRANSITIVE_ISSUE_PACKAGE` (issue #24), since a failed
    lock-wide refresh has no `PackageOutcome` of its own to route through
    the normal per-package path.

    Callers are responsible for not calling this at all for an aborted run
    (the outcome list is partial - see `run_issue_management`) or when the
    feature is disabled.
    """
    targets: dict[str, IssueTarget] = {}
    for outcome in outcomes:
        target = issue_target_for(outcome)
        if target is not None:
            targets[normalize_name(outcome.name)] = target
    if extra_targets:
        targets.update(extra_targets)

    by_package: dict[str, list[ManagedIssue]] = defaultdict(list)
    for managed in open_managed_issues:
        by_package[managed.package].append(managed)

    actions: list[IssueAction] = []
    canonical_by_package: dict[str, ManagedIssue] = {}
    for package, managed_issues in by_package.items():
        ordered = sorted(managed_issues, key=lambda mi: mi.number)
        canonical_by_package[package] = ordered[0]
        for duplicate in ordered[1:]:
            actions.append(
                IssueAction(
                    package=package,
                    action="close",
                    issue=duplicate.number,
                    duplicate_of=ordered[0].number,
                )
            )

    for norm_name, target in targets.items():
        existing = canonical_by_package.get(norm_name)
        version_str = target.attempted_version or ""
        kind_str = target.failure_kind or ""
        if existing is None:
            actions.append(
                IssueAction(package=norm_name, action="create", issue=None, target=target)
            )
        else:
            changed = (existing.last_version or "") != version_str or (
                existing.last_kind or ""
            ) != kind_str
            actions.append(
                IssueAction(
                    package=norm_name,
                    action="update",
                    issue=existing.number,
                    target=target,
                    comment=changed,
                )
            )

    for package, canonical in canonical_by_package.items():
        if package not in targets:
            actions.append(
                IssueAction(
                    package=package,
                    action="close",
                    issue=canonical.number,
                    close_reason=(disabled_reasons or {}).get(package),
                )
            )

    return actions


def issue_actions_to_json(actions: list[IssueAction]) -> str:
    """The public `issue-actions` output: a single-line, compact
    (no-whitespace) JSON array of `{package, action, issue}` records,
    plus an additive `error` key (only present when `execute_issue_actions`
    recorded one for that action) - deliberately not the full `IssueAction`
    (no `target`/`comment`/`duplicate_of`), matching the field set the
    README documents. Compact separators so a consumer (or a shell
    `case`/substring check, as in check_action.yml's e2e assertion) can
    match the exact `{"package":"idna","action":"create","issue":null}`
    shape without worrying about json.dumps' default `", "`/`": "` spacing."""
    records = []
    for a in actions:
        record = {"package": a.package, "action": a.action, "issue": a.issue}
        if a.error is not None:
            record["error"] = a.error
        records.append(record)
    return json.dumps(records, separators=(",", ":"))


def render_issue_title(target: IssueTarget) -> str:
    """Truncated to `_MAX_TITLE_LENGTH`: the package name (and its `: `
    separator) is always kept intact - it is what actually identifies the
    issue to a human - only the version/kind tail is cut, with a trailing
    ellipsis marking the cut.

    `target.kind == "transitive"` (the update-transitive step's own
    managed issue, issue #24) gets its own, fixed title instead - there is
    no single package/version this failure is about (see
    `transitive_issue_target`), so the generic "<pkg>: update to <version>
    fails (<kind>)" shape would be actively misleading here."""
    if target.kind == "transitive":
        kind = target.failure_kind or "failed"
        return f"transitive dependencies: lock-wide refresh fails ({kind})"

    kind = target.failure_kind or "failed"
    version = target.attempted_version or "unknown"
    if target.held_back:
        title = f"{target.package}: update beyond declared constraint to {version} fails ({kind})"
    else:
        title = f"{target.package}: update to {version} fails ({kind})"

    if len(title) <= _MAX_TITLE_LENGTH:
        return title

    ellipsis = "…"
    prefix = f"{target.package}: "
    if len(prefix) >= _MAX_TITLE_LENGTH:
        # Pathological: even the package name alone does not fit - fall
        # back to a hard truncation of the whole title as a last resort.
        return title[: _MAX_TITLE_LENGTH - len(ellipsis)] + ellipsis

    tail_budget = _MAX_TITLE_LENGTH - len(prefix) - len(ellipsis)
    tail = title[len(prefix) :]
    return prefix + tail[:tail_budget] + ellipsis


def _issue_footer_lines(
    target: IssueTarget, run_url: str, pr_url: str | None, last_seen: str
) -> list[str]:
    """The trailer every managed issue body shares, regardless of `kind`:
    the workflow run (and PR, if any) link, "last seen", the managed-by
    footer, and the state marker `plan_issue_actions` reads back next
    run."""
    version_str = target.attempted_version or ""
    kind_str = target.failure_kind or ""
    lines = [f"Workflow run: {run_url}"]
    if pr_url:
        lines.append(f"Pull request: {pr_url}")
    lines.append(f"Last seen: {last_seen}")
    lines.append("")
    lines.append(_MANAGED_BY_FOOTER)
    lines.append(f"<!-- test-gated-updates:state={version_str}|{kind_str} -->")
    return lines


def _render_transitive_issue_body(
    target: IssueTarget, run_url: str, pr_url: str | None, last_seen: str
) -> str:
    """Body for the `update-transitive` step's own managed issue (issue
    #24, `target.kind == "transitive"`) - lists the packages the failed
    lock-wide refresh actually changed (name, old -> new, capped at
    `_MAX_CHANGED_PACKAGES_IN_ISSUE`) before the usual captured-output
    detail block, since there is no single package/version for a heading
    table row the way a normal package issue has."""
    kind_label = _REASON_LABELS.get(target.failure_kind, target.failure_kind or "failed")
    lines = [
        f"<!-- test-gated-updates:pkg={TRANSITIVE_ISSUE_PACKAGE} -->",
        f"The `update-transitive` lock-wide refresh fails ({kind_label}).",
        "",
    ]
    if target.changed_packages:
        shown = target.changed_packages[:_MAX_CHANGED_PACKAGES_IN_ISSUE]
        omitted = len(target.changed_packages) - len(shown)
        lines.append("Packages the refresh changed before it was discarded:")
        lines.append("")
        lines.append("| package | old | new |")
        lines.append("| --- | --- | --- |")
        lines += [f"| {_cell(p.name)} | {_cell(p.old)} | {_cell(p.new)} |" for p in shown]
        if omitted:
            lines.append("")
            lines.append(f"_… and {omitted} more changed package(s)._")
        lines.append("")
    lines.append(_detail_block("transitive dependencies", target.output_tail))
    lines += _issue_footer_lines(target, run_url, pr_url, last_seen)
    return "\n".join(lines) + "\n"


def render_issue_body(target: IssueTarget, run_url: str, pr_url: str | None, last_seen: str) -> str:
    """The managed issue's body. Reuses `report.py`'s `_cell` (safe inline
    escaping) and `_detail_block` (fenced, `</details>`-safe captured
    output) so a package name/version/output tail can never break this
    body's markdown, exactly as it cannot break the PR body/job summary.

    `target.kind == "transitive"` (issue #24) branches to
    `_render_transitive_issue_body` instead - see its own docstring and
    `IssueTarget`'s for why."""
    if target.kind == "transitive":
        return _render_transitive_issue_body(target, run_url, pr_url, last_seen)

    kind_label = _REASON_LABELS.get(target.failure_kind, target.failure_kind or "failed")
    old_cell = _cell(target.old_version)
    attempted_cell = _cell(target.attempted_version)

    if target.held_back:
        heading = (
            f"Update **beyond the declared constraint** for `{_cell(target.package)}` to "
            f"`{attempted_cell}` fails ({kind_label})."
        )
    else:
        heading = (
            f"Update for `{_cell(target.package)}` to `{attempted_cell}` fails ({kind_label})."
        )

    lines = [
        f"<!-- test-gated-updates:pkg={normalize_name(target.package)} -->",
        heading,
        "",
        "| current | attempted | reason |",
        "| --- | --- | --- |",
        f"| {old_cell} | {attempted_cell} | {_cell(kind_label)} |",
        "",
        _detail_block(target.package, target.output_tail),
    ]
    lines += _issue_footer_lines(target, run_url, pr_url, last_seen)
    return "\n".join(lines) + "\n"


def _render_update_comment(target: IssueTarget, run_url: str, pr_url: str | None) -> str:
    kind_label = _REASON_LABELS.get(target.failure_kind, target.failure_kind or "failed")
    lines = [
        f"Now attempting `{_cell(target.attempted_version)}` ({kind_label}).",
        f"Workflow run: {run_url}",
    ]
    if pr_url:
        lines.append(f"Pull request: {pr_url}")
    return "\n".join(lines)


def _render_close_comment(run_url: str, pr_url: str | None, reason: str | None = None) -> str:
    """`reason`, when given (see `IssueAction.close_reason`), replaces the
    default "no longer failing" first line - used when that claim would
    not actually be true (the package has no target this run because the
    *feature that would have produced one* is itself disabled, not because
    anything was checked and found passing - see `plan_issue_actions`'
    `disabled_reasons`)."""
    lines = [
        reason or "No longer failing or held back as of this run - closing automatically.",
        f"Workflow run: {run_url}",
    ]
    if pr_url:
        lines.append(f"Pull request: {pr_url}")
    return "\n".join(lines)


def _render_duplicate_close_comment(canonical_number: int) -> str:
    return f"Duplicate of #{canonical_number} - closing automatically."


class GithubIssues:
    """Wraps the `gh issue` CLI, mirroring `GithubPR`'s shape. Relies on
    GH_TOKEN being present in the environment (see `GithubPR`)."""

    # `in:body` narrows the full-text search to the body only, so a pkg
    # marker mentioned in a comment (e.g. this action's own "closing"
    # comment on a previous, unrelated issue) never produces a false
    # match - but see list_open_managed for why this is only ever a
    # supplementary lookup, never trusted (or used) on its own.
    SEARCH_QUERY = '"test-gated-updates:pkg=" in:body'

    def __init__(self, runner: CommandRunner, directory: str):
        self.runner = runner
        self.directory = directory

    def list_open_managed(self, limit: int = 200) -> list[ManagedIssue]:
        """Every open issue this action manages.

        Always starts from a plain, unfiltered `gh issue list` - GitHub's
        issue *search* index is only eventually consistent (see the module
        docstring), so using `--search` as the primary/only source could
        miss an issue this same run - or a concurrent one - just created,
        producing a duplicate. If the plain listing comes back at exactly
        `limit` results (i.e. it may itself have been truncated - there are
        more than `limit` open issues in the repo), a second, `--search`
        narrowed call is made and merged in by issue number, so a managed
        issue that fell outside the first `limit` plain results is not
        missed either. A failure of that supplementary search call is not
        fatal - it only ever adds coverage, so the plain listing's results
        are used as-is rather than failing the whole lookup over it.
        """
        result = self.runner.run(
            [
                "gh",
                "issue",
                "list",
                "--state",
                "open",
                "--json",
                "number,body",
                "--limit",
                str(limit),
            ],
            cwd=self.directory,
        )
        if not result.ok:
            raise ActionError(f"gh issue list failed: {result.stderr}")
        data = json.loads(result.stdout or "[]")

        if len(data) >= limit:
            search_result = self.runner.run(
                [
                    "gh",
                    "issue",
                    "list",
                    "--state",
                    "open",
                    "--search",
                    self.SEARCH_QUERY,
                    "--json",
                    "number,body",
                    "--limit",
                    str(limit),
                ],
                cwd=self.directory,
            )
            if search_result.ok:
                seen = {item["number"] for item in data}
                for item in json.loads(search_result.stdout or "[]"):
                    if item["number"] not in seen:
                        data.append(item)
                        seen.add(item["number"])

        return parse_managed_issues(data)

    def create(self, title: str, body: str, labels: list[str]):
        args = ["gh", "issue", "create", "--title", title, "--body", body]
        for label in labels:
            args += ["--label", label]
        return self.runner.run(args, cwd=self.directory)

    def edit(self, number: int, body: str):
        return self.runner.run(
            ["gh", "issue", "edit", str(number), "--body", body], cwd=self.directory
        )

    def comment(self, number: int, body: str):
        return self.runner.run(
            ["gh", "issue", "comment", str(number), "--body", body], cwd=self.directory
        )

    def close(self, number: int, comment: str):
        return self.runner.run(
            ["gh", "issue", "close", str(number), "--comment", comment], cwd=self.directory
        )


_ISSUE_URL_RE = re.compile(r"/issues/(\d+)")


def _parse_created_issue_number(stdout: str) -> int | None:
    """`gh issue create` prints the new issue's URL as its only stdout
    line on success."""
    match = _ISSUE_URL_RE.search(stdout)
    return int(match.group(1)) if match else None


def _describe_action(action: IssueAction) -> str:
    suffix = f" (#{action.issue})" if action.issue is not None else ""
    return f"{action.action} for {action.package}{suffix}"


def _execute_one_action(
    gh_issues: GithubIssues,
    action: IssueAction,
    run_url: str,
    pr_url: str | None,
    labels: list[str],
    last_seen: str,
) -> IssueAction:
    """Runs the `gh` call(s) for a single, non-dry-run action and returns
    it updated (`issue` filled in for a "create"). Raises `ActionError` on
    any `gh` failure - the caller (`execute_issue_actions`) is what turns
    that into a recorded `error` instead of aborting the rest of the plan."""
    if action.action == "create":
        title = render_issue_title(action.target)
        body = render_issue_body(action.target, run_url, pr_url, last_seen)
        result = gh_issues.create(title, body, labels)
        if not result.ok:
            raise ActionError(f"gh issue create failed for {action.package}: {result.stderr}")
        return replace(action, issue=_parse_created_issue_number(result.stdout))

    if action.action == "update":
        body = render_issue_body(action.target, run_url, pr_url, last_seen)
        edit_result = gh_issues.edit(action.issue, body)
        if not edit_result.ok:
            raise ActionError(
                f"gh issue edit failed for {_describe_action(action)}: {edit_result.stderr}"
            )
        if action.comment:
            comment_result = gh_issues.comment(
                action.issue, _render_update_comment(action.target, run_url, pr_url)
            )
            if not comment_result.ok:
                raise ActionError(
                    f"gh issue comment failed for {_describe_action(action)}: "
                    f"{comment_result.stderr}"
                )
        return action

    # "close"
    comment_body = (
        _render_duplicate_close_comment(action.duplicate_of)
        if action.duplicate_of is not None
        else _render_close_comment(run_url, pr_url, reason=action.close_reason)
    )
    close_result = gh_issues.close(action.issue, comment_body)
    if not close_result.ok:
        raise ActionError(
            f"gh issue close failed for {_describe_action(action)}: {close_result.stderr}"
        )
    return action


def execute_issue_actions(
    gh_issues: GithubIssues,
    actions: list[IssueAction],
    run_url: str,
    pr_url: str | None,
    labels: list[str],
    last_seen: str,
    dry_run: bool,
) -> tuple[list[IssueAction], list[str]]:
    """Executes `actions` against `gh_issues` - or, when `dry_run`,
    performs no `gh` calls that write anything at all - and returns
    `(executed, errors)`:

    - `executed` mirrors `actions` one for one (same length, same order),
      with `issue` filled in for any "create" that actually ran (still
      `None` in dry-run, since nothing was created - the
      `{"action": "create", "issue": null}` shape the `issue-actions`
      output documents for dry-run), and `error` set on any action whose
      own `gh` call(s) failed.
    - `errors` is the same failure messages as a flat list, in action
      order, for the caller to print (one `::warning::` each - see
      `run_issue_management`/`run()`).

    One action's `gh` failure never stops the rest of the plan from being
    attempted - each action's `gh` call(s) are isolated in their own
    try/except, so e.g. a single unreachable/already-closed issue does not
    also prevent every other package's issue from being created/updated/
    closed this run.
    """
    executed: list[IssueAction] = []
    errors: list[str] = []
    for action in actions:
        if dry_run:
            executed.append(action)
            continue
        try:
            executed.append(
                _execute_one_action(gh_issues, action, run_url, pr_url, labels, last_seen)
            )
        except Exception as exc:  # deliberately broad - isolate this action, keep going
            message = f"{_describe_action(action)}: {exc}"
            errors.append(message)
            executed.append(replace(action, error=message))
    return executed, errors


def summarize_issue_actions(actions: list[IssueAction], dry_run: bool) -> str:
    """One compact line for the job summary."""
    created = sum(1 for a in actions if a.action == "create")
    updated = sum(1 for a in actions if a.action == "update")
    commented = sum(1 for a in actions if a.action == "update" and a.comment)
    closed = sum(1 for a in actions if a.action == "close")
    failed = sum(1 for a in actions if a.error is not None)
    failed_note = f", {failed} failed" if failed else ""
    suffix = " (dry-run: planned only, no writes performed)" if dry_run else ""
    return (
        f"Issue actions: {created} created, {updated} updated ({commented} commented), "
        f"{closed} closed{failed_note}{suffix}."
    )


def _now_last_seen() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def run_issue_management(
    cfg,
    runner: CommandRunner,
    outcomes: list[PackageOutcome],
    run_url: str,
    pr_url: str | None,
    gh_issues: GithubIssues | None = None,
    transitive: TransitiveOutcome | None = None,
) -> tuple[list[IssueAction], list[str]]:
    """Entry point called from `updater.__main__.run()`, after the PR has
    been created/edited (or, in dry-run, would have been) so `pr_url` is
    already known. Returns `([], [])` with no `gh` calls at all when the
    feature is off (`cfg.create_issues` false) - callers must not call this
    at all for an aborted run (see the module docstring); this function
    does not know about `UpdateAborted` itself, keeping that decision, and
    the "why" behind it, in `run()`.

    `transitive` (the `update-transitive` step's own result, issue #24) is
    folded in via `transitive_issue_target()`: a failed step files/updates
    `TRANSITIVE_ISSUE_PACKAGE`'s own managed issue, exactly like any other
    failed package's - reusing the very same create/update/close machinery
    below, just with a target built directly from a `TransitiveOutcome`
    instead of a `PackageOutcome`. `transitive` is `None` whenever
    `update-transitive` itself is disabled (the step never ran, so there is
    nothing to report) - in that case, any *existing* open managed issue
    for that marker package is still closed (see `plan_issue_actions`'
    `disabled_reasons`), but with a close comment that says the feature is
    disabled rather than the usual "no longer failing" claim, which would
    not be true here - nothing was actually checked this run.

    A single action's `gh` failure is isolated by `execute_issue_actions`
    and comes back as an entry in the second, `errors` element of the
    returned tuple - it does not stop this function or raise. This
    function itself still *can* raise (e.g. `list_open_managed` itself
    failing outright - not one action among many, but the lookup the whole
    plan depends on); `run()` is responsible for catching that and turning
    it into a `::warning::` instead of a hard failure, on top of printing
    one `::warning::` per entry in `errors`.
    """
    if not cfg.create_issues:
        return [], []

    gh_issues = gh_issues or GithubIssues(runner, cfg.directory)
    labels = parse_labels(cfg.issue_labels)
    open_managed = gh_issues.list_open_managed()

    extra_target = transitive_issue_target(transitive)
    extra_targets = {TRANSITIVE_ISSUE_PACKAGE: extra_target} if extra_target else None
    disabled_reasons = None
    if not cfg.update_transitive:
        disabled_reasons = {
            TRANSITIVE_ISSUE_PACKAGE: (
                "update-transitive is disabled as of this run - closing automatically. "
                "This does not mean the underlying refresh now succeeds, only that it is "
                "no longer being checked."
            )
        }

    actions = plan_issue_actions(
        outcomes, open_managed, extra_targets=extra_targets, disabled_reasons=disabled_reasons
    )
    return execute_issue_actions(
        gh_issues,
        actions,
        run_url,
        pr_url,
        labels,
        _now_last_seen(),
        dry_run=cfg.dry_run,
    )
