import pytest

from updater.errors import ActionError
from updater.groups import (
    check_group_selection,
    check_known_groups,
    poetry_group_args,
    poetry_known_groups,
    uv_group_sync_args,
    uv_known_groups,
)


def write(tmp_path, text):
    path = tmp_path / "pyproject.toml"
    path.write_text(text)
    return path


# --- check_group_selection (mutual exclusivity, pure) ------------------------


def test_only_groups_alone_is_fine():
    check_group_selection([], [], ["docs"])


def test_with_and_without_together_is_fine():
    check_group_selection(["docs"], ["dev"], [])


def test_only_groups_with_with_groups_raises():
    with pytest.raises(ActionError):
        check_group_selection(["docs"], [], ["dev"])


def test_only_groups_with_without_groups_raises():
    with pytest.raises(ActionError):
        check_group_selection([], ["docs"], ["dev"])


def test_no_groups_at_all_is_fine():
    check_group_selection([], [], [])


# --- poetry_known_groups / uv_known_groups ------------------------------------


def test_poetry_known_groups_includes_main_and_declared_groups():
    data = {
        "tool": {"poetry": {"group": {"dev": {}, "docs": {}}, "dev-dependencies": {"idna": "*"}}}
    }
    assert poetry_known_groups(data, "2.4.3") == {"main", "dev", "docs"}


def test_poetry_known_groups_includes_pep735_dependency_groups_when_supported():
    data = {"dependency-groups": {"test": ["pytest"]}}
    assert poetry_known_groups(data, "2.2.0") == {"main", "test"}
    assert poetry_known_groups(data, "2.4.3") == {"main", "test"}


def test_poetry_known_groups_excludes_pep735_dependency_groups_when_too_old():
    """PEP 735 [dependency-groups] support was added in Poetry 2.2.0 (see
    groups.py's own citation) - verified empirically too, against real
    poetry==2.1.4 (does not see it at all) vs poetry==2.2.0 (does)."""
    data = {"dependency-groups": {"test": ["pytest"]}}
    assert poetry_known_groups(data, "2.1.4") == {"main"}
    assert poetry_known_groups(data, "2.1.3") == {"main"}
    assert poetry_known_groups(data, "1.8.3") == {"main"}
    assert poetry_known_groups(data, "") == {"main"}


def test_poetry_known_groups_is_just_main_for_a_plain_project():
    assert poetry_known_groups({}, "2.4.3") == {"main"}


def test_uv_known_groups_includes_main_dependency_groups_and_legacy_dev():
    data = {
        "dependency-groups": {"docs": ["mkdocs"]},
        "tool": {"uv": {"dev-dependencies": ["pytest"]}},
    }
    assert uv_known_groups(data) == {"main", "docs", "dev"}


def test_uv_known_groups_is_just_main_for_a_plain_project():
    assert uv_known_groups({}) == {"main"}


# --- check_known_groups (fail fast, reads pyproject.toml) --------------------


def test_check_known_groups_noop_when_nothing_requested(tmp_path):
    # No file at all, and no requested groups - must not even try to read.
    check_known_groups("poetry", str(tmp_path), [], [], [])


def test_check_known_groups_accepts_known_poetry_groups(tmp_path):
    write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = []

        [tool.poetry.group.dev.dependencies]
        idna = "*"
        """,
    )
    check_known_groups("poetry", str(tmp_path), [], ["dev"], [])
    check_known_groups("poetry", str(tmp_path), [], ["main"], [])


def test_check_known_groups_rejects_unknown_poetry_group(tmp_path):
    write(tmp_path, '[project]\nname = "x"\ndependencies = []\n')
    with pytest.raises(ActionError, match="unknown dependency group"):
        check_known_groups("poetry", str(tmp_path), [], [], ["doesnotexist"])


def test_check_known_groups_accepts_pep735_group_with_a_new_enough_poetry_version(tmp_path):
    write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = []

        [dependency-groups]
        test = ["pytest"]
        """,
    )
    check_known_groups("poetry", str(tmp_path), [], [], ["test"], poetry_version="2.2.0")
    check_known_groups("poetry", str(tmp_path), [], [], ["test"], poetry_version="2.4.3")


