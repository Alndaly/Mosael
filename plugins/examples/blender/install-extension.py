#!/usr/bin/env python3
"""把上游的 Blender MCP Add-on 装成 **Extension**(Blender 4.2+ 的新体系)。

## 为什么需要这个脚本

上游 `blender-mcp` 只发**旧式单文件** add-on(`bl_info` 声明兼容 Blender 3.0),它的
`install-addon` 把文件放进 `scripts/addons/`。那在 Blender 4.2 之前是唯一的形状。

Blender 4.2 起分成两套:Extensions(`blender_manifest.toml`)和 legacy add-ons。
**5.x 的 Preferences → Add-ons 默认只列 Extensions**,legacy 那一栏要手动放开筛选才看得见 ——
于是装完之后界面上"找不到插件",而文件其实就在那儿。这个脚本消除那一步困惑。

## 它做什么

1. 从 `blender-mcp` 包里取出那份 add-on(`bundled/addon.py`,上游 install-addon 也只是拷它);
2. 读 `bl_info` 拿版本号,生成 `blender_manifest.toml`,**权限按它实际用的写**;
3. 装进 `extensions/user_default/blender_mcp/`;
4. **删掉同版本的 legacy 副本**。两份并存会抢同一个 9876 端口,而那种冲突的症状是"时好时坏"。

每次上游升级重跑一遍即可 —— 它从上游那份重新生成,不会留下旧内容。

## 用法

    uv run plugins/examples/blender/install-extension.py

    --version 1.9.1          # 装哪个上游版本(默认与 README 钉的一致)
    --blender 5.2            # 只装到某个 Blender 版本(默认:所有 >= 4.2 的)
    --list                   # 只看会装到哪里,不动手

只用标准库,`python3 install-extension.py` 直接跑也行(需要 PATH 上有 uvx)。
"""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
from pathlib import Path

#: 与 README 钉的一致。改这里要连 README 一起改 —— Add-on 与 MCP server 的协议版本是配套的。
DEFAULT_UPSTREAM = "1.9.1"

#: Extensions 体系从 4.2 开始。更早的 Blender 只能用 legacy,那时该跑上游的 install-addon。
MIN_EXTENSION_BLENDER = (4, 2)

EXTENSION_ID = "blender_mcp"


def blender_config_roots() -> list[Path]:
    """Blender 放用户配置的地方,按平台。"""
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return [home / "Library" / "Application Support" / "Blender"]
    if system == "Windows":
        import os

        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / "Blender Foundation" / "Blender"] if appdata else []
    return [home / ".config" / "blender"]


def installed_versions(only: str | None) -> list[tuple[tuple[int, ...], Path]]:
    """找出装了哪些 Blender 版本。返回 (版本元组, 该版本的配置目录)。"""
    found: list[tuple[tuple[int, ...], Path]] = []
    for root in blender_config_roots():
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not re.fullmatch(r"\d+\.\d+", child.name):
                continue
            version = tuple(int(part) for part in child.name.split("."))
            if version < MIN_EXTENSION_BLENDER:
                continue
            if only and child.name != only:
                continue
            found.append((version, child))
    return found


def upstream_addon(version: str) -> tuple[str, str]:
    """取上游那份 add-on 的源码,以及它 `bl_info` 里的版本号。

    直接读包里的 `bundled/addon.py` —— 上游的 install-addon 也只是把它拷过去(哈希一致)。
    经 uvx 取而不是要求先装好:这个脚本的读者刚照 README 装完 uv,不该再要求他建一个 venv。
    """
    code = (
        "import blender_mcp, pathlib, sys;"
        "sys.stdout.write(str(pathlib.Path(blender_mcp.__file__).parent / 'bundled' / 'addon.py'))"
    )
    try:
        result = subprocess.run(
            ["uvx", "--python", "3.11", "--with", f"blender-mcp=={version}", "python", "-c", code],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit("找不到 uvx。先装 uv:https://docs.astral.sh/uv/getting-started/installation/") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"取 blender-mcp=={version} 失败:\n{exc.stderr.strip()[:800]}") from exc

    source_path = Path(result.stdout.strip())
    if not source_path.is_file():
        raise SystemExit(f"上游包里没有 {source_path} —— 这个版本的结构可能变了。")
    source = source_path.read_text(encoding="utf-8")

    match = re.search(r'"version"\s*:\s*\(([^)]*)\)', source)
    if not match:
        raise SystemExit("读不到 bl_info 里的 version —— 上游结构变了,这个脚本要跟着改。")
    parts = [p.strip() for p in match.group(1).split(",") if p.strip()]
    # Extension 的版本必须是 x.y.z 三段;上游 bl_info 常常只给两段。
    while len(parts) < 3:
        parts.append("0")
    return source, ".".join(parts[:3])


