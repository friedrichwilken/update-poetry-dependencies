"""Fixture test command for the e2e test.

Fails when idna's installed version differs from the version it was
originally locked at. `idna` is updatable (up to 3.20 at fixture creation
time), so updating it changes the installed version and this check fails,
landing idna in `failed-packages`. `six` is also updatable (1.15.0 -> newer),
but updating it does not touch idna, so this check only passes for six if the
environment was correctly re-synced back to idna's old version after idna's
failed update. Since idna sorts before six, six being reported as passed
proves that re-sync happened.
"""

import sys
from importlib.metadata import version

OLD_IDNA_VERSION = "3.4"


def main() -> int:
    installed = version("idna")
    if installed != OLD_IDNA_VERSION:
        print(
            f"idna version mismatch: expected {OLD_IDNA_VERSION}, got {installed}",
            file=sys.stderr,
        )
        return 1
    print(f"idna is at the expected version {installed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
