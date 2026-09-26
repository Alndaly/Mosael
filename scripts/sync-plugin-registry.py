#!/usr/bin/env python3
"""由 plugins/examples/ 和 plugins/bundled/ 的清单生成插件市场索引。**一个生成器,两份产物:**

    # 官网上的插件目录(main 上的源码):写进 website/public/plugins/registry.json
    python3 scripts/sync-plugin-registry.py

    # 应用里的市场装的那一份:发版流程在打好插件包之后跑,和插件包一起传到那次 Release
    python3 scripts/sync-plugin-registry.py --release v1.5.3 --repo Alndaly/Mosael --packages dist/plugins

**应用装的是发版产物,不是 main。** 此前应用读的是官网上那份(由 main 生成),下载地址却指向
最新一次 Release 的附件 —— main 上改了插件版本、还没发版的那段时间里,索引许的是 0.2.0,下载给的
还是 0.1.0:「更新」装回旧版,「有新版」永远不消失。现在应用读的索引由发版流程生成,和它打包的是
**同一份源码**,每条的下载地址钉在**同一个 tag** 上,生成时还逐个打开包核对 id 与版本 —— 许的
就是给的(见 docs/RELEASING.md「插件市场索引」)。

官网那一份照旧从 main 生成,标 `"channel": "main"`:它说的是仓库里的源码现在是哪一版。已经发出去的
老版本应用(1.5.x 及更早)把 mosael.com 上这份写死成默认地址,所以它的下载地址仍是「最新一次
Release 的附件」;新版本应用不读它。

**两个目录一条规则。** examples 是要从市场装的;bundled 是随应用一起发的第一方插件(ComfyUI),
装好就在 —— 但它照样该在市场里搜得到:用户不知道哪些是内置的,他只会去市场里找「ComfyUI」,
找不到就以为没有。内置的条目标 `bundled: true`、不给下载地址(它跟着应用走,不从市场装,
新版也跟着应用来);应用里的市场据此只标「内置」,不给装 / 更新 / 卸载。

**索引不手写。** 手写的话它和插件本身会漂:版本号改了索引没改、插件加了个权限索引还写着
旧的那几条 —— 而用户在装之前看到的正是索引里那一份。由清单生成,漂不了。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 工具的后果按后端**同一个函数**算(它是个不依赖任何模块的叶子),不在这里抄一份规则。
sys.path.insert(0, str(ROOT / "backend"))
from app.domain.effects import plugin_tool_effects  # noqa: E402
EXAMPLES = ROOT / "plugins" / "examples"
BUNDLED = ROOT / "plugins" / "bundled"
WEBSITE_OUT = ROOT / "website" / "public" / "plugins" / "registry.json"
MANIFEST_NAME = "mosael.plugin.json"
RELEASE_INDEX_NAME = "registry.json"
DEFAULT_REPO = "Alndaly/Mosael"

#: 发版产物里的下载地址:**钉在生成这份索引的那个 tag 上**。索引和插件包由同一次发版传到同一个
#: Release,应用经 `releases/latest/download/registry.json` 拿到索引,再按这里的地址下包 ——
#: 读索引的那一刻恰好发了新版,拿到的也是「那一版的索引 + 那一版的包」,不会错配。
RELEASE_DOWNLOAD_TEMPLATE = "https://github.com/{repo}/releases/download/{tag}/{id}.zip"

#: 官网那一份(main)的下载地址:最新一次 Release 的附件。只有已经发出去的老版本应用还从这份装
#: (它们的默认索引地址写死成了 mosael.com 上这份);它的版本号是 main 上的,可能比这个地址给的新
#: —— 这正是新版本应用改读发版产物的原因。
WEBSITE_DOWNLOAD_TEMPLATE = "https://github.com/{repo}/releases/latest/download/{id}.zip"

#: tag 形状与 release.yml 的触发条件一致(v 开头);挡住把分支名之类传进来。
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _effects(raw: dict, tool: dict) -> str:
    """一个声明过的工具的后果:覆盖 > 声明 > 包上的 default_effects > external;只读的是 none。
    与后端 plugins.registry._market_effects 同一个算法(真正的规则在 plugin_tool_effects 里)。"""
    policy = raw.get("tools") or {}
    override = (policy.get("overrides") or {}).get(tool["name"]) or {}
    return plugin_tool_effects(
        read_only=override.get("read_only") is True or tool.get("read_only") is True,
        declared=override.get("effects") or tool.get("effects"),
        default=policy.get("default_effects"),
    )


def entry(manifest_path: Path, *, download: str) -> dict:
    """一条索引。内置插件的那一条与后端 registry.bundled_entry 由本机清单生成的一一对应。

    `download` 由调用方按产物给(发版那份钉 tag,官网那份指最新 Release);内置插件给空串。
    """
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    skills = raw.get("skills") or []
    return {
        "id": raw["id"],
        "name": raw.get("name", ""),
        "version": raw.get("version", ""),
        # 描述取第一条技能的说明 —— 那句话本来就是写给"这东西是干嘛的"的。
        "description": (skills[0].get("description") if skills else "") or "",
        # 作者从清单来(清单里是 {name, url})。**author 仍是一个字符串** —— 已经装着的旧版本
        # 按字符串读它;改成对象的话,它们的市场里会显示一串 {'name': …}。主页另起一个键。
        "author": str((raw.get("author") or {}).get("name") or ""),
        "author_url": str((raw.get("author") or {}).get("url") or ""),
        # 在 Mosael 里怎么用的文档,可按语言分;原样带过去,由读的一方挑语言。
        "docs": raw.get("docs") or "",
        # 主页**只从清单来**:仓库里每个插件都写了(见 backend/tests/test_first_party_plugins_name_a_homepage.py),
        # 应用的插件页读的也是清单里这一个值 —— 两处一条规矩。
        "homepage": str(raw["homepage"]).strip(),
        "download": download,
        # 权限**从清单来**:界面在装之前把它摊开给用户看,写错等于骗人。
        "permissions": [p for p in (raw.get("permissions") or []) if isinstance(p, str)],
        # 它是本机脚本还是一个 MCP server —— 后者的工具由 server 自己报,装之前列不出来,
        # 市场详情据此说「装上之后才知道」,而不是显示一个空的工具清单。
        "runtime": str((raw.get("runtime") or {}).get("kind") or "process"),
        # 它能替 Mosael 做哪类事(公网直链…)。和工具清单一样是「装了能得到什么」。
        "provides": [p for p in (raw.get("provides") or []) if isinstance(p, str)],
        # 声明的工具:名字、显示名和说明(按语言分的原样带过去)。**不带入参 schema** ——
        # 市场里要回答的是"它能干什么",怎么调是装上之后的事,而 schema 会让索引胖一个数量级。
        # 每个工具带上它的后果(none / paid / external / local-code):市场详情据此标出哪些工具智能体调用前会先问你。
        "tools": [
            {
                "name": str(tool["name"]),
                "label": tool.get("label") or "",
                "description": tool.get("description") or "",
                "effects": _effects(raw, tool),
            }
            for tool in ((raw.get("tools") or {}).get("declare") or [])
            if isinstance(tool, dict) and tool.get("name")
        ],
        "bundled": manifest_path.parent.parent == BUNDLED,
    }


def build_entries(download_for: Callable[[str], str]) -> list[dict]:
    """两份产物共用的条目:只有下载地址按产物不同(`download_for(id)`),内置的永远没有下载地址。"""
    examples = [
        entry(path, download=download_for(json.loads(path.read_text(encoding="utf-8"))["id"]))
        for path in EXAMPLES.glob(f"*/{MANIFEST_NAME}")
    ]
    bundled = [entry(path, download="") for path in BUNDLED.glob(f"*/{MANIFEST_NAME}")]
    return sorted(examples + bundled, key=lambda one: one["id"])


def website_index(repo: str = DEFAULT_REPO) -> dict:
    """官网上那一份:main 上的源码。"""
    return {
        "channel": "main",
        "plugins": build_entries(lambda plugin_id: WEBSITE_DOWNLOAD_TEMPLATE.format(repo=repo, id=plugin_id)),
    }


def release_index(tag: str, repo: str = DEFAULT_REPO) -> dict:
    """应用里的市场装的那一份:这一次发版(`tag`)的产物,下载地址钉在这个 tag 上。"""
    if not TAG_RE.match(tag):
        raise SystemExit(f"--release 要的是发版的 tag(v1.2.3),拿到的是 {tag!r}")
    if not REPO_RE.match(repo):
        raise SystemExit(f"--repo 要的是 owner/name,拿到的是 {repo!r}")
    return {
        "channel": "release",
        "release": tag,
        "plugins": build_entries(lambda plugin_id: RELEASE_DOWNLOAD_TEMPLATE.format(repo=repo, tag=tag, id=plugin_id)),
    }


def verify_packages(index: dict, packages: Path) -> None:
    """**逐个打开这次打好的包**,核对它就是索引许的那一版:每条都有 `<id>.zip`、包里清单的 id 与版本
    和索引一致,也没有索引外的包。对不上就让发版失败 —— 那正是「许的新版下载给不出来」。"""
    wanted = {one["id"]: one for one in index["plugins"] if not one["bundled"]}
    found = {path.stem for path in packages.glob("*.zip")}
    problems = [f"{plugin_id}: 没有 {plugin_id}.zip" for plugin_id in sorted(set(wanted) - found)]
    problems += [f"{stem}.zip: 索引里没有这个插件" for stem in sorted(found - set(wanted))]
    for plugin_id in sorted(set(wanted) & found):
        with zipfile.ZipFile(packages / f"{plugin_id}.zip") as archive:
            names = [name for name in archive.namelist() if name.rsplit("/", 1)[-1] == MANIFEST_NAME]
            if not names:
                problems.append(f"{plugin_id}.zip: 包里没有 {MANIFEST_NAME}")
                continue
            # 与应用装包时同一个认法:离根最近的那份清单(见 backend domain/plugins/registry._manifest_root)。
            raw = json.loads(archive.read(min(names, key=lambda name: name.count("/"))).decode("utf-8"))
        if raw.get("id") != plugin_id or raw.get("version") != wanted[plugin_id]["version"]:
            problems.append(
                f"{plugin_id}.zip: 包里是 {raw.get('id')} {raw.get('version')},索引许的是 "
                f"{plugin_id} {wanted[plugin_id]['version']}"
            )
    if problems:
        raise SystemExit("插件包和索引对不上:\n  " + "\n  ".join(problems))


def _write(index: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--release", metavar="TAG", help="生成发版产物:这次发版的 tag(v1.2.3)")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"owner/name(默认 {DEFAULT_REPO})")
    parser.add_argument(
        "--packages",
        type=Path,
        help=f"发版产物:打好的插件包所在目录;逐个核对后把 {RELEASE_INDEX_NAME} 写在它旁边",
    )
    args = parser.parse_args(argv)
    if args.release is None:
        if args.packages is not None:
            parser.error("--packages 只用于发版产物(--release)")
        index = website_index(args.repo)
        _write(index, WEBSITE_OUT)
        print(f"已写入 {WEBSITE_OUT.relative_to(ROOT)}(main,{len(index['plugins'])} 个插件)")
        return
    if args.packages is None:
        parser.error("--release 要带 --packages:索引只能和它核对过的那批插件包一起发")
    index = release_index(args.release, args.repo)
    verify_packages(index, args.packages)
    out = args.packages / RELEASE_INDEX_NAME
    _write(index, out)
    print(f"已写入 {out}({args.release},{len(index['plugins'])} 个插件,插件包逐个核对过)")


if __name__ == "__main__":
    main()
