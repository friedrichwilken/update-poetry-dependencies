import json

import pytest

from updater.report import (
    MAX_BODY_CHARS,
    MAX_REPORT_JSON_BYTES,
    MAX_SUMMARY_CHARS,
    render_body,
    report_json,
    write_outputs,
)
from updater.updater import PackageOutcome, UpdateResult


def _outcome(**overrides) -> PackageOutcome:
    base = dict(name="pkg", status="updated", old_version="1.0.0", new_version="1.1.0")
    base.update(overrides)
    return PackageOutcome(**base)


def test_render_body_includes_run_url():
    body = render_body(UpdateResult(), "https://example.com/run/1")
    assert "https://example.com/run/1" in body


def test_render_body_shows_clear_message_when_nothing_happened():
    body = render_body(UpdateResult(), "https://example.com/run/1")
    assert "No packages were updated" in body


def test_render_body_updated_table_has_old_and_new_versions():
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="updated", old_version="1.0.0", new_version="1.1.0"),
            _outcome(name="b", status="updated", old_version="2.0.0", new_version="2.5.0"),
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "## ✅ Updated" in body
    assert "| a | 1.0.0 | 1.1.0 |" in body
    assert "| b | 2.0.0 | 2.5.0 |" in body


def test_render_body_failed_table_has_current_attempted_and_reason():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="c",
                status="failed",
                old_version="1.0.0",
                new_version="1.2.0",
                failure_kind="resolution",
                output_tail="boom",
            ),
            _outcome(
                name="d",
                status="failed",
                old_version="2.0.0",
                new_version="2.2.0",
                failure_kind="test",
                output_tail="assert 1 == 2",
            ),
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "## \U0001f6d1 Failed" in body
    assert "| c | 1.0.0 | 1.2.0 | resolution failed |" in body
    assert "| d | 2.0.0 | 2.2.0 | tests failed |" in body


def test_render_body_failed_packages_get_a_details_block_with_output():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="c",
                status="failed",
                failure_kind="test",
                output_tail="some captured test output",
            )
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "<details>" in body
    assert "<summary>c: output</summary>" in body
    assert "some captured test output" in body
    assert "</details>" in body


def test_render_body_skipped_is_a_compact_comma_separated_line_not_a_list():
    result = UpdateResult(
        outcomes=[
            _outcome(name="e", status="skipped"),
            _outcome(name="f", status="skipped"),
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "## ⏭ No update available" in body
    assert "e, f" in body
    # compact: not one bullet per package
    assert "- e" not in body


def test_render_body_omits_empty_sections():
    result = UpdateResult(outcomes=[_outcome(name="a", status="updated")])

    body = render_body(result, "https://example.com/run/1")

    assert "## \U0001f6d1 Failed" not in body
    assert "## ⏭ No update available" not in body


def test_render_body_backtick_fence_longer_than_content_backticks():
    """A fenced code block must use a fence longer than any backtick run
    already present in the content, or the content could break out of the
    fence and corrupt the rest of the markdown."""
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="c",
                status="failed",
                failure_kind="test",
                output_tail="here is a fence: ```` four backticks ````",
            )
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    # the fence used for the block must be longer than the longest run
    # of backticks appearing in the captured content (4)
    assert "`````" in body


def test_render_body_neutralizes_closing_details_tag_in_output():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="c",
                status="failed",
                failure_kind="test",
                output_tail="oops </details> more text after",
            )
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    # the literal, unescaped closing tag from the captured output must not
    # appear verbatim (it would prematurely close the details block)
    assert "oops </details> more text after" not in body
    # but the visible content ("more text after") must survive
    assert "more text after" in body


def test_render_body_stays_under_the_budget_and_truncates_details_with_a_note():
    huge_output = "x" * 5000
    outcomes = [
        _outcome(name=f"pkg{i}", status="failed", failure_kind="test", output_tail=huge_output)
        for i in range(50)
    ]
    result = UpdateResult(outcomes=outcomes)

    body = render_body(result, "https://example.com/run/1")

    assert len(body) < MAX_BODY_CHARS + 5000  # well under a hard blow-up
    assert "omitted" in body.lower()


