"""Keeps README.md's Inputs/Outputs tables honest against action.yml.

Deliberately a small, dependency-free, line-based text scan (no PyYAML
dependency) - the same style as test_action_yml.py's run: block scanner.
It only checks that every input/output *name* declared in action.yml shows
up as a table cell in the matching README section; it does not attempt to
diff descriptions or defaults.
"""

import re
from pathlib import Path

ACTION_YML = Path(__file__).resolve().parents[2] / "action.yml"
README = Path(__file__).resolve().parents[2] / "README.md"


def _keys_in_section(text: str, section: str) -> list[str]:
    """Return the top-level keys (2-space indented) directly under a
    top-level `section:` key in action.yml, e.g. 'inputs' or 'outputs'."""
    keys = []
    in_section = False
    for line in text.splitlines():
        if re.match(rf"^{section}:\s*$", line):
            in_section = True
            continue
        if not in_section:
            continue
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        if indent == 2 and re.match(r"^ {2}[A-Za-z0-9_-]+:\s*$", line):
            keys.append(line.strip().rstrip(":"))
    return keys


def _readme_section(heading: str) -> str:
    """Return the README.md text between a `### <heading>` line and the
    next `###` (or end of file), so the presence check below only looks at
    that section's own table rather than anywhere in the whole README."""
    text = README.read_text(encoding="utf-8")
    match = re.search(
        rf"^### {re.escape(heading)}\s*$(.*?)(?=^### |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"expected a '### {heading}' section in README.md"
    return match.group(1)


def test_action_yml_has_inputs_and_outputs():
    text = ACTION_YML.read_text(encoding="utf-8")
    assert _keys_in_section(text, "inputs"), "expected action.yml to declare at least one input"
    assert _keys_in_section(text, "outputs"), "expected action.yml to declare at least one output"


def test_every_action_yml_input_is_documented_in_the_readme_inputs_table():
    action_text = ACTION_YML.read_text(encoding="utf-8")
    inputs_section = _readme_section("Inputs")

    names = _keys_in_section(action_text, "inputs")
    missing = [
        name for name in names if not re.search(rf"\|\s*{re.escape(name)}\s*\|", inputs_section)
    ]
    assert missing == [], f"action.yml inputs missing from the README Inputs table: {missing}"


def test_every_action_yml_output_is_documented_in_the_readme_outputs_table():
    action_text = ACTION_YML.read_text(encoding="utf-8")
    outputs_section = _readme_section("Outputs")

    names = _keys_in_section(action_text, "outputs")
    missing = [
        name for name in names if not re.search(rf"\|\s*{re.escape(name)}\s*\|", outputs_section)
    ]
    assert missing == [], f"action.yml outputs missing from the README Outputs table: {missing}"
