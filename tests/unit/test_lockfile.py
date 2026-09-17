from pathlib import Path

from updater.lockfile import locked_version

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixture"


def test_locked_version_reads_from_real_poetry_lock_fixture():
    lock = FIXTURE_ROOT / "poetry" / "poetry.lock"
    assert locked_version(lock, "idna") == "3.4"
    assert locked_version(lock, "six") == "1.15.0"


def test_locked_version_reads_from_real_uv_lock_fixture():
    lock = FIXTURE_ROOT / "uv" / "uv.lock"
    assert locked_version(lock, "idna") == "3.4"
    assert locked_version(lock, "six") == "1.15.0"


def test_locked_version_returns_none_when_package_missing(tmp_path):
    lock = tmp_path / "poetry.lock"
    lock.write_text(
        """
        [[package]]
        name = "idna"
        version = "3.4"
        """
    )
    assert locked_version(lock, "nonexistent") is None


def test_locked_version_returns_none_when_lock_file_missing(tmp_path):
    assert locked_version(tmp_path / "does-not-exist.lock", "idna") is None


def test_locked_version_returns_none_for_unparsable_lock_file(tmp_path):
    lock = tmp_path / "poetry.lock"
    lock.write_text("this is not [ valid toml")
    assert locked_version(lock, "idna") is None


def test_locked_version_normalizes_package_name_pep503(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text(
        """
        [[package]]
        name = "My.Cool_Package"
        version = "1.2.3"
        """
    )
    assert locked_version(lock, "my-cool-package") == "1.2.3"
    assert locked_version(lock, "My_Cool.Package") == "1.2.3"


def test_locked_version_joins_multiple_distinct_versions_sorted(tmp_path):
    """uv can record more than one [[package]] entry for the same
    normalized name (e.g. distinct forks per environment marker); every
    distinct version found should be reported, not just one arbitrarily."""
    lock = tmp_path / "uv.lock"
    lock.write_text(
        """
        [[package]]
        name = "numpy"
        version = "2.0.0"

        [[package]]
        name = "numpy"
        version = "1.26.0"
        """
    )
    assert locked_version(lock, "numpy") == "1.26.0, 2.0.0"


def test_locked_version_deduplicates_identical_versions_across_entries(tmp_path):
    lock = tmp_path / "poetry.lock"
    lock.write_text(
        """
        [[package]]
        name = "requests"
        version = "2.31.0"

        [[package]]
        name = "requests"
        version = "2.31.0"
        """
    )
    assert locked_version(lock, "requests") == "2.31.0"