def test_report_json_shape():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a",
                status="updated",
                old_version="1.0.0",
                new_version="1.1.0",
                failure_kind=None,
                output_tail="",
            ),
            _outcome(
                name="b",
                status="failed",
                old_version="1.0.0",
                new_version="1.1.0",
                failure_kind="test",
                output_tail="boom",
            ),
        ]
    )

    data = json.loads(report_json(result))

    assert data == [
        {
            "name": "a",
            "status": "updated",
            "old_version": "1.0.0",
            "new_version": "1.1.0",
            "failure_kind": None,
            "output_tail": "",
        },
        {
            "name": "b",
            "status": "failed",
            "old_version": "1.0.0",
            "new_version": "1.1.0",
            "failure_kind": "test",
            "output_tail": "boom",
        },
    ]


def test_report_json_is_a_single_line():
    result = UpdateResult(outcomes=[_outcome(output_tail="line1\nline2")])
    assert "\n" not in report_json(result)


def test_write_outputs_keeps_passed_failed_skipped_byte_compatible(tmp_path):
    output_file = tmp_path / "output.txt"
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="updated"),
            _outcome(name="b", status="failed", failure_kind="test"),
            _outcome(name="c", status="skipped"),
        ]
    )

    write_outputs(str(output_file), result, "the body")

    content = output_file.read_text()
    assert "passed-packages=a\n" in content
    assert "failed-packages=b\n" in content
    assert "skipped-packages=c\n" in content
    assert "pr-body<<" in content
    assert "the body" in content


def test_write_outputs_includes_report_json(tmp_path):
    output_file = tmp_path / "output.txt"
    result = UpdateResult(outcomes=[_outcome(name="a", status="updated")])

    write_outputs(str(output_file), result, "body")

    content = output_file.read_text()
    assert "report-json=" in content
    line = next(line for line in content.splitlines() if line.startswith("report-json="))
    data = json.loads(line[len("report-json=") :])
    assert data[0]["name"] == "a"


def test_write_outputs_writes_job_summary_when_path_given(tmp_path):
    output_file = tmp_path / "output.txt"
    summary_file = tmp_path / "summary.md"
    result = UpdateResult(outcomes=[_outcome(name="a", status="updated")])

    write_outputs(str(output_file), result, "rendered report body", str(summary_file))

    assert "rendered report body" in summary_file.read_text()


def test_write_outputs_does_not_touch_summary_when_no_path_given(tmp_path):
    output_file = tmp_path / "output.txt"
    result = UpdateResult(outcomes=[])

    # must not raise even though no summary_path was given
    write_outputs(str(output_file), result, "body")


# --- Table cell escaping -----------------------------------------------


