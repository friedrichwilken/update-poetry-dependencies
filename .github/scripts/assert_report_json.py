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


SCENARIOS = {"basic": check_basic, "major": check_major}


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

    return status


if __name__ == "__main__":
    sys.exit(main())
