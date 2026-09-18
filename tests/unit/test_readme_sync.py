"""Keeps docs/manual/inputs.md and docs/manual/outputs.md honest against
action.yml (the inputs/outputs tables used to live in README.md itself -
see docs/manual/README.md for why they moved). Deliberately a small,
dependency-free, line-based text scan (no PyYAML dependency) - the same
style as test_action_yml.py's own run: block scanner.

Checks, per input: the name shows up as a table cell somewhere in
inputs.md, and the *default* shown there matches action.yml's own default
(or, for the one required input with no default, that the table says so
rather than showing a stale value). Outputs have no defaults, so only
presence is checked for them.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTION_YML = ROOT / "action.yml"
INPUTS_MD = ROOT / "docs" / "manual" / "inputs.md"
OUTPUTS_MD = ROOT / "docs" / "manual" / "outputs.md"

_TABLE_ROW_RE = re.compile(r"^\s*\|\s*`([A-Za-z0-9_-]+)`\s*\|(.*)\|\s*(?:\|.*)?$")
_BACKTICK_RE = re.compile(r"`([^`]*)`")


def _keys_and_defaults_in_section(text: str, section: str) -> dict[str, str | None]:
    """Return {name: default-string-or-None} for the top-level keys
    (2-space indented) directly under a top-level `section:` key in
    action.yml, e.g. 'inputs' or 'outputs'."""
    result: dict[str, str | None] = {}
    in_section = False
    current: str | None = None
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
            current = line.strip().rstrip(":")
            result[current] = None
            continue
        if indent == 4 and current is not None:
            m = re.match(r"^ {4}default:\s*(.*)$", line)
            if m:
                result[current] = m.group(1).strip().strip("'\"")
    return result


def _table_rows(text: str) -> dict[str, str]:
    """Every `| \\`name\\` | ... |` row anywhere in a manual page, mapping
    name -> the raw text of the next (default) column, if any."""
    rows: dict[str, str] = {}
    for line in text.splitlines():
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        name, rest = m.group(1), m.group(2)
        rows.setdefault(name, rest.strip())
    return rows


def _normalize_documented_default(cell: str) -> str:
    m = _BACKTICK_RE.search(cell)
    if not m:
        return cell.strip()
    value = m.group(1)
    return "" if value == '""' else value


def test_action_yml_has_inputs_and_outputs():
    text = ACTION_YML.read_text(encoding="utf-8")
    assert _keys_and_defaults_in_section(text, "inputs"), (
        "expected action.yml to declare at least one input"
    )
    assert _keys_and_defaults_in_section(text, "outputs"), (
        "expected action.yml to declare at least one output"
    )


def test_every_action_yml_input_is_documented_in_inputs_md():
    action_text = ACTION_YML.read_text(encoding="utf-8")
    inputs = _keys_and_defaults_in_section(action_text, "inputs")
    documented = _table_rows(INPUTS_MD.read_text(encoding="utf-8"))

    missing = [name for name in inputs if name not in documented]
    assert missing == [], f"action.yml inputs missing from docs/manual/inputs.md: {missing}"


def test_documented_input_defaults_match_action_yml():
    action_text = ACTION_YML.read_text(encoding="utf-8")
    inputs = _keys_and_defaults_in_section(action_text, "inputs")
    documented = _table_rows(INPUTS_MD.read_text(encoding="utf-8"))

    mismatches = []
    for name, default in inputs.items():
        cell = documented.get(name)
        if cell is None:
            continue  # already reported by the "missing" test above
        if default is None:
            # No default in action.yml == required (only github_token today):
            # the table must say so, not show a stale placeholder value.
            if "required" not in cell.lower() and "none" not in cell.lower():
                mismatches.append(
                    f"{name}: action.yml has no default (required), "
                    f"docs/manual/inputs.md shows {cell!r}"
                )
            continue
        documented_default = _normalize_documented_default(cell)
        if documented_default != default:
            mismatches.append(
                f"{name}: action.yml default is {default!r}, "
                f"docs/manual/inputs.md shows {documented_default!r} (raw: {cell!r})"
            )
    assert mismatches == [], "\n".join(mismatches)


def test_every_action_yml_output_is_documented_in_outputs_md():
    action_text = ACTION_YML.read_text(encoding="utf-8")
    outputs = _keys_and_defaults_in_section(action_text, "outputs")
    documented = _table_rows(OUTPUTS_MD.read_text(encoding="utf-8"))

    missing = [name for name in outputs if name not in documented]
    assert missing == [], f"action.yml outputs missing from docs/manual/outputs.md: {missing}"
