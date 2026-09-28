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


def test_安装脚本不写扩展名的默认值() -> None:
    script = _script()
    #: `WriteRegStr SHCTX "Software\Classes\.mp4" "" …` 这种写扩展名默认值的,一条都不许有。
    writes_default = re.findall(r'WriteRegStr\s+\w+\s+"Software\\Classes\\\.[^"\\]+"\s+""', script)
    assert writes_default == []
    assert "OpenWithProgids" in script and "RegisteredApplications" in script
    assert "!macro customInstall" in script and "!macro customUnInstall" in script


def test_两边的扩展名是同一份() -> None:
    script = _script()
    mac = {one["name"]: sorted(one["ext"]) for one in _build()["mac"]["fileAssociations"]}
    listed = {
        "视频": sorted(re.search(r"MOSAEL-VIDEO-EXTS: (.+)", script).group(1).split()),
        "音频": sorted(re.search(r"MOSAEL-AUDIO-EXTS: (.+)", script).group(1).split()),
    }
    registered = {
        "视频": sorted(re.findall(r'!insertmacro \$\{ACTION\} "(\w+)" "Mosael\.Video"', script)),
        "音频": sorted(re.findall(r'!insertmacro \$\{ACTION\} "(\w+)" "Mosael\.Audio"', script)),
    }
    assert mac == listed == registered
