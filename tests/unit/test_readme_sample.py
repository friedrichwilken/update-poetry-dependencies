"""Keeps README.md's "What you get" example honest against the real
renderer: renders a small, fixed UpdateResult through report.render_body()
and asserts every table row shown in the README also appears in that real
output (and vice versa isn't required - the README trims to just the two
headed tables), so the sample can never quietly drift from what the action
actually produces.
"""

from pathlib import Path

from updater.report import render_body
from updater.updater import PackageOutcome, UpdateResult

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


def _sample_result() -> UpdateResult:
    return UpdateResult(
        outcomes=[
            PackageOutcome(
                name="six", status="updated", old_version="1.16.0", new_version="1.17.0"
            ),
            PackageOutcome(
                name="idna",
                status="failed",
                old_version="3.6",
                new_version="3.7",
                failure_kind="test",
                output_tail="FAILED tests/test_idna.py",
            ),
        ]
    )


def test_readme_sample_rows_match_the_real_render():
    body = render_body(_sample_result(), "https://example.invalid/run")
    readme_text = README.read_text(encoding="utf-8")

    assert "## ✅ Updated" in body
    assert "## \U0001f6d1 Failed" in body

    expected_rows = [
        "| package | old | new |",
        "| six | 1.16.0 | 1.17.0 |",
        "| package | current | attempted | reason |",
        "| idna | 3.6 | 3.7 | tests failed |",
    ]
    for row in expected_rows:
        assert row in body, f"expected real render_body() output to contain {row!r}"
        assert row in readme_text, (
            f"README.md's sample is out of sync with the real render: missing {row!r}"
        )
