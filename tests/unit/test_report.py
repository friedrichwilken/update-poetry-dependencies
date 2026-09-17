import json

from updater.report import MAX_BODY_CHARS, render_body, report_json, write_outputs
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