def manifest(addon_version: str) -> str:
    """Extension 清单。**权限按 add-on 实际做的事写**,不抄通用模板。"""
    return f'''schema_version = "1.0.0"

id = "{EXTENSION_ID}"
version = "{addon_version}"
name = "MCP for Blender"
tagline = "Connect Blender to Mosael and agents over MCP"
maintainer = "BlenderMCP <https://github.com/ahujasid/blender-mcp>"
type = "add-on"

website = "https://github.com/ahujasid/blender-mcp"
tags = ["Development", "Import-Export"]

blender_version_min = "{MIN_EXTENSION_BLENDER[0]}.{MIN_EXTENSION_BLENDER[1]}.0"
license = ["SPDX:MIT"]

# 如实申报,不是抄的模板:
[permissions]
network = "Serves the local MCP socket that Mosael and agents connect to."
files = "Reads and writes .blend and glTF files during scene exchange."
'''


def install(config_dir: Path, source: str, addon_version: str, dry_run: bool) -> list[str]:
    """装进一个 Blender 版本,返回给人看的动作说明。"""
    target = config_dir / "extensions" / "user_default" / EXTENSION_ID
    legacy = config_dir / "scripts" / "addons" / f"{EXTENSION_ID}.py"
    notes = [f"extension → {target}"]
    if legacy.is_file():
        # 两份并存会抢同一个端口,而那种冲突表现为"时好时坏",最难查。
        notes.append(f"删除 legacy 副本 → {legacy}")
    if dry_run:
        return notes

    target.mkdir(parents=True, exist_ok=True)
    (target / "__init__.py").write_text(source, encoding="utf-8")
    (target / "blender_manifest.toml").write_text(manifest(addon_version), encoding="utf-8")
    if legacy.is_file():
        legacy.unlink()
        parent = legacy.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", default=DEFAULT_UPSTREAM, help=f"上游 blender-mcp 版本(默认 {DEFAULT_UPSTREAM})")
    parser.add_argument("--blender", help="只装到这个 Blender 版本,例如 5.2")
    parser.add_argument("--list", action="store_true", help="只看会装到哪里,不动手")
    args = parser.parse_args()

    targets = installed_versions(args.blender)
    if not targets:
        where = " / ".join(str(p) for p in blender_config_roots())
        extra = f"(只找 {args.blender})" if args.blender else f"(只认 {MIN_EXTENSION_BLENDER[0]}.{MIN_EXTENSION_BLENDER[1]} 及以上)"
        print(f"没找到 Blender 的配置目录 {extra}。找过:{where}\n先把 Blender 打开一次,它会建出这些目录。", file=sys.stderr)
        return 1

    source, addon_version = upstream_addon(args.version)
    print(f"blender-mcp {args.version} · add-on {addon_version}")
    for version, config_dir in targets:
        label = ".".join(str(p) for p in version)
        for note in install(config_dir, source, addon_version, args.list):
            print(f"  Blender {label}: {note}")

    if args.list:
        print("\n(--list:什么都没动)")
        return 0

    print(
        "\n装好了。打开 Blender → Preferences → Add-ons,搜 MCP,勾选 "
        "**MCP for Blender**;然后在 3D 视口按 N,侧栏里点 Start MCP Server。\n"
        "Blender 已经开着的话要重启一次 —— 扩展是启动时扫的。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
