#!/usr/bin/env python3
"""从 plugins/examples/ 生成插件市场索引,写进 website/public/plugins/registry.json。

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
OUT = ROOT / "website" / "public" / "plugins" / "registry.json"
MANIFEST_NAME = "open-studio.plugin.json"

#: 插件包的下载地址。CI 在打 tag 时把每个插件目录打成 <id>-<version>.zip 传到 Release。
DOWNLOAD_TEMPLATE = "https://github.com/Alndaly/OpenStudio/releases/download/plugins-v{version}/{id}.zip"


def entry(manifest_path: Path) -> dict:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    skills = raw.get("skills") or []
    return {
        "id": raw["id"],
        "name": raw.get("name", ""),
        "version": raw.get("version", ""),
        # 描述取第一条技能的说明 —— 那句话本来就是写给"这东西是干嘛的"的。
        "description": (skills[0].get("description") if skills else "") or "",
        "author": "Open Studio",
        "homepage": f"https://github.com/Alndaly/OpenStudio/tree/main/plugins/examples/{manifest_path.parent.name}",
        "download": DOWNLOAD_TEMPLATE.format(id=raw["id"], version=raw.get("version", "")),
        # 权限**从清单来**:界面在装之前把它摊开给用户看,写错等于骗人。
        "permissions": [p for p in (raw.get("permissions") or []) if isinstance(p, str)],
    }


def main() -> None:
    entries = sorted(
        (entry(path) for path in EXAMPLES.glob(f"*/{MANIFEST_NAME}")),
        key=lambda one: one["id"],
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"plugins": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {OUT.relative_to(ROOT)}({len(entries)} 个插件)")


if __name__ == "__main__":
    main()
