"""Renders the PR body / job summary report and the action's outputs from
an `UpdateResult`.

The whole body is rendered under an explicit character budget
(`max_chars`): each section (tables, skipped line, per-package failure
`<details>` blocks) caps itself to a fair share of the remaining budget
and adds a "N more - see report-json/job summary" note when it has to
drop rows, and a final, unconditional truncation guard
(`_hard_truncate`) enforces `len(body) <= max_chars` no matter what the
section-level budgeting produced - so the guarantee holds for any input,
not just the common case. The PR body and the job summary reuse the same
renderer with different budgets (`MAX_BODY_CHARS`/`MAX_SUMMARY_CHARS`).
"""

from __future__ import annotations

import json
import re
import secrets

from .updater import PackageOutcome, UpdateResult

# Comfortably below GitHub's 65536 character PR body limit.
MAX_BODY_CHARS = 60000

# The job summary has a much larger (1 MiB) GitHub limit; keep comfortably
# under it too, while still allowing a much fuller report than the PR body.
MAX_SUMMARY_CHARS = 900_000

# Cap on the serialized size of the report-json output. GITHUB_OUTPUT has
# no hard documented limit as tight as the PR body's, but an unbounded
# array of full captured-output tails could still make it enormous, so
# output_tail is progressively dropped (see report_json()) to keep it
# under this.
MAX_REPORT_JSON_BYTES = 256 * 1024

_REASON_LABELS = {"resolution": "resolution failed", "test": "tests failed"}

_SEE_FULL_LIST = "see `report-json` or the job summary for the full list"


def _cell(value: object) -> str:
    """Renders a table cell (or similar inline markdown context) safely:
    neutralizes `|` (the column separator), backticks, angle brackets and
    embedded newlines, so a package name/version/reason coming out of a
    lock file or captured output can never break the table structure or
    be interpreted as markup/HTML. Falsy values render as "-"."""
    if not value:
        return "-"
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    text = text.replace("`", "\\`")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text


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


def _table_section(
    heading: str, header_lines: list[str], rows: list[str], budget: int, noun: str
) -> str:
    """`heading` + `header_lines` + as many `rows` as fit within `budget`
    characters, else a trailing "N more" note - by construction, this
    never returns more than roughly `budget` characters (a small,
    bounded overshoot is possible only from the note's own text, which is
    reserved for up front)."""
    prefix = f"{heading}\n\n"
    header_text = "\n".join(header_lines)
    note_reserve = 200  # generous upper bound for the "N more" note below

    available = budget - len(prefix) - len(header_text) - 1 - note_reserve
    fitted: list[str] = []
    used = 0
    if available > 0:
        for row in rows:
            row_cost = len(row) + 1
            if used + row_cost > available:
                break
            fitted.append(row)
            used += row_cost
    omitted = len(rows) - len(fitted)

    text = prefix + "\n".join(header_lines + fitted) + "\n"
    if omitted:
        text += f"\n_… and {omitted} more {noun}; {_SEE_FULL_LIST}._\n"
    return text


def _bump_cell(o: PackageOutcome) -> str:
    if not o.bump:
        return "-"
    return f"{o.bump} (raised)" if o.constraint_raised else o.bump


def _updated_table(outcomes: list[PackageOutcome], budget: int) -> str:
    # The "bump" column is additive: it only appears at all once at least
    # one outcome actually used it, so a run that never touches
    # allow-major (issue #21) renders byte-identically to before the
    # feature existed. `bump` reports the *actual* release segment that
    # changed (major/minor/patch/other) - going beyond the declared
    # constraint is not necessarily a semver-major jump - and
    # "(raised)" marks the rows where the constraint itself was rewritten.
    if any(o.bump for o in outcomes):
        rows = [
            f"| {_cell(o.name)} | {_cell(o.old_version)} | {_cell(o.new_version)} | "
            f"{_cell(_bump_cell(o))} |"
            for o in outcomes
        ]
        return _table_section(
            "## ✅ Updated",
            ["| package | old | new | bump |", "| --- | --- | --- | --- |"],
            rows,
            budget,
            "updated package(s)",
        )

    rows = [
        f"| {_cell(o.name)} | {_cell(o.old_version)} | {_cell(o.new_version)} |" for o in outcomes
    ]
    return _table_section(
        "## ✅ Updated",
        ["| package | old | new |", "| --- | --- | --- |"],
        rows,
        budget,
        "updated package(s)",
    )


