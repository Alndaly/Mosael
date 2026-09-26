"""插件市场索引必须和插件清单对得上。

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。

索引是**用户在装之前看到的那一份** —— 名字、版本、尤其是**权限清单**。手写的话它和插件
本身会漂:版本号改了索引没改、插件加了个权限索引还写着旧的那几条。而权限那一栏漂了不是
显示问题:用户是照着它决定装不装的。

所以索引由 scripts/sync-plugin-registry.py 生成,这条钉住它没过期。

索引收两类插件:`plugins/examples/`(从市场装)和 `plugins/bundled/`(随应用内置)。后者此前
漏在索引外面 —— ComfyUI 成了内置插件之后,在市场里怎么搜都搜不到它。
"""

from __future__ import annotations

RATCHET = True

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "plugins" / "examples"
BUNDLED = ROOT / "plugins" / "bundled"
REGISTRY = ROOT / "website" / "public" / "plugins" / "registry.json"
MANIFEST_NAME = "mosael.plugin.json"


def _registry() -> dict[str, dict]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {one["id"]: one for one in payload["plugins"]}


def _manifests() -> list[Path]:
    """索引收的所有插件清单:要从市场装的 + 随应用内置的。"""
    return [*EXAMPLES.glob(f"*/{MANIFEST_NAME}"), *BUNDLED.glob(f"*/{MANIFEST_NAME}")]


def test_每个插件都在索引里() -> None:
    """漏一个的话,那个插件对用市场的人根本不存在 —— 而它明明就在仓库里。"""
    manifests = {json.loads(p.read_text(encoding="utf-8"))["id"] for p in _manifests()}
    assert manifests == set(_registry()), "索引和 plugins/examples + plugins/bundled 对不上,跑一下 scripts/sync-plugin-registry.py"


def test_内置插件标了_bundled_且没有下载地址() -> None:
    """内置插件跟着应用走:市场里只标「内置」,不给装。给了下载地址,界面就会长出一颗「安装」。"""
    registry = _registry()
    bundled_ids = {json.loads(p.read_text(encoding="utf-8"))["id"] for p in BUNDLED.glob(f"*/{MANIFEST_NAME}")}
    assert bundled_ids, "plugins/bundled 下一个插件都没扫到"
    for plugin_id, entry in registry.items():
        assert entry["bundled"] is (plugin_id in bundled_ids), f"{plugin_id} 的 bundled 标记不对"
        if plugin_id in bundled_ids:
            assert entry["download"] == "", f"{plugin_id} 是内置的,不该有下载地址"


def test_版本号一致() -> None:
    registry = _registry()
    for path in _manifests():
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert registry[raw["id"]]["version"] == raw.get("version"), f"{raw['id']} 的版本号漂了"


def test_权限清单一致() -> None:
    """这一条最要紧:用户是照着索引里的权限决定装不装的。少写一条 = 骗人。"""
    registry = _registry()
    for path in _manifests():
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
        if entry["bundled"]:
            continue  # 内置的不从市场装,CI 也不打它的包(见上一条)
        assert entry["download"].endswith(f"/{entry['id']}.zip"), f"{entry['id']} 的下载地址和 CI 的文件名对不上"
        # 官网这份是 main 上的源码,不跟任何一次发版走:只有已经发出去的老版本应用还从它装,
        # 给它们的是最新一次 Release 的附件。新版本应用读的是发版产物(见
        # test_plugin_market_index_is_a_release_artifact),那一份的下载地址钉在 tag 上。
        assert "/releases/latest/download/" in entry["download"], f"{entry['id']} 的下载地址钉死了版本"


def test_官网这份标明是_main_上的源码() -> None:
    """应用装的是发版产物;官网这份说的是 main 上现在是哪一版。标出来,读的人(和写自建索引的人)
    分得清这两份 —— 把它当成「可下载的版本」正是「明明装好了还显示更新」的来源。"""
    assert json.loads(REGISTRY.read_text(encoding="utf-8"))["channel"] == "main"


def test_工具清单与运行方式一致() -> None:
    """市场详情里「它带来哪些工具」照着索引列。漂了的话,用户装之前看到的是另一个插件。"""
    registry = _registry()
    for path in _manifests():
        raw = json.loads(path.read_text(encoding="utf-8"))
        declared = [tool["name"] for tool in ((raw.get("tools") or {}).get("declare") or [])]
        assert [tool["name"] for tool in registry[raw["id"]]["tools"]] == declared, f"{raw['id']} 的工具清单漂了"
        runtime = (raw.get("runtime") or {}).get("kind") or "process"
        assert registry[raw["id"]]["runtime"] == runtime, f"{raw['id']} 的运行方式漂了"


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天目录改了名,上面三条会一起真空通过。"""
    assert len(list(EXAMPLES.glob(f"*/{MANIFEST_NAME}"))) >= 3
    assert len(list(BUNDLED.glob(f"*/{MANIFEST_NAME}"))) >= 1
