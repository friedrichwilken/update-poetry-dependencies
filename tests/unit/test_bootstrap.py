import os

import pytest
from fakes import FakeCommandRunner, result

from updater.bootstrap import bootstrap, bootstrap_poetry, find_project_python
from updater.errors import ActionError


@pytest.fixture(autouse=True)
def _clean_path_env():
    # bootstrap mutates os.environ (PATH, POETRY_VIRTUALENVS_IN_PROJECT) as
    # a side effect of provisioning poetry; keep tests isolated from each
    # other and from the real environment.
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def test_find_project_python_installs_then_finds():
    runner = FakeCommandRunner(
        results=[result(True), result(True, stdout="/opt/python/3.12/bin/python3.12\n")]
    )

    path = find_project_python(runner, "3.12")

    assert runner.calls[0]["args"] == ["uv", "python", "install", "3.12"]
    assert runner.calls[1]["args"] == ["uv", "python", "find", "3.12", "--resolve-links"]
    assert path == "/opt/python/3.12/bin/python3.12"


def test_find_project_python_raises_when_install_fails():
    runner = FakeCommandRunner(results=[result(False, stderr="network error")])

    with pytest.raises(ActionError):
        find_project_python(runner, "3.12")


def test_find_project_python_raises_when_find_fails():
    runner = FakeCommandRunner(results=[result(True), result(False, stderr="not found")])

    with pytest.raises(ActionError):
        find_project_python(runner, "3.12")


def test_bootstrap_poetry_installs_tool_extends_path_and_sets_env(tmp_path):
    runner = FakeCommandRunner(
        results=[
            result(True),  # uv tool install poetry==...
            result(True, stdout=str(tmp_path) + "\n"),  # uv tool dir --bin
            result(True),  # uv venv
        ]
    )

    bootstrap_poetry(runner, "project/dir", "2.1.3", "/opt/python/3.12/bin/python3.12")

    assert runner.calls[0]["args"] == ["uv", "tool", "install", "poetry==2.1.3"]
    assert runner.calls[1]["args"] == ["uv", "tool", "dir", "--bin"]
    assert runner.calls[2]["args"] == [
        "uv",
        "venv",
        "--python",
        "/opt/python/3.12/bin/python3.12",
        "--clear",
        "project/dir/.venv",
    ]
    assert str(tmp_path) in os.environ["PATH"].split(os.pathsep)
    assert os.environ["POETRY_VIRTUALENVS_IN_PROJECT"] == "true"


def test_bootstrap_poetry_persists_path_and_env_for_later_job_steps(tmp_path):
    """PATH/env changes made by mutating os.environ only apply to this
    process and its children - never to a *later*, separate step of the
    same GitHub Actions job (a fresh shell/process). $GITHUB_PATH and
    $GITHUB_ENV are the files Actions reads to carry additions forward to
    those later steps, so bootstrap must write to them too."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    github_path_file = tmp_path / "github_path"
    github_env_file = tmp_path / "github_env"
    os.environ["GITHUB_PATH"] = str(github_path_file)
    os.environ["GITHUB_ENV"] = str(github_env_file)

    runner = FakeCommandRunner(
        results=[
            result(True),
            result(True, stdout=str(bin_dir) + "\n"),
            result(True),
        ]
    )

    bootstrap_poetry(runner, "project/dir", "2.1.3", "/opt/python/3.12/bin/python3.12")

    assert github_path_file.read_text() == str(bin_dir) + "\n"
    assert github_env_file.read_text() == "POETRY_VIRTUALENVS_IN_PROJECT=true\n"


def test_bootstrap_poetry_raises_when_tool_install_fails():
    runner = FakeCommandRunner(results=[result(False, stderr="boom")])

    with pytest.raises(ActionError):
        bootstrap_poetry(runner, "project/dir", "2.1.3", "/opt/python/3.12/bin/python3.12")


def test_bootstrap_poetry_raises_when_uv_venv_fails(tmp_path):
    runner = FakeCommandRunner(
        results=[
            result(True),
            result(True, stdout=str(tmp_path)),
            result(False, stderr="no such interpreter"),
        ]
    )

    with pytest.raises(ActionError):
        bootstrap_poetry(runner, "project/dir", "2.1.3", "/opt/python/3.12/bin/python3.12")


def test_bootstrap_only_installs_poetry_for_the_poetry_backend():
    runner = FakeCommandRunner(
        results=[
            result(True),  # uv python install
            result(True, stdout="/opt/python/3.12/bin/python3.12\n"),  # uv python find
        ]
    )

    bootstrap(runner, "uv", "project/dir", "3.12", "2.1.3")

    assert len(runner.calls) == 2
    assert runner.calls[0]["args"] == ["uv", "python", "install", "3.12"]
    assert runner.calls[1]["args"] == ["uv", "python", "find", "3.12", "--resolve-links"]


def test_bootstrap_installs_poetry_for_the_poetry_backend():
    runner = FakeCommandRunner(
        results=[
            result(True),  # uv python install
            result(True, stdout="/opt/python/3.12/bin/python3.12\n"),  # uv python find
            result(True),  # uv tool install poetry
            result(True, stdout="/opt/uv/bin\n"),  # uv tool dir --bin
            result(True),  # uv venv
        ]
    )

    bootstrap(runner, "poetry", "project/dir", "3.12", "2.1.3")

    assert len(runner.calls) == 5
    assert runner.calls[2]["args"] == ["uv", "tool", "install", "poetry==2.1.3"]
