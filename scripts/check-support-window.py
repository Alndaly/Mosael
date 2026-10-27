#!/usr/bin/env python3
"""Fail a release when the oldest supported version drifts past the 8-version window."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.support_window import MAX_RELEASES_BEHIND, OLDEST_SUPPORTED_RELEASE  # noqa: E402

VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def version_key(tag: str) -> tuple[int, int, int, tuple[str, ...]] | None:
    match = VERSION.fullmatch(tag)
    if match is None:
        return None
    return int(match[1]), int(match[2]), int(match[3]), tuple((match[4] or "").split("."))


def fetch_releases(repo: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "mosael-support-window-check",
            **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def stable_tags(releases: list[dict[str, Any]]) -> list[str]:
    tags = [
        str(release.get("tag_name") or "")
        for release in releases
        if not release.get("draft") and not release.get("prerelease")
    ]
    return sorted((tag for tag in tags if version_key(tag) is not None), key=version_key, reverse=True)


def check_window(
    releases: list[dict[str, Any]],
    *,
    latest: str,
    oldest: str = OLDEST_SUPPORTED_RELEASE,
    max_behind: int = MAX_RELEASES_BEHIND,
) -> int:
    if version_key(latest) is None:
        raise ValueError(f"release tag is not a stable version: {latest!r}")
    tags = [tag for tag in stable_tags(releases) if version_key(tag) <= version_key(latest)]
    if latest not in tags:
        tags.append(latest)
        tags.sort(key=version_key, reverse=True)
    if oldest not in tags:
        raise ValueError(f"oldest supported release {oldest} is not a published stable release")
    behind = tags.index(oldest)
    if behind != max_behind:
        expected = tags[max_behind] if len(tags) > max_behind else "<not published yet>"
        shown = ", ".join(tags[: max_behind + 2])
        raise ValueError(
            f"support window is {behind} versions behind {latest}, expected exactly {max_behind}. "
            f"Move OLDEST_SUPPORTED_RELEASE (currently {oldest}) to {expected} and regenerate "
            f"backend/tests/schema_baseline.json + test/upgrade_db_fixture.py. Recent stable tags: {shown}"
        )
    print(
        f"support window: {latest} → {oldest} is {behind} versions behind "
        f"({behind + 1} supported releases)"
    )
    return behind


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="Alndaly/Mosael")
    parser.add_argument("--latest", default="", help="version being released; defaults to latest stable API tag")
    parser.add_argument("--oldest", default=OLDEST_SUPPORTED_RELEASE)
    parser.add_argument("--max-behind", type=int, default=MAX_RELEASES_BEHIND)
    parser.add_argument("--releases-json", type=Path, help="fixture file instead of the GitHub API")
    args = parser.parse_args()
    try:
        releases = json.loads(args.releases_json.read_text(encoding="utf-8")) if args.releases_json else fetch_releases(args.repo)
        latest = args.latest or (stable_tags(releases)[0] if stable_tags(releases) else "")
        check_window(releases, latest=latest, oldest=args.oldest, max_behind=args.max_behind)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"support window check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
