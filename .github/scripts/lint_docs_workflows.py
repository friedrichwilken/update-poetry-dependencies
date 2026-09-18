"""CI-only (see check_action.yml's `docs` job): renders every complete
workflow example documented in README.md/docs/**/*.md against the local
action.yml (`uses: ./`) and runs actionlint on the result - a documented
`with:` key/value that actionlint itself would reject (not just an unknown
input, which tests/unit/test_docs_examples.py already catches) fails CI.

Also renders a mechanical Poetry rendition of each example: every line
carrying a `# Poetry: <value>` (or `# new - Poetry: <value>`) trailing
comment has its value swapped in for the uv one before linting, so the
Poetry variant documented only as an inline comment throughout the
tutorial is actually validated too, not just eyeballed.

Deliberately a small, dependency-free, line-based scan (no PyYAML) - same
style as tests/unit/test_docs_examples.py, which this intentionally
duplicates rather than imports (same reasoning as test_action_yml.py's own
independent scanner: these are two different consumers of the same
convention, kept decoupled on purpose).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

USES_TARGET_RE = re.compile(
    r"uses:(\s*)(friedrichwilken/"
    r"(?:update-poetry-dependencies|test-gated-python-updates)(?:@\S*)?)"
)
# The value on both sides of "Poetry:" is always a single-quoted YAML
# string in this tutorial (e.g. 'uv run pytest') - matched quote-aware
# (`'[^']*'`, stopping at the closing quote) rather than "everything up to
# the next #", so a value that itself contains a `#` or `:` inside its
# quotes can never be mistaken for the start of the trailing comment. Works
# whether the comment is the plain `# Poetry: '...'` form or the combined
# `# <- <description>. Poetry: '...'` form used the one time a line is
# both new and Poetry-divergent - `.*?` only needs to reach the first
# "Poetry:" after the `#`, regardless of what comes before it.
POETRY_LINE_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+:\s*)(?P<oldval>'[^']*')"
    r"\s*#.*?Poetry:\s*(?P<newval>'[^']*')\s*$"
)


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


def is_complete_workflow(block: str) -> bool:
    """A block that stands on its own as a runnable workflow file - has a
    `name:`, `on:` and `jobs:` top-level key - as opposed to a short
    fragment (a single step, a `permissions:` snippet, ...)."""
    return bool(
        re.search(r"^name:\s", block, re.MULTILINE)
        and re.search(r"^on:", block, re.MULTILINE)
        and re.search(r"^jobs:", block, re.MULTILINE)
    )


def rewrite_uses_to_local(text: str) -> str:
    """`uses: friedrichwilken/<this action>@...` -> `uses: ./`, so
    actionlint validates `with:` against the *local* action.yml instead of
    trying (and failing) to resolve a remote action it cannot see."""
    return USES_TARGET_RE.sub(lambda m: f"uses:{m.group(1)}./", text)


def poetrify(text: str) -> str:
    """Apply every `# Poetry: <value>` inline comment: swap that line's
    value for the Poetry one, dropping the comment."""
    out_lines = []
    for line in text.splitlines():
        m = POETRY_LINE_RE.match(line)
        if m:
            out_lines.append(f"{m.group('indent')}{m.group('key')}{m.group('newval')}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def workflow_filename(source: Path, index: int, variant: str) -> str:
    stem = source.relative_to(ROOT).as_posix().replace("/", "_").rsplit(".", 1)[0]
    return f"{stem}_{index}_{variant}.yml"


def render_all(workflows_dir: Path) -> int:
    rendered = 0
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        for index, block in enumerate(yaml_blocks(text)):
            if not is_complete_workflow(block):
                continue
            for variant, render in (("uv", lambda b: b), ("poetry", poetrify)):
                rendered_text = rewrite_uses_to_local(render(block))
                out_path = workflows_dir / workflow_filename(path, index, variant)
                out_path.write_text(rendered_text + "\n", encoding="utf-8")
                rendered += 1
    return rendered


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="docs-workflow-lint-") as tmp:
        workdir = Path(tmp)
        workflows_dir = workdir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        shutil.copy2(ROOT / "action.yml", workdir / "action.yml")
        # actionlint locates the repository root (to resolve `uses: ./`)
        # by walking up to a `.git` directory - this scratch dir needs one
        # of its own, it is never pushed anywhere.
        subprocess.run(["git", "init", "-q"], cwd=workdir, check=True, stdout=subprocess.DEVNULL)

        rendered = render_all(workflows_dir)
        print(f"rendered {rendered} workflow file(s) into {workflows_dir}")
        if rendered == 0:
            print("::error::no complete workflow examples found in README.md/docs/**/*.md")
            return 1

        result = subprocess.run(["actionlint"], cwd=workdir, check=False)
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
