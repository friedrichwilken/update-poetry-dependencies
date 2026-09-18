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


# --- update_all / all_locked_versions (batch-first strategy, issue #23) -


def test_uv_backend_update_all_upgrades_every_package_in_one_lock_call_then_syncs():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12")

    backend.update_all(["idna", "six"])

    assert runner.calls[0] == {
        "args": [
            "uv",
            "lock",
            "--upgrade-package",
            "idna",
            "--upgrade-package",
            "six",
            "--python",
            "3.12",
        ],
        "cwd": "some/dir",
    }
    assert runner.calls[1]["args"][:2] == ["uv", "sync"]


def test_uv_backend_update_all_does_not_sync_when_lock_fails():
    runner = FakeCommandRunner(results=[result(False, stderr="boom")])
    backend = UvBackend(runner, "some/dir", "3.12")

    update_result = backend.update_all(["idna", "six"])

    assert not update_result.ok
    assert len(runner.calls) == 1


def test_uv_backend_update_all_with_no_packages_still_locks_and_syncs():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12")

    backend.update_all([])

    assert runner.calls[0]["args"] == ["uv", "lock", "--python", "3.12"]


def test_poetry_backend_update_all_updates_every_package_in_one_call():
    runner = FakeCommandRunner()
    backend = PoetryBackend(runner, "some/dir", "2.4.3")

    backend.update_all(["idna", "six"])

    assert runner.calls == [
        {
            "args": ["poetry", "update", "idna", "six", "--no-interaction"],
            "cwd": "some/dir",
        }
    ]


def test_uv_backend_all_locked_versions_reads_every_package(tmp_path):
    (tmp_path / "uv.lock").write_text(
        """
        [[package]]
        name = "idna"
        version = "3.4"

        [[package]]
        name = "six"
        version = "1.15.0"
        """
    )
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")

    assert backend.all_locked_versions() == {"idna": "3.4", "six": "1.15.0"}


def test_poetry_backend_all_locked_versions_reads_every_package(tmp_path):
    (tmp_path / "poetry.lock").write_text(
        """
        [[package]]
        name = "idna"
        version = "3.4"

        [[package]]
        name = "six"
        version = "1.15.0"
        """
    )
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.4.3")

    assert backend.all_locked_versions() == {"idna": "3.4", "six": "1.15.0"}


def test_all_locked_versions_missing_lock_file_returns_empty_dict(tmp_path):
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12")
    assert backend.all_locked_versions() == {}


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
        with_groups = ""
        without_groups = ""
        only_groups = ""

    backend = make_backend("poetry", FakeCommandRunner(), Cfg())
    assert isinstance(backend, PoetryBackend)


def test_make_backend_returns_uv_backend():
    class Cfg:
        directory = "."
        poetry_version = "2.1.3"
        python_version = "3.12.7"
        uv_sync_args = ""
        with_groups = ""
        without_groups = ""
        only_groups = ""

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
        with_groups = ""
        without_groups = ""
        only_groups = ""

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
    attempt must be discarded via `discarded_reason` (never surfaced as a
    resolution failure_kind) - but the tool call itself is still reported
    as having succeeded, since it did."""
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
    assert attempt.resolve_result.ok
    assert attempt.discarded_reason == "manifest changed beyond the version constraint"


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


def test_uv_sync_conflicts_warning_is_only_printed_once_per_backend(tmp_path, capsys):
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
    backend = UvBackend(runner, str(tmp_path), "3.12")

    backend.sync()
    backend.sync()
    backend.sync()

    out = capsys.readouterr().out
    assert out.count("::warning::") == 1


# --- Review fixes: optional=true, pre-release discard, OR constraints ---


def test_poetry_try_major_passes_optional_flag_for_legacy_optional_dependency(tmp_path):
    """Verified against real poetry==2.4.3: `poetry add pkg@latest` drops
    an existing `optional = true` entirely unless told which extra it
    belongs to via `--optional <extra>` - so the plan must always pass it
    when the table entry is optional."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
        [tool.poetry.dependencies]
        requests = { version = "^2.28.0", extras = ["socks"], optional = true }

        [tool.poetry.extras]
        http = ["requests"]
        """
    )
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "requests"\nversion = "2.28.0"\n')
    after_pyproject = (
        "[tool.poetry.dependencies]\n"
        'requests = { version = "^3.0.0", extras = ["socks"], optional = true }\n\n'
        "[tool.poetry.extras]\n"
        'http = ["requests"]\n'
    )
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject=after_pyproject,
        after_lock='[[package]]\nname = "requests"\nversion = "3.0.0"\n',
    )
    backend = PoetryBackend(runner, str(tmp_path), "2.4.3")

    attempt = backend.try_major("requests")

    assert runner.calls[0]["args"] == [
        "poetry",
        "add",
        "requests[socks]@latest",
        "-n",
        "--optional",
        "http",
    ]
    assert attempt.skip_reason is None
    assert attempt.discarded_reason is None
    assert attempt.resolve_result.ok


def test_poetry_try_major_skips_optional_dependency_with_no_matching_extra(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.poetry.dependencies]\nrequests = { version = "^2.28.0", optional = true }\n'
    )
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.4.3")

    attempt = backend.try_major("requests")

    assert attempt.skip_reason == "optional dependency not listed in any [tool.poetry.extras] entry"


def test_poetry_try_major_discards_a_prerelease_attempt(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.poetry.dependencies]\nsix = "^1.15.0"\n')
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "six"\nversion = "1.15.0"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject='[tool.poetry.dependencies]\nsix = "^2.0.0a1"\n',
        after_lock='[[package]]\nname = "six"\nversion = "2.0.0a1"\n',
    )
    backend = PoetryBackend(runner, str(tmp_path), "2.4.3")

    attempt = backend.try_major("six")

    assert attempt.skip_reason is None
    assert attempt.resolve_result.ok
    assert attempt.discarded_reason == "attempted version is a pre-release"


def test_poetry_try_major_does_not_discard_when_already_on_a_prerelease(tmp_path):
    """A project that was already tracking a pre-release itself should not
    be penalized for landing on another one."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.poetry.dependencies]\nsix = "^2.0.0a1"\n')
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "six"\nversion = "2.0.0a1"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject='[tool.poetry.dependencies]\nsix = "^2.0.0a2"\n',
        after_lock='[[package]]\nname = "six"\nversion = "2.0.0a2"\n',
    )
    backend = PoetryBackend(runner, str(tmp_path), "2.4.3")

    attempt = backend.try_major("six")

    assert attempt.discarded_reason is None
    assert attempt.resolve_result.ok


