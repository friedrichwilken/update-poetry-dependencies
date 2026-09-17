import pytest

from updater.constraints import (
    pep508_has_upper_bound,
    pep508_is_exact_pin,
    pep508_parse_specifiers,
    pep508_strip_upper_bound,
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
