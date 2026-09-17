from updater.poetry_manifest import (
    constraint_text,
    extras_of,
    find_extra_for_optional,
    find_poetry_table_declaration,
    is_optional,
    normalized_extra_fields,
    unsupported_key,
)


def test_find_poetry_table_declaration_in_main_dependencies():
    data = {"tool": {"poetry": {"dependencies": {"six": "^1.15.0"}}}}
    decl = find_poetry_table_declaration(data, "six")
    assert decl.table == "tool.poetry.dependencies"
    assert decl.group is None
    assert decl.name == "six"
    assert decl.value == "^1.15.0"


def test_find_poetry_table_declaration_in_group():
    data = {
        "tool": {
            "poetry": {
                "dependencies": {},
                "group": {"dev": {"dependencies": {"pytest": "^7.0"}}},
            }
        }
    }
    decl = find_poetry_table_declaration(data, "pytest")
    assert decl.table == "tool.poetry.group.dependencies"
    assert decl.group == "dev"


def test_find_poetry_table_declaration_in_legacy_dev_dependencies():
    data = {"tool": {"poetry": {"dependencies": {}, "dev-dependencies": {"pytest": "^7.0"}}}}
    decl = find_poetry_table_declaration(data, "pytest")
    assert decl.table == "tool.poetry.dev-dependencies"
    assert decl.group == "dev"


def test_find_poetry_table_declaration_normalizes_name():
    data = {"tool": {"poetry": {"dependencies": {"My.Cool_Package": "^1.0"}}}}
    decl = find_poetry_table_declaration(data, "my-cool-package")
    assert decl is not None
    assert decl.name == "My.Cool_Package"


def test_find_poetry_table_declaration_returns_none_when_absent():
    data = {"tool": {"poetry": {"dependencies": {"six": "^1.15.0"}}}}
    assert find_poetry_table_declaration(data, "nonexistent") is None


def test_find_extra_for_optional():
    data = {"tool": {"poetry": {"extras": {"http": ["requests", "urllib3"]}}}}
    assert find_extra_for_optional(data, "requests") == "http"
    assert find_extra_for_optional(data, "Requests") == "http"
    assert find_extra_for_optional(data, "nonexistent") is None


def test_unsupported_key_detects_git_path_url_source_markers_python_platform():
    for key, value in [
        ("git", "https://example.com/repo.git"),
        ("path", "../local"),
        ("url", "https://example.com/pkg.whl"),
        ("source", "private"),
        ("markers", "sys_platform == 'win32'"),
        ("python", "<3.10"),
        ("platform", "linux"),
        ("allow-prereleases", True),
    ]:
        assert unsupported_key({"version": "^1.0", key: value}) == key


def test_unsupported_key_none_for_plain_entry():
    assert unsupported_key({"version": "^1.0", "extras": ["socks"], "optional": True}) is None
    assert unsupported_key("^1.0") is None


def test_constraint_text_from_string_and_table():
    assert constraint_text("^1.0") == "^1.0"
    assert constraint_text({"version": "^1.0"}) == "^1.0"
    assert constraint_text({"git": "https://example.com"}) is None


def test_extras_of():
    assert extras_of("^1.0") == ()
    assert extras_of({"version": "^1.0", "extras": ["socks"]}) == ("socks",)


def test_is_optional():
    assert is_optional("^1.0") is False
    assert is_optional({"version": "^1.0", "optional": True}) is True
    assert is_optional({"version": "^1.0"}) is False


def test_normalized_extra_fields_string_entries_are_equal():
    assert normalized_extra_fields("^1.0") == normalized_extra_fields("^2.0")


def test_normalized_extra_fields_detects_extras_change():
    before = {"version": "^1.0", "extras": ["socks"]}
    after = {"version": "^2.0", "extras": []}
    assert normalized_extra_fields(before) != normalized_extra_fields(after)


def test_normalized_extra_fields_ignores_version_only_change():
    before = {"version": "^1.0", "extras": ["socks"], "optional": True}
    after = {"version": "^2.0", "extras": ["socks"], "optional": True}
    assert normalized_extra_fields(before) == normalized_extra_fields(after)


def test_normalized_extra_fields_detects_new_key_appearing():
    before = {"version": "^1.0"}
    after = {"version": "^2.0", "markers": "sys_platform == 'win32'"}
    assert normalized_extra_fields(before) != normalized_extra_fields(after)