def _failed_table(outcomes: list[PackageOutcome], budget: int) -> str:
    rows = []
    for o in outcomes:
        reason = _REASON_LABELS.get(o.failure_kind, o.failure_kind or "failed")
        rows.append(
            f"| {_cell(o.name)} | {_cell(o.old_version)} | {_cell(o.new_version)} | "
            f"{_cell(reason)} |"
        )
    return _table_section(
        "## \U0001f6d1 Failed",
        ["| package | current | attempted | reason |", "| --- | --- | --- | --- |"],
        rows,
        budget,
        "failed package(s)",
    )


def _held_back_table(outcomes: list[PackageOutcome], budget: int) -> str:
    rows = []
    for o in outcomes:
        reason = _REASON_LABELS.get(
            o.beyond_constraint_failure_kind, o.beyond_constraint_failure_kind or "failed"
        )
        rows.append(
            f"| {_cell(o.name)} | {_cell(o.old_version)} | "
            f"{_cell(o.beyond_constraint_version)} | {_cell(reason)} |"
        )
    return _table_section(
        "## ⚠️ Held back (update beyond declared constraint failed)",
        ["| package | current | attempted | reason |", "| --- | --- | --- | --- |"],
        rows,
        budget,
        "held-back update(s)",
    )


def _beyond_constraint_skip_reasons_line(outcomes: list[PackageOutcome], budget: int) -> str:
    """A compact, one-line-per-run note of packages where `allow-major` is
    enabled but no attempt could be made at all (unsupported declaration
    shape) - deliberately never shown in the PR body (only ever rendered
    when `include_major_skip_notes` is set, i.e. for the job summary): the
    full reasons already live in `report-json`, and the PR body has
    limited room better spent on things a reviewer needs to act on."""
    heading = "## ℹ️ Update beyond constraint skipped\n\n"
    items = [f"{_cell(o.name)} ({_cell(o.beyond_constraint_skip_reason)})" for o in outcomes]
    full = ", ".join(items)
    if len(heading) + len(full) + 1 <= budget:
        return heading + full + "\n"

    note_reserve = 150
    available = budget - len(heading) - note_reserve
    fitted: list[str] = []
    used = 0
    if available > 0:
        for item in items:
            cost = len(item) + 2
            if used + cost > available:
                break
            fitted.append(item)
            used += cost
    omitted = len(items) - len(fitted)

    text = heading + ", ".join(fitted)
    if omitted:
        text += f", … and {omitted} more; {_SEE_FULL_LIST}."
    return text + "\n"


def _skipped_line(outcomes: list[PackageOutcome], budget: int) -> str:
    heading = "## ⏭ No update available\n\n"
    names = [_cell(o.name) for o in outcomes]
    full = ", ".join(names)
    if len(heading) + len(full) + 1 <= budget:
        return heading + full + "\n"

    note_reserve = 150
    available = budget - len(heading) - note_reserve
    fitted: list[str] = []
    used = 0
    if available > 0:
        for name in names:
            cost = len(name) + 2
            if used + cost > available:
                break
            fitted.append(name)
            used += cost
    omitted = len(names) - len(fitted)

    text = heading + ", ".join(fitted)
    if omitted:
        text += f", … and {omitted} more; {_SEE_FULL_LIST}."
    return text + "\n"


def _detail_block(name: str, output_tail: str) -> str:
    content = _neutralize_details(output_tail) or "(no output captured)"
    fence = _fence_for(content)
    cell_name = _cell(name)
    return (
        f"<details>\n<summary>{cell_name}: output</summary>\n\n"
        f"{fence}\n{content}\n{fence}\n\n</details>\n"
    )


def _omitted_details_note(names: list[str], noun: str = "failed package(s)") -> str:
    shown = ", ".join(_cell(n) for n in names)
    return (
        f"_Output for {len(names)} {noun} omitted to keep this report under "
        f"the size limit: {shown}. {_SEE_FULL_LIST}._"
    )


def _budgeted_details(
    entries: list[tuple[str, str]], budget: int, noun: str = "failed package(s)"
) -> str:
    """As many full per-package `<details>` blocks as fit in `budget`
    characters, in order; anything that would not fit is dropped and named
    in a trailing note instead of being silently lost. `entries` is a list
    of (name, output_tail) pairs - kept generic (rather than
    `PackageOutcome`) so both the "Failed" and "Held back" sections can
    reuse it against their own output field."""
    if not entries:
        return ""
    if budget <= 0:
        return _omitted_details_note([name for name, _ in entries], noun)

    blocks: list[str] = []
    used = 0
    omitted: list[str] = []
    for name, output_tail in entries:
        block = _detail_block(name, output_tail)
        if used + len(block) <= budget:
            blocks.append(block)
            used += len(block)
        else:
            omitted.append(name)

    text = "\n".join(blocks)
    if omitted:
        note = _omitted_details_note(omitted, noun)
        text = f"{text}\n\n{note}" if text else note
    return text