def test_render_body_escapes_pipe_in_package_name_and_version():
    result = UpdateResult(
        outcomes=[_outcome(name="evil|pkg", status="updated", old_version="1|0", new_version="2|0")]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "| evil\\|pkg | 1\\|0 | 2\\|0 |" in body
    # the raw, unescaped pipes must not appear as if they were real table
    # column separators
    assert "| evil|pkg |" not in body


def test_render_body_escapes_newline_in_package_name():
    result = UpdateResult(
        outcomes=[
            _outcome(name="evil\nname", status="updated", old_version="1.0", new_version="2.0")
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    # a raw newline inside a cell would break the table row in two
    assert "evil\nname" not in body
    assert "evil name" in body


def test_render_body_escapes_backticks_and_angle_brackets_in_version():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="pkg", status="updated", old_version="1.0`</details>", new_version="<b>2.0"
            )
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "1.0`</details>" not in body
    assert "<b>2.0" not in body
    assert "&lt;b&gt;2.0" in body


def test_render_body_escapes_pipe_in_failed_table_and_summary():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a|b",
                status="failed",
                old_version="1.0",
                new_version="1|1",
                failure_kind="test",
                output_tail="boom",
            )
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "| a\\|b | 1.0 | 1\\|1 | tests failed |" in body
    assert "<summary>a\\|b: output</summary>" in body


# --- Table row capping at scale -----------------------------------------


def test_render_body_caps_table_rows_and_notes_how_many_more():
    outcomes = [
        _outcome(
            name=f"updated-package-{i:05d}",
            status="updated",
            old_version="1.0.0",
            new_version="1.0.1",
        )
        for i in range(3000)
    ]
    result = UpdateResult(outcomes=outcomes)

    body = render_body(result, "https://example.com/run/1")

    assert len(body) <= MAX_BODY_CHARS
    assert "more updated package(s)" in body


@pytest.mark.parametrize("n", [0, 1, 50, 2000])
def test_render_body_stays_within_budget_for_various_sizes(n):
    outcomes = (
        [
            _outcome(name=f"upd-{i}", status="updated", old_version="1.0.0", new_version="1.0.1")
            for i in range(n)
        ]
        + [
            _outcome(
                name=f"fail-{i}",
                status="failed",
                old_version="1.0.0",
                new_version="1.0.1",
                failure_kind="test",
                output_tail="some test output\n" * 20,
            )
            for i in range(n)
        ]
        + [_outcome(name=f"skip-{i}", status="skipped") for i in range(n)]
    )
    result = UpdateResult(outcomes=outcomes)

    body = render_body(result, "https://example.com/run/1")

    assert len(body) <= MAX_BODY_CHARS


def test_render_body_2000_of_each_status_stays_under_the_pr_body_budget():
    """The size guarantee must hold for any input, not just the common
    case of a handful of chatty test failures - this is the extreme case
    named in review: 2000 failed + 2000 updated + 2000 skipped."""
    outcomes = (
        [
            _outcome(name=f"upd-{i}", status="updated", old_version="1.0.0", new_version="1.0.1")
            for i in range(2000)
        ]
        + [
            _outcome(
                name=f"fail-{i}",
                status="failed",
                old_version="1.0.0",
                new_version="1.0.1",
                failure_kind="test",
                output_tail="boom\n" * 100,
            )
            for i in range(2000)
        ]
        + [_outcome(name=f"skip-{i}", status="skipped") for i in range(2000)]
    )
    result = UpdateResult(outcomes=outcomes)

    body = render_body(result, "https://example.com/run/1")

    assert len(body) <= MAX_BODY_CHARS


def test_render_body_job_summary_budget_allows_a_much_larger_report():
    """The job summary reuses the same renderer with a bigger budget, so
    it can carry a fuller report than the PR body for the same result."""
    outcomes = [
        _outcome(
            name=f"fail-{i}",
            status="failed",
            old_version="1.0.0",
            new_version="1.0.1",
            failure_kind="test",
            output_tail="boom\n" * 50,
        )
        for i in range(200)
    ]
    result = UpdateResult(outcomes=outcomes)

    pr_body = render_body(result, "https://example.com/run/1")
    summary = render_body(result, "https://example.com/run/1", max_chars=MAX_SUMMARY_CHARS)

    assert len(summary) <= MAX_SUMMARY_CHARS
    assert len(summary) > len(pr_body)
    # the PR body had to drop/omit some failures' output at this scale;
    # the summary (much bigger budget) should not have needed to
    assert "omitted" not in summary.lower()


# --- Abort banner ---------------------------------------------------------


def test_render_body_aborted_reason_is_shown_as_a_banner_at_the_top():
    result = UpdateResult(outcomes=[_outcome(name="a", status="updated")])

    body = render_body(result, "https://example.com/run/1", aborted_reason="re-sync failed after a")

    assert body.index("Run aborted") < body.index("Workflow run:")
    assert "re-sync failed after a" in body


def test_render_body_aborted_with_no_outcomes_still_shows_the_banner():
    body = render_body(UpdateResult(), "https://example.com/run/1", aborted_reason="boom")

    assert "Run aborted" in body
    assert "boom" in body


# --- report_json size cap --------------------------------------------------


def test_report_json_drops_output_tail_progressively_when_too_large():
    big = "x" * (200 * 1024)
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a",
                status="failed",
                failure_kind="test",
                output_tail=big,
            ),
            _outcome(
                name="b",
                status="failed",
                failure_kind="test",
                output_tail=big,
            ),
            _outcome(name="c", status="updated", output_tail=""),
        ]
    )

    text = report_json(result, max_bytes=256 * 1024)

    assert len(text.encode("utf-8")) <= 256 * 1024
    data = json.loads(text)
    # every package still gets a record - the array itself is never
    # truncated, only output_tail contents
    assert [r["name"] for r in data] == ["a", "b", "c"]
    truncated = [r for r in data if r.get("output_truncated")]
    assert truncated, "expected at least one record to have its output_tail dropped"
    for record in truncated:
        assert record["output_tail"] == ""


