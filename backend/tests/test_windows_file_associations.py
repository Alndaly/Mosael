"""装了 Mosael 不能把电脑上视频、音频的默认程序改成它自己(用户:「理论上应该是设置默认打开方式后才替换才对吧」)。

electron-builder 的 fileAssociations 在 Windows 上走 APP_ASSOCIATE,第一行就写扩展名的默认值 —— 所以 Windows 这边
不交给它:package.json 里的关联只留在 mac 下(而且标成备选,不和 QuickTime / 音乐争),Windows 由 build/installer.nsh
自己登记进「打开方式」和「默认应用」的候选,一个扩展名的默认值都不写。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _build() -> dict:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["build"]


def _script() -> str:
    return (ROOT / "build" / "installer.nsh").read_text(encoding="utf-8")


def test_关联只在_mac_下声明_而且是备选() -> None:
    build = _build()
    assert "fileAssociations" not in build, "顶层的会进 Windows 安装包,抢走默认程序"
    assert "fileAssociations" not in build.get("win", {}) and "fileAssociations" not in build.get("nsis", {})
    mac = build["mac"]["fileAssociations"]
    assert mac and all(one.get("rank") == "Alternate" for one in mac)


def test_mac_上只当看的程序_不当编辑器() -> None:
    """macOS 选默认程序时先比 LSHandlerRank,同档再看角色:Editor 压过 Viewer。QuickTime / 音乐声明的是 Viewer,
    Mosael 写 Editor 就有机会在同档里赢过它们,双击 mp4 打开的成了 Mosael(用户报的就是这个)。
    Mosael 也确实不在原文件上改 —— 拖进来是导入一份进素材库 —— 所以是 Viewer。

    不写 None:那样「打开方式」菜单里就没有 Mosael 了,拖到程序坞图标上导入也可能不认。electron-builder 不写 rank
    时默认是 Default(1.8.0 之前的包就是这样,本机老包至今还在抢 mp4),所以 rank 和 role 两样都钉住。"""
    for one in _build()["mac"]["fileAssociations"]:
        assert (one.get("rank"), one.get("role")) == ("Alternate", "Viewer"), one


def test_安装脚本不写扩展名的默认值() -> None:
    script = _script()
    #: `WriteRegStr SHCTX "Software\Classes\.mp4" "" …` 这种写扩展名默认值的,一条都不许有。
    writes_default = re.findall(r'WriteRegStr\s+\w+\s+"Software\\Classes\\\.[^"\\]+"\s+""', script)
    assert writes_default == []
    assert "OpenWithProgids" in script and "RegisteredApplications" in script
    assert "!macro customInstall" in script and "!macro customUnInstall" in script


def test_两边的扩展名是同一份() -> None:
    """mac 那一份声明和 installer.nsh 里登记的是同一份清单。

    一边加了扩展名、另一边忘了加,后果是两个平台的行为悄悄分叉:mac 上「打开方式」里有 Mosael、
    Windows 上没有(或者反过来,Windows 认得而主进程压根不接这个后缀,双击了什么都不发生)。
    所以每一组都钉住三处:**mac 声明的、注释里列出的、真正 !insertmacro 登记的**。

    组名(「视频」/「音频」/「图片」)→ NSIS 侧那对(注释标签、ProgID)写在这里。新加一组时,
    这里不补上就会红 —— 那正是要的:加一组关联是有 Windows 这一半的。
    """
    script = _script()
    mac = {one["name"]: sorted(one["ext"]) for one in _build()["mac"]["fileAssociations"]}
    groups = {
        "视频": ("VIDEO", "Mosael.Video"),
        "音频": ("AUDIO", "Mosael.Audio"),
        "图片": ("IMAGE", "Mosael.Image"),
    }
    listed = {
        name: sorted(re.search(rf"MOSAEL-{tag}-EXTS: (.+)", script).group(1).split())
        for name, (tag, _) in groups.items()
    }
    registered = {
        name: sorted(re.findall(rf'!insertmacro \$\{{ACTION\}} "(\w+)" "{progid}"', script))
        for name, (_, progid) in groups.items()
    }
    assert mac == listed == registered


def test_每一个_ProgID_都在安装和卸载两边各出现一次() -> None:
    """登记了 ProgID 却忘了在 customUnInstall 里删,卸载之后注册表里留着一个指向空目录的类。

    这个类还挂在每个扩展名的 OpenWithProgids 下 —— Windows 的「打开方式」里会留下一个点了没反应的
    Mosael(卸载器删了 OpenWithProgids 里的值,但类本身和 Capabilities 是另一回事)。
    """
    script = _script()
    progids = ["Mosael.Video", "Mosael.Audio", "Mosael.Image"]
    install, uninstall = script.split("!macro customInstall", 1)[1].split("!macro customUnInstall", 1)
    for progid in progids:
        assert f'!insertmacro mosaelProgId "{progid}"' in install, progid
        assert f'DeleteRegKey SHCTX "Software\\Classes\\{progid}"' in uninstall, progid