def _hard_truncate(body: str, max_chars: int) -> str:
    """Unconditional final guard: whatever the section-level budgeting
    above produced, `len(result) <= max_chars` always holds afterwards -
    this is what makes the size guarantee true for any input, not just
    the cases the section budgeting above was designed for."""
    if len(body) <= max_chars:
        return body
    note = "\n\n_⚠️ Report truncated to fit the size limit._\n"
    keep = max(max_chars - len(note), 0)
    return body[:keep] + note[: max_chars - keep]


def render_body(
    result: UpdateResult,
    run_url: str,
    max_chars: int = MAX_BODY_CHARS,
    aborted_reason: str | None = None,
    include_major_skip_notes: bool = False,
) -> str:
    """`include_major_skip_notes` adds a compact "packages where an update
    beyond the declared constraint was skipped" line (issue #21) -
    deliberately opt-in and left off for the PR body (see
    `_beyond_constraint_skip_reasons_line`), and turned on by the caller
    only for the job summary. All of the allow-major sections below are
    additive: with `allow_major` disabled (or simply no held-back/skipped
    outcomes), neither `held_back` nor `beyond_constraint_skipped` is
    non-empty, so this renders byte-identically to before the feature
    existed."""
    updated = [o for o in result.outcomes if o.status == "updated"]
    failed = [o for o in result.outcomes if o.status == "failed"]
    skipped = [o for o in result.outcomes if o.status == "skipped"]
    held_back = [o for o in result.outcomes if o.held_back_beyond_constraint]
    beyond_constraint_skipped = [o for o in result.outcomes if o.beyond_constraint_skip_reason]

    # strategy: batch-first (issue #23) - additive, only ever true when
    # that strategy was requested and its one-shot batch test itself
    # failed, so every outcome fell back through the ordinary per-package
    # loop instead (see `updater._fall_back_to_per_package`). A run using
    # the default per-package strategy never sets this, so the banner
    # never appears and this renders byte-identically to before the
    # feature existed.
    batch_fallback_banner = (
        "⚠️ Batch update failed tests, fell back to per-package.\n\n"
        if any(o.batch_test_failed for o in result.outcomes)
        else ""
    )

    banner = f"⚠️ **Run aborted:** {aborted_reason}\n\n" if aborted_reason else ""
    header = f"{batch_fallback_banner}{banner}Workflow run: {run_url}"

    if not updated and not failed and not skipped:
        body = f"{header}\n\nNo packages were updated - nothing changed in this run.\n"
        return _hard_truncate(body, max_chars)

    remaining = max(max_chars - len(header) - 2, 0)

    parts = [header]
    if updated:
        section = _updated_table(updated, remaining)
        parts.append(section)
        remaining = max(remaining - len(section) - 2, 0)
    if failed:
        section = _failed_table(failed, remaining)
        parts.append(section)
        remaining = max(remaining - len(section) - 2, 0)
    if skipped:
        section = _skipped_line(skipped, remaining)
        parts.append(section)
        remaining = max(remaining - len(section) - 2, 0)
    if held_back:
        section = _held_back_table(held_back, remaining)
        parts.append(section)
        remaining = max(remaining - len(section) - 2, 0)
    if beyond_constraint_skipped and include_major_skip_notes:
        section = _beyond_constraint_skip_reasons_line(beyond_constraint_skipped, remaining)
        parts.append(section)
        remaining = max(remaining - len(section) - 2, 0)

    body = "\n\n".join(parts) + "\n"

    if failed:
        budget = max_chars - len(body)
        details = _budgeted_details(
            [(o.name, o.output_tail) for o in failed], budget, "failed package(s)"
        )
        if details:
            body += "\n" + details

    if held_back:
        budget = max_chars - len(body)
        details = _budgeted_details(
            [(o.name, o.beyond_constraint_output_tail) for o in held_back],
            budget,
            "held-back update(s)",
        )
        if details:
            body += "\n" + details

    return _hard_truncate(body, max_chars)


