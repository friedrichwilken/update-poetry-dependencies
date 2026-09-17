"""Keeps README.md's Inputs/Outputs tables honest against action.yml.

Deliberately a small, dependency-free, line-based text scan (no PyYAML
dependency) - the same style as test_action_yml.py's run: block scanner.
It only checks that every input/output *name* declared in action.yml shows
up as a table cell in README.md; it does not attempt to diff descriptions
or defaults.
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


def test_action_yml_has_inputs_and_outputs():
    text = ACTION_YML.read_text(encoding="utf-8")
    assert _keys_in_section(text, "inputs"), "expected action.yml to declare at least one input"
    assert _keys_in_section(text, "outputs"), "expected action.yml to declare at least one output"


def test_every_action_yml_input_and_output_is_documented_in_readme():
    action_text = ACTION_YML.read_text(encoding="utf-8")
    readme_text = README.read_text(encoding="utf-8")

    names = _keys_in_section(action_text, "inputs") + _keys_in_section(action_text, "outputs")

    missing = [
        name for name in names if not re.search(rf"\|\s*{re.escape(name)}\s*\|", readme_text)
    ]
    assert missing == [], f"action.yml names missing from a README table: {missing}"