def test_report_json_leaves_small_output_untouched():
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="failed", failure_kind="test", output_tail="small output")
        ]
    )

    data = json.loads(report_json(result))

    assert data[0]["output_tail"] == "small output"
    assert "output_truncated" not in data[0]


def test_report_json_default_budget_constant_is_documented_sane():
    assert MAX_REPORT_JSON_BYTES == 256 * 1024


# --- Major-bump reporting (issue #21) ------------------------------------


def test_default_off_report_json_is_byte_identical_to_the_old_shape():
    """With no outcome ever touching the major-bump fields, report-json
    must render with exactly the six original keys - no bump/major_*
    fields at all - so a consumer parsing today's shape never breaks."""
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="updated", old_version="1.0.0", new_version="1.1.0"),
            _outcome(
                name="b",
                status="failed",
                failure_kind="test",
                output_tail="boom",
            ),
            _outcome(name="c", status="skipped"),
        ]
    )

    data = json.loads(report_json(result))

    for record in data:
        assert set(record.keys()) <= {
            "name",
            "status",
            "old_version",
            "new_version",
            "failure_kind",
            "output_tail",
        }


def test_default_off_render_body_has_no_bump_column_or_new_sections():
    result = UpdateResult(
        outcomes=[_outcome(name="a", status="updated", old_version="1.0.0", new_version="2.0.0")]
    )

    body = render_body(result, "https://example.com/run/1", include_major_skip_notes=True)

    assert "| package | old | new |" in body
    assert "bump" not in body
    assert "Held back (update beyond declared constraint failed)" not in body
    assert "Update beyond constraint skipped" not in body


def test_report_json_includes_bump_field_for_a_major_update():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a", status="updated", old_version="1.0.0", new_version="2.0.0", bump="major"
            )
        ]
    )

    data = json.loads(report_json(result))
    assert data[0]["bump"] == "major"


def test_report_json_includes_held_back_fields():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a",
                status="updated",
                old_version="1.0.0",
                new_version="1.1.0",
                beyond_constraint_version="3.0.0",
                beyond_constraint_failure_kind="test",
                beyond_constraint_output_tail="assert failed",
            )
        ]
    )

    data = json.loads(report_json(result))
    record = data[0]
    assert record["beyond_constraint_version"] == "3.0.0"
    assert record["beyond_constraint_failure_kind"] == "test"
    assert record["beyond_constraint_output_tail"] == "assert failed"
    # the ordinary status/failure_kind fields are unaffected
    assert record["status"] == "updated"
    assert record["failure_kind"] is None


def test_report_json_includes_beyond_constraint_skip_reason():
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="updated", beyond_constraint_skip_reason="exact version pin"),
        ]
    )
    data = json.loads(report_json(result))
    assert data[0]["beyond_constraint_skip_reason"] == "exact version pin"


