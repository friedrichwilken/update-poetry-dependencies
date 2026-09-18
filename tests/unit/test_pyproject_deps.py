import pytest

from updater.pyproject_deps import (
    find_pep_declaration,
    has_uv_conflicts,
    list_top_level_dependency_names,
    normalize_name,
    parse_requirement,
)


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


def test_dependency_groups_include_group_entries_are_skipped_but_target_group_still_walked(
    tmp_path,
):
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
    path = write(tmp_path, '[project]\nname = "x"\n')
    assert list_top_level_dependency_names(path) == []


def test_has_uv_conflicts_false_when_absent(tmp_path):
    path = write(tmp_path, '[project]\nname = "x"\n')
    assert has_uv_conflicts(path) is False


def test_has_uv_conflicts_false_when_empty(tmp_path):
    path = write(tmp_path, '[project]\nname = "x"\n\n[tool.uv]\nconflicts = []\n')
    assert has_uv_conflicts(path) is False


def test_has_uv_conflicts_true_when_declared(tmp_path):
    path = write(
        tmp_path,
        """
        [project]
        name = "x"

        [tool.uv]
        conflicts = [[{extra = "cpu"}, {extra = "gpu"}]]
        """,
    )
    assert has_uv_conflicts(path) is True


# --- parse_requirement --------------------------------------------------


def test_parse_requirement_plain():
    parsed = parse_requirement("idna")
    assert parsed.name == "idna"
    assert parsed.extras == ()
    assert parsed.specifier_text == ""
    assert parsed.marker is None
    assert parsed.is_direct_reference is False


def test_parse_requirement_with_extras_and_specifier():
    parsed = parse_requirement("requests[socks,security]>=2.28.0,<3.0")
    assert parsed.name == "requests"
    assert parsed.extras == ("socks", "security")
    assert parsed.specifier_text == ">=2.28.0,<3.0"


def test_parse_requirement_with_parenthesized_specifier():
    """Poetry's own PEP 621 `[project.dependencies]` writes the specifier
    wrapped in parens, e.g. `idna (>=3.4,<4.0)`."""
    parsed = parse_requirement("idna (>=3.4,<4.0)")
    assert parsed.name == "idna"
    assert parsed.specifier_text == ">=3.4,<4.0"


def test_parse_requirement_with_marker():
    parsed = parse_requirement("black>=24; python_version >= '3.9'")
    assert parsed.name == "black"
    assert parsed.specifier_text == ">=24"
    assert parsed.marker == "python_version >= '3.9'"


def test_parse_requirement_direct_reference():
    parsed = parse_requirement("mypkg @ https://example.com/mypkg-1.0-py3-none-any.whl")
    assert parsed.name == "mypkg"
    assert parsed.is_direct_reference is True
    assert parsed.specifier_text == ""


def test_parse_requirement_empty_is_none():
    assert parse_requirement("") is None
    assert parse_requirement("   ") is None


# --- find_pep_declaration ------------------------------------------------


def test_find_pep_declaration_in_main_dependencies():
    data = {"project": {"dependencies": ["idna>=3.4,<4.0", "six>=1.15.0,<2.0"]}}
    decl = find_pep_declaration(data, "six")
    assert decl.table == "dependencies"
    assert decl.group is None
    assert decl.index == 1
    assert decl.parsed.specifier_text == ">=1.15.0,<2.0"


def test_find_pep_declaration_in_optional_dependencies():
    data = {
        "project": {
            "dependencies": [],
            "optional-dependencies": {"http": ["requests[socks]>=2.28.0,<3.0"]},
        }
    }
    decl = find_pep_declaration(data, "requests")
    assert decl.table == "optional-dependencies"
    assert decl.group == "http"
    assert decl.parsed.extras == ("socks",)


def test_find_pep_declaration_in_dependency_groups():
    data = {"project": {"dependencies": []}, "dependency-groups": {"dev": ["pytest>=7,<8"]}}
    decl = find_pep_declaration(data, "pytest")
    assert decl.table == "dependency-groups"
    assert decl.group == "dev"


def test_find_pep_declaration_skips_include_group_entries():
    data = {
        "project": {"dependencies": []},
        "dependency-groups": {"dev": [{"include-group": "test"}, "mypy>=1.0"]},
    }
    decl = find_pep_declaration(data, "mypy")
    assert decl.table == "dependency-groups"
    assert decl.group == "dev"


def test_find_pep_declaration_in_legacy_tool_uv_dev_dependencies():
    data = {
        "project": {"dependencies": []},
        "tool": {"uv": {"dev-dependencies": ["pytest>=7,<8"]}},
    }
    decl = find_pep_declaration(data, "pytest")
    assert decl.table == "tool.uv.dev-dependencies"
    assert decl.group is None


def test_find_pep_declaration_normalizes_name():
    data = {"project": {"dependencies": ["My_Package>=1.0,<2.0"]}}
    decl = find_pep_declaration(data, "my-package")
    assert decl is not None
    assert decl.parsed.name == "My_Package"


def test_find_pep_declaration_returns_none_when_absent():
    data = {"project": {"dependencies": ["idna>=3.4,<4.0"]}}
    assert find_pep_declaration(data, "nonexistent") is None


# --- list_top_level_dependency_names group filtering (issue #4) --------------


def _write_grouped(tmp_path):
    return write(
        tmp_path,
        """
        [project]
        name = "x"
        dependencies = ["six"]

        [project.optional-dependencies]
        cpu = ["numpy"]

        [dependency-groups]
        dev = ["idna"]
        docs = ["zipp"]

        [tool.uv]
        dev-dependencies = ["legacydev"]
        """,
    )


def test_group_filter_default_includes_everything(tmp_path):
    path = _write_grouped(tmp_path)
    assert list_top_level_dependency_names(path) == [
        "idna",
        "legacydev",
        "numpy",
        "six",
        "zipp",
    ]


def test_without_groups_excludes_named_group_but_keeps_extras(tmp_path):
    path = _write_grouped(tmp_path)
    names = list_top_level_dependency_names(path, without_groups=("dev",))
    assert "idna" not in names
    assert "legacydev" not in names  # tool.uv.dev-dependencies is also "dev"
    assert "numpy" in names  # an extra - never filtered by groups
    assert "six" in names
    assert "zipp" in names


def test_without_groups_main_excludes_plain_dependencies(tmp_path):
    path = _write_grouped(tmp_path)
    names = list_top_level_dependency_names(path, without_groups=("main",))
    assert "six" not in names
    assert "idna" in names


def test_only_groups_restricts_to_named_groups_plus_extras(tmp_path):
    path = _write_grouped(tmp_path)
    names = list_top_level_dependency_names(path, only_groups=("docs",))
    assert names == ["numpy", "zipp"]  # extras (numpy) are always included


def test_only_groups_main_restricts_to_plain_dependencies_plus_extras(tmp_path):
    path = _write_grouped(tmp_path)
    names = list_top_level_dependency_names(path, only_groups=("main",))
    assert names == ["numpy", "six"]


def test_with_groups_alone_has_no_effect_on_listing(tmp_path):
    """Every group is already iterated by default (unlike Poetry's own
    optional groups), so with_groups has nothing left to add - see
    list_top_level_dependency_names's own docstring."""
    path = _write_grouped(tmp_path)
    assert list_top_level_dependency_names(
        path, with_groups=("docs",)
    ) == list_top_level_dependency_names(path)
