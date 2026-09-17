from poetry_update.report import render_body
from poetry_update.updater import UpdateResult


def test_render_body_lists_packages_by_section():
    result = UpdateResult(passed=["a", "b"], failed=["c"], skipped=["d"])

    body = render_body(result, "https://example.com/run/1")

    assert "https://example.com/run/1" in body
    assert "## ✅ Updated packages:" in body
    assert "- a" in body
    assert "- b" in body
    assert "## \U0001f6d1 Packages failed to update:" in body
    assert "- c" in body
    assert "## ⏭ Package without updates:" in body
    assert "- d" in body


def test_render_body_shows_none_for_empty_sections():
    result = UpdateResult(passed=[], failed=[], skipped=[])

    body = render_body(result, "https://example.com/run/1")

    assert body.count("None") == 3
