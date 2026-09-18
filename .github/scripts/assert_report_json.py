"""e2e-only assertion helper for `check_action.yml`: verifies the shape of
the `report-json` output against a fixture project's known outcome. Not
part of the action package itself, not covered by the `ruff`
extend-exclude for `tests/fixture`, so it is written to the same
lint/format standard as `updater/`.

Parametrized by the `SCENARIO` env var so both e2e fixture families share
this one script rather than each getting their own inline assertion
block:

- "basic" (the default, `tests/fixture/poetry`/`tests/fixture/uv`): idna
  fails its test, six updates cleanly - see those fixtures' `check.py`
  for why.
- "major" (`tests/fixture/poetry-major`/`tests/fixture/uv-major`, run
  with `allow-major: 'true'`): zipp's update beyond its declared
  constraint passes and is committed with `bump: "major"` and
  `constraint_raised: true`; charset-normalizer's equivalent attempt
  fails the test command and is held back, falling back to a passing
  in-range update (`bump: "minor"`, `constraint_raised` absent) - see
  those fixtures' `check.py` for why.
- "batch-fallback" (`tests/fixture/poetry`/`tests/fixture/uv` again, run
  with `strategy: 'batch-first'`): idna's update still fails the same
  fixture test, so the one-shot batch test fails and this run falls back
  to the per-package loop - the final outcome is identical to "basic"
  (idna failed, six updated), but every record must additionally carry
  `strategy: "batch-first"` and `batch_test_failed: true` (issue #23).
- "batch-happy" (`tests/fixture/poetry-batch`/`tests/fixture/uv-batch`,
  run with `strategy: 'batch-first'`): both idna and six update cleanly,
  so the batch's one test run passes outright - every record is
  `updated` with `strategy: "batch-first"` and `tested_in_batch: true`,
  and `batch_test_failed` is absent (the batch never failed here). These
  two matrix entries also run with `update-transitive: 'true'` (issue
  #24): both fixtures' packages are leaf packages with no dependencies of
  their own, and the fixtures' "dev" group member (typing-extensions) is
  exactly pinned, so the transitive step deterministically has nothing
  left to do - `transitive-report` (the `TRANSITIVE_REPORT` env var,
  checked separately from `REPORT_JSON`/`by_name`) must be `{"status":
  "unchanged", "changed_packages": []}`.
- "groups" (`tests/fixture/poetry-batch`/`tests/fixture/uv-batch` again,
  run with `without-groups: 'dev'`, issue #4): the fixtures' "dev" group
  member (typing-extensions) must never appear in `report-json` at all -
  only idna/six ("main"), both updated cleanly, same as "batch-happy"
  minus the batch-first-specific fields.
"""

from __future__ import annotations

import json
import os
import sys


def check_basic(by_name: dict, check) -> None:
    check("idna" in by_name, "expected an idna record")
    check("six" in by_name, "expected a six record")

    idna = by_name.get("idna", {})
    check(idna.get("status") == "failed", f"idna status: {idna.get('status')!r}")
    check(
        idna.get("failure_kind") == "test",
        f"idna failure_kind: {idna.get('failure_kind')!r}",
    )
    check(bool(idna.get("old_version")), "idna old_version should be non-empty")
    check(bool(idna.get("new_version")), "idna new_version (attempted) should be non-empty")
    check("bump" not in idna, "idna should have no bump field (allow-major not used)")

    six = by_name.get("six", {})
    check(six.get("status") == "updated", f"six status: {six.get('status')!r}")
    check(bool(six.get("old_version")), "six old_version should be non-empty")
    check(bool(six.get("new_version")), "six new_version should be non-empty")
    check(
        six.get("old_version") != six.get("new_version"),
        f"six old_version == new_version: {six.get('old_version')!r}",
    )
    check("bump" not in six, "six should have no bump field (allow-major not used)")


