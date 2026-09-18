from fakes import FakeGithubPR

from updater.github_pr import GithubPR, create_or_edit, parse_created_pr_number
from updater.runner import CommandResult


class _RecordingRunner:
    def __init__(self):
        self.calls: list[list] = []

    def run(self, args, cwd=None):
        self.calls.append(list(args))
        return CommandResult(list(args), 0, "[]", "")


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
    assert gh.edit_calls == [{"number": 42, "title": "title", "body": "body", "labels": []}]
    assert gh.create_calls == []


def test_create_or_edit_forwards_labels_to_edit():
    gh = FakeGithubPR(open_pr_number=42)

    create_or_edit(gh, "deps/branch", "title", "body", "main", ["dep", "automerge"])

    assert gh.edit_calls == [
        {
            "number": 42,
            "title": "title",
            "body": "body",
            "labels": ["dep", "automerge"],
        }
    ]


def test_edit_passes_add_label_for_each_label():
    runner = _RecordingRunner()
    gh = GithubPR(runner, ".")

    gh.edit(7, "title", "body", ["a", "b"])

    assert runner.calls[-1] == [
        "gh",
        "pr",
        "edit",
        "7",
        "--title",
        "title",
        "--body",
        "body",
        "--add-label",
        "a",
        "--add-label",
        "b",
    ]


def test_edit_omits_add_label_when_no_labels_given():
    runner = _RecordingRunner()
    gh = GithubPR(runner, ".")

    gh.edit(7, "title", "body")

    assert "--add-label" not in runner.calls[-1]


# --- parse_created_pr_number ------------------------------------------------


def test_parse_created_pr_number_from_url_only():
    stdout = "https://github.com/owner/repo/pull/42\n"
    assert parse_created_pr_number(stdout) == 42


def test_parse_created_pr_number_with_leading_lines_before_the_url():
    # A stray leading line (e.g. a warning) before the URL must not break
    # parsing - only the last line is expected to carry the URL.
    stdout = "Warning: 1 uncommitted change\nhttps://github.com/owner/repo/pull/42\n"
    assert parse_created_pr_number(stdout) == 42


def test_parse_created_pr_number_on_a_github_enterprise_server_host():
    stdout = "https://github.example.com/owner/repo/pull/99\n"
    assert parse_created_pr_number(stdout) == 99


def test_parse_created_pr_number_returns_none_when_no_url_is_present():
    assert parse_created_pr_number("no PR URL in this output\n") is None
    assert parse_created_pr_number("") is None
