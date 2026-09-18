"""Keeps every documented `uses: <this action>` example (README.md and
docs/**/*.md) honest against action.yml: every `with:` key it passes must be
a real, current input - catches both a typo and a removed/renamed input
left behind in the docs. Deliberately a small, dependency-free, line-based
scan (no PyYAML) - same style as test_action_yml.py/test_readme_sync.py.

Reused (in spirit - kept independently duplicated, same as
test_action_yml.py's own scanner is independent of action.yml's own
production code) by the `docs` CI job, which additionally renders each
complete workflow example and runs actionlint on it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTION_YML = ROOT / "action.yml"

# Matches this action, old or new repo name, at any ref, or the local `./`
# this repo's own workflows use.
ACTION_USES_RE = re.compile(
    r"^(friedrichwilken/(update-poetry-dependencies|test-gated-python-updates)(@\S*)?|\./)$"
)


def known_inputs() -> set[str]:
    text = ACTION_YML.read_text(encoding="utf-8")
    names = []
    in_inputs = False
    for line in text.splitlines():
        if re.match(r"^inputs:\s*$", line):
            in_inputs = True
            continue
        if not in_inputs:
            continue
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        if indent == 2 and re.match(r"^ {2}[A-Za-z0-9_-]+:\s*$", line):
            names.append(line.strip().rstrip(":"))
    return set(names)


def markdown_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files += sorted((ROOT / "docs").rglob("*.md"))
    return files


def yaml_blocks(md_text: str) -> list[str]:
    """Every fenced ```yaml ... ``` block's body, in order."""
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


def with_key_groups_for_this_action(yaml_text: str) -> list[list[str]]:
    """One list of `with:` keys per `uses:` step targeting this action
    found in `yaml_text` (an empty list for a step with no `with:` block at
    all, e.g. a bare `actions/checkout@v4`-style step that happened to
    match)."""
    lines = yaml_text.splitlines()
    groups: list[list[str]] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        m = re.match(r"^-?\s*uses:\s*(\S+)", stripped)
        if not m or not ACTION_USES_RE.match(m.group(1)):
            continue

        leading_ws = len(line) - len(line.lstrip(" "))
        # "- uses: x" puts the *key* two columns to the right of the dash;
        # a sibling "with:" aligns with that key, not with the dash.
        uses_indent = leading_ws + 2 if line.lstrip(" ").startswith("- ") else leading_ws

        with_indent = None
        keys: list[str] = []
        j = idx + 1
        while j < len(lines):
            candidate = lines[j]
            if candidate.strip() == "":
                j += 1
                continue
            cand_indent = len(candidate) - len(candidate.lstrip(" "))
            if with_indent is None:
                if cand_indent < uses_indent:
                    break  # left this step without ever finding a with:
                if cand_indent == uses_indent and candidate.strip() == "with:":
                    with_indent = cand_indent
                j += 1
                continue
            if cand_indent <= with_indent:
                break
            key_match = re.match(r"^\s*([A-Za-z0-9_-]+):", candidate)
            if key_match:
                keys.append(key_match.group(1))
            j += 1
        groups.append(keys)
    return groups


def test_action_uses_regex_matches_expected_targets():
    for ok in (
        "friedrichwilken/test-gated-python-updates@v2",
        "friedrichwilken/test-gated-python-updates@abc123",
        "friedrichwilken/update-poetry-dependencies@main",
        "./",
    ):
        assert ACTION_USES_RE.match(ok), ok
    for bad in ("actions/checkout@v4", "friedrichwilken/some-other-action@v1"):
        assert not ACTION_USES_RE.match(bad), bad


def test_every_documented_with_key_is_a_real_action_input():
    known = known_inputs()
    assert known, "expected action.yml to declare at least one input"

    offenders = []
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        for block in yaml_blocks(text):
            for keys in with_key_groups_for_this_action(block):
                for key in keys:
                    if key not in known:
                        offenders.append(
                            f"{path.relative_to(ROOT)}: documented `with:` key "
                            f"{key!r} is not a real action.yml input"
                        )
    assert offenders == [], "\n".join(offenders)


def test_at_least_one_documented_example_is_scanned():
    # Guards against the scan above silently finding nothing to check (e.g.
    # a heading/fence format change breaking yaml_blocks()).
    total = 0
    for path in markdown_files():
        for block in yaml_blocks(path.read_text(encoding="utf-8")):
            total += len(with_key_groups_for_this_action(block))
    assert total > 0, "expected at least one documented `uses:` step for this action"