def check_major(by_name: dict, check) -> None:
    check("zipp" in by_name, "expected a zipp record")
    check("charset-normalizer" in by_name, "expected a charset-normalizer record")

    zipp = by_name.get("zipp", {})
    check(zipp.get("status") == "updated", f"zipp status: {zipp.get('status')!r}")
    check(zipp.get("bump") == "major", f"zipp bump: {zipp.get('bump')!r}")
    check(
        zipp.get("constraint_raised") is True,
        f"zipp constraint_raised: {zipp.get('constraint_raised')!r}",
    )
    check(bool(zipp.get("old_version")), "zipp old_version should be non-empty")
    check(bool(zipp.get("new_version")), "zipp new_version should be non-empty")
    check(
        zipp.get("old_version") != zipp.get("new_version"),
        f"zipp old_version == new_version: {zipp.get('old_version')!r}",
    )
    check(
        zipp.get("beyond_constraint_version") is None,
        "zipp should have no held-back attempt - its own update *is* the one beyond the constraint",
    )

    cn = by_name.get("charset-normalizer", {})
    check(cn.get("status") == "updated", f"charset-normalizer status: {cn.get('status')!r}")
    check(
        cn.get("failure_kind") is None,
        f"charset-normalizer failure_kind: {cn.get('failure_kind')!r}",
    )
    check(
        "constraint_raised" not in cn,
        "charset-normalizer's own update is the in-range fallback, not a raised constraint",
    )
    check(
        cn.get("bump") == "minor",
        f"charset-normalizer bump (its own in-range fallback update): {cn.get('bump')!r}",
    )
    check(
        bool(cn.get("beyond_constraint_version")),
        "charset-normalizer should report a held-back beyond_constraint_version",
    )
    beyond_kind = cn.get("beyond_constraint_failure_kind")
    check(
        beyond_kind == "test",
        f"charset-normalizer beyond_constraint_failure_kind: {beyond_kind!r}",
    )
    check(
        bool(cn.get("beyond_constraint_output_tail")),
        "charset-normalizer should carry the held-back attempt's captured output",
    )
    check(
        cn.get("old_version") != cn.get("new_version"),
        "charset-normalizer should still have moved forward in-range "
        f"(old={cn.get('old_version')!r}, new={cn.get('new_version')!r})",
    )


def check_batch_fallback(by_name: dict, check) -> None:
    # Same final outcome as "basic" - the batch's own one-shot test fails
    # (idna) exactly like the per-package update would, so this run falls
    # back to the per-package loop and reproduces it byte-for-byte, aside
    # from the additive batch-first fields checked below.
    check_basic(by_name, check)

    for name in ("idna", "six"):
        record = by_name.get(name, {})
        check(
            record.get("strategy") == "batch-first",
            f"{name} strategy: {record.get('strategy')!r}",
        )
        check(
            record.get("batch_test_failed") is True,
            f"{name} batch_test_failed: {record.get('batch_test_failed')!r}",
        )


def check_batch_happy(by_name: dict, check) -> None:
    check("idna" in by_name, "expected an idna record")
    check("six" in by_name, "expected a six record")

    for name in ("idna", "six"):
        record = by_name.get(name, {})
        check(record.get("status") == "updated", f"{name} status: {record.get('status')!r}")
        check(
            record.get("old_version") != record.get("new_version"),
            f"{name} old_version == new_version: {record.get('old_version')!r}",
        )
        check(
            record.get("strategy") == "batch-first",
            f"{name} strategy: {record.get('strategy')!r}",
        )
        check(
            record.get("tested_in_batch") is True,
            f"{name} tested_in_batch: {record.get('tested_in_batch')!r}",
        )
        check(
            "batch_test_failed" not in record,
            f"{name} should have no batch_test_failed field (the batch test passed)",
        )


def check_groups(by_name: dict, check) -> None:
    check("idna" in by_name, "expected an idna record")
    check("six" in by_name, "expected a six record")
    check(
        "typing-extensions" not in by_name,
        "typing-extensions must be excluded entirely by without-groups: dev, "
        f"got a record for it: {by_name.get('typing-extensions')!r}",
    )

    for name in ("idna", "six"):
        record = by_name.get(name, {})
        check(record.get("status") == "updated", f"{name} status: {record.get('status')!r}")
        check(
            record.get("old_version") != record.get("new_version"),
            f"{name} old_version == new_version: {record.get('old_version')!r}",
        )


SCENARIOS = {
    "basic": check_basic,
    "major": check_major,
    "batch-fallback": check_batch_fallback,
    "batch-happy": check_batch_happy,
    "groups": check_groups,
}

# update-transitive (issue #24) is only ever turned on for the
# "batch-happy" matrix entries (see check_action.yml) - deterministically
# "unchanged" there (see check_batch_happy's own note above). Every other
# scenario leaves update-transitive at its default off, so transitive-report
# must be the JSON literal null for them.
EXPECTED_TRANSITIVE_REPORT = {
    "batch-happy": {"status": "unchanged", "changed_packages": []},
}


def check_transitive_report(scenario: str, check) -> None:
    transitive = json.loads(os.environ.get("TRANSITIVE_REPORT", "null"))
    expected = EXPECTED_TRANSITIVE_REPORT.get(scenario)
    check(
        transitive == expected,
        f"transitive-report for scenario {scenario!r}: expected {expected!r}, got {transitive!r}",
    )


def main() -> int:
    scenario = os.environ.get("SCENARIO", "basic")
    records = json.loads(os.environ["REPORT_JSON"])
    by_name = {record["name"]: record for record in records}

    status = 0

    def check(condition: bool, message: str) -> None:
        nonlocal status
        if not condition:
            print(f"report-json assertion failed: {message}")
            status = 1

    SCENARIOS[scenario](by_name, check)
    check_transitive_report(scenario, check)

    return status


if __name__ == "__main__":
    sys.exit(main())
