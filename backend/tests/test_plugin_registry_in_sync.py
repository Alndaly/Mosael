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
MANIFEST_NAME = "mosael.plugin.json"


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


def test_下载地址和_CI_产出的文件名对得上() -> None:
    """索引说去哪儿下,CI 决定传上去的叫什么。**两边对不上就是 404**,而索引看起来一切正常。

    这条上一版就是错的:索引里挂着 `plugins-v1.0.0/<id>.zip`,而那个 tag 从来没存在过 ——
    用户点「安装」拿到一个 404,而市场页上那条目长得和能用的一模一样。
    """
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "dist/plugins/$id.zip" in workflow, "CI 不再按 <id>.zip 打包了"
    assert "gh release upload" in workflow and "dist/plugins/*.zip" in workflow, "CI 没有上传插件包"
    for entry in _registry().values():
        assert entry["download"].endswith(f"/{entry['id']}.zip"), f"{entry['id']} 的下载地址和 CI 的文件名对不上"
        # 不钉版本号:索引由网站部署、附件由发版流程产出,两者各走各的。
        assert "/releases/latest/download/" in entry["download"], f"{entry['id']} 的下载地址钉死了版本"


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天目录改了名,上面三条会一起真空通过。"""
    assert len(list(EXAMPLES.glob(f"*/{MANIFEST_NAME}"))) >= 3
