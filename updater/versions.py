"""Minimal version parsing/comparison. No external dependency needed for the
simple "at least X.Y" checks this action does."""

from __future__ import annotations


def parse_version(version: str) -> tuple:
    parts = []
    for part in version.strip().split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def version_at_least(version: str, minimum: str) -> bool:
    v = parse_version(version)
    m = parse_version(minimum)
    length = max(len(v), len(m))
    v = v + (0,) * (length - len(v))
    m = m + (0,) * (length - len(m))
    return v >= m
