"""插件市场索引必须和插件清单对得上。

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。

索引是**用户在装之前看到的那一份** —— 名字、版本、尤其是**权限清单**。手写的话它和插件
本身会漂:版本号改了索引没改、插件加了个权限索引还写着旧的那几条。而权限那一栏漂了不是
显示问题:用户是照着它决定装不装的。

所以索引由 scripts/sync-plugin-registry.py 生成,这条钉住它没过期。
"""

from __future__ import annotations

RATCHET = True

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "plugins" / "examples"
REGISTRY = ROOT / "website" / "public" / "plugins" / "registry.json"
MANIFEST_NAME = "open-studio.plugin.json"


def _registry() -> dict[str, dict]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {one["id"]: one for one in payload["plugins"]}


def test_每个示例插件都在索引里() -> None:
    """漏一个的话,那个插件对用市场的人根本不存在 —— 而它明明就在仓库里。"""
    manifests = {json.loads(p.read_text(encoding="utf-8"))["id"] for p in EXAMPLES.glob(f"*/{MANIFEST_NAME}")}
    assert manifests == set(_registry()), "索引和 plugins/examples 对不上,跑一下 scripts/sync-plugin-registry.py"


def test_版本号一致() -> None:
    registry = _registry()
    for path in EXAMPLES.glob(f"*/{MANIFEST_NAME}"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert registry[raw["id"]]["version"] == raw.get("version"), f"{raw['id']} 的版本号漂了"


def test_权限清单一致() -> None:
    """这一条最要紧:用户是照着索引里的权限决定装不装的。少写一条 = 骗人。"""
    registry = _registry()
    for path in EXAMPLES.glob(f"*/{MANIFEST_NAME}"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert registry[raw["id"]]["permissions"] == (raw.get("permissions") or []), f"{raw['id']} 的权限清单漂了"


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天目录改了名,上面三条会一起真空通过。"""
    assert len(list(EXAMPLES.glob(f"*/{MANIFEST_NAME}"))) >= 3
