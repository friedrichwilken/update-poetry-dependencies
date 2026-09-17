import pytest

from poetry_update.config import check_versions, parse_labels
from poetry_update.errors import ActionError


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


def test_check_versions_accepts_supported_versions():
    check_versions("3.12.7", "2.0.0")  # should not raise


def test_check_versions_rejects_old_python():
    with pytest.raises(ActionError):
        check_versions("3.9.0", "2.0.0")


def test_check_versions_rejects_old_poetry():
    with pytest.raises(ActionError):
        check_versions("3.12.7", "1.1.0")
