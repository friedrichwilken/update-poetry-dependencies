import pytest

from updater.constraints import (
    all_clauses_parseable,
    pep508_has_upper_bound,
    pep508_is_exact_pin,
    pep508_parse_specifiers,
    pep508_strip_upper_bound,
    poetry_classify_constraint,
    poetry_has_upper_bound,
    poetry_is_exact_pin,
    poetry_parse_constraint,
)

# --- PEP 508 specifiers ------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        (">=1.2,<2.0", [(">=", "1.2"), ("<", "2.0")]),
        (">=1.2", [(">=", "1.2")]),
        ("~=2.1", [("~=", "2.1")]),
        ("==2.*", [("==", "2.*")]),
        ("==1.2.3", [("==", "1.2.3")]),
        ("", []),
        ("*", None),
    ],
)
def test_pep508_parse_specifiers(text, expected):
    clauses = pep508_parse_specifiers(text)
    if expected is None:
        assert clauses is None
    else:
        assert [(c.op, c.version) for c in clauses] == expected


@pytest.mark.parametrize(
    "text, has_upper",
    [
        (">=1.2,<2.0", True),
        ("<3", True),
        ("<=3.0", True),
        ("~=2.1", True),
        ("==2.*", True),
        (">=1.2", False),
        ("", False),
        ("!=1.5", False),
    ],
)
def test_pep508_has_upper_bound(text, has_upper):
    clauses = pep508_parse_specifiers(text)
    assert pep508_has_upper_bound(clauses) is has_upper


@pytest.mark.parametrize(
    "text, is_pin",
    [
        ("==1.2.3", True),
        ("==2.*", False),
        (">=1.2,<2.0", False),
        ("==1.2.3,!=1.2.4", False),
    ],
)
def test_pep508_is_exact_pin(text, is_pin):
    clauses = pep508_parse_specifiers(text)
    assert pep508_is_exact_pin(clauses) is is_pin


@pytest.mark.parametrize(
    "text, stripped",
    [
        (">=1.2,<2.0", ">=1.2"),
        ("<3", ">=0"),
        ("~=2.1", ">=2.1"),
        ("==2.*", ">=2"),
        (">=1.2", ">=1.2"),
        (">=1.2,!=1.5,<2.0", ">=1.2,!=1.5"),
    ],
)
def test_pep508_strip_upper_bound(text, stripped):
    clauses = pep508_parse_specifiers(text)
    assert pep508_strip_upper_bound(clauses) == stripped


# --- Poetry shorthand constraints ---------------------------------------


@pytest.mark.parametrize(
    "text, has_upper",
    [
        ("^1.2.3", True),
        ("~1.2", True),
        ("1.2.*", True),
        (">=1.2,<2.0", True),
        ("1.2.3", True),  # bare version: exact pin, its own upper bound
        (">=1.2", False),
        ("*", False),
        ("", False),
    ],
)
def test_poetry_has_upper_bound(text, has_upper):
    clauses = poetry_parse_constraint(text)
    assert clauses is not None
    assert poetry_has_upper_bound(clauses) is has_upper


@pytest.mark.parametrize(
    "text, is_pin",
    [
        ("1.2.3", True),
        ("==1.2.3", True),
        ("^1.2.3", False),
        ("~1.2", False),
        ("1.2.*", False),
        (">=1.2,<2.0", False),
    ],
)
def test_poetry_is_exact_pin(text, is_pin):
    clauses = poetry_parse_constraint(text)
    assert poetry_is_exact_pin(clauses) is is_pin


def test_poetry_parse_constraint_unparsable():
    assert poetry_parse_constraint(",,,") is None


def test_poetry_parse_constraint_wildcard_star_is_universal():
    assert poetry_parse_constraint("*") == []
    assert poetry_parse_constraint("") == []


# --- ~= handling and OR ("||") constraints (review fix) -----------------


def test_poetry_parse_constraint_recognizes_compatible_release_operator():
    clauses = poetry_parse_constraint("~=2.1")
    assert [(c.op, c.version) for c in clauses] == [("~=", "2.1")]


def test_poetry_has_upper_bound_true_for_compatible_release():
    clauses = poetry_parse_constraint("~=2.1")
    assert poetry_has_upper_bound(clauses) is True


def test_poetry_is_exact_pin_false_for_compatible_release():
    clauses = poetry_parse_constraint("~=2.1")
    assert poetry_is_exact_pin(clauses) is False


@pytest.mark.parametrize(
    "text, needed, reason",
    [
        ("^1.2.3", True, None),
        ("~1.2", True, None),
        ("~=2.1", True, None),
        ("1.2.*", True, None),
        (">=1.2", False, None),
        ("*", False, None),
        ("", False, None),
        ("1.2.3", False, "exact version pin"),
        (",,,", False, "unparsable version constraint"),
        ("^abc", False, "unparsable version constraint"),
        (">=1.0,<2.0 || >=3", False, None),
        (">=1.0,<2.0 || >=3.0,<4.0", False, "unsupported constraint syntax"),
        (">=1.0,<2.0 || garbage", False, "unparsable version constraint"),
    ],
)
def test_poetry_classify_constraint(text, needed, reason):
    assert poetry_classify_constraint(text) == (needed, reason)


def test_all_clauses_parseable():
    assert all_clauses_parseable(poetry_parse_constraint("^1.2.3")) is True
    assert all_clauses_parseable(poetry_parse_constraint("^abc")) is False
    assert all_clauses_parseable(poetry_parse_constraint("1.2.*")) is True
