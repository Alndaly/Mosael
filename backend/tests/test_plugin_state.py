"""插件把一点东西记到下次调用。

插件是无状态的:环境变量进、JSON 出。对纯计算的工具这没问题,对**要续期的凭据**就是个
死结 —— 百度网盘的 access_token 三十天到期,插件拿 refresh_token 换一个新的很容易,难的是
换完之后没地方放。结果是每个 OAuth 类插件都只能让用户三十天回来粘一次。

`state` 只能写清单里声明过的键。三条理由都在 domain/plugins/state 的文档里,这里钉的是
它们真的成立 —— 尤其是**分流**:刷新出来的令牌进加密凭据库,「上次同步到哪」进明文配置,
两者不该存在同一个地方。
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginInstance, PluginPackage
from app.domain.plugins import instances as inst, state as plugin_state
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.tools import invoke
from tests.util import fresh_client

MANIFEST = {
    "id": "state-demo",
    "name": "记性",
    "version": "0.1.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "instance": {
        "credentials": [{"key": "TOKEN", "label": "令牌", "required": False}],
        "config": [{"key": "CURSOR", "label": "游标", "type": "text", "required": False}],
    },
    "tools": {"expose": "all", "declare": [{"name": "go", "description": "跑一下"}]},
}


def install(tmp_path: Path, body: str) -> tuple[str, str]:
    """装一个插件并接一次,返回 (workspace_id, instance_id)。"""
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(body), encoding="utf-8")
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        package = PluginPackage(
            id="state-demo",
            name="记性",
            version="0.1.0",
            manifest={**MANIFEST, "_path": str(plugin_dir)},
        )
        db.add(package)
        db.flush()
        instance = PluginInstance(package_id=package.id, name="记性", enabled=True, owner_user_id="")
        db.add(instance)
        db.commit()
        return ws, instance.id


WRITES_BOTH = """
    import json, sys
    sys.stdin.read()
    print(json.dumps({
        "ok": True,
        "output": {"done": True},
        "state": {"TOKEN": "刷新出来的", "CURSOR": "第 7 页"},
    }))
