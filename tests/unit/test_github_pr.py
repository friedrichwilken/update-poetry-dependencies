from fakes import FakeGithubPR

from poetry_update.github_pr import create_or_edit


def test_create_or_edit_creates_when_no_open_pr():
    gh = FakeGithubPR(open_pr_number=None)

    existing, _ = create_or_edit(gh, "deps/branch", "title", "body", "main", ["dep"])

    assert existing is None
    assert len(gh.create_calls) == 1
    assert gh.create_calls[0] == {
        "title": "title",
        "body": "body",
        "base": "main",
        "head": "deps/branch",
        "labels": ["dep"],
    }
    assert gh.edit_calls == []


def test_create_or_edit_edits_when_open_pr_exists():
    gh = FakeGithubPR(open_pr_number=42)

    existing, _ = create_or_edit(gh, "deps/branch", "title", "body", "main", [])

    assert existing == 42
    assert gh.edit_calls == [{"number": 42, "title": "title", "body": "body"}]
    assert gh.create_calls == []
