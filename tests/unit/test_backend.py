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


# --- try_major (issue #21) ----------------------------------------------


class _RewritingRunner:
    """Fake CommandRunner for try_major tests: simulates what `poetry add`
    / `uv add` actually does to the manifest and lock file on disk (a real
    subprocess would rewrite both) without shelling out for real."""

    def __init__(self, pyproject_path, lock_path, ok=True, after_pyproject=None, after_lock=None):
        self.pyproject_path = pyproject_path
        self.lock_path = lock_path
        self.ok = ok
        self.after_pyproject = after_pyproject
        self.after_lock = after_lock
        self.calls: list[dict] = []

    def run(self, args, cwd=None):
        self.calls.append({"args": list(args), "cwd": cwd})
        if self.ok:
            if self.after_pyproject is not None:
                self.pyproject_path.write_text(self.after_pyproject)
            if self.after_lock is not None:
                self.lock_path.write_text(self.after_lock)
            return result(True, stdout="Using version ^2.0.0 for pkg\n")
        return result(False, stderr="resolver blew up")


def test_poetry_try_major_not_needed_when_no_upper_bound(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.poetry.dependencies]\nsix = ">=1.15.0"\n')
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.4.3")

    assert backend.try_major("six") is None


def test_poetry_try_major_skips_python():
    backend = PoetryBackend(FakeCommandRunner(), ".", "2.4.3")
    attempt = backend.try_major("python")
    assert attempt.skip_reason == "python itself is never bumped"


def test_poetry_try_major_skips_exact_pin(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.poetry.dependencies]\nsix = "1.15.0"\n')
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.4.3")

    attempt = backend.try_major("six")
    assert attempt.skip_reason == "exact version pin"


def test_poetry_try_major_skips_git_dependency(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.poetry.dependencies]\nsix = { git = "https://example.com/six.git" }\n'
    )
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.4.3")

    attempt = backend.try_major("six")
    assert attempt.skip_reason == "git dependency"


def test_poetry_try_major_skips_multi_constraint_entries(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
        [tool.poetry.dependencies]
        six = [
            { version = "^1.0", python = "<3.10" },
            { version = "^2.0", python = ">=3.10" },
        ]
        """
    )
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.4.3")

    attempt = backend.try_major("six")
    assert "multiple constraint" in attempt.skip_reason


def test_poetry_try_major_uses_group_flag_for_group_dependency(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.poetry.group.dev.dependencies]\nsix = "^1.15.0"\n')
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "six"\nversion = "1.15.0"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject='[tool.poetry.group.dev.dependencies]\nsix = "^2.0.0"\n',
        after_lock='[[package]]\nname = "six"\nversion = "2.0.0"\n',
    )
    backend = PoetryBackend(runner, str(tmp_path), "2.4.3")

    attempt = backend.try_major("six")

    assert attempt.skip_reason is None
    assert attempt.resolve_result.ok
    assert runner.calls[0]["args"] == ["poetry", "add", "six@latest", "-n", "--group", "dev"]
    assert backend.locked_version("six") == "2.0.0"


def test_poetry_try_major_preserves_extras_in_requirement_string(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.poetry.dependencies]\nrequests = { version = "^2.28.0", extras = ["socks"] }\n'
    )
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "requests"\nversion = "2.28.0"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject=(
            '[tool.poetry.dependencies]\nrequests = { version = "^3.0.0", extras = ["socks"] }\n'
        ),
        after_lock='[[package]]\nname = "requests"\nversion = "3.0.0"\n',
    )
    backend = PoetryBackend(runner, str(tmp_path), "2.4.3")

    attempt = backend.try_major("requests")

    assert attempt.skip_reason is None
    assert runner.calls[0]["args"][2] == "requests[socks]@latest"


def test_poetry_try_major_discards_when_more_than_version_changed(tmp_path):
    """`poetry add` succeeding is not enough - if it changed anything
    besides the version constraint (here: dropped the extras), the
    attempt must be treated as failed rather than silently kept."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.poetry.dependencies]\nrequests = { version = "^2.28.0", extras = ["socks"] }\n'
    )
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "requests"\nversion = "2.28.0"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject='[tool.poetry.dependencies]\nrequests = "^3.0.0"\n',
        after_lock='[[package]]\nname = "requests"\nversion = "3.0.0"\n',
    )
    backend = PoetryBackend(runner, str(tmp_path), "2.4.3")

    attempt = backend.try_major("requests")

    assert attempt.skip_reason is None
    assert not attempt.resolve_result.ok
    assert "changed more than the version constraint" in attempt.resolve_result.stderr


