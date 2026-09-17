import pytest

from updater.detect import detect_package_manager
from updater.errors import ActionError


def test_explicit_poetry_is_returned_without_touching_the_filesystem(tmp_path):
    # an empty directory has neither lock file; an explicit choice must
    # still be honoured
    assert detect_package_manager(str(tmp_path), "poetry") == "poetry"


def test_explicit_uv_is_returned_without_touching_the_filesystem(tmp_path):
    assert detect_package_manager(str(tmp_path), "uv") == "uv"


def test_explicit_choice_is_case_insensitive(tmp_path):
    assert detect_package_manager(str(tmp_path), "Poetry") == "poetry"
    assert detect_package_manager(str(tmp_path), "UV") == "uv"


def test_auto_detects_uv_from_uv_lock(tmp_path):
    (tmp_path / "uv.lock").write_text("")
    assert detect_package_manager(str(tmp_path), "auto") == "uv"


def test_auto_detects_poetry_from_poetry_lock(tmp_path):
    (tmp_path / "poetry.lock").write_text("")
    assert detect_package_manager(str(tmp_path), "auto") == "poetry"


def test_empty_input_defaults_to_auto(tmp_path):
    (tmp_path / "poetry.lock").write_text("")
    assert detect_package_manager(str(tmp_path), "") == "poetry"


def test_auto_raises_when_both_lock_files_are_present(tmp_path):
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "poetry.lock").write_text("")
    with pytest.raises(ActionError):
        detect_package_manager(str(tmp_path), "auto")


def test_auto_raises_when_neither_lock_file_is_present(tmp_path):
    with pytest.raises(ActionError):
        detect_package_manager(str(tmp_path), "auto")


def test_invalid_choice_raises():
    with pytest.raises(ActionError):
        detect_package_manager(".", "pipenv")
