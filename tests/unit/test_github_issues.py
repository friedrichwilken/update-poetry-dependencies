import json

import pytest
from fakes import FakeGithubIssues

from updater.errors import ActionError
from updater.github_issues import (
    _MANAGED_BY_FOOTER,
    GithubIssues,
    IssueAction,
    IssueTarget,
    ManagedIssue,
    execute_issue_actions,
    issue_actions_to_json,
    issue_target_for,
    parse_managed_issues,
    plan_issue_actions,
    render_issue_body,
    render_issue_title,
    run_issue_management,
    summarize_issue_actions,
)
from updater.runner import CommandResult
from updater.updater import PackageOutcome


class _RecordingRunner:
    def __init__(self, results: list | None = None):
        self._results = list(results or [])
        self.calls: list[list] = []

    def run(self, args, cwd=None):
        self.calls.append(list(args))
        if self._results:
            return self._results.pop(0)
        return CommandResult(list(args), 0, "[]", "")


def _outcome(**overrides) -> PackageOutcome:
    base = dict(name="pkg", status="updated")
    base.update(overrides)
    return PackageOutcome(**base)


def _managed_body(package: str, version: str = "", kind: str = "") -> str:
    """A realistic managed-issue body: all three of the pkg marker, the
    state marker, and the managed-by footer - what `render_issue_body`
    actually produces, and what `parse_managed_issues` now requires all
    three of (see item 3 of the follow-up review)."""
    return (
        f"<!-- test-gated-updates:pkg={package} -->\n"
        "some body text\n\n"
        f"{_MANAGED_BY_FOOTER}\n"
        f"<!-- test-gated-updates:state={version}|{kind} -->"
    )


# --- issue_target_for ----------------------------------------------------


def test_issue_target_for_failed_outcome():
    outcome = _outcome(
        status="failed",
        old_version="1.0.0",
        new_version="2.0.0",
        failure_kind="test",
        output_tail="boom",
    )
    target = issue_target_for(outcome)
    assert target == IssueTarget(
        package="pkg",
        held_back=False,
        old_version="1.0.0",
        attempted_version="2.0.0",
        failure_kind="test",
        output_tail="boom",
    )


def test_issue_target_for_held_back_outcome():
    outcome = _outcome(
        status="updated",
        old_version="1.0.0",
        new_version="1.1.0",
        beyond_constraint_version="2.0.0",
        beyond_constraint_failure_kind="resolution",
        beyond_constraint_output_tail="resolver blew up",
    )
    target = issue_target_for(outcome)
    assert target == IssueTarget(
        package="pkg",
        held_back=True,
        old_version="1.0.0",
        attempted_version="2.0.0",
        failure_kind="resolution",
        output_tail="resolver blew up",
    )


def test_issue_target_for_failed_wins_over_held_back():
    """A package whose beyond-constraint attempt AND in-range fallback both
    failed reports one target (the plain failure), not two."""
    outcome = _outcome(
        status="failed",
        old_version="1.0.0",
        new_version="1.1.0",
        failure_kind="test",
        output_tail="in-range failure output",
        beyond_constraint_version="2.0.0",
        beyond_constraint_failure_kind="resolution",
        beyond_constraint_output_tail="beyond-constraint failure output",
    )
    target = issue_target_for(outcome)
    assert target.held_back is False
    assert target.attempted_version == "1.1.0"
    assert target.output_tail == "in-range failure output"


def test_issue_target_for_updated_outcome_with_no_held_back_is_none():
    assert issue_target_for(_outcome(status="updated")) is None


def test_issue_target_for_skipped_outcome_is_none():
    assert issue_target_for(_outcome(status="skipped")) is None


# --- parse_managed_issues --------------------------------------------------


def test_parse_managed_issues_extracts_package_and_state():
    raw = [{"number": 42, "body": _managed_body("idna", version="4.0.0", kind="test")}]
    managed = parse_managed_issues(raw)
    assert managed == [
        ManagedIssue(number=42, package="idna", last_version="4.0.0", last_kind="test")
    ]


def test_parse_managed_issues_drops_issues_without_the_pkg_marker():
    raw = [{"number": 1, "body": "just a regular issue, unrelated"}]
    assert parse_managed_issues(raw) == []


