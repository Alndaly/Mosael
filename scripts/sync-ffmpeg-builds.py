#!/usr/bin/env python3
"""把「带 libass 的完整版 ffmpeg」在各平台上的钉死构建写进清单(backend/app/domain/media_tool_builds.json)。

## 为什么两个来源

macOS 与 Linux 用 <https://ffmpeg.martin-riedl.de>(静态、带 libass、amd64 和 arm64 都有,
而且**每个文件按 `<构建号>_<版本>` 归档** —— 路径本身不可变,旁边就是 `.sha256`);
Windows 用它没有 Windows 构建,改用 <https://github.com/BtbN/FFmpeg-Builds> 的
**按日期打标签的 release**(`autobuild-YYYY-MM-DD-HH-MM`),同一个 release 里带
`checksums.sha256` 把每个包的摘要列全。

两边的归档形状不一样,清单里照实记:macOS/Linux 是**两个包**(ffmpeg.zip、ffprobe.zip,
解出来就是可执行文件本身),Windows 是**一个包**(bin/ffmpeg.exe 与 bin/ffprobe.exe 都在里面)。

## 什么时候跑

发版前跑一次(和 sync-plugin-registry.py 同一类),把清单钉住;运行时装的就是清单里那一个包,
摘要对不上就拒 —— 上游换了内容不会悄悄装进用户机器。

    python scripts/sync-ffmpeg-builds.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "app" / "domain" / "media_tool_builds.json"

RIEDL = "https://ffmpeg.martin-riedl.de"
BTBN_RELEASES = "https://github.com/BtbN/FFmpeg-Builds/releases"

#: 清单里的平台键:`sys.platform` + 归一化的 `platform.machine()`(见 media_tools_install.target_key)。
TARGETS: list[tuple[str, str, str]] = [
    # (清单键, 来源, 该来源的路径片段)
    ("darwin-arm64", "riedl", "macos/arm64"),
    ("darwin-x86_64", "riedl", "macos/amd64"),
    ("linux-x86_64", "riedl", "linux/amd64"),
    ("linux-arm64", "riedl", "linux/arm64"),
]


def _get(url: str, *, attempts: int = 3) -> bytes:
    """下载一个地址。上游偶发地把连接掐掉(实测过一次),所以重试几次再放弃。"""
    request = urllib.request.Request(url, headers={"User-Agent": "mosael-sync-ffmpeg-builds"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 — 地址全是常量
                return response.read()
        except OSError as exc:
            if attempt + 1 == attempts:
                raise SystemExit(f"取不到 {url}:{exc}") from exc
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"取不到 {url}")


def _riedl_release(platform_path: str) -> tuple[str, dict[str, str]]:
    """这个平台最新的一版**发行构建**(`<构建号>_<版本>`,不是 `N-…` 的快照),和它每个包的摘要。

    页面上一版一行,每行给的是 `/download/<平台>/<构建>/<文件>.sha256` 这样的链接 —— 从这里认版本、
    再拼出包本身的地址(它就是 sha256 链接去掉 `.sha256`)。
    """
    html = _get(f"{RIEDL}/").decode("utf-8", "replace")
    wanted = re.compile(rf"/download/{re.escape(platform_path)}/(\d+_[\d.]+)/(ff(?:mpeg|probe)\.zip)\.sha256")
    found: dict[str, str] = {}
    version = ""
    for build, name in wanted.findall(html):
        # 同一平台上可能有几版(发行版、快照版);只认发行版(`<时间戳>_<版本>`),取构建号最大的那一版。
        if version and build < version:
            continue
        if build != version:
            version, found = build, {}
        found[name] = build
    if not found:
        raise SystemExit(f"在 {RIEDL} 上找不到 {platform_path} 的发行构建")
    archives = {}
    for name, build in sorted(found.items()):
        digest = _get(f"{RIEDL}/download/{platform_path}/{build}/{name}.sha256").decode().split()[0]
        archives[f"{RIEDL}/download/{platform_path}/{build}/{name}"] = digest
    return version.split("_", 1)[1], archives


def _btbn_windows() -> tuple[str, dict[str, str], str]:
    """Windows:最新的那个按日期打标签的 release 里的 win64-gpl 包 + 它的摘要。

    `latest` 那个 release 的内容会变(文件名里就写着 latest),所以取**日期标签**那一版:
    地址不可变,摘要也就不用跟着上游漂。
    """
    html = _get(f"{BTBN_RELEASES}").decode("utf-8", "replace")
    tags = sorted(set(re.findall(r"autobuild-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}", html)))
    if not tags:
        raise SystemExit(f"在 {BTBN_RELEASES} 上找不到按日期打标签的 release")
    tag = tags[-1]
    sums = _get(f"{BTBN_RELEASES}/download/{tag}/checksums.sha256").decode()
    pattern = re.compile(r"^([0-9a-f]{64})\s+(\S*win64-gpl\.zip)$", re.M)
    for digest, name in pattern.findall(sums):
        return tag, {f"{BTBN_RELEASES}/download/{tag}/{name}": digest}, name
    raise SystemExit(f"{tag} 里没有 win64-gpl.zip")


def build_manifest() -> dict:
    targets: dict[str, dict] = {}
    for key, source, path in TARGETS:
        version, archives = _riedl_release(path)
        targets[key] = {
            "version": version,
            "source": "ffmpeg.martin-riedl.de",
            "archives": [{"url": url, "sha256": digest} for url, digest in archives.items()],
            #: 每个包里解出来的可执行文件叫什么(解到同一个目录里)。
            "binaries": {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"},
        }
    tag, archives, name = _btbn_windows()
    targets["win32-x86_64"] = {
        "version": tag,
        "source": "github.com/BtbN/FFmpeg-Builds",
        "archives": [{"url": url, "sha256": digest} for url, digest in archives.items()],
        #: 一个包里两个都有,而且多一层根目录(解的时候剥掉)。
        "binaries": {"ffmpeg": "bin/ffmpeg.exe", "ffprobe": "bin/ffprobe.exe"},
        "release_asset": name,
    }
    return {
        "_comment": "由 scripts/sync-ffmpeg-builds.py 生成,不要手改。装的是带 libass 的静态构建,摘要对不上就拒。",
        "targets": dict(sorted(targets.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="只核对现有清单是否和上游一致(不写文件)")
    args = parser.parse_args(argv)
    manifest = build_manifest()
    if args.check:
        current = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        if current.get("targets") != manifest["targets"]:
            print("清单和上游不一致,重跑一次不带 --check 的。", file=sys.stderr)
            return 1
        print("清单和上游一致")
        return 0
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key, one in manifest["targets"].items():
        print(f"{key}: {one['version']}({one['source']},{len(one['archives'])} 个包)")
    print(f"已写入 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
