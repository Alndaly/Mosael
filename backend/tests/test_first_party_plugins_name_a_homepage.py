"""仓库里的每个插件都在清单里写明主页。

插件页的「插件主页」按钮只认清单里的 `homepage`;市场索引此前在没写时自己退到仓库目录 ——
同一件事两条规矩,于是对象存储、文本工具在官网上有主页、在应用的插件页上没有(用户指出过)。
清单是唯一来源:写在清单里,两处读的就是同一个值。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "plugins"
MANIFESTS = sorted([*ROOT.glob("examples/*/mosael.plugin.json"), *ROOT.glob("bundled/*/mosael.plugin.json")])


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda path: path.parent.name)
def test_清单写明了主页(path: Path) -> None:
    homepage = str(json.loads(path.read_text(encoding="utf-8")).get("homepage") or "").strip()
    assert homepage.startswith("https://"), f"{path.parent.name} 的清单没写主页(https://…)"