def test_parse_managed_issues_requires_the_state_marker_too():
    """A pkg marker alone (no state marker) is not enough - item 3 of the
    follow-up review tightens identity to require all three markers/footer,
    since the pkg marker alone already proved too easy to false-positive
    on (see test_parse_managed_issues_ignores_documentation_placeholder_marker)."""
    raw = [
        {
            "number": 2,
            "body": f"<!-- test-gated-updates:pkg=six -->\n{_MANAGED_BY_FOOTER}",
        }
    ]
    assert parse_managed_issues(raw) == []


def test_parse_managed_issues_requires_the_managed_by_footer_too():
    raw = [
        {
            "number": 2,
            "body": "<!-- test-gated-updates:pkg=six -->\n<!-- test-gated-updates:state=|  -->",
        }
    ]
    assert parse_managed_issues(raw) == []


def test_parse_managed_issues_ignores_marker_mentioned_without_exact_prefix():
    raw = [{"number": 3, "body": "talking about test-gated-updates:pkg= in prose, not a comment"}]
    assert parse_managed_issues(raw) == []


def test_parse_managed_issues_ignores_documentation_placeholder_marker():
    """Regression test for a real false positive found by dry-running
    against this repo: issue #28 (the design issue for this very feature)
    quotes `<!-- test-gated-updates:pkg=<name> -->` in its body as a
    documentation example. Without validating the payload, that would be
    picked up as a real marker (package "<name>") and a live run would try
    to close issue #28 itself as "no longer failing"."""
    raw = [
        {
            "number": 28,
            "body": (
                "Identify via a hidden marker in the body "
                "(`<!-- test-gated-updates:pkg=<name> -->`), not via the title"
            ),
        }
    ]
    assert parse_managed_issues(raw) == []


def test_parse_managed_issues_ignores_documentation_placeholder_even_with_state_and_footer():
    """The stricter item-3 check (pkg + state + footer) does not weaken the
    item-3.5 normalized-name guard - a documentation issue that happened to
    also mention the other two markers verbatim (e.g. quoting this whole
    module's docstring) must still be rejected on the invalid pkg payload."""
    raw = [
        {
            "number": 29,
            "body": (
                "<!-- test-gated-updates:pkg=<name> -->\n"
                f"{_MANAGED_BY_FOOTER}\n"
                "<!-- test-gated-updates:state=<version>|<kind> -->"
            ),
        }
    ]
    assert parse_managed_issues(raw) == []


def test_parse_managed_issues_accepts_a_real_normalized_name():
    raw = [{"number": 4, "body": _managed_body("charset-normalizer")}]
    managed = parse_managed_issues(raw)
    assert len(managed) == 1
    assert managed[0].package == "charset-normalizer"


def test_parse_managed_issues_copy_pasted_body_is_accepted_edge_case():
    """Documented, accepted edge case (see README): copy-pasting a managed
    issue's entire body verbatim into an unrelated issue makes it managed
    too, since it then genuinely carries all three signals."""
    raw = [{"number": 5, "body": _managed_body("idna", version="4.0.0", kind="test")}]
    managed = parse_managed_issues(raw)
    assert len(managed) == 1


# --- plan_issue_actions: decision table ------------------------------------