def test_render_body_updated_table_gets_bump_column_when_a_major_update_exists():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a",
                status="updated",
                old_version="1.0.0",
                new_version="2.0.0",
                bump="major",
                constraint_raised=True,
            ),
            _outcome(
                name="b", status="updated", old_version="1.0.0", new_version="1.1.0", bump="minor"
            ),
            _outcome(name="c", status="updated", old_version="1.0.0", new_version="1.0.0"),
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "| package | old | new | bump |" in body
    assert "| a | 1.0.0 | 2.0.0 | major (raised) |" in body
    assert "| b | 1.0.0 | 1.1.0 | minor |" in body
    # c has no bump set at all (e.g. produced outside an allow-major run)
    assert "| c | 1.0.0 | 1.0.0 | - |" in body


def test_render_body_has_a_held_back_table_with_details():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a",
                status="updated",
                old_version="1.0.0",
                new_version="1.1.0",
                beyond_constraint_version="3.0.0",
                beyond_constraint_failure_kind="test",
                beyond_constraint_output_tail="assertion failed in test",
            )
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "Held back (update beyond declared constraint failed)" in body
    assert "| a | 1.0.0 | 3.0.0 | tests failed |" in body
    assert "<summary>a: output</summary>" in body
    assert "assertion failed in test" in body


def test_beyond_constraint_skip_reasons_only_shown_when_include_major_skip_notes_is_true():
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="updated", beyond_constraint_skip_reason="exact version pin"),
        ]
    )

    pr_body = render_body(result, "https://example.com/run/1")
    summary = render_body(result, "https://example.com/run/1", include_major_skip_notes=True)

    assert "Update beyond constraint skipped" not in pr_body
    assert "exact version pin" not in pr_body
    assert "Update beyond constraint skipped" in summary
    assert "a (exact version pin)" in summary


def test_held_back_table_and_updated_table_both_render_together():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a", status="updated", old_version="1.0.0", new_version="2.0.0", bump="major"
            ),
            _outcome(
                name="b",
                status="skipped",
                old_version="1.0.0",
                beyond_constraint_version="3.0.0",
                beyond_constraint_failure_kind="resolution",
                beyond_constraint_output_tail="no matching version",
            ),
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "## ✅ Updated" in body
    assert "Held back (update beyond declared constraint failed)" in body
    assert "## ⏭ No update available" in body
    assert "b" in body


def test_render_body_held_back_stays_within_budget_at_scale():
    outcomes = [
        _outcome(
            name=f"pkg{i}",
            status="skipped",
            old_version="1.0.0",
            beyond_constraint_version="3.0.0",
            beyond_constraint_failure_kind="test",
            beyond_constraint_output_tail="boom\n" * 100,
        )
        for i in range(500)
    ]
    result = UpdateResult(outcomes=outcomes)

    body = render_body(result, "https://example.com/run/1")

    assert len(body) <= MAX_BODY_CHARS


def test_held_back_packages_output_property():
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="updated"),
            _outcome(
                name="b",
                status="failed",
                beyond_constraint_version="2.0.0",
                beyond_constraint_failure_kind="resolution",
            ),
        ]
    )
    assert result.held_back == ["b"]


def test_write_outputs_includes_held_back_packages(tmp_path):
    output_file = tmp_path / "output.txt"
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a",
                status="updated",
                beyond_constraint_version="2.0.0",
                beyond_constraint_failure_kind="test",
            )
        ]
    )

    write_outputs(str(output_file), result, "body")

    content = output_file.read_text()
    assert "held-back-packages=a\n" in content


