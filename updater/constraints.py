"""Pure functions for analyzing version constraints/specifiers, for the
major-bump feature (issue #21): does a declared constraint already allow
anything ("no upper bound", so the ordinary in-range update already finds
the latest release and a separate major attempt would just double-test the
same thing), is it an exact pin (the user pinned on purpose, never touch
it), and - for uv - how to rewrite a capped specifier to drop the cap while
keeping whatever lower bound it already had.

Two dialects are covered, matching where each is actually used in a
`pyproject.toml`:

- PEP 508 specifiers (`>=1.2,<2.0`, `~=2.1`, `==2.*`, ...), used by uv's
  `[project.dependencies]` / `[project.optional-dependencies]` /
  `[dependency-groups]` and by Poetry's own PEP 621 tables of the same
  name (Poetry >= 2).
- Poetry's own shorthand (`^1.2.3`, `~1.2`, `1.2.*`, plain `1.2.3` meaning
  an exact pin, or a comma separated combination of these and/or plain
  comparison operators), used by `[tool.poetry.dependencies]` and
  `[tool.poetry.group.<g>.dependencies]`.

Both dialects reduce to the same shape once parsed: a list of (operator,
version) clauses, ANDed together (comma separated).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .pep440 import Version, parse_version

_UPPER_BOUND_OPS = {"<", "<="}


@dataclass(frozen=True)
class Clause:
    op: str
    version: str


# --- PEP 508 specifiers ----------------------------------------------------

_PEP508_CLAUSE_RE = re.compile(r"^\s*(===|==|!=|<=|>=|<|>|~=)\s*(.+?)\s*$")


def pep508_parse_specifiers(text: str) -> list[Clause] | None:
    """Parse a PEP 508 specifier set (the part after the package name and
    extras, e.g. ">=1.2,<2.0"). An empty/whitespace-only string is a valid,
    empty specifier set (matches anything). Returns None if any clause
    fails to parse."""
    text = (text or "").strip()
    if not text:
        return []
    clauses = []
    for part in text.split(","):
        match = _PEP508_CLAUSE_RE.match(part)
        if not match:
            return None
        op, version = match.group(1), match.group(2).strip()
        if op == "===":
            op = "=="
        clauses.append(Clause(op, version))
    return clauses


def pep508_has_upper_bound(clauses: list[Clause]) -> bool:
    """True if this specifier set excludes some sufficiently high version -
    an explicit `<`/`<=`, a compatible-release `~=` (which always implies
    an upper bound), or a wildcard `==X.*` equality."""
    for clause in clauses:
        if clause.op in _UPPER_BOUND_OPS:
            return True
        if clause.op == "~=":
            return True
        if clause.op == "==" and clause.version.rstrip().endswith(".*"):
            return True
    return False


def pep508_is_exact_pin(clauses: list[Clause]) -> bool:
    """True for a single `==`/`===` clause pinning one concrete version
    (not a `.*` wildcard, which is a range, not a pin)."""
    if len(clauses) != 1:
        return False
    clause = clauses[0]
    return clause.op == "==" and not clause.version.rstrip().endswith(".*")


def pep508_strip_upper_bound(clauses: list[Clause]) -> str:
    """Rewrite a clause list to drop whatever excludes a higher version,
    keeping any real lower bound intact, as a new specifier string ready to
    hand to `uv add`. `~=X.Y` becomes `>=X.Y`; `==X.*` becomes `>=X` (the
    wildcard's own prefix as a plain lower bound); a bare `<`/`<=` clause is
    simply dropped. If nothing is left afterwards (the constraint was
    upper-bound-only, e.g. just "<3"), falls back to ">=0" so the result is
    still a valid, universally-true lower bound."""
    kept: list[str] = []
    for clause in clauses:
        if clause.op in _UPPER_BOUND_OPS:
            continue
        if clause.op == "~=":
            kept.append(f">={clause.version}")
            continue
        if clause.op == "==" and clause.version.rstrip().endswith(".*"):
            prefix = clause.version.rstrip()[:-2].rstrip(".")
            kept.append(f">={prefix or '0'}")
            continue
        kept.append(f"{clause.op}{clause.version}")
    return ",".join(kept) if kept else ">=0"


# --- Poetry shorthand constraints -------------------------------------------

_POETRY_CLAUSE_RE = re.compile(r"^\s*(\^|~|==|!=|<=|>=|<|>)?\s*(.+?)\s*$")


def poetry_parse_constraint(text: str) -> list[Clause] | None:
    """Parse a Poetry-syntax constraint string (e.g. "^1.2.3", "~1.2",
    "1.2.*", ">=1.2,<2.0", or a plain "1.2.3" meaning an exact pin).
    Returns None on anything unparsable (e.g. a git/url reference that
    somehow ended up here, or garbage)."""
    text = (text or "").strip()
    if not text or text == "*":
        return []
    clauses = []
    for part in text.split(","):
        match = _POETRY_CLAUSE_RE.match(part)
        if not match:
            return None
        op, version = match.group(1), match.group(2).strip()
        if not version:
            return None
        clauses.append(Clause(op or "==", version))
    return clauses


def _caret_has_upper_bound(_version: str) -> bool:
    # A caret constraint always implies an upper bound (the next
    # significant version bump from the leftmost non-zero component), by
    # definition - there is no caret form that means "unbounded".
    return True


def poetry_has_upper_bound(clauses: list[Clause]) -> bool:
    for clause in clauses:
        if clause.op in _UPPER_BOUND_OPS:
            return True
        if clause.op == "^":
            return True
        if clause.op == "~":
            return True
        if clause.version.rstrip().endswith(".*"):
            return True
        if clause.op == "==" and not clause.version.rstrip().endswith(".*"):
            # A bare version with no operator (e.g. "1.2.3") is Poetry
            # shorthand for an exact pin, which is trivially its own upper
            # bound too - but exact pins are handled (and skipped) via
            # poetry_is_exact_pin() before this ever matters for deciding
            # whether to attempt a major bump.
            return True
    return False


def poetry_is_exact_pin(clauses: list[Clause]) -> bool:
    if len(clauses) != 1:
        return False
    clause = clauses[0]
    return clause.op == "==" and not clause.version.rstrip().endswith(".*")


# --- Shared helpers ----------------------------------------------------------


def parse_clause_version(clause: Clause) -> Version | None:
    return parse_version(clause.version.rstrip().removesuffix(".*"))
