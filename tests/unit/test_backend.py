import pytest
from fakes import FakeCommandRunner, result

from updater.backend import PoetryBackend, UvBackend, make_backend
from updater.errors import ActionError


def test_uv_backend_install_runs_locked_sync_with_all_groups_and_extras():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12")

    backend.install()

    assert runner.calls == [
        {
            "args": [
                "uv",
                "sync",
                "--locked",
                "--all-groups",
                "--all-extras",
                "--python",
                "3.12",
            ],
            "cwd": "some/dir",
        }
    ]


def test_uv_backend_sync_uses_the_same_command_as_install():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12")

    backend.sync()

    assert runner.calls[0]["args"][:2] == ["uv", "sync"]
    assert "--locked" in runner.calls[0]["args"]


def test_uv_backend_update_package_locks_then_syncs():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12")

    backend.update_package("idna")

    assert runner.calls[0] == {
        "args": ["uv", "lock", "--upgrade-package", "idna"],
        "cwd": "some/dir",
    }
    assert runner.calls[1]["args"][:2] == ["uv", "sync"]


def test_uv_backend_update_package_does_not_sync_when_lock_fails():
    runner = FakeCommandRunner(results=[result(False, stderr="boom")])
    backend = UvBackend(runner, "some/dir", "3.12")

    update_result = backend.update_package("idna")

    assert not update_result.ok
    assert len(runner.calls) == 1


def test_uv_backend_lock_file_path_and_files_to_stage():
    backend = UvBackend(FakeCommandRunner(), "some/dir", "3.12")

    assert str(backend.lock_file_path()) == "some/dir/uv.lock"
    assert backend.files_to_stage() == ["uv.lock"]


def test_uv_backend_lock_exists(tmp_path):
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")
    assert backend.lock_exists() is False

    (tmp_path / "uv.lock").write_text("")
    assert backend.lock_exists() is True


def test_uv_backend_list_top_level_packages_reads_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "x"
        dependencies = ["idna", "requests[socks]>=2"]
        """
    )
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")

    assert backend.list_top_level_packages() == ["idna", "requests"]


def test_uv_backend_list_top_level_packages_raises_when_pyproject_missing(tmp_path):
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")

    with pytest.raises(ActionError):
        backend.list_top_level_packages()


def test_make_backend_returns_poetry_backend():
    class Cfg:
        directory = "."
        poetry_version = "2.1.3"
        python_version = "3.12.7"

    backend = make_backend("poetry", FakeCommandRunner(), Cfg())
    assert isinstance(backend, PoetryBackend)


def test_make_backend_returns_uv_backend():
    class Cfg:
        directory = "."
        poetry_version = "2.1.3"
        python_version = "3.12.7"

    backend = make_backend("uv", FakeCommandRunner(), Cfg())
    assert isinstance(backend, UvBackend)


def test_make_backend_raises_for_unknown_manager():
    class Cfg:
        directory = "."
        poetry_version = "2.1.3"
        python_version = "3.12.7"

    with pytest.raises(ActionError):
        make_backend("pipenv", FakeCommandRunner(), Cfg())
