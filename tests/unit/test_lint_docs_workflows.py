"""Unit tests for .github/scripts/lint_docs_workflows.py's Poetry-value
extraction (poetrify()) - loaded by path since that script is CI-only
tooling, not part of the `updater` package (see its own module docstring).
Covers both comment forms the tutorial uses (plain `# Poetry: '...'` and
the combined `# <- <description>. Poetry: '...'` form used the one time a
line is both new and Poetry-divergent), and values containing `#`/`:`
inside their quotes, which a naive "split at the first #" parse would
mis-locate.
"""

import importlib.util
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / ".github" / "scripts" / "lint_docs_workflows.py"
)
_spec = importlib.util.spec_from_file_location("lint_docs_workflows", _SCRIPT_PATH)
lint_docs_workflows = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(lint_docs_workflows)

poetrify = lint_docs_workflows.poetrify


def test_poetrify_plain_form():
    line = "          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'"
    assert poetrify(line) == "          test-command: 'poetry run pytest'"


def test_poetrify_combined_arrow_and_poetry_form():
    line = (
        "          test-command: 'uv run pytest'   "
        "# <- runs after every single update. Poetry: 'poetry run pytest'"
    )
    assert poetrify(line) == "          test-command: 'poetry run pytest'"


def test_poetrify_value_containing_hash_and_colon_inside_quotes():
    line = (
        "          test-command: 'echo \"#weird:val\" && pytest'   "
        "# Poetry: 'echo \"#other:val\" && poetry run pytest'"
    )
    assert poetrify(line) == "          test-command: 'echo \"#other:val\" && poetry run pytest'"


def test_poetrify_combined_form_with_hash_and_colon_in_both_values():
    line = "          test-command: 'echo \"#a:b\"'   # <- prints a marker. Poetry: 'echo \"#c:d\"'"
    assert poetrify(line) == "          test-command: 'echo \"#c:d\"'"


def test_poetrify_leaves_non_poetry_lines_unchanged():
    line = "          github_token: ${{ secrets.GITHUB_TOKEN }}   # <- lets it push"
    assert poetrify(line) == line


def test_poetrify_operates_line_by_line_over_a_whole_block():
    block = (
        "      - uses: friedrichwilken/test-gated-python-updates@v2\n"
        "        with:\n"
        "          test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'\n"
        "          github_token: ${{ secrets.GITHUB_TOKEN }}\n"
    )
    rendered = poetrify(block)
    assert "test-command: 'poetry run pytest'" in rendered
    assert "github_token: ${{ secrets.GITHUB_TOKEN }}" in rendered
    assert "uv run pytest" not in rendered
