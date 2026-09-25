#!/usr/bin/env python3
"""从 plugins/examples/ 和 plugins/bundled/ 生成插件市场索引,写进 website/public/plugins/registry.json。

**两个目录一条规则。** examples 是要从市场装的;bundled 是随应用一起发的第一方插件(ComfyUI),
装好就在 —— 但它照样该在市场里搜得到:用户不知道哪些是内置的,他只会去市场里找「ComfyUI」,
找不到就以为没有。内置的条目标 `bundled: true`、不给下载地址(它跟着应用走,不从市场装,
新版也跟着应用来);应用里的市场据此只标「内置」,不给装 / 更新 / 卸载。

**索引不手写。** 手写的话它和插件本身会漂:版本号改了索引没改、插件加了个权限索引还写着
旧的那几条 —— 而用户在装之前看到的正是索引里那一份。由清单生成,漂不了。

下载地址指向仓库的 **归档接口**:`.../archive/refs/heads/main.zip` 会把整个仓库打下来,
太大;`.../archive/<ref>.zip` 加上子目录做不到。所以用 codeload 的 tar 不行、用 GitHub 的
"download a folder" 也没有官方接口 —— 这里指向的是**每个插件自己的 release zip**,
由 CI 在打 tag 时产出(见 .github/workflows)。没有产出之前,download 留空,界面上那个
「安装」按钮是禁用的,而不是点了报 404。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "plugins" / "examples"
BUNDLED = ROOT / "plugins" / "bundled"
OUT = ROOT / "website" / "public" / "plugins" / "registry.json"
MANIFEST_NAME = "mosael.plugin.json"

#: 插件包的下载地址。CI 在打 tag 时把每个插件目录打成 <id>.zip 传到那次 Release
#: (见 .github/workflows/release.yml 的 Package plugins)。
#:
#: **用 `releases/latest/download` 而不是钉某个版本号**:索引由网站部署、附件由发版流程
#: 产出,两者各走各的。写死版本号的话,发了新版而网站还没重新部署,索引就指向一个还不存在
#: 的附件 —— 而那正是这条上一版踩的坑(索引里挂着 plugins-v1.0.0,那个 tag 从来没有过)。
#: latest 由 GitHub 转发到最新一次 Release,永远指得到东西。
DOWNLOAD_TEMPLATE = "https://github.com/Alndaly/Mosael/releases/latest/download/{id}.zip"


#: 仓库里插件目录的网页地址。与后端 domain/plugins/registry.REPO_PLUGINS_URL 是同一个。
REPO_PLUGINS_URL = "https://github.com/Alndaly/Mosael/tree/main/plugins"


def entry(manifest_path: Path, *, bundled: bool = False) -> dict:
    """一条索引。内置插件的那一条与后端 registry.bundled_entry 由本机清单生成的一一对应。"""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    folder = manifest_path.parent
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
        # 主页**先用插件自己写的**:那是它的文档站,是用户装之前真正想看的东西。
        # 没写才退到仓库里它的目录 —— 至少还能读到源码和 README。
        "homepage": str(raw.get("homepage") or "").strip()
        or f"{REPO_PLUGINS_URL}/{folder.parent.name}/{folder.name}",
        # 内置的不给下载地址:它不从市场装,CI 也不把它打成 release 附件。
        "download": "" if bundled else DOWNLOAD_TEMPLATE.format(id=raw["id"]),
        # 权限**从清单来**:界面在装之前把它摊开给用户看,写错等于骗人。
        "permissions": [p for p in (raw.get("permissions") or []) if isinstance(p, str)],
        # 它是本机脚本还是一个 MCP server —— 后者的工具由 server 自己报,装之前列不出来,
        # 市场详情据此说「装上之后才知道」,而不是显示一个空的工具清单。
        "runtime": str((raw.get("runtime") or {}).get("kind") or "process"),
        # 它能替 Mosael 做哪类事(公网直链…)。和工具清单一样是「装了能得到什么」。
        "provides": [p for p in (raw.get("provides") or []) if isinstance(p, str)],
        # 声明的工具:名字、显示名和说明(按语言分的原样带过去)。**不带入参 schema** ——
        # 市场里要回答的是"它能干什么",怎么调是装上之后的事,而 schema 会让索引胖一个数量级。
        "tools": [
            {
                "name": str(tool["name"]),
                "label": tool.get("label") or "",
                "description": tool.get("description") or "",
            }
            for tool in ((raw.get("tools") or {}).get("declare") or [])
            if isinstance(tool, dict) and tool.get("name")
        ],
        "bundled": bundled,
    }


def main() -> None:
    entries = sorted(
        [entry(path) for path in EXAMPLES.glob(f"*/{MANIFEST_NAME}")]
        + [entry(path, bundled=True) for path in BUNDLED.glob(f"*/{MANIFEST_NAME}")],
        key=lambda one: one["id"],
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"plugins": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {OUT.relative_to(ROOT)}({len(entries)} 个插件)")


if __name__ == "__main__":
    main()
