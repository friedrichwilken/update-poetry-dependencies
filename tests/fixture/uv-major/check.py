"""Fixture test command for the e2e `allow-major` test.

Two packages, each with a capped constraint (an upper bound the current
release already sits under):

- `zipp` is capped at `<4.0` while a `4.x` release exists - a major
  attempt should succeed (this check does not care what version of zipp
  is installed, only that it still imports), so it should end up
  `updated` with `bump: "major"` and a raised constraint.
- `charset-normalizer` is capped at `<3.0` while a `3.x` release exists,
  but this check fails whenever its installed *major* version is not 2 -
  a major attempt (which would jump to `3.x`) should therefore fail this
  check and get held back, while the in-range fallback (still within
  `<3.0`, where there is room to move from the fixture's originally
  locked 2.0.12 up to a newer 2.x release) should still pass. Checking
  the major version number rather than a specific release keeps this
  assertion stable as new 2.x/3.x releases of charset-normalizer come
  out.
"""

import sys
from importlib.metadata import version

CHARSET_NORMALIZER_MAJOR = 2


def main() -> int:
    import zipp  # noqa: F401 - proves the package actually imports

    installed = version("charset-normalizer")
    major = int(installed.split(".")[0])
    if major != CHARSET_NORMALIZER_MAJOR:
        print(
            f"charset-normalizer major version mismatch: expected "
            f"{CHARSET_NORMALIZER_MAJOR}.x, got {installed}",
            file=sys.stderr,
        )
        return 1
    print(f"charset-normalizer is at the expected major version {installed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
