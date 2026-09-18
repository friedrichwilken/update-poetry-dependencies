"""Keeps the top-level docs restructure (README.md kept short, docs/
cross-links honest) from rotting. Deliberately small, dependency-free,
line-based text scans - same style as test_action_yml.py/test_readme_sync.py.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

README_MAX_LINES = 70
README_MAX_TABLE_COLUMNS = 3

_FENCE_RE = re.compile(r"^\s*```")
_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LINK_RE = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _all_markdown_files() -> list[Path]:
    files = [README]
    files += sorted((ROOT / "docs").rglob("*.md"))
    return files


def _strip_code_fences(lines: list[str]) -> list[tuple[int, str]]:
    """Return (0-based index, line) pairs for lines outside fenced code
    blocks."""
    kept = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append((i, line))
    return kept


def _table_row_columns(line: str) -> int:
    """Number of columns in a `| a | b | c |` (or `a | b | c`) row."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return len(stripped.split("|"))


def slugify(heading: str) -> str:
    """A simple version of GitHub's own heading-anchor slug rule: lowercase,
    strip punctuation (anything that isn't alphanumeric, a space or a
    hyphen), then turn spaces into hyphens."""
    text = re.sub(r"[^A-Za-z0-9 \-]", "", heading)
    text = text.lower().strip()
    text = re.sub(r"\s+", "-", text)
    return text


def _headings(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    slugs: dict[str, int] = {}
    result = set()
    for _, line in _strip_code_fences(lines):
        m = _ATX_HEADING_RE.match(line)
        if not m:
            continue
        slug = slugify(m.group(2))
        n = slugs.get(slug, 0)
        slugs[slug] = n + 1
        result.add(slug if n == 0 else f"{slug}-{n}")
    return result


def test_readme_line_limit():
    lines = README.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= README_MAX_LINES, (
        f"README.md has {len(lines)} lines, must be <= {README_MAX_LINES} "
        "(everything else belongs in docs/)"
    )


def test_readme_has_no_wide_tables():
    lines = README.read_text(encoding="utf-8").splitlines()
    offenders = []
    for i, line in _strip_code_fences(lines):
        if not _TABLE_ROW_RE.match(line) or _TABLE_SEPARATOR_RE.match(line):
            continue
        columns = _table_row_columns(line)
        if columns > README_MAX_TABLE_COLUMNS:
            offenders.append(f"README.md:{i + 1}: table row with {columns} columns: {line!r}")
    assert offenders == [], "\n".join(offenders)


def test_readme_has_no_input_table():
    text = README.read_text(encoding="utf-8")
    for name in ("python-version", "package-manager", "poetry-version", "github_token"):
        assert f"`{name}`" not in text, (
            f"README.md should not contain a full inputs table - found `{name}`; "
            "inputs belong in docs/manual/inputs.md"
        )


def test_relative_links_resolve():
    offenders = []
    for path in _all_markdown_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for _, line in _strip_code_fences(lines):
            for target in _LINK_RE.findall(line):
                if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", target):  # http:, mailto:, etc.
                    continue
                file_part, _, anchor = target.partition("#")
                if file_part == "":
                    resolved = path
                else:
                    resolved = (path.parent / file_part).resolve()
                if not resolved.is_file():
                    offenders.append(f"{path.relative_to(ROOT)}: broken link target {target!r}")
                    continue
                if anchor and anchor not in _headings(resolved):
                    offenders.append(
                        f"{path.relative_to(ROOT)}: anchor {target!r} has no matching "
                        f"heading in {resolved.relative_to(ROOT)}"
                    )
    assert offenders == [], "\n".join(offenders)
