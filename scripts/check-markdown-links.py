#!/usr/bin/env python3
"""Validate relative file targets and heading fragments in tracked Markdown."""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote


LINK_RE = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def github_slug(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value).strip().lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return re.sub(r"\s", "-", value)


def heading_anchors(path: Path) -> set[str]:
    seen: Counter[str] = Counter()
    anchors: set[str] = set()
    for heading in HEADING_RE.findall(path.read_text(encoding="utf-8")):
        base = github_slug(heading)
        duplicate = seen[base]
        seen[base] += 1
        anchors.add(base if duplicate == 0 else f"{base}-{duplicate}")
    return anchors


def tracked_markdown() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def main() -> int:
    failures: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}

    for source in tracked_markdown():
        for raw_target in LINK_RE.findall(source.read_text(encoding="utf-8")):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue

            path_text, separator, fragment = target.partition("#")
            destination = source if not path_text else source.parent / unquote(path_text)
            destination = destination.resolve()

            if not destination.exists():
                failures.append(f"{source}: missing target {target}")
                continue

            if separator and fragment and destination.suffix.lower() == ".md":
                anchors = anchor_cache.setdefault(destination, heading_anchors(destination))
                if unquote(fragment).lower() not in anchors:
                    failures.append(f"{source}: missing heading fragment {target}")

    if failures:
        print("Markdown link validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("All tracked Markdown relative links and heading fragments resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
