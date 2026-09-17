import pytest

from updater.config import check_versions, parse_labels, resolve_base_branch
from updater.errors import ActionError


def test_parse_labels_comma_separated():
    assert parse_labels("bug,needs review,high priority") == [
        "bug",
        "needs review",
        "high priority",
    ]


def test_parse_labels_newline_separated():
    assert parse_labels("bug\nneeds review\nhigh priority") == [
        "bug",
        "needs review",
        "high priority",
    ]


def test_parse_labels_mixed_with_blank_lines_and_whitespace():
    assert parse_labels(" bug ,\n\nneeds review\n, ,high priority\n") == [
        "bug",
        "needs review",
        "high priority",
    ]


def test_parse_labels_empty_string():
    assert parse_labels("") == []


def test_parse_labels_only_whitespace_and_separators():
    assert parse_labels(" , \n , \n") == []


def test_check_versions_accepts_supported_poetry_versions():
    check_versions("poetry", "3.12.7", "2.0.0")  # should not raise


def test_check_versions_accepts_supported_uv_versions():
    check_versions("uv", "3.12.7", "")  # should not raise; poetry-version is unused


def test_check_versions_rejects_old_python_for_poetry():
    with pytest.raises(ActionError):
        check_versions("poetry", "3.9.0", "2.0.0")


def test_check_versions_rejects_old_poetry():
    with pytest.raises(ActionError):
        check_versions("poetry", "3.12.7", "1.1.0")


def test_check_versions_does_not_enforce_poetry_minimum_for_uv_backend():
    check_versions("uv", "3.12.7", "0.0.1")  # should not raise; not a poetry run


def test_check_versions_uv_backend_has_a_lower_python_floor_than_poetry():
    with pytest.raises(ActionError):
        check_versions("poetry", "3.9.5", "2.0.0")
    check_versions("uv", "3.9.5", "")  # should not raise


def test_resolve_base_branch_prefers_explicit_input():
    assert resolve_base_branch("release", "feature", "main") == "release"


def test_resolve_base_branch_prefers_explicit_input_even_when_detached():
    assert resolve_base_branch("release", "HEAD", "main") == "release"


def test_resolve_base_branch_uses_current_branch_when_not_detached():
    assert resolve_base_branch("", "feature", "") == "feature"


def test_resolve_base_branch_falls_back_to_github_base_ref_when_detached():
    assert resolve_base_branch("", "HEAD", "main") == "main"


def test_resolve_base_branch_raises_when_detached_and_no_fallback():
    with pytest.raises(ActionError):
        resolve_base_branch("", "HEAD", "")


def test_resolve_base_branch_raises_when_current_branch_is_empty_and_no_fallback():
    with pytest.raises(ActionError):
        resolve_base_branch("", "", "")
