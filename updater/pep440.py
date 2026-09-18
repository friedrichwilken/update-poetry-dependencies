"""A small, PEP 440-*enough* version parser and comparator.

Only what the major-bump feature (issue #21) actually needs: parsing a
release's numeric segments plus pre/post/dev markers, ordering two
versions, and telling whether a version is a pre-release (so the major
attempt never silently jumps onto a pre-release just because it happens to
sort "highest"). No epoch, no local version segment comparison beyond
storing it - real-world package versions on PyPI essentially never need
either for this comparison to be useful here, and adding them would just be
unused complexity, not correctness.

Deliberately stdlib-only (no `packaging` dependency, matching the rest of
`updater/`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# PEP 440-ish: release segment, optional pre-release (a|b|rc + N), optional
# post-release (post/rev/r + N, or the implicit "-N" shorthand), optional
# dev-release (dev + N). Local version (+something) is captured but not
# used for comparison.
_VERSION_RE = re.compile(
    r"""^\s*
    v?
    (?P<release>[0-9]+(?:\.[0-9]+)*)
    (?:
        [-_.]?(?P<pre_l>a|b|c|rc|alpha|beta|pre|preview)
        [-_.]?(?P<pre_n>[0-9]*)
    )?
    (?:
        (?:
            [-_.]?(?P<post_l>post|rev|r)[-_.]?(?P<post_n1>[0-9]*)
        )
        |
        (?:-(?P<post_n2>[0-9]+))
    )?
    (?:
        [-_.]?dev[-_.]?(?P<dev_n>[0-9]*)
    )?
    (?:\+(?P<local>[a-zA-Z0-9]+(?:[-_.][a-zA-Z0-9]+)*))?
    \s*$""",
    re.VERBOSE,
)

_PRE_NORMALIZE = {
    "alpha": "a",
    "beta": "b",
    "c": "rc",
    "pre": "rc",
    "preview": "rc",
}


@dataclass(frozen=True)
class Version:
    release: tuple[int, ...]
    pre: tuple[str, int] | None = None  # ("a" | "b" | "rc", N)
    post: int | None = None
    dev: int | None = None
    local: str | None = None
    original: str = ""

    @property
    def is_prerelease(self) -> bool:
        return self.pre is not None or self.dev is not None

    def _sort_key(self) -> tuple:
        # Release segments compared as a tuple; a dev release sorts before
        # the corresponding non-dev release, a pre-release sorts before the
        # final release, and a post-release sorts after it.
        pre_key = (1, "", 0) if self.pre is None else (0, self.pre[0], self.pre[1])
        dev_key = (0,) if self.dev is None else (-1, self.dev)
        post_key = (-1,) if self.post is None else (1, self.post)
        return (self.release, pre_key, dev_key, post_key)


def parse_version(text: str) -> Version | None:
    """Parse a version string loosely following PEP 440. Returns None if
    `text` cannot be parsed at all (the caller should then skip whatever
    version-dependent decision it was trying to make, rather than guess)."""
    if not text:
        return None
    match = _VERSION_RE.match(text)
    if not match:
        return None

    release = tuple(int(p) for p in match.group("release").split("."))

    pre = None
    pre_l = match.group("pre_l")
    if pre_l:
        normalized = _PRE_NORMALIZE.get(pre_l, pre_l)
        pre_n = match.group("pre_n")
        pre = (normalized, int(pre_n) if pre_n else 0)

    post = None
    post_n1 = match.group("post_n1")
    post_n2 = match.group("post_n2")
    if match.group("post_l") is not None:
        post = int(post_n1) if post_n1 else 0
    elif post_n2 is not None:
        post = int(post_n2)

    dev = None
    dev_n = match.group("dev_n")
    if dev_n is not None:
        dev = int(dev_n) if dev_n else 0

    local = match.group("local")

    return Version(release=release, pre=pre, post=post, dev=dev, local=local, original=text)


def compare_versions(a: Version, b: Version) -> int:
    """-1 / 0 / 1 like a classic comparator."""
    ak, bk = a._sort_key(), b._sort_key()
    if ak < bk:
        return -1
    if ak > bk:
        return 1
    return 0


def is_prerelease(text: str) -> bool:
    """True if `text` parses and is a pre-release/dev-release. A version
    that fails to parse is conservatively treated as *not* a pre-release,
    matching the "never bump onto a pre-release" rule the safe way around:
    callers that need parseability should check `parse_version` first."""
    version = parse_version(text)
    return bool(version and version.is_prerelease)


def bump_kind(old_version: str | None, new_version: str | None) -> str:
    """Which release segment actually changed between `old_version` and
    `new_version`: `"major"`, `"minor"`, `"patch"`, or `"other"` - "other"
    covers everything this classification cannot make a confident claim
    about: a missing/unparsable version, `locked_version()`'s
    comma-joined "more than one distinct locked version" case, the two
    versions comparing equal, or a difference confined to a segment past
    the first three (or a pre/post/dev/local-only difference, e.g.
    "1.0" -> "1.0.post1")."""
    if not old_version or not new_version or "," in old_version or "," in new_version:
        return "other"

    old = parse_version(old_version)
    new = parse_version(new_version)
    if old is None or new is None:
        return "other"
    if compare_versions(old, new) == 0:
        return "other"

    length = max(len(old.release), len(new.release), 3)
    old_release = old.release + (0,) * (length - len(old.release))
    new_release = new.release + (0,) * (length - len(new.release))

    if old_release[0] != new_release[0]:
        return "major"
    if old_release[1] != new_release[1]:
        return "minor"
    if old_release[2] != new_release[2]:
        return "patch"
    return "other"
