from updater.versions import parse_version, version_at_least


def test_parse_version_basic():
    assert parse_version("3.12.7") == (3, 12, 7)


def test_parse_version_leading_zero_component():
    assert parse_version("3.12.00") == (3, 12, 0)


def test_version_at_least_true_for_equal():
    assert version_at_least("3.10", "3.10")


def test_version_at_least_true_for_greater():
    assert version_at_least("3.12.7", "3.10")


def test_version_at_least_false_for_lesser():
    assert not version_at_least("3.9", "3.10")


def test_version_at_least_handles_different_lengths():
    assert version_at_least("2.0", "1.2")
    assert not version_at_least("1.1", "1.2")