def test_poetry_try_major_or_constraint_not_needed_when_an_alternative_is_open(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.poetry.dependencies]\nsix = ">=1.0,<2.0 || >=3.0"\n')
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.4.3")

    assert backend.try_major("six") is None


def test_poetry_try_major_or_constraint_all_bounded_is_skipped(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.poetry.dependencies]\nsix = ">=1.0,<2.0 || >=3.0,<4.0"\n')
    backend = PoetryBackend(FakeCommandRunner(), str(tmp_path), "2.4.3")

    attempt = backend.try_major("six")

    assert attempt.skip_reason == "unsupported constraint syntax"


def test_uv_try_major_discards_a_prerelease_attempt(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\ndependencies = ["six>=1.15.0,<1.16"]\n')
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "six"\nversion = "1.15.0"\n')
    runner = _RewritingRunner(
        pyproject,
        lock,
        after_pyproject='[project]\nname = "x"\ndependencies = ["six>=1.15.0"]\n',
        after_lock='[[package]]\nname = "six"\nversion = "2.0.0a1"\n',
    )
    backend = UvBackend(runner, str(tmp_path), "3.12")

    attempt = backend.try_major("six")

    assert attempt.skip_reason is None
    assert attempt.resolve_result.ok
    assert attempt.discarded_reason == "attempted version is a pre-release"


# --- with-groups/without-groups/only-groups threading (issue #4) -------------


def test_poetry_backend_list_top_level_packages_passes_group_flags():
    runner = FakeCommandRunner()
    backend = PoetryBackend(
        runner, "some/dir", "2.4.3", with_groups=["docs"], without_groups=["dev"]
    )

    backend.list_top_level_packages()

    assert runner.calls[0]["args"] == [
        "poetry",
        "show",
        "--top-level",
        "--with",
        "docs",
        "--without",
        "dev",
    ]


def test_poetry_backend_list_top_level_packages_no_flags_by_default():
    runner = FakeCommandRunner()
    backend = PoetryBackend(runner, "some/dir", "2.4.3")

    backend.list_top_level_packages()

    assert runner.calls[0]["args"] == ["poetry", "show", "--top-level"]


def test_poetry_backend_install_passes_only_groups_flag():
    runner = FakeCommandRunner()
    backend = PoetryBackend(runner, "some/dir", "2.4.3", only_groups=["dev"])

    backend.install()

    assert runner.calls[0]["args"] == ["poetry", "install", "--only", "dev"]


def test_poetry_backend_sync_passes_group_flags():
    runner = FakeCommandRunner()
    backend = PoetryBackend(runner, "some/dir", "2.4.3", without_groups=["dev"])

    backend.sync()

    assert runner.calls[0]["args"] == ["poetry", "sync", "--without", "dev"]


def test_poetry_backend_update_package_and_update_all_ignore_group_flags():
    """A named package's own update is not restricted by group selection -
    see PoetryBackend._group_args's own docstring."""
    runner = FakeCommandRunner()
    backend = PoetryBackend(runner, "some/dir", "2.4.3", only_groups=["dev"])

    backend.update_package("idna")
    backend.update_all(["idna", "six"])

    assert runner.calls[0]["args"] == ["poetry", "update", "idna", "--no-interaction"]
    assert runner.calls[1]["args"] == ["poetry", "update", "idna", "six", "--no-interaction"]


def test_uv_backend_list_top_level_packages_applies_without_groups(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "x"
        dependencies = ["six"]

        [dependency-groups]
        dev = ["idna"]
        """
    )
    backend = UvBackend(FakeCommandRunner(), str(tmp_path), "3.12", without_groups=["dev"])

    assert backend.list_top_level_packages() == ["six"]


def test_uv_backend_sync_switches_to_native_default_when_a_group_input_is_set():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12", with_groups=["docs"])

    backend.sync()

    assert runner.calls[0]["args"] == [
        "uv",
        "sync",
        "--locked",
        "--group",
        "docs",
        "--all-extras",
        "--python",
        "3.12",
    ]


def test_uv_backend_sync_only_groups_maps_to_only_group_flags():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12", only_groups=["dev", "docs"])

    backend.sync()

    assert runner.calls[0]["args"] == [
        "uv",
        "sync",
        "--locked",
        "--only-group",
        "dev",
        "--only-group",
        "docs",
        "--all-extras",
        "--python",
        "3.12",
    ]


def test_uv_backend_sync_without_main_warns_but_still_installs_main(capsys):
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12", without_groups=["main"])

    backend.sync()

    assert "--no-group" not in runner.calls[0]["args"]
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "without-groups" in out


def test_uv_backend_sync_uv_sync_args_wins_even_with_group_inputs_set():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12", uv_sync_args="--extra cpu", only_groups=["dev"])

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


def test_uv_backend_sync_default_unaffected_when_no_group_input_is_set():
    """Byte-compat: with none of with-groups/without-groups/only-groups
    set, sync's selection is exactly what it was before issue #4."""
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12")

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


def test_make_backend_threads_group_inputs_through_to_the_backend():
    class Cfg:
        directory = "."
        poetry_version = "2.1.3"
        python_version = "3.12.7"
        uv_sync_args = ""
        with_groups = "docs"
        without_groups = "dev"
        only_groups = ""

    backend = make_backend("poetry", FakeCommandRunner(), Cfg())
    assert backend.with_groups == ["docs"]
    assert backend.without_groups == ["dev"]


# --- update_transitive (update-transitive, issue #24) -------------------------


def test_poetry_backend_update_transitive_locks_only_then_syncs():
    runner = FakeCommandRunner()
    backend = PoetryBackend(runner, "some/dir", "2.4.3")

    backend.update_transitive()

    assert runner.calls[0]["args"] == ["poetry", "update", "--lock", "--no-interaction"]
    assert runner.calls[1]["args"][:2] == ["poetry", "sync"]


def test_poetry_backend_update_transitive_does_not_sync_when_lock_fails():
    runner = FakeCommandRunner(results=[result(False, stderr="boom")])
    backend = PoetryBackend(runner, "some/dir", "2.4.3")

    update_result = backend.update_transitive()

    assert not update_result.ok
    assert len(runner.calls) == 1


def test_poetry_backend_update_transitive_ignores_group_flags():
    """Deliberately refreshes the whole lock within its existing
    constraints, same scope as a plain `poetry update` - see the
    backend's own docstring."""
    runner = FakeCommandRunner()
    backend = PoetryBackend(runner, "some/dir", "2.4.3", only_groups=["dev"])

    backend.update_transitive()

    assert runner.calls[0]["args"] == ["poetry", "update", "--lock", "--no-interaction"]


def test_uv_backend_update_transitive_upgrades_then_syncs():
    runner = FakeCommandRunner()
    backend = UvBackend(runner, "some/dir", "3.12")

    backend.update_transitive()

    assert runner.calls[0] == {
        "args": ["uv", "lock", "--upgrade", "--python", "3.12"],
        "cwd": "some/dir",
    }
    assert runner.calls[1]["args"][:2] == ["uv", "sync"]


def test_uv_backend_update_transitive_does_not_sync_when_lock_fails():
    runner = FakeCommandRunner(results=[result(False, stderr="boom")])
    backend = UvBackend(runner, "some/dir", "3.12")

    update_result = backend.update_transitive()

    assert not update_result.ok
    assert len(runner.calls) == 1
