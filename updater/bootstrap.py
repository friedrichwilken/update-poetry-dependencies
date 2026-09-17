"""Provisions the project's interpreter and, for the Poetry backend, Poetry
itself - via `uv`, which the composite action installs before running this
package (see `action.yml`).

All of the branching between backends lives here in Python rather than in
`action.yml`'s bash, per issue #20: the composite action always runs the
same single `uv run --no-project --python 3.14 -m updater` step regardless
of which backend the project uses.

This only ever runs for real from `updater.__main__.run()`, and only when
no backend was injected (i.e. never in the unit tests, which always inject
a fake backend and so never need a fake `uv`/`poetry` on PATH).
"""

from __future__ import annotations

import os

from .errors import ActionError
from .runner import CommandRunner

POETRY_VIRTUALENVS_IN_PROJECT = "POETRY_VIRTUALENVS_IN_PROJECT"


def _run(runner: CommandRunner, args: list[str], cwd: str | None = None):
    result = runner.run(args, cwd=cwd)
    print(result.stdout)
    print(result.stderr)
    return result


def find_project_python(runner: CommandRunner, python_version: str) -> str:
    """Install (if needed) and locate the interpreter for `python_version`.
    Deliberately independent of the interpreter the updater itself runs
    on (pinned to 3.14 by action.yml)."""
    install_result = _run(runner, ["uv", "python", "install", python_version])
    if not install_result.ok:
        raise ActionError(
            f"uv python install {python_version} failed: {install_result.stderr}"
        )

    find_result = _run(runner, ["uv", "python", "find", python_version])
    if not find_result.ok:
        raise ActionError(
            f"uv python find {python_version} failed: {find_result.stderr}"
        )
    return find_result.stdout.strip()


def _prepend_to_path(directory: str) -> None:
    """Make `directory` discoverable both for the rest of *this* process
    (os.environ, inherited by every subprocess the updater itself spawns
    from here on) and, via $GITHUB_PATH, for every later step of the same
    job - e.g. a test-command or a workflow step written by whoever uses
    this action, run outside the updater's own process entirely."""
    if not directory:
        return
    existing = os.environ.get("PATH", "")
    if directory not in existing.split(os.pathsep):
        os.environ["PATH"] = directory + os.pathsep + existing if existing else directory

    github_path = os.environ.get("GITHUB_PATH")
    if github_path:
        with open(github_path, "a", encoding="utf-8") as fh:
            fh.write(directory + "\n")


def _set_env_var(name: str, value: str) -> None:
    """Same idea as `_prepend_to_path`, for a plain env var: set it for the
    rest of this process, and persist it via $GITHUB_ENV for later steps."""
    os.environ[name] = value

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def bootstrap_poetry(
    runner: CommandRunner, directory: str, poetry_version: str, project_python: str
) -> None:
    """Install Poetry as a `uv` tool (isolated from the project's own
    dependencies) and point it at the project interpreter explicitly, so it
    never falls back to uv's own tool interpreter or whatever `python`
    happens to resolve to on PATH."""
    install_result = _run(runner, ["uv", "tool", "install", f"poetry=={poetry_version}"])
    if not install_result.ok:
        raise ActionError(
            f"uv tool install poetry=={poetry_version} failed: {install_result.stderr}"
        )

    bin_dir_result = _run(runner, ["uv", "tool", "dir", "--bin"])
    if bin_dir_result.ok:
        _prepend_to_path(bin_dir_result.stdout.strip())

    # Equivalent to snok/install-poetry's virtualenvs-in-project: true.
    _set_env_var(POETRY_VIRTUALENVS_IN_PROJECT, "true")

    env_use_result = _run(runner, ["poetry", "env", "use", project_python], cwd=directory)
    if not env_use_result.ok:
        raise ActionError(
            f"poetry env use {project_python} failed: {env_use_result.stderr}"
        )


def bootstrap(runner: CommandRunner, package_manager: str, directory: str, python_version: str, poetry_version: str) -> None:
    print("::group::bootstrapping project interpreter")
    project_python = find_project_python(runner, python_version)
    if package_manager == "poetry":
        bootstrap_poetry(runner, directory, poetry_version, project_python)
    print("::endgroup::")
