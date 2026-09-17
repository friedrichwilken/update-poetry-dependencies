"""e2e-only assertion helper for `check_action.yml`: verifies the shape of
the `report-json` output against the fixture project's known outcome
(idna fails its test, six updates cleanly - see `tests/fixture/*/check.py`
for why). Not part of the action package itself, not covered by the
`ruff` extend-exclude for `tests/fixture`, so it is written to the same
lint/format standard as `updater/`.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    records = json.loads(os.environ["REPORT_JSON"])
    by_name = {record["name"]: record for record in records}

    status = 0

    def check(condition: bool, message: str) -> None:
        nonlocal status
        if not condition:
            print(f"report-json assertion failed: {message}")
            status = 1

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

    six = by_name.get("six", {})
    check(six.get("status") == "updated", f"six status: {six.get('status')!r}")
    check(bool(six.get("old_version")), "six old_version should be non-empty")
    check(bool(six.get("new_version")), "six new_version should be non-empty")
    check(
        six.get("old_version") != six.get("new_version"),
        f"six old_version == new_version: {six.get('old_version')!r}",
    )

    return status


if __name__ == "__main__":
    sys.exit(main())