def test_check_known_groups_rejects_pep735_group_with_too_old_a_poetry_version(tmp_path):
    write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = []

        [dependency-groups]
        test = ["pytest"]
        """,
    )
    with pytest.raises(ActionError, match="poetry-version >= 2.2") as excinfo:
        check_known_groups("poetry", str(tmp_path), [], [], ["test"], poetry_version="2.1.4")
    assert "test" in str(excinfo.value)
    assert "[dependency-groups]" in str(excinfo.value)


def test_check_known_groups_pep735_version_gate_does_not_affect_uv(tmp_path):
    """poetry_version is only ever consulted for the poetry backend - a
    [dependency-groups] name is always valid for uv regardless of it."""
    write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = []

        [dependency-groups]
        test = ["pytest"]
        """,
    )
    check_known_groups("uv", str(tmp_path), [], [], ["test"], poetry_version="1.0.0")


def test_check_known_groups_accepts_known_uv_groups(tmp_path):
    write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = []

        [dependency-groups]
        docs = ["mkdocs"]
        """,
    )
    check_known_groups("uv", str(tmp_path), ["docs"], [], [])


def test_check_known_groups_rejects_unknown_uv_group(tmp_path):
    write(tmp_path, '[project]\nname = "x"\ndependencies = []\n')
    with pytest.raises(ActionError, match="unknown dependency group"):
        check_known_groups("uv", str(tmp_path), [], [], ["nope"])


def test_check_known_groups_missing_pyproject_is_not_this_functions_job(tmp_path):
    # Let the ordinary "manifest not found" checks elsewhere report this -
    # must not raise here.
    check_known_groups("poetry", str(tmp_path), [], [], ["dev"])


# --- poetry_group_args ---------------------------------------------------------


def test_poetry_group_args_empty_when_nothing_set():
    assert poetry_group_args([], [], []) == []


def test_poetry_group_args_with_and_without():
    assert poetry_group_args(["docs"], ["dev"], []) == [
        "--with",
        "docs",
        "--without",
        "dev",
    ]


def test_poetry_group_args_only_wins_over_with_and_without():
    assert poetry_group_args(["docs"], ["dev"], ["test"]) == ["--only", "test"]


def test_poetry_group_args_only_multiple():
    assert poetry_group_args([], [], ["dev", "docs"]) == ["--only", "dev", "--only", "docs"]


def test_poetry_group_args_main_passes_through_unchanged():
    assert poetry_group_args([], ["main"], []) == ["--without", "main"]
    assert poetry_group_args([], [], ["main"]) == ["--only", "main"]


# --- uv_group_sync_args ---------------------------------------------------------


def test_uv_group_sync_args_none_when_nothing_set():
    assert uv_group_sync_args([], [], []) is None


def test_uv_group_sync_args_with_and_without():
    assert uv_group_sync_args(["docs"], ["dev"], []) == ["--group", "docs", "--no-group", "dev"]


def test_uv_group_sync_args_skips_main_in_with_groups():
    assert uv_group_sync_args(["main"], [], []) == []


def test_uv_group_sync_args_skips_main_in_without_groups():
    # main can't be excluded from uv sync's own selection - see the
    # ::warning:: UvBackend._selection_args prints for this case.
    assert uv_group_sync_args([], ["main"], []) == []


def test_uv_group_sync_args_only_custom_groups_maps_to_only_group():
    assert uv_group_sync_args([], [], ["docs", "dev"]) == [
        "--only-group",
        "docs",
        "--only-group",
        "dev",
    ]


def test_uv_group_sync_args_only_with_main_uses_no_default_groups():
    assert uv_group_sync_args([], [], ["main"]) == ["--no-default-groups"]
    assert uv_group_sync_args([], [], ["main", "docs"]) == [
        "--no-default-groups",
        "--group",
        "docs",
    ]
