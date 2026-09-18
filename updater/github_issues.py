"""Opt-in (`create-issues`): one GitHub issue per top-level package that is
either `failed` or has a held-back beyond-constraint attempt
(`beyond_constraint_failure_kind` set - see `updater.py`/issue #21),
created/updated/closed across runs instead of piling up noise.

Identity is a hidden marker in the issue body,
`<!-- test-gated-updates:pkg=<normalized name> -->` - never the title, which
is free to change. A second marker,
`<!-- test-gated-updates:state=<version>|<kind> -->`, records what the last
run reported for that package, so `plan_issue_actions` can tell whether a
comment is warranted without an extra `gh` call.

The module is split into three layers, in line with the rest of this
codebase's style (see `updater.py`/`github_pr.py`):

- `issue_target_for`/`plan_issue_actions`: pure decision logic, no `gh`
  calls, fully unit testable as a decision table.
- `render_issue_title`/`render_issue_body`: pure rendering, reusing
  `report.py`'s safe-cell/fence helpers so a package name or captured
  output can never break the issue body's markdown.
- `GithubIssues`/`execute_issue_actions`/`run_issue_management`: the `gh`
  CLI wrapper and the orchestration that actually calls it (or, in
  dry-run, does not).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from .config import parse_labels
from .errors import ActionError
from .pyproject_deps import normalize_name
from .report import _REASON_LABELS, _cell, _detail_block
from .runner import CommandRunner
from .updater import PackageOutcome

IssueActionKind = Literal["create", "update", "close"]

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
    "[update-poetry-dependencies](https://github.com/friedrichwilken/update-poetry-dependencies) "
    "action's `create-issues` feature: it is updated on every run while the "
    "package keeps failing or being held back, and closed automatically "
    "once it no longer is. It should not be edited by hand._"
)


@dataclass
class ManagedIssue:
    """One open issue this action already owns, as found via
    `GithubIssues.list_open_managed` - `package` and the `last_*` fields
    come straight from the two markers in its body (see module docstring),
    confirmed locally rather than trusted from `gh`'s search results."""

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
    held-back beyond-constraint attempt - an issue is about."""

    package: str  # original (display) name
    held_back: bool
    old_version: str | None
    attempted_version: str | None
    failure_kind: str | None
    output_tail: str


@dataclass
class IssueAction:
    """One planned (and, unless dry-run, executed) action for one package.
    `package` is always PEP 503 normalized, matching the pkg marker.
    `target`/`comment` carry the detail `execute_issue_actions` needs and
    are not part of the public `issue-actions` output (see
    `issue_actions_to_json`)."""

    package: str
    action: IssueActionKind
    issue: int | None
    target: IssueTarget | None = None  # None for "close"
    comment: bool = False  # only meaningful for "update"


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


def parse_managed_issues(raw_issues: list[dict]) -> list[ManagedIssue]:
    """Confirms the pkg marker locally in each candidate's body - `gh`'s
    `--search` is never trusted on its own - and extracts the package plus
    whatever the state marker last recorded. An issue with no pkg marker,
    or whose marker payload does not look like a real normalized package
    name (see `_VALID_NORMALIZED_NAME_RE`), is silently dropped: it is not
    one this action manages, and must never be touched (this is what keeps
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
        last_version = last_kind = None
        state_match = _STATE_MARKER_RE.search(body)
        if state_match:
            last_version = state_match.group(1) or None
            last_kind = state_match.group(2) or None
        managed.append(
            ManagedIssue(
                number=item["number"],
                package=pkg_match.group(1),
                last_version=last_version,
                last_kind=last_kind,
            )
        )
    return managed


def plan_issue_actions(
    outcomes: list[PackageOutcome], open_managed_issues: list[ManagedIssue]
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
      dependency at all) -> `close`
    - anything else (an open issue with no pkg marker at all) is never
      returned here in the first place - see `parse_managed_issues`.

    Callers are responsible for not calling this at all for an aborted run
    (the outcome list is partial - see `run_issue_management`) or when the
    feature is disabled.
    """
    targets: dict[str, IssueTarget] = {}
    for outcome in outcomes:
        target = issue_target_for(outcome)
        if target is not None:
            targets[normalize_name(outcome.name)] = target

    existing_by_package = {mi.package: mi for mi in open_managed_issues}

    actions: list[IssueAction] = []
    for norm_name, target in targets.items():
        existing = existing_by_package.get(norm_name)
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

    for managed in open_managed_issues:
        if managed.package not in targets:
            actions.append(
                IssueAction(package=managed.package, action="close", issue=managed.number)
            )

    return actions


def issue_actions_to_json(actions: list[IssueAction]) -> str:
    """The public `issue-actions` output: a single-line, compact
    (no-whitespace) JSON array of `{package, action, issue}` - deliberately
    not the full `IssueAction` (no `target`/`comment`), matching the field
    set the README documents. Compact separators so a consumer (or a shell
    `case`/substring check, as in check_action.yml's e2e assertion) can
    match the exact `{"package":"idna","action":"create","issue":null}`
    shape without worrying about json.dumps' default `", "`/`": "` spacing."""
    records = [{"package": a.package, "action": a.action, "issue": a.issue} for a in actions]
    return json.dumps(records, separators=(",", ":"))


def render_issue_title(target: IssueTarget) -> str:
    kind = target.failure_kind or "failed"
    version = target.attempted_version or "unknown"
    if target.held_back:
        return f"{target.package}: update beyond declared constraint to {version} fails ({kind})"
    return f"{target.package}: update to {version} fails ({kind})"


def render_issue_body(target: IssueTarget, run_url: str, pr_url: str | None, last_seen: str) -> str:
    """The managed issue's body. Reuses `report.py`'s `_cell` (safe inline
    escaping) and `_detail_block` (fenced, `</details>`-safe captured
    output) so a package name/version/output tail can never break this
    body's markdown, exactly as it cannot break the PR body/job summary."""
    kind_label = _REASON_LABELS.get(target.failure_kind, target.failure_kind or "failed")
    old_cell = _cell(target.old_version)
    attempted_cell = _cell(target.attempted_version)
    version_str = target.attempted_version or ""
    kind_str = target.failure_kind or ""

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
        f"Workflow run: {run_url}",
    ]
    if pr_url:
        lines.append(f"Pull request: {pr_url}")
    lines.append(f"Last seen: {last_seen}")
    lines.append("")
    lines.append(_MANAGED_BY_FOOTER)
    lines.append(f"<!-- test-gated-updates:state={version_str}|{kind_str} -->")
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


def _render_close_comment(run_url: str, pr_url: str | None) -> str:
    lines = [
        "No longer failing or held back as of this run - closing automatically.",
        f"Workflow run: {run_url}",
    ]
    if pr_url:
        lines.append(f"Pull request: {pr_url}")
    return "\n".join(lines)


class GithubIssues:
    """Wraps the `gh issue` CLI, mirroring `GithubPR`'s shape. Relies on
    GH_TOKEN being present in the environment (see `GithubPR`)."""

    # `in:body` narrows the full-text search to the body only, so a pkg
    # marker mentioned in a comment (e.g. this action's own "closing"
    # comment on a previous, unrelated issue) never produces a false
    # match - but see list_open_managed for why the result is never
    # trusted on its own regardless.
    SEARCH_QUERY = '"test-gated-updates:pkg=" in:body'

    def __init__(self, runner: CommandRunner, directory: str):
        self.runner = runner
        self.directory = directory

    def list_open_managed(self, limit: int = 200) -> list[ManagedIssue]:
        """Every open issue this action manages. Tries `gh`'s `--search`
        first (a single call covers every package, for both the
        create/update lookup and the close scan); if that fails - `gh`
        version differences, a search backend hiccup, whatever - falls
        back to a plain open-issue listing and leans entirely on the
        local marker check in `parse_managed_issues`, which never trusts
        `gh`'s search results on their own anyway."""
        result = self.runner.run(
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
        if not result.ok:
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


def execute_issue_actions(
    gh_issues: GithubIssues,
    actions: list[IssueAction],
    run_url: str,
    pr_url: str | None,
    labels: list[str],
    last_seen: str,
    dry_run: bool,
) -> list[IssueAction]:
    """Executes `actions` against `gh_issues` - or, when `dry_run`,
    performs no `gh` calls that write anything at all - and returns a new
    list with `issue` filled in for any "create" that was actually
    executed (still `None` in dry-run, since nothing was created; this is
    exactly the `{"action": "create", "issue": null}` shape the
    `issue-actions` output documents for dry-run)."""
    executed: list[IssueAction] = []
    for action in actions:
        if action.action == "create":
            if dry_run:
                executed.append(action)
                continue
            title = render_issue_title(action.target)
            body = render_issue_body(action.target, run_url, pr_url, last_seen)
            result = gh_issues.create(title, body, labels)
            if not result.ok:
                raise ActionError(f"gh issue create failed for {action.package}: {result.stderr}")
            number = _parse_created_issue_number(result.stdout)
            executed.append(replace(action, issue=number))

        elif action.action == "update":
            if not dry_run:
                body = render_issue_body(action.target, run_url, pr_url, last_seen)
                edit_result = gh_issues.edit(action.issue, body)
                if not edit_result.ok:
                    raise ActionError(
                        f"gh issue edit failed for {action.package} (#{action.issue}): "
                        f"{edit_result.stderr}"
                    )
                if action.comment:
                    comment_result = gh_issues.comment(
                        action.issue, _render_update_comment(action.target, run_url, pr_url)
                    )
                    if not comment_result.ok:
                        raise ActionError(
                            f"gh issue comment failed for {action.package} "
                            f"(#{action.issue}): {comment_result.stderr}"
                        )
            executed.append(action)

        elif action.action == "close":
            if not dry_run:
                close_result = gh_issues.close(action.issue, _render_close_comment(run_url, pr_url))
                if not close_result.ok:
                    raise ActionError(
                        f"gh issue close failed for #{action.issue}: {close_result.stderr}"
                    )
            executed.append(action)

    return executed


def summarize_issue_actions(actions: list[IssueAction], dry_run: bool) -> str:
    """One compact line for the job summary."""
    created = sum(1 for a in actions if a.action == "create")
    updated = sum(1 for a in actions if a.action == "update")
    commented = sum(1 for a in actions if a.action == "update" and a.comment)
    closed = sum(1 for a in actions if a.action == "close")
    suffix = " (dry-run: planned only, no writes performed)" if dry_run else ""
    return (
        f"Issue actions: {created} created, {updated} updated ({commented} commented), "
        f"{closed} closed{suffix}."
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
) -> list[IssueAction]:
    """Entry point called from `updater.__main__.run()`, after the PR has
    been created/edited (or, in dry-run, would have been) so `pr_url` is
    already known. Returns `[]` with no `gh` calls at all when the feature
    is off (`cfg.create_issues` false) - callers must not call this at all
    for an aborted run (see the module docstring); this function does not
    know about `UpdateAborted` itself, keeping that decision, and the "why"
    behind it, in `run()`.

    Deliberately does not catch its own exceptions - a `gh` failure here
    should stop *this* function's work, but must not take down the whole
    action once the PR (the primary product) already exists; `run()` is
    responsible for catching and turning a failure here into a
    `::warning::` instead of a hard failure.
    """
    if not cfg.create_issues:
        return []

    gh_issues = gh_issues or GithubIssues(runner, cfg.directory)
    labels = parse_labels(cfg.issue_labels)
    open_managed = gh_issues.list_open_managed()
    actions = plan_issue_actions(outcomes, open_managed)
    return execute_issue_actions(
        gh_issues,
        actions,
        run_url,
        pr_url,
        labels,
        _now_last_seen(),
        dry_run=cfg.dry_run,
    )
