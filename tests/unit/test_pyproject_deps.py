import pytest

from updater.pyproject_deps import list_top_level_dependency_names, normalize_name


def write(tmp_path, text):
    path = tmp_path / "pyproject.toml"
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    "raw, normalized",
    [
        ("requests", "requests"),
        ("Requests", "requests"),
        ("My_Package.Name", "my-package-name"),
        ("some--weird...name__here", "some-weird-name-here"),
        ("FooBar", "foobar"),
    ],
)
def test_normalize_name(raw, normalized):
    assert normalize_name(raw) == normalized


def test_plain_project_dependencies(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["requests>=2,<3", "idna"]
        """,
    )
    assert list_top_level_dependency_names(path) == ["idna", "requests"]


def test_extras_and_specifiers_are_stripped(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["requests[socks]>=2,<3"]
        """,
    )
    assert list_top_level_dependency_names(path) == ["requests"]


def test_environment_markers_are_stripped(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["black>=24; python_version >= '3.9'"]
        """,
    )
    assert list_top_level_dependency_names(path) == ["black"]


def test_optional_dependencies_extras_are_included(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["idna"]

        [project.optional-dependencies]
        socks = ["pysocks"]
        speed = ["cchardet", "idna"]
        """,
    )
    assert list_top_level_dependency_names(path) == ["cchardet", "idna", "pysocks"]


def test_dependency_groups_are_included(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["idna"]

        [dependency-groups]
        dev = ["pytest>=7"]
        lint = ["ruff"]
        """,
    )
    assert list_top_level_dependency_names(path) == ["idna", "pytest", "ruff"]


def test_dependency_groups_include_group_entries_are_skipped_but_target_group_still_walked(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = []

        [dependency-groups]
        test = ["pytest"]
        dev = [{include-group = "test"}, "mypy"]
        """,
    )
    assert list_top_level_dependency_names(path) == ["mypy", "pytest"]


def test_legacy_tool_uv_dev_dependencies_are_included(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["idna"]

        [tool.uv]
        dev-dependencies = ["pytest"]
        """,
    )
    assert list_top_level_dependency_names(path) == ["idna", "pytest"]


def test_direct_url_dependency_is_skipped(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = [
            "idna",
            "mypkg @ https://example.com/mypkg-1.0-py3-none-any.whl",
        ]
        """,
    )
    assert list_top_level_dependency_names(path) == ["idna"]


@pytest.mark.parametrize("source_table", ["git", "path", "url", "workspace"])
def test_tool_uv_sources_git_path_url_workspace_are_skipped(tmp_path, source_table):
    value = "true" if source_table == "workspace" else '"somewhere"'
    path = write(
        tmp_path,
        f"""
        [project]
        name = "x"
        dependencies = ["idna", "internal-pkg"]

        [tool.uv.sources]
        internal-pkg = {{ {source_table} = {value} }}
        """,
    )
    assert list_top_level_dependency_names(path) == ["idna"]


def test_tool_uv_sources_index_is_not_skipped(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["idna", "torch"]

        [tool.uv.sources]
        torch = { index = "pytorch" }
        """,
    )
    assert list_top_level_dependency_names(path) == ["idna", "torch"]


def test_duplicates_across_sections_are_deduplicated(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["idna"]

        [project.optional-dependencies]
        extra = ["Idna"]

        [dependency-groups]
        dev = ["IDNA"]
        """,
    )
    assert list_top_level_dependency_names(path) == ["idna"]


def test_empty_pyproject_has_no_dependencies(tmp_path):
    path = write(tmp_path, "[project]\nname = \"x\"\n")
    assert list_top_level_dependency_names(path) == []
