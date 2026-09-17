"""Renders the PR body / job summary report and the action's outputs from
an `UpdateResult`.

The body is built as independent sections (updated table, failed table +
per-package `<details>` output blocks, skipped line) that are then joined
under a total character budget (`MAX_BODY_CHARS`), comfortably below
GitHub's 65536 character PR body limit, so a handful of very chatty test
failures can never make the PR create/edit call fail outright - captured
output is truncated (with a note saying so) rather than the whole report.
"""

from __future__ import annotations

import json
import re
import secrets

from .updater import PackageOutcome, UpdateResult

# Comfortably below GitHub's 65536 character PR body limit, leaving
# headroom for the fixed sections (tables, headings, run link) around the
# budgeted <details> blocks.
MAX_BODY_CHARS = 60000

_REASON_LABELS = {"resolution": "resolution failed", "test": "tests failed"}


def _v(version: str | None) -> str:
    return version if version else "-"


def _updated_table(outcomes: list[PackageOutcome]) -> str:
    lines = ["| package | old | new |", "| --- | --- | --- |"]
    for o in outcomes:
        lines.append(f"| {o.name} | {_v(o.old_version)} | {_v(o.new_version)} |")
    return "## ✅ Updated\n\n" + "\n".join(lines) + "\n"


def _failed_table(outcomes: list[PackageOutcome]) -> str:
    lines = ["| package | current | attempted | reason |", "| --- | --- | --- | --- |"]
    for o in outcomes:
        reason = _REASON_LABELS.get(o.failure_kind, o.failure_kind or "failed")
        lines.append(f"| {o.name} | {_v(o.old_version)} | {_v(o.new_version)} | {reason} |")
    return "## \U0001f6d1 Failed\n\n" + "\n".join(lines) + "\n"


def _skipped_line(outcomes: list[PackageOutcome]) -> str:
    names = ", ".join(o.name for o in outcomes)
    return f"## ⏭ No update available\n\n{names}\n"


def _fence_for(content: str) -> str:
    """A backtick fence at least one character longer than the longest run
    of backticks already in `content`, so the fence can never be broken
    out of by captured output that itself contains backticks."""
    longest = max((len(m.group()) for m in re.finditer(r"`+", content)), default=0)
    return "`" * max(longest + 1, 3)


def _neutralize_details(text: str) -> str:
    """A literal `</details>` inside captured output would close the
    collapsible block early and corrupt everything after it; splice in a
    zero-width space so it renders as visible text instead of markup."""
    return re.sub(r"</details>", "<​/details>", text, flags=re.IGNORECASE)


def _detail_block(outcome: PackageOutcome) -> str:
    content = _neutralize_details(outcome.output_tail) or "(no output captured)"
    fence = _fence_for(content)
    return (
        f"<details>\n<summary>{outcome.name}: output</summary>\n\n"
        f"{fence}\n{content}\n{fence}\n\n</details>\n"
    )


def _omitted_note(names: list[str]) -> str:
    return (
        f"_Output for {len(names)} failed package(s) omitted to keep this report under "
        f"GitHub's PR body size limit: {', '.join(names)}. See the workflow run for the "
        "full output._"
    )


def _budgeted_details(failed: list[PackageOutcome], budget: int) -> str:
    """As many full per-package `<details>` blocks as fit in `budget`
    characters, in order; anything that would not fit is dropped and named
    in a trailing note instead of being silently lost."""
    if not failed:
        return ""
    if budget <= 0:
        return _omitted_note([o.name for o in failed])

    blocks: list[str] = []
    used = 0
    omitted: list[str] = []
    for o in failed:
        block = _detail_block(o)
        if used + len(block) <= budget:
            blocks.append(block)
            used += len(block)
        else:
            omitted.append(o.name)

    text = "\n".join(blocks)
    if omitted:
        note = _omitted_note(omitted)
        text = f"{text}\n\n{note}" if text else note
    return text


def render_body(result: UpdateResult, run_url: str) -> str:
    updated = [o for o in result.outcomes if o.status == "updated"]
    failed = [o for o in result.outcomes if o.status == "failed"]
    skipped = [o for o in result.outcomes if o.status == "skipped"]

    parts = [f"Workflow run: {run_url}"]

    if not updated and not failed and not skipped:
        parts.append("No packages were updated - nothing changed in this run.")
        return "\n\n".join(parts) + "\n"

    if updated:
        parts.append(_updated_table(updated))
    if failed:
        parts.append(_failed_table(failed))
    if skipped:
        parts.append(_skipped_line(skipped))

    body = "\n\n".join(parts) + "\n"

    if failed:
        budget = MAX_BODY_CHARS - len(body)
        details = _budgeted_details(failed, budget)
        if details:
            body += "\n" + details

    return body


def _outcome_to_dict(o: PackageOutcome) -> dict:
    return {
        "name": o.name,
        "status": o.status,
        "old_version": o.old_version,
        "new_version": o.new_version,
        "failure_kind": o.failure_kind,
        "output_tail": o.output_tail,
    }


def report_json(result: UpdateResult) -> str:
    """A single-line JSON array of per-package records, one per
    `PackageOutcome` (field names: name, status, old_version, new_version,
    failure_kind, output_tail) - see the README Outputs table for the
    field documentation. `json.dumps` escapes embedded newlines/control
    characters within strings, so this never contains a literal newline
    and is safe to write as a plain `key=value` GITHUB_OUTPUT line."""
    return json.dumps([_outcome_to_dict(o) for o in result.outcomes])


def write_outputs(
    output_path: str, result: UpdateResult, body: str, summary_path: str = ""
) -> None:
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"passed-packages={','.join(result.passed)}\n")
            fh.write(f"failed-packages={','.join(result.failed)}\n")
            fh.write(f"skipped-packages={','.join(result.skipped)}\n")
            fh.write(f"report-json={report_json(result)}\n")
            delimiter = f"ghadelim_{secrets.token_hex(16)}"
            fh.write(f"pr-body<<{delimiter}\n{body}\n{delimiter}\n")

    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(body)
            fh.write("\n")