def _outcome_to_dict(o: PackageOutcome, drop_output: bool = False) -> dict:
    """Additive-only: the six original fields keep their exact names and
    meaning, and every field issue #21 added (`bump`, `constraint_raised`,
    `beyond_constraint_*`) is only ever present in the dict when it
    actually has something to say - a run with `allow_major` disabled
    never sets any of them, so its `report-json` is byte-identical to
    before the feature existed."""
    record = {
        "name": o.name,
        "status": o.status,
        "old_version": o.old_version,
        "new_version": o.new_version,
        "failure_kind": o.failure_kind,
        "output_tail": "" if drop_output else o.output_tail,
    }
    if drop_output and o.output_tail:
        record["output_truncated"] = True
    if o.bump:
        record["bump"] = o.bump
    if o.constraint_raised:
        record["constraint_raised"] = True
    if o.beyond_constraint_version is not None:
        record["beyond_constraint_version"] = o.beyond_constraint_version
    if o.beyond_constraint_failure_kind is not None:
        record["beyond_constraint_failure_kind"] = o.beyond_constraint_failure_kind
    if o.beyond_constraint_output_tail:
        record["beyond_constraint_output_tail"] = (
            "" if drop_output else o.beyond_constraint_output_tail
        )
        if drop_output:
            record["beyond_constraint_output_truncated"] = True
    if o.beyond_constraint_skip_reason:
        record["beyond_constraint_skip_reason"] = o.beyond_constraint_skip_reason
    if o.strategy:
        record["strategy"] = o.strategy
    if o.tested_in_batch:
        record["tested_in_batch"] = True
    if o.batch_test_failed:
        record["batch_test_failed"] = True
    return record


def _output_size(o: PackageOutcome) -> int:
    return len(o.output_tail) + len(o.beyond_constraint_output_tail)


def report_json(result: UpdateResult, max_bytes: int = MAX_REPORT_JSON_BYTES) -> str:
    """A single-line JSON array of per-package records, one per
    `PackageOutcome` - see the README Outputs table for the field
    reference. `json.dumps` escapes embedded newlines/control characters
    within strings, so this never contains a literal newline and is safe
    to write as a plain `key=value` GITHUB_OUTPUT line.

    Every package always gets a record - if the serialized array would
    exceed `max_bytes`, the captured-output fields (`output_tail` and, for
    a held-back update, `beyond_constraint_output_tail` - the only fields
    that can be large) are dropped together, largest first, from as many
    records as it takes to fit, rather than truncating the array itself.
    """
    records = [_outcome_to_dict(o) for o in result.outcomes]
    text = json.dumps(records)
    if len(text.encode("utf-8")) <= max_bytes or not result.outcomes:
        return text

    by_output_size = sorted(
        range(len(result.outcomes)),
        key=lambda i: _output_size(result.outcomes[i]),
        reverse=True,
    )
    dropped: set[int] = set()
    for i in by_output_size:
        if not _output_size(result.outcomes[i]):
            break  # remaining outcomes have no captured output left to drop
        dropped.add(i)
        records = [
            _outcome_to_dict(o, drop_output=(idx in dropped))
            for idx, o in enumerate(result.outcomes)
        ]
        text = json.dumps(records)
        if len(text.encode("utf-8")) <= max_bytes:
            break

    return text


def write_outputs(
    output_path: str,
    result: UpdateResult,
    body: str,
    summary_path: str = "",
    summary_body: str | None = None,
    issue_actions_json: str = "[]",
) -> None:
    """`issue_actions_json` defaults to an empty JSON array so every
    existing call site (the early always-write guard in `run()`, the
    `UpdateAborted` path, and any test that does not care about
    `create-issues`) keeps writing a well-formed `issue-actions` output
    without having to know about the feature at all - only the one
    successful, non-aborted path in `run()` ever passes a real value."""
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"passed-packages={','.join(result.passed)}\n")
            fh.write(f"failed-packages={','.join(result.failed)}\n")
            fh.write(f"skipped-packages={','.join(result.skipped)}\n")
            fh.write(f"held-back-packages={','.join(result.held_back)}\n")
            fh.write(f"report-json={report_json(result)}\n")
            fh.write(f"issue-actions={issue_actions_json}\n")
            delimiter = f"ghadelim_{secrets.token_hex(16)}"
            fh.write(f"pr-body<<{delimiter}\n{body}\n{delimiter}\n")

    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(summary_body if summary_body is not None else body)
            fh.write("\n")
