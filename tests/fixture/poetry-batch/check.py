"""Fixture test command for the batch-first happy-path e2e test.

Unlike `tests/fixture/poetry`'s `check.py`, this one does not pin idna to
its original version - both idna and six are expected to update cleanly
here, so `strategy: batch-first`'s happy path (update everything, test
once, replay the result as per-package commits without testing again) can
be exercised without idna's update failing the way it deliberately does in
`tests/fixture/poetry` (which instead proves the batch-test-failed
fallback path - see the "e2e (poetry, batch)" job in check_action.yml).

Every invocation appends a line to `test_runs.log` next to this file (kept
out of git - see `.gitignore`), so the workflow can assert exactly how many
times the test command actually ran: 1, if the batch-first happy path
really only tests once for both packages combined, instead of once per
package.
"""

import sys
from importlib.metadata import version
from pathlib import Path

LOG_FILE = Path(__file__).parent / "test_runs.log"


def main() -> int:
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write("run\n")

    # Neither package's version is pinned here (unlike
    # tests/fixture/poetry/check.py) - both are expected to update
    # cleanly, so this only needs to prove both are still
    # importable/resolvable.
    idna_version = version("idna")
    six_version = version("six")
    print(f"idna {idna_version}, six {six_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
