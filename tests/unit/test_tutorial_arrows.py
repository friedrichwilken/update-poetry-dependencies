"""Keeps docs/tutorials/weekly-updates.md's `# <-` convention honest:
every step shows the complete workflow file so far, and a line should
carry a `# <-` comment exactly when it is new or changed compared to the
*previous* occurrence of that same workflow (identified by its `name:`
key) - never on an unrelated, already-introduced line, and never missing
on a line that really did just change.

The tutorial is a single workflow "lineage" (`update dependencies`) grown
one step at a time - grouped here by `name:` so a step is always compared
only against its own most recent prior version. Kept as a grouped-by-name
scan rather than a flat step-by-step diff so a future tutorial step that
ever does introduce a second workflow (as an earlier revision of step 9's
auto-merge step used to) is still handled correctly, without special-casing
either shape. Deliberately a small, dependency-free, line-based scan
(stdlib `difflib` only) - same style as the other tests/unit/test_docs_*.py
checks.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TUTORIAL = ROOT / "docs" / "tutorials" / "weekly-updates.md"

ARROW = "# <-"


def yaml_blocks(md_text: str) -> list[str]:
    blocks = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() == "```yaml":
            j = i + 1
            body = []
            while j < len(lines) and lines[j].strip() != "```":
                body.append(lines[j])
                j += 1
            blocks.append("\n".join(body))
            i = j + 1
        else:
            i += 1
    return blocks


def is_complete_workflow(block: str) -> bool:
    return bool(
        re.search(r"^name:\s", block, re.MULTILINE)
        and re.search(r"^on:", block, re.MULTILINE)
        and re.search(r"^jobs:", block, re.MULTILINE)
    )


def workflow_name(block: str) -> str:
    match = re.search(r"^name:\s*(.+?)\s*$", block, re.MULTILINE)
    assert match, "expected every complete workflow block to have a name: line"
    return match.group(1)


def strip_trailing_comment(line: str) -> str:
    """Everything from the first ` #` onward is a comment in this
    tutorial's own style (no line's real YAML content contains a literal
    `#`) - stripped so the diff below compares code, not commentary."""
    return re.sub(r"\s+#.*$", "", line)


def changed_line_indices(prev_block: str, new_block: str) -> set[int]:
    """Indices (into new_block's own lines) that a line-level diff
    (comment-stripped) considers inserted/replaced relative to
    prev_block - i.e. genuinely new or changed content, not just an
    unchanged line that happens to sit at a different position (a
    trailing comment added/removed/changed doesn't count either, since
    both sides are stripped first)."""
    prev_lines = [strip_trailing_comment(line) for line in prev_block.splitlines()]
    new_lines = [strip_trailing_comment(line) for line in new_block.splitlines()]
    matcher = difflib.SequenceMatcher(a=prev_lines, b=new_lines, autojunk=False)
    changed = set()
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            changed.update(range(j1, j2))
    return changed


def test_tutorial_has_complete_workflow_examples():
    text = TUTORIAL.read_text(encoding="utf-8")
    blocks = [b for b in yaml_blocks(text) if is_complete_workflow(b)]
    assert len(blocks) >= 2, "expected at least two complete workflow examples (steps grow one)"


def test_arrow_marks_exactly_the_changed_lines_within_each_lineage():
    text = TUTORIAL.read_text(encoding="utf-8")
    blocks = [b for b in yaml_blocks(text) if is_complete_workflow(b)]

    by_name: dict[str, list[str]] = {}
    for block in blocks:
        by_name.setdefault(workflow_name(block), []).append(block)

    offenders = []
    for name, occurrences in by_name.items():
        # The first occurrence of a workflow is its own introduction step,
        # manually curated rather than diffed against nothing - see the
        # module docstring.
        for prev_block, new_block in zip(occurrences, occurrences[1:], strict=False):
            new_lines = new_block.splitlines()
            changed = changed_line_indices(prev_block, new_block)
            for idx, line in enumerate(new_lines):
                if line.strip() == "":
                    continue  # a blank line can never carry a comment
                has_arrow = ARROW in line
                is_changed = idx in changed
                if is_changed and not has_arrow:
                    offenders.append(f"{name!r}: changed line has no {ARROW!r}: {line!r}")
                elif has_arrow and not is_changed:
                    offenders.append(f"{name!r}: unchanged line still carries {ARROW!r}: {line!r}")
    assert offenders == [], "\n".join(offenders)


def test_final_recap_has_no_arrows():
    text = TUTORIAL.read_text(encoding="utf-8")
    blocks = [b for b in yaml_blocks(text) if is_complete_workflow(b)]

    by_name: dict[str, list[str]] = {}
    for block in blocks:
        by_name.setdefault(workflow_name(block), []).append(block)

    offenders = []
    for name, occurrences in by_name.items():
        last = occurrences[-1]
        if ARROW in last:
            offenders.append(name)
    assert offenders == [], f"final recap block(s) still contain {ARROW!r}: {offenders}"
