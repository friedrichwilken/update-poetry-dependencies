import pytest

from updater.pep440 import compare_versions, is_prerelease, parse_version


@pytest.mark.parametrize(
    "text, release",
    [
        ("1.2.3", (1, 2, 3)),
        ("1.2", (1, 2)),
        ("3.20", (3, 20)),
        ("2026.7.22", (2026, 7, 22)),
        ("v1.2.3", (1, 2, 3)),
    ],
)
def test_parse_version_release_segment(text, release):
    version = parse_version(text)
    assert version is not None
    assert version.release == release


@pytest.mark.parametrize("text", ["", "not-a-version", "1!1.0", None])
def test_parse_version_returns_none_for_unparsable(text):
    assert parse_version(text) is None


@pytest.mark.parametrize(
    "text, is_pre",
    [
        ("1.0.0", False),
        ("2.0.0a1", True),
        ("2.0.0b2", True),
        ("2.0.0rc1", True),
        ("2.0.0.dev1", True),
        ("1.0.post1", False),
        ("1.0", False),
    ],
)
def test_is_prerelease(text, is_pre):
    assert is_prerelease(text) is is_pre


def test_is_prerelease_false_for_unparsable_text():
    assert is_prerelease("garbage") is False


@pytest.mark.parametrize(
    "lower, higher",
    [
        ("1.2.3", "1.2.10"),
        ("1.2.3", "1.3.0"),
        ("2.0.0a1", "2.0.0"),
        ("2.0.0a1", "2.0.0b1"),
        ("2.0.0b1", "2.0.0rc1"),
        ("2.0.0rc1", "2.0.0"),
        ("1.0.dev1", "1.0"),
        ("1.0", "1.0.post1"),
        ("1.0", "2.0"),
    ],
)
def test_compare_versions_orders_lower_before_higher(lower, higher):
    assert compare_versions(parse_version(lower), parse_version(higher)) == -1
    assert compare_versions(parse_version(higher), parse_version(lower)) == 1


def test_compare_versions_equal():
    assert compare_versions(parse_version("1.2.3"), parse_version("1.2.3")) == 0