def test_render_body_stays_under_budget_with_2000_of_every_major_bump_kind_too():
    """Extends the existing 2000-of-each-status stress test (issue #21):
    add 2000 major-updated, 2000 held-back, and 2000 major-skipped
    outcomes on top and the hard size guarantee must still hold."""
    outcomes = (
        [
            _outcome(
                name=f"upd-{i}",
                status="updated",
                old_version="1.0.0",
                new_version="1.0.1",
                bump="major" if i % 2 == 0 else None,
            )
            for i in range(2000)
        ]
        + [
            _outcome(
                name=f"fail-{i}",
                status="failed",
                old_version="1.0.0",
                new_version="1.0.1",
                failure_kind="test",
                output_tail="boom\n" * 100,
            )
            for i in range(2000)
        ]
        + [
            _outcome(
                name=f"heldback-{i}",
                status="skipped",
                old_version="1.0.0",
                beyond_constraint_version="3.0.0",
                beyond_constraint_failure_kind="test",
                beyond_constraint_output_tail="boom\n" * 100,
                beyond_constraint_skip_reason=None,
            )
            for i in range(2000)
        ]
        + [
            _outcome(
                name=f"majorskip-{i}", status="skipped", beyond_constraint_skip_reason="exact pin"
            )
            for i in range(2000)
        ]
    )
    result = UpdateResult(outcomes=outcomes)

    body = render_body(result, "https://example.com/run/1", include_major_skip_notes=True)
    summary = render_body(
        result,
        "https://example.com/run/1",
        max_chars=MAX_SUMMARY_CHARS,
        include_major_skip_notes=True,
    )

    assert len(body) <= MAX_BODY_CHARS
    assert len(summary) <= MAX_SUMMARY_CHARS


def test_report_json_drops_beyond_constraint_output_tail_too_when_too_large():
    big = "x" * (200 * 1024)
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a",
                status="updated",
                beyond_constraint_version="2.0.0",
                beyond_constraint_failure_kind="test",
                beyond_constraint_output_tail=big,
            ),
            _outcome(
                name="b",
                status="updated",
                beyond_constraint_version="2.0.0",
                beyond_constraint_failure_kind="test",
                beyond_constraint_output_tail=big,
            ),
        ]
    )

    text = report_json(result, max_bytes=256 * 1024)

    assert len(text.encode("utf-8")) <= 256 * 1024
    data = json.loads(text)
    truncated = [r for r in data if r.get("beyond_constraint_output_truncated")]
    assert truncated
    for record in truncated:
        assert record.get("beyond_constraint_output_tail", "") == ""


# --- strategy: batch-first (issue #23) -----------------------------------


def test_report_json_includes_batch_first_additive_fields():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="a",
                status="updated",
                strategy="batch-first",
                tested_in_batch=True,
            )
        ]
    )

    (record,) = json.loads(report_json(result))

    assert record["strategy"] == "batch-first"
    assert record["tested_in_batch"] is True
    assert "batch_test_failed" not in record


def test_report_json_includes_batch_test_failed_field():
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="updated", strategy="batch-first", batch_test_failed=True)
        ]
    )

    (record,) = json.loads(report_json(result))

    assert record["batch_test_failed"] is True
    assert "tested_in_batch" not in record


def test_report_json_includes_bundled_with_field():
    result = UpdateResult(
        outcomes=[
            _outcome(
                name="b",
                status="updated",
                strategy="batch-first",
                tested_in_batch=True,
                bundled_with="a",
            )
        ]
    )

    (record,) = json.loads(report_json(result))

    assert record["bundled_with"] == "a"


def test_report_json_omits_bundled_with_when_not_set():
    (record,) = json.loads(report_json(UpdateResult(outcomes=[_outcome(name="a")])))
    assert "bundled_with" not in record


def test_render_body_shows_batch_fallback_banner_when_batch_test_failed():
    result = UpdateResult(
        outcomes=[
            _outcome(name="a", status="updated", strategy="batch-first", batch_test_failed=True)
        ]
    )

    body = render_body(result, "https://example.com/run/1")

    assert "Batch update failed tests, fell back to per-package" in body


def test_render_body_has_no_batch_fallback_banner_by_default():
    result = UpdateResult(outcomes=[_outcome(name="a", status="updated")])

    body = render_body(result, "https://example.com/run/1")

    assert "Batch update failed tests" not in body
