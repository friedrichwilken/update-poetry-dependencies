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
        "args": ["uv", "lock", "--upgrade-package", "idna", "--python", "3.12"],
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


def test_uv_sync_args_replaces_the_default_selection(tmp_path):
    """Default '--all-groups --all-extras' is unconditional and fails
    outright for a project with tool.uv.conflicts ("Extras `cpu` and `gpu`
    are incompatible with the declared conflicts"); uv-sync-args, when
    set, always wins and replaces it, parsed as shell arguments."""
    runner = FakeCommandRunner()
    backend = UvBackend(runner, str(tmp_path), "3.12", uv_sync_args="--extra cpu --group dev")

    backend.sync()

    assert runner.calls == [
        {
            "args": [
                "uv",
                "sync",
                "--locked",
                "--extra",
                "cpu",
                "--group",
                "dev",
                "--python",
                "3.12",
            ],
            "cwd": str(tmp_path),
        }
    ]


def test_uv_sync_args_default_is_all_groups_and_extras_without_conflicts(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "x"
        dependencies = []
        """
    )
    runner = FakeCommandRunner()
    backend = UvBackend(runner, str(tmp_path), "3.12")

    backend.sync()

    assert runner.calls[0]["args"] == [
        "uv",
        "sync",
        "--locked",
        "--all-groups",
        "--all-extras",
        "--python",
        "3.12",
    ]


def test_uv_sync_falls_back_to_no_selection_when_conflicts_declared_and_no_args_given(
    tmp_path, capsys
):
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "x"
        dependencies = []

        [project.optional-dependencies]
        cpu = ["idna"]
        gpu = ["six"]

        [tool.uv]
        conflicts = [[{extra = "cpu"}, {extra = "gpu"}]]
        """
    )
    runner = FakeCommandRunner()
    backend = UvBackend(runner, str(tmp_path), "3.12")

    backend.sync()

    assert runner.calls[0]["args"] == ["uv", "sync", "--locked", "--python", "3.12"]
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "uv-sync-args" in out


def test_uv_sync_args_explicit_wins_even_with_conflicts_declared(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "x"
        dependencies = []

        [tool.uv]
        conflicts = [[{extra = "cpu"}, {extra = "gpu"}]]
        """
    )
    runner = FakeCommandRunner()
    backend = UvBackend(runner, str(tmp_path), "3.12", uv_sync_args="--extra cpu")

    backend.sync()

    assert runner.calls[0]["args"] == [
        "uv",
        "sync",
        "--locked",
        "--extra",
        "cpu",
        "--python",
        "3.12",
    ]
    assert "::warning::" not in capsys.readouterr().out


def test_make_backend_returns_poetry_backend():
    class Cfg:
        directory = "."
        poetry_version = "2.1.3"
        python_version = "3.12.7"
        uv_sync_args = ""

    backend = make_backend("poetry", FakeCommandRunner(), Cfg())
    assert isinstance(backend, PoetryBackend)


def test_make_backend_returns_uv_backend():
    class Cfg:
        directory = "."
        poetry_version = "2.1.3"
        python_version = "3.12.7"
        uv_sync_args = ""

    backend = make_backend("uv", FakeCommandRunner(), Cfg())
    assert isinstance(backend, UvBackend)


def test_poetry_backend_locked_version_reads_the_lock_file(tmp_path):
    (tmp_path / "poetry.lock").write_text(
        """
        [[package]]
        name = "idna"
        version = "3.4"
        """
    )
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.1.3")

    assert backend.locked_version("idna") == "3.4"
    assert backend.locked_version("nonexistent") is None


def test_uv_backend_locked_version_reads_the_lock_file(tmp_path):
    (tmp_path / "uv.lock").write_text(
        """
        [[package]]
        name = "idna"
        version = "3.4"
        """
    )
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")

    assert backend.locked_version("idna") == "3.4"
    assert backend.locked_version("nonexistent") is None


def test_make_backend_raises_for_unknown_manager():
    class Cfg:
        directory = "."
        poetry_version = "2.1.3"
        python_version = "3.12.7"
        uv_sync_args = ""

    with pytest.raises(ActionError):
        make_backend("pipenv", FakeCommandRunner(), Cfg())