def test_plan_creates_for_failed_package_with_no_existing_issue():
    outcomes = [_outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test")]
    actions = plan_issue_actions(outcomes, [])
    assert len(actions) == 1
    assert actions[0].package == "idna"
    assert actions[0].action == "create"
    assert actions[0].issue is None


def test_plan_updates_without_comment_when_nothing_changed():
    outcomes = [_outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test")]
    existing = [ManagedIssue(number=7, package="idna", last_version="4.0.0", last_kind="test")]
    actions = plan_issue_actions(outcomes, existing)
    assert len(actions) == 1
    assert actions[0].action == "update"
    assert actions[0].issue == 7
    assert actions[0].comment is False


def test_plan_updates_with_comment_when_version_changed():
    outcomes = [_outcome(name="idna", status="failed", new_version="5.0.0", failure_kind="test")]
    existing = [ManagedIssue(number=7, package="idna", last_version="4.0.0", last_kind="test")]
    actions = plan_issue_actions(outcomes, existing)
    assert actions[0].action == "update"
    assert actions[0].comment is True


def test_plan_updates_with_comment_when_kind_changed():
    outcomes = [
        _outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="resolution")
    ]
    existing = [ManagedIssue(number=7, package="idna", last_version="4.0.0", last_kind="test")]
    actions = plan_issue_actions(outcomes, existing)
    assert actions[0].action == "update"
    assert actions[0].comment is True


def test_plan_closes_managed_issue_whose_package_is_no_longer_failing():
    outcomes = [_outcome(name="idna", status="updated")]
    existing = [ManagedIssue(number=7, package="idna", last_version="4.0.0", last_kind="test")]
    actions = plan_issue_actions(outcomes, existing)
    assert len(actions) == 1
    assert actions[0] == IssueAction(package="idna", action="close", issue=7)


def test_plan_closes_managed_issue_for_package_no_longer_present_at_all():
    """The package dropped out of the outcome list entirely (no longer a
    top-level dependency) - still closed."""
    existing = [ManagedIssue(number=7, package="idna", last_version="4.0.0", last_kind="test")]
    actions = plan_issue_actions([], existing)
    assert actions == [IssueAction(package="idna", action="close", issue=7)]


def test_plan_creates_issue_for_held_back_package_even_though_status_is_updated():
    outcomes = [
        _outcome(
            name="charset-normalizer",
            status="updated",
            beyond_constraint_version="3.0.0",
            beyond_constraint_failure_kind="test",
        )
    ]
    actions = plan_issue_actions(outcomes, [])
    assert len(actions) == 1
    assert actions[0].action == "create"
    assert actions[0].target.held_back is True


def test_plan_never_touches_an_unrelated_open_issue():
    """An issue with no pkg marker never even reaches plan_issue_actions
    (see parse_managed_issues) - this proves the plan is empty when the
    "open_managed_issues" list passed in correctly excludes it."""
    outcomes = [_outcome(name="idna", status="updated")]
    actions = plan_issue_actions(outcomes, [])
    assert actions == []


def test_plan_normalizes_package_names():
    outcomes = [_outcome(name="Foo_Bar", status="failed", new_version="1.0", failure_kind="test")]
    existing = [ManagedIssue(number=1, package="foo-bar", last_version="1.0", last_kind="test")]
    actions = plan_issue_actions(outcomes, existing)
    assert len(actions) == 1
    assert actions[0].action == "update"
    assert actions[0].package == "foo-bar"


def test_plan_is_empty_for_no_outcomes_and_no_managed_issues():
    assert plan_issue_actions([], []) == []


def test_plan_mixed_create_update_close_in_one_run():
    outcomes = [
        _outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test"),
        _outcome(name="six", status="updated"),
        _outcome(name="zipp", status="failed", new_version="9.0.0", failure_kind="resolution"),
    ]
    existing = [
        ManagedIssue(number=1, package="six", last_version="1.0.0", last_kind="test"),
        ManagedIssue(number=2, package="zipp", last_version="9.0.0", last_kind="resolution"),
    ]
    actions = plan_issue_actions(outcomes, existing)
    by_pkg = {a.package: a for a in actions}
    assert by_pkg["idna"].action == "create"
    assert by_pkg["six"].action == "close"
    assert by_pkg["zipp"].action == "update"
    assert by_pkg["zipp"].comment is False


# --- plan_issue_actions: duplicate managed issues for one package ----------


def test_plan_closes_duplicates_as_the_non_canonical_higher_numbers():
    """Two open managed issues for the same package (possible via the
    eventually-consistent search / a truncated listing / concurrent runs -
    see item 1 of the follow-up review): the lowest-numbered one is
    canonical, every other one is closed as a duplicate."""
    outcomes = [_outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test")]
    existing = [
        ManagedIssue(number=12, package="idna", last_version="4.0.0", last_kind="test"),
        ManagedIssue(number=7, package="idna", last_version="4.0.0", last_kind="test"),
        ManagedIssue(number=20, package="idna", last_version="4.0.0", last_kind="test"),
    ]
    actions = plan_issue_actions(outcomes, existing)

    closes = {a.issue: a for a in actions if a.action == "close"}
    assert set(closes) == {12, 20}
    assert closes[12].duplicate_of == 7
    assert closes[20].duplicate_of == 7

    updates = [a for a in actions if a.action == "update"]
    assert len(updates) == 1
    assert updates[0].issue == 7


def test_plan_duplicate_close_actions_are_not_flagged_as_the_no_longer_failing_close():
    """A duplicate's close action is distinguishable (via `duplicate_of`)
    from an ordinary "package no longer failing" close - execute_issue_actions
    uses this to pick the right comment."""
    existing = [
        ManagedIssue(number=7, package="idna", last_version="4.0.0", last_kind="test"),
        ManagedIssue(number=9, package="idna", last_version="4.0.0", last_kind="test"),
    ]
    actions = plan_issue_actions([], existing)
    by_issue = {a.issue: a for a in actions}
    # the canonical (7) is closed too, since idna is no longer failing -
    # but only the duplicate (9) carries duplicate_of
    assert by_issue[7].action == "close"
    assert by_issue[7].duplicate_of is None
    assert by_issue[9].action == "close"
    assert by_issue[9].duplicate_of == 7


def test_plan_no_duplicate_actions_when_only_one_managed_issue_per_package():
    outcomes = [_outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test")]
    existing = [ManagedIssue(number=7, package="idna", last_version="4.0.0", last_kind="test")]
    actions = plan_issue_actions(outcomes, existing)
    assert all(a.duplicate_of is None for a in actions)


# --- issue_actions_to_json --------------------------------------------------


def test_issue_actions_to_json_only_exposes_package_action_issue():
    actions = [
        IssueAction(
            package="idna",
            action="create",
            issue=None,
            target=IssueTarget("idna", False, None, None, None, ""),
        )
    ]
    data = json.loads(issue_actions_to_json(actions))
    assert data == [{"package": "idna", "action": "create", "issue": None}]


def test_issue_actions_to_json_empty_list():
    assert issue_actions_to_json([]) == "[]"


def test_issue_actions_to_json_includes_error_only_when_set():
    actions = [
        IssueAction(package="idna", action="create", issue=None),
        IssueAction(package="six", action="update", issue=7, error="gh issue edit failed: boom"),
    ]
    data = json.loads(issue_actions_to_json(actions))
    assert data[0] == {"package": "idna", "action": "create", "issue": None}
    assert data[1] == {
        "package": "six",
        "action": "update",
        "issue": 7,
        "error": "gh issue edit failed: boom",
    }


def test_issue_actions_to_json_is_compact():
    actions = [IssueAction(package="idna", action="create", issue=None)]
    assert issue_actions_to_json(actions) == '[{"package":"idna","action":"create","issue":null}]'


# --- rendering ---------------------------------------------------------


def test_render_issue_title_plain_failure():
    target = IssueTarget("idna", False, "3.0", "4.0", "test", "")
    assert render_issue_title(target) == "idna: update to 4.0 fails (test)"


def test_render_issue_title_held_back():
    target = IssueTarget("zipp", True, "1.0", "9.0", "resolution", "")
    assert (
        render_issue_title(target)
        == "zipp: update beyond declared constraint to 9.0 fails (resolution)"
    )


def test_render_issue_title_truncates_long_version_kind_tail():
    """The title's length is capped at 256 chars: the package name (and
    its ': ' separator) is kept intact, only the version/kind tail is cut,
    with a trailing ellipsis."""
    long_version = "9" * 400
    target = IssueTarget("idna", False, "3.0", long_version, "resolution", "")
    title = render_issue_title(target)
    assert len(title) == 256
    assert title.startswith("idna: ")
    assert title.endswith("…")


def test_render_issue_title_leaves_short_titles_untouched():
    target = IssueTarget("idna", False, "3.0", "4.0", "test", "")
    title = render_issue_title(target)
    assert len(title) < 256
    assert not title.endswith("…")


def test_render_issue_body_contains_marker_versions_and_links():
    target = IssueTarget("idna", False, "3.0", "4.0", "test", "boom output")
    body = render_issue_body(
        target, "https://example/run/1", "https://example/pull/2", "2026-01-01"
    )
    assert "<!-- test-gated-updates:pkg=idna -->" in body
    assert "<!-- test-gated-updates:state=4.0|test -->" in body
    assert "3.0" in body and "4.0" in body
    assert "boom output" in body
    assert "https://example/run/1" in body
    assert "https://example/pull/2" in body
    assert "2026-01-01" in body


def test_render_issue_body_omits_pr_link_when_none():
    target = IssueTarget("idna", False, "3.0", "4.0", "test", "")
    body = render_issue_body(target, "https://example/run/1", None, "2026-01-01")
    assert "Pull request:" not in body


def test_render_issue_body_escapes_pipe_in_package_name():
    target = IssueTarget("weird|name", False, None, None, "test", "")
    body = render_issue_body(target, "run", None, "now")
    assert "weird\\|name" in body


def test_render_issue_body_neutralizes_literal_details_close_tag_in_output_tail():
    """A literal `</details>` in captured output must not be able to close
    the collapsible block early (see report._neutralize_details) - it must
    show up neutralized (with a zero-width space spliced in), never as the
    real closing tag, ahead of the outer block's own closing `</details>`."""
    target = IssueTarget("idna", False, None, None, "test", "</details><script>evil</script>")
    body = render_issue_body(target, "run", None, "now")
    assert "<​/details>" in body
    # the neutralized copy must appear strictly before the real closing tag
    assert body.index("<​/details>") < body.rindex("</details>")


# --- GithubIssues (gh CLI wrapper) ------------------------------------------


def test_list_open_managed_uses_the_plain_listing_as_primary():
    """The plain, unfiltered listing is the primary (and, below the
    truncation threshold, only) source - GitHub's issue search index is
    only eventually consistent (item 1 of the follow-up review), so
    --search is never the primary lookup."""
    runner = _RecordingRunner(
        [CommandResult([], 0, json.dumps([{"number": 1, "body": _managed_body("idna")}]), "")]
    )
    gh = GithubIssues(runner, ".")
    managed = gh.list_open_managed(limit=200)
    assert managed == [ManagedIssue(number=1, package="idna", last_version=None, last_kind=None)]
    assert len(runner.calls) == 1
    assert runner.calls[0][:5] == ["gh", "issue", "list", "--state", "open"]
    assert "--search" not in runner.calls[0]


def test_list_open_managed_raises_when_the_plain_listing_fails():
    runner = _RecordingRunner([CommandResult([], 1, "", "boom")])
    gh = GithubIssues(runner, ".")
    with pytest.raises(ActionError):
        gh.list_open_managed()


def test_list_open_managed_supplements_with_search_when_the_plain_listing_is_truncated():
    """The plain listing coming back at exactly `limit` results means it
    may itself have been truncated (more than `limit` open issues exist) -
    a second, --search narrowed call then runs and is merged in by issue
    number, so a managed issue beyond the first `limit` plain results is
    not missed."""
    runner = _RecordingRunner(
        [
            CommandResult(
                [],
                0,
                json.dumps(
                    [
                        {"number": 1, "body": _managed_body("idna")},
                        {"number": 2, "body": _managed_body("six")},
                    ]
                ),
                "",
            ),
            CommandResult(
                [],
                0,
                # 2: already seen, must not be duplicated; 3: beyond the
                # (truncated) plain listing's limit, must be picked up.
                json.dumps(
                    [
                        {"number": 2, "body": _managed_body("six")},
                        {"number": 3, "body": _managed_body("zipp")},
                    ]
                ),
                "",
            ),
        ]
    )
    gh = GithubIssues(runner, ".")
    managed = gh.list_open_managed(limit=2)

    assert len(runner.calls) == 2
    assert "--search" in runner.calls[1]

    numbers = {mi.number for mi in managed}
    assert numbers == {1, 2, 3}
    packages = {mi.package for mi in managed}
    assert packages == {"idna", "six", "zipp"}


def test_list_open_managed_tolerates_a_failing_supplementary_search():
    """A failure of the supplementary --search call is not fatal - it only
    ever adds coverage, so the (possibly truncated) plain listing's
    results are still returned rather than raising."""
    runner = _RecordingRunner(
        [
            CommandResult(
                [],
                0,
                json.dumps(
                    [
                        {"number": 1, "body": _managed_body("idna")},
                        {"number": 2, "body": _managed_body("six")},
                    ]
                ),
                "",
            ),
            CommandResult([], 1, "", "search backend hiccup"),
        ]
    )
    gh = GithubIssues(runner, ".")
    managed = gh.list_open_managed(limit=2)
    assert {mi.number for mi in managed} == {1, 2}


def test_list_open_managed_does_not_supplement_when_below_the_limit():
    runner = _RecordingRunner(
        [CommandResult([], 0, json.dumps([{"number": 1, "body": _managed_body("idna")}]), "")]
    )
    gh = GithubIssues(runner, ".")
    gh.list_open_managed(limit=200)
    assert len(runner.calls) == 1


def test_create_only_passes_label_flags_when_labels_given():
    runner = _RecordingRunner()
    gh = GithubIssues(runner, ".")
    gh.create("title", "body", [])
    assert "--label" not in runner.calls[-1]

    gh.create("title", "body", ["dependencies", "bug"])
    assert runner.calls[-1][-4:] == ["--label", "dependencies", "--label", "bug"]


def test_close_passes_comment_flag():
    runner = _RecordingRunner()
    gh = GithubIssues(runner, ".")
    gh.close(9, "closing now")
    assert runner.calls[-1] == ["gh", "issue", "close", "9", "--comment", "closing now"]


# --- execute_issue_actions ---------------------------------------------


def test_execute_dry_run_performs_no_writes():
    gh = FakeGithubIssues()
    actions = [
        IssueAction(
            package="idna",
            action="create",
            issue=None,
            target=IssueTarget("idna", False, None, "4.0", "test", ""),
        ),
        IssueAction(package="six", action="close", issue=7),
    ]
    executed, errors = execute_issue_actions(gh, actions, "run", None, [], "now", dry_run=True)
    assert gh.create_calls == []
    assert gh.close_calls == []
    assert executed == actions
    assert executed[0].issue is None
    assert errors == []


def test_execute_create_fills_in_the_new_issue_number():
    gh = FakeGithubIssues(created_issue_number=99)
    target = IssueTarget("idna", False, None, "4.0", "test", "")
    actions = [IssueAction(package="idna", action="create", issue=None, target=target)]
    executed, errors = execute_issue_actions(
        gh, actions, "run", "pr", ["dependencies"], "now", dry_run=False
    )
    assert len(gh.create_calls) == 1
    assert gh.create_calls[0]["labels"] == ["dependencies"]
    assert executed[0].issue == 99
    assert errors == []


def test_execute_update_comments_only_when_flagged():
    gh = FakeGithubIssues()
    target = IssueTarget("idna", False, None, "4.0", "test", "")
    actions = [
        IssueAction(package="idna", action="update", issue=5, target=target, comment=False),
    ]
    execute_issue_actions(gh, actions, "run", None, [], "now", dry_run=False)
    assert len(gh.edit_calls) == 1
    assert gh.comment_calls == []

    actions = [
        IssueAction(package="idna", action="update", issue=5, target=target, comment=True),
    ]
    execute_issue_actions(gh, actions, "run", None, [], "now", dry_run=False)
    assert len(gh.comment_calls) == 1


def test_execute_close_calls_close_with_comment():
    gh = FakeGithubIssues()
    actions = [IssueAction(package="idna", action="close", issue=5)]
    execute_issue_actions(gh, actions, "https://run", "https://pr", [], "now", dry_run=False)
    assert len(gh.close_calls) == 1
    assert gh.close_calls[0]["number"] == 5
    assert "https://run" in gh.close_calls[0]["comment"]
    assert "https://pr" in gh.close_calls[0]["comment"]


def test_execute_close_uses_duplicate_comment_when_duplicate_of_is_set():
    gh = FakeGithubIssues()
    actions = [IssueAction(package="idna", action="close", issue=9, duplicate_of=7)]
    execute_issue_actions(gh, actions, "run", None, [], "now", dry_run=False)
    assert "Duplicate of #7" in gh.close_calls[0]["comment"]


def test_execute_isolates_a_failing_action_and_continues_with_the_rest():
    """Item 2 of the follow-up review: one failing gh call must not abort
    the rest of the plan, and the failure must still be reported."""
    gh = FakeGithubIssues(fail_numbers={5})
    actions = [
        IssueAction(
            package="idna",
            action="create",
            issue=None,
            target=IssueTarget("idna", False, None, "4.0", "test", ""),
        ),
        IssueAction(
            package="six",
            action="update",
            issue=5,
            target=IssueTarget("six", False, None, "1.0", "test", ""),
            comment=False,
        ),
        IssueAction(package="zipp", action="close", issue=9),
    ]

    executed, errors = execute_issue_actions(gh, actions, "run", None, [], "now", dry_run=False)

    assert len(executed) == 3
    assert len(gh.create_calls) == 1  # idna: attempted
    assert len(gh.edit_calls) == 1  # six: attempted (and failed)
    assert len(gh.close_calls) == 1  # zipp: attempted (unaffected by six's failure)

    by_pkg = {a.package: a for a in executed}
    assert by_pkg["idna"].error is None
    assert by_pkg["six"].error is not None
    assert "six" in by_pkg["six"].error
    assert by_pkg["zipp"].error is None

    assert len(errors) == 1
    assert "six" in errors[0]


def test_execute_create_failure_is_recorded_with_issue_still_none():
    gh = FakeGithubIssues(fail_create=True)
    target = IssueTarget("idna", False, None, "4.0", "test", "")
    actions = [IssueAction(package="idna", action="create", issue=None, target=target)]
    executed, errors = execute_issue_actions(gh, actions, "run", None, [], "now", dry_run=False)
    assert executed[0].issue is None
    assert executed[0].error is not None
    assert len(errors) == 1


# --- summarize_issue_actions -------------------------------------------


def test_summarize_issue_actions_counts_each_kind():
    actions = [
        IssueAction(package="a", action="create", issue=None),
        IssueAction(package="b", action="update", issue=1, comment=True),
        IssueAction(package="c", action="update", issue=2, comment=False),
        IssueAction(package="d", action="close", issue=3),
    ]
    summary = summarize_issue_actions(actions, dry_run=False)
    assert "1 created" in summary
    assert "2 updated" in summary
    assert "1 commented" in summary
    assert "1 closed" in summary
    assert "dry-run" not in summary
    assert "failed" not in summary


def test_summarize_issue_actions_notes_dry_run():
    assert "dry-run" in summarize_issue_actions([], dry_run=True)


def test_summarize_issue_actions_counts_failed():
    actions = [
        IssueAction(package="a", action="create", issue=None),
        IssueAction(package="b", action="update", issue=1, error="boom"),
    ]
    summary = summarize_issue_actions(actions, dry_run=False)
    assert "1 failed" in summary


# --- run_issue_management (orchestration) -------------------------------


class _Cfg:
    def __init__(self, create_issues=True, issue_labels="", dry_run=False, directory="."):
        self.create_issues = create_issues
        self.issue_labels = issue_labels
        self.dry_run = dry_run
        self.directory = directory


def test_run_issue_management_returns_empty_when_feature_off():
    gh = FakeGithubIssues()
    actions, errors = run_issue_management(
        _Cfg(create_issues=False), None, [], "run", None, gh_issues=gh
    )
    assert actions == []
    assert errors == []
    assert gh.create_calls == []


def test_run_issue_management_full_cycle_create():
    outcomes = [_outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test")]
    gh = FakeGithubIssues(open_managed=[], created_issue_number=55)
    actions, errors = run_issue_management(
        _Cfg(create_issues=True), None, outcomes, "run", "pr", gh_issues=gh
    )
    assert len(actions) == 1
    assert actions[0].action == "create"
    assert actions[0].issue == 55
    assert len(gh.create_calls) == 1
    assert errors == []


def test_run_issue_management_dry_run_creates_nothing_but_plans():
    outcomes = [_outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test")]
    gh = FakeGithubIssues(open_managed=[])
    actions, errors = run_issue_management(
        _Cfg(create_issues=True, dry_run=True), None, outcomes, "run", None, gh_issues=gh
    )
    assert len(actions) == 1
    assert actions[0].action == "create"
    assert actions[0].issue is None
    assert gh.create_calls == []
    assert errors == []


def test_run_issue_management_uses_issue_labels():
    outcomes = [_outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test")]
    gh = FakeGithubIssues()
    run_issue_management(
        _Cfg(create_issues=True, issue_labels="dependencies, bug"),
        None,
        outcomes,
        "run",
        None,
        gh_issues=gh,
    )
    assert gh.create_calls[0]["labels"] == ["dependencies", "bug"]


def test_run_issue_management_surfaces_a_per_action_error_without_raising():
    """One action's failure (item 2 of the follow-up review) comes back as
    an entry in the errors list rather than an exception - the caller
    (`run()`) decides how to report it (a ::warning:: per entry)."""
    outcomes = [_outcome(name="idna", status="failed", new_version="4.0.0", failure_kind="test")]
    gh = FakeGithubIssues(open_managed=[], fail_create=True)
    actions, errors = run_issue_management(
        _Cfg(create_issues=True), None, outcomes, "run", None, gh_issues=gh
    )
    assert len(actions) == 1
    assert actions[0].error is not None
    assert len(errors) == 1
