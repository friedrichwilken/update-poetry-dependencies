"""actionlint does not check the shell scripts inside a composite action's
own action.yml `run:` steps (it only validates the `with:` inputs a
workflow passes to a local action against its declared inputs) - the run:
step bodies of the action.yml that ships an action are simply not linted by
`uses: raven-actions/actionlint@v2` / `uses: ./`. So bug #15 (script
injection via `${{ }}` interpolated straight into a run: script) needs its
own guard here: a small, dependency-free line-based scan of action.yml that
fails if any `${{ }}` expression appears inside a `run:` block body.
"""

from pathlib import Path

ACTION_YML = Path(__file__).resolve().parents[2] / "action.yml"


def _run_block_lines(text: str) -> list[str]:
    """Return every line that is part of a `run:` step's script body."""
    block_lines: list[str] = []
    in_block = False
    key_indent = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not in_block and stripped.startswith("run:"):
            key_indent = len(line) - len(line.lstrip())
            after = stripped[len("run:"):].strip()
            block_scalar_indicators = ("|", ">", "|-", ">-", "|+", ">+")
            if after and after not in block_scalar_indicators:
                # inline `run: some command` on the same line as the key
                block_lines.append(after)
            else:
                in_block = True
            continue
        if in_block:
            if stripped == "":
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= key_indent:
                in_block = False
            else:
                block_lines.append(line)
    return block_lines


def test_scanner_finds_a_synthetic_run_block():
    text = """
runs:
  using: composite
  steps:
    - name: bad
      run: |
        echo "${{ inputs.foo }}"
"""
    lines = _run_block_lines(text)
    assert any("${{" in line for line in lines)


def test_scanner_ignores_expressions_outside_run_blocks():
    text = """
runs:
  using: composite
  steps:
    - name: fine
      env:
        FOO: ${{ inputs.foo }}
      run: |
        echo "$FOO"
"""
    lines = _run_block_lines(text)
    assert not any("${{" in line for line in lines)


def test_action_yml_has_at_least_one_run_block():
    lines = _run_block_lines(ACTION_YML.read_text())
    assert lines, "expected action.yml to contain at least one run: block"


def test_action_yml_run_blocks_never_interpolate_expressions():
    text = ACTION_YML.read_text()
    offending = [line for line in _run_block_lines(text) if "${{" in line]
    assert offending == [], (
        "run: blocks in action.yml must never interpolate ${{ }} expressions "
        f"directly - pass them through env: instead: {offending}"
    )