def test_poetry_try_major_resolution_failure_is_reported(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.poetry.dependencies]\nsix = "^1.15.0"\n')
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "six"\nversion = "1.15.0"\n')
    runner = _RewritingRunner(pyproject, lock, ok=False)
    backend = PoetryBackend(runner, str(tmp_path), "2.4.3")

    attempt = backend.try_major("six")

    assert attempt.skip_reason is None
    assert not attempt.resolve_result.ok
    assert "resolver blew up" in attempt.resolve_result.stderr


def test_poetry_try_major_pep621_optional_dependency_uses_optional_flag(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
        [project]
        name = "x"
        dependencies = []

        [project.optional-dependencies]
        http = ["requests (>=2.28.0,<3.0)"]
        """
    )
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "requests"\nversion = "2.28.0"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject=(
            '[project]\nname = "x"\ndependencies = []\n\n'
            '[project.optional-dependencies]\nhttp = ["requests (>=3.0.0,<4.0.0)"]\n'
        ),
        after_lock='[[package]]\nname = "requests"\nversion = "3.0.0"\n',
    )
    backend = PoetryBackend(runner, str(tmp_path), "2.4.3")

    attempt = backend.try_major("requests")

    assert attempt.skip_reason is None
    assert runner.calls[0]["args"] == [
        "poetry",
        "add",
        "requests@latest",
        "-n",
        "--optional",
        "http",
    ]


def test_uv_try_major_not_needed_when_no_upper_bound(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\ndependencies = ["six>=1.15.0"]\n')
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")

    assert backend.try_major("six") is None


def test_uv_try_major_skips_exact_pin(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\ndependencies = ["six==1.15.0"]\n')
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")

    attempt = backend.try_major("six")
    assert attempt.skip_reason == "exact version pin"


def test_uv_try_major_skips_marker(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "x"
dependencies = ["six>=1.15.0,<2.0; python_version >= '3.10'"]
"""
    )
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")

    attempt = backend.try_major("six")
    assert attempt.skip_reason == "environment marker"


def test_uv_try_major_skips_git_path_url_workspace_source(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "x"
dependencies = ["internal-pkg>=1.0,<2.0"]

[tool.uv.sources]
internal-pkg = { path = "../internal-pkg" }
"""
    )
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")

    attempt = backend.try_major("internal-pkg")
    assert attempt.skip_reason == "git/path/url/workspace source"


def test_uv_try_major_strips_upper_bound_and_uses_no_sync(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\ndependencies = ["six>=1.15.0,<1.16"]\n')
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "six"\nversion = "1.15.0"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject='[project]\nname = "x"\ndependencies = ["six>=1.15.0"]\n',
        after_lock='[[package]]\nname = "six"\nversion = "1.17.0"\n',
    )
    backend = UvBackend(runner, str(tmp_path), "3.12")

    attempt = backend.try_major("six")

    assert attempt.skip_reason is None
    assert attempt.resolve_result.ok
    add_call = runner.calls[0]
    assert add_call["args"][:2] == ["uv", "add"]
    assert add_call["args"][2] == "six>=1.15.0"
    assert "--no-sync" in add_call["args"]
    assert "--upgrade-package" in add_call["args"]
    # sync() is called explicitly afterwards, matching the project's own
    # selection args rather than whatever `uv add` would have chosen.
    assert runner.calls[-1]["args"][:2] == ["uv", "sync"]
    assert backend.locked_version("six") == "1.17.0"


def test_uv_try_major_uses_group_and_optional_flags(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "x"
dependencies = []

[dependency-groups]
dev = ["six>=1.15.0,<1.16"]
"""
    )
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "six"\nversion = "1.15.0"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject=(
            '[project]\nname = "x"\ndependencies = []\n\n'
            '[dependency-groups]\ndev = ["six>=1.15.0"]\n'
        ),
        after_lock='[[package]]\nname = "six"\nversion = "1.17.0"\n',
    )
    backend = UvBackend(runner, str(tmp_path), "3.12")

    attempt = backend.try_major("six")

    assert attempt.skip_reason is None
    add_call = runner.calls[0]
    assert "--group" in add_call["args"]
    assert add_call["args"][add_call["args"].index("--group") + 1] == "dev"


def test_uv_try_major_resolution_failure_is_reported(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\ndependencies = ["six>=1.15.0,<1.16"]\n')
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "six"\nversion = "1.15.0"\n')
    runner = _RewritingRunner(pyproject, lock, ok=False)
    backend = UvBackend(runner, str(tmp_path), "3.12")

    attempt = backend.try_major("six")

    assert attempt.skip_reason is None
    assert not attempt.resolve_result.ok


def test_major_files_to_stage_includes_manifest():
    poetry_backend = PoetryBackend(FakeCommandRunner(), ".", "2.4.3")
    assert poetry_backend.major_files_to_stage() == ["pyproject.toml", "poetry.lock"]

    uv_backend = UvBackend(FakeCommandRunner(), ".", "3.12")
    assert uv_backend.major_files_to_stage() == ["pyproject.toml", "uv.lock"]
