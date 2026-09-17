from __future__ import annotations

import secrets

from .updater import UpdateResult


def _section(title: str, packages: list[str]) -> str:
    lines = [title]
    if packages:
        lines.extend(f"- {pkg}" for pkg in packages)
    else:
        lines.append("None")
    return "\n".join(lines)


def render_body(result: UpdateResult, run_url: str) -> str:
    parts = [
        f"Workflow details: {run_url}",
        _section("## ✅ Updated packages:", result.passed),
        _section("## \U0001f6d1 Packages failed to update:", result.failed),
        _section("## ⏭ Package without updates:", result.skipped),
    ]
    return "\n\n".join(parts) + "\n"


def write_outputs(output_path: str, result: UpdateResult, body: str) -> None:
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        fh.write(f"passed-packages={','.join(result.passed)}\n")
        fh.write(f"failed-packages={','.join(result.failed)}\n")
        fh.write(f"skipped-packages={','.join(result.skipped)}\n")
        delimiter = f"ghadelim_{secrets.token_hex(16)}"
        fh.write(f"pr-body<<{delimiter}\n{body}\n{delimiter}\n")