"""


class Test落库并分流:
    def test_凭据进加密库_配置进明文(self, tmp_path) -> None:
        """混在一起的话,一个刷新出来的令牌会以明文躺在配置里,而配置是接口直接返回的。"""
        ws, instance_id = install(tmp_path, WRITES_BOTH)
        with SessionLocal() as db:
            assert invoke(db, instance_id, "go", {}, workspace_id=ws).status == "succeeded"
            instance = db.get(PluginInstance, instance_id)
            assert inst.credential_values(db, instance_id)["TOKEN"] == "刷新出来的"
            assert instance.config["CURSOR"] == "第 7 页"
            assert "TOKEN" not in instance.config, "令牌漏进了明文配置"

    def test_下一次调用注入回去(self, tmp_path) -> None:
        """记住了但不注入回去,等于没记 —— 插件下次拿到的还是旧值。"""
        ws, instance_id = install(
            tmp_path,
            """
            import json, os, sys
            sys.stdin.read()
            seen = os.environ.get("TOKEN", "")
            out = {"ok": True, "output": {"seen": seen}}
            if not seen:
                out["state"] = {"TOKEN": "第一次存的"}
            print(json.dumps(out))
            """,
        )
        with SessionLocal() as db:
            first = invoke(db, instance_id, "go", {}, workspace_id=ws)
            assert first.output["seen"] == ""
            second = invoke(db, instance_id, "go", {}, workspace_id=ws)
            assert second.output["seen"] == "第一次存的"

    def test_state_不进_output(self, tmp_path) -> None:
        """output 会交给调用方和模型。刚续出来的令牌顺着工具结果流进对话记录,是不该发生的。"""
        ws, instance_id = install(tmp_path, WRITES_BOTH)
        with SessionLocal() as db:
            output = invoke(db, instance_id, "go", {}, workspace_id=ws).output
            assert "state" not in output
            assert "刷新出来的" not in json.dumps(output, ensure_ascii=False)


class Test只能写声明过的键:
    def test_没声明的键当场失败(self, tmp_path) -> None:
        """忽略的话插件以为自己存下了,下次拿到旧值,而错误表现在几十分钟后的另一个地方。"""
        ws, instance_id = install(
            tmp_path,
            """
            import json, sys
            sys.stdin.read()
            print(json.dumps({"ok": True, "output": {}, "state": {"随便一个键": "x"}}))
            """,
        )
        with SessionLocal() as db:
            invocation = invoke(db, instance_id, "go", {}, workspace_id=ws)
            assert invocation.status == "failed"
            assert "未声明" in (invocation.error or "")

    def test_值太长也拦(self, tmp_path) -> None:
        """挡的是「把整份响应缓存塞进 state」—— 那会让每次调用都重写一遍数据库。"""
        ws, instance_id = install(tmp_path, WRITES_BOTH)
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            with pytest.raises(PluginDomainError, match="过长"):
                plugin_state.persist(db, instance, {"TOKEN": "x" * (plugin_state.MAX_VALUE_CHARS + 1)}, baseline={})

    def test_空的什么都不做(self, tmp_path) -> None:
        ws, instance_id = install(tmp_path, WRITES_BOTH)
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            plugin_state.persist(db, instance, {}, baseline={})
            assert inst.credential_values(db, instance_id) == {}

    def test_state_不是对象就报错(self, tmp_path) -> None:
        ws, instance_id = install(
            tmp_path,
            """
            import json, sys
            sys.stdin.read()
            print(json.dumps({"ok": True, "output": {}, "state": "不是对象"}))
            """,
        )
        with SessionLocal() as db:
            invocation = invoke(db, instance_id, "go", {}, workspace_id=ws)
            assert invocation.status == "failed" and "必须是对象" in (invocation.error or "")


class Test并发写回:
    def test_调用途中令牌被别的调用换过了_不拿这次的旧结果盖掉(self, tmp_path, monkeypatch) -> None:
        """同一个连接上两次调用各拿同一个旧 refresh_token 去换。会轮换令牌的服务上,先换的那次拿到的
        令牌随即被后换的那次作废。此前谁后**结束**谁写 —— 先换的那次结束得晚,就把作废的令牌盖在
        新令牌上,之后每次调用都报令牌失效。"""
        from app.domain.plugins import tools
        from app.domain.plugins.runtime import ToolResult

        ws, instance_id = install(tmp_path, WRITES_BOTH)
        with SessionLocal() as db:
            inst.set_credentials(db, db.get(PluginInstance, instance_id), {"TOKEN": "RT0"}, notify=False)

        def slow_call(*args, **kwargs) -> ToolResult:
            # 这次调用拿着 RT0 跑的时候,另一次调用先结束、把 RT2 写回去了。
            with SessionLocal() as other:
                inst.set_credentials(other, other.get(PluginInstance, instance_id), {"TOKEN": "RT2"}, notify=False)
            return ToolResult(output={"done": True}, state={"TOKEN": "RT1(已作废)", "CURSOR": "第 7 页"})

        monkeypatch.setattr(tools, "execute_tool", slow_call)
        with SessionLocal() as db:
            assert invoke(db, instance_id, "go", {}, workspace_id=ws).status == "succeeded"
            assert inst.credential_values(db, instance_id)["TOKEN"] == "RT2"
            # 途中没人动过的那一格照常写回。
            assert db.get(PluginInstance, instance_id).config["CURSOR"] == "第 7 页"

    def test_途中没人动过就照常写回(self, tmp_path) -> None:
        ws, instance_id = install(tmp_path, WRITES_BOTH)
        with SessionLocal() as db:
            inst.set_credentials(db, db.get(PluginInstance, instance_id), {"TOKEN": "RT0"}, notify=False)
            assert invoke(db, instance_id, "go", {}, workspace_id=ws).status == "succeeded"
            assert inst.credential_values(db, instance_id)["TOKEN"] == "刷新出来的"


class Test顺序:
    def test_先落状态再收产出(self) -> None:
        """反过来的话,收产出那一步出任何岔子(下载失败、磁盘满),这次刷新就白做了 ——
        而旧令牌已经被百度那边作废了,下一次调用会拿着它去撞一个查不出原因的失败。"""
        source = Path(__file__).resolve().parents[1] / "app" / "domain" / "plugins" / "tools.py"
        code = source.read_text(encoding="utf-8")
        persist_at = code.index("plugin_state.persist(")
        collect_at = code.index("output = _collect_artifact(")
        assert persist_at < collect_at, "收产出排在了落状态前面"


class Test失败时交回的状态也要记住:
    def test_续了令牌之后这次调用失败_新令牌照样落库(self, tmp_path) -> None:
        """百度换 access_token 时会**连 refresh_token 一起轮换**,旧的当场作废。插件续完令牌、重试却撞上
        「文件不存在」这类与令牌无关的失败时,此前宿主只在成功时读 `state` —— 新令牌随失败一起丢了,
        下一次拿着已作废的 refresh_token 去换,用户只能重新授权。"""
        ws, instance_id = install(
            tmp_path,
            """
            import json, sys
            sys.stdin.read()
            print(json.dumps({"ok": False, "error": "文件不存在", "state": {"TOKEN": "续出来的"}}))
            """,
        )
        with SessionLocal() as db:
            invocation = invoke(db, instance_id, "go", {}, workspace_id=ws)
            assert invocation.status == "failed" and "文件不存在" in (invocation.error or "")
            assert inst.credential_values(db, instance_id)["TOKEN"] == "续出来的"
