"""插件交出**文件**的那条路。

插件协议是 JSON over stdio,输出上限 1MB。于是一个插件能告诉你「这个网盘目录里有哪些文件」,
却没办法把一个 2GB 的 mp4 交给素材库 —— 想搬字节只能 base64 塞进 JSON,而那塞不下。

加的是一种约定形状:插件要么把文件写在给它的暂存目录里,要么只交出下载凭据(url + 请求头)
让后端去下。**第二种才是重点** —— 百度网盘的 dlink 就是这个形状(带时效、要带特定请求头)。
让插件负责换取凭据、后端负责搬字节,进度、取消、重试全都复用现成的机制,插件一行都不用写;
反过来让每个插件自己下的话,它们会各实现各的。
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from app.db.models import Asset
from app.domain.plugins import artifacts
from app.domain.plugins.artifacts import ArtifactError, SCRATCH_ENV
from app.domain.plugins.runtime import execute_tool
from tests.util import fresh_client


def make_plugin(tmp_path: Path, entry_body: str) -> tuple[Path, str]:
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(entry_body), encoding="utf-8")
    return plugin_dir, "main.py"


class Test暂存目录:
    def test_插件收得到那个目录(self, tmp_path) -> None:
        """协议只搬 JSON,所以搬字节这件事得另开一条路 —— 而插件得知道往哪儿写。"""
        plugin = make_plugin(
            tmp_path,
            """
            import json, os, sys
            sys.stdin.read()
            print(json.dumps({"ok": True, "output": {"dir": os.environ.get("MOSAEL_PLUGIN_OUTPUT_DIR", "")}}))
            """,
        )
        scratch = tmp_path / "out"
        scratch.mkdir()
        output = execute_tool(*plugin, "x", {}, scratch_dir=scratch).output
        assert output["dir"] == str(scratch)

    def test_没给暂存目录时不注入这个变量(self, tmp_path) -> None:
        """不是所有工具都产文件。凭空多一个指向不存在目录的环境变量,只会让插件写进去然后丢掉。"""
        plugin = make_plugin(
            tmp_path,
            """
            import json, os, sys
            sys.stdin.read()
            print(json.dumps({"ok": True, "output": {"has": "MOSAEL_PLUGIN_OUTPUT_DIR" in os.environ}}))
            """,
        )
        assert execute_tool(*plugin, "x", {}).output["has"] is False


class Test交出本地文件:
    def test_收进素材库(self, tmp_path) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        scratch = tmp_path / "out"
        scratch.mkdir()
        (scratch / "a.txt").write_text("hello", encoding="utf-8")

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            # 返回的是**引用**,不是 ORM 对象 —— 这一层不认识素材库(见 plugins/media_bridge)。
            ref, name = artifacts.register(
                db, {"path": "a.txt"}, scratch, workspace_id=ws, project_id=None, fallback_name="t"
            )
            db.commit()
            assert name == "a.txt"
            assert db.get(Asset, ref).source == "plugin"

    def test_不能交出暂存目录以外的文件(self, tmp_path) -> None:
        """插件本来就以用户身份运行、读得到用户读得到的一切,所以这不挡提权。

        它挡的是「随手交出一个别处的文件」—— 比如把 ~/.ssh/id_rsa 收进素材库,而素材库里的
        东西是能被发布出去的。限定目录还让清理变成一件确定的事。
        """
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        scratch = tmp_path / "out"
        scratch.mkdir()
        outsider = tmp_path / "secret.txt"
        outsider.write_text("x", encoding="utf-8")

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            with pytest.raises(ArtifactError, match=SCRATCH_ENV):
                artifacts.register(
                    db, {"path": str(outsider)}, scratch, workspace_id=ws, project_id=None, fallback_name="t"
                )

    def test_用_dotdot_也绕不出去(self, tmp_path) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        scratch = tmp_path / "out"
        scratch.mkdir()
        (tmp_path / "secret.txt").write_text("x", encoding="utf-8")

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            with pytest.raises(ArtifactError, match=SCRATCH_ENV):
                artifacts.register(
                    db, {"path": "../secret.txt"}, scratch, workspace_id=ws, project_id=None, fallback_name="t"
                )

    def test_文件不存在说得明白(self, tmp_path) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        scratch = tmp_path / "out"
        scratch.mkdir()

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            with pytest.raises(ArtifactError, match="不存在"):
                artifacts.register(db, {"path": "nope"}, scratch, workspace_id=ws, project_id=None, fallback_name="t")


class Test交出下载凭据:
    def test_只接受_http(self, tmp_path) -> None:
        """file:// 会让插件把本机任意文件读进素材库,绕开上面那条目录限制。"""
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        scratch = tmp_path / "out"
        scratch.mkdir()

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            with pytest.raises(ArtifactError, match="http"):
                artifacts.register(
                    db,
                    {"url": "file:///etc/passwd"},
                    scratch,
                    workspace_id=ws,
                    project_id=None,
                    fallback_name="t",
                )

    def test_下载时带上插件给的请求头(self, tmp_path, monkeypatch) -> None:
        """百度网盘的 dlink 不带 User-Agent 直接 403 —— 请求头是凭据的一部分,不是可选装饰。"""
        seen: dict = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_bytes(self):
                yield b"payload"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class FakeClient:
            def __init__(self, **kw):
                seen["headers"] = kw.get("headers")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def stream(self, method, url):
                seen["url"] = url
                return FakeResponse()

        monkeypatch.setattr(artifacts, "RetryingClient", FakeClient)
        scratch = tmp_path / "out"
        scratch.mkdir()
        path = artifacts._download({"url": "https://e/x.mp4", "headers": {"User-Agent": "pan"}, "filename": "x.mp4"}, scratch)
        assert seen["headers"] == {"User-Agent": "pan"}
        assert path.read_bytes() == b"payload"

    def test_下载也有大小上限(self, tmp_path, monkeypatch) -> None:
        """不是怕慢,是怕一个跑飞的插件把磁盘写满 —— 那时候整个应用都动不了,而现象和插件毫无关系。"""

        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_bytes(self):
                while True:
                    yield b"x" * 1024

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class FakeClient:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def stream(self, method, url):
                return FakeResponse()

        monkeypatch.setattr(artifacts, "RetryingClient", FakeClient)
        monkeypatch.setattr(artifacts, "MAX_ARTIFACT_BYTES", 4096)
        scratch = tmp_path / "out"
        scratch.mkdir()
        with pytest.raises(ArtifactError, match="大小上限"):
            artifacts._download({"url": "https://e/big"}, scratch)


class Test收口在唯一那条执行路径:
    def test_产出换成_asset_id(self, tmp_path) -> None:
        """换掉而不是两个都留:留着的话下游会拿到一个指向已删暂存目录的路径 —— 它在返回的
        那一刻就失效了,而看起来完全像个能用的路径。"""
        from app.domain.plugins.tools import _collect_artifact

        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        scratch = tmp_path / "out"
        scratch.mkdir()
        (scratch / "a.txt").write_text("hi", encoding="utf-8")

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            out = _collect_artifact(
                db,
                {"artifact": {"path": "a.txt"}, "note": "留着"},
                scratch,
                workspace_id=ws,
                project_id=None,
                fallback_name="t",
            )
            db.commit()
        assert "artifact" not in out
        assert out["asset_id"] and out["asset_name"] == "a.txt"
        assert out["note"] == "留着", "顺带把别的输出弄丢了"

    def test_没有产出的工具原样返回(self, tmp_path) -> None:
        from app.domain.plugins.tools import _collect_artifact

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            out = _collect_artifact(db, {"text": "x"}, None, workspace_id=None, project_id=None, fallback_name="t")
        assert out == {"text": "x"}

    def test_没有归属工作区时说清楚(self, tmp_path) -> None:
        """一份素材总得属于某个工作区。默默丢掉的话,用户看到的是「工具跑成功了但什么都没有」。"""
        from app.domain.plugins.tools import _collect_artifact

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            with pytest.raises(ArtifactError, match="工作区"):
                _collect_artifact(
                    db, {"artifact": {"path": "a"}}, tmp_path, workspace_id=None, project_id=None, fallback_name="t"
                )


class Test暂存目录一定被清掉:
    def test_成功之后清掉(self) -> None:
        scratch = artifacts.make_scratch_dir()
        assert scratch.is_dir()
        artifacts.cleanup_scratch_dir(scratch)
        assert not scratch.exists()

    def test_invoke_里放在_finally(self) -> None:
        """插件崩了、超时了、产出不合法 —— 每一种都得清。漏掉的话,一个反复失败的插件会
        在临时目录里堆下一堆没人认领的大文件,而没有任何东西会提到它。"""
        from pathlib import Path as P

        source = P(__file__).resolve().parents[1] / "app" / "domain" / "plugins" / "tools.py"
        code = source.read_text(encoding="utf-8")
        assert "finally:\n        cleanup_scratch_dir(scratch)" in code


class Test端到端:
    def test_插件写文件_一路进素材库(self, tmp_path) -> None:
        """把整条路走一遍:插件往暂存目录写一个文件 → invoke 收下 → 素材库里查得到。

        分段测过不等于整条通 —— 这条路跨了三个模块(runtime 给目录、artifacts 收字节、
        tools 换 asset_id),接缝上错一处,每一段的用例还是绿的。
        """
        import json as _json
        import textwrap as _tw

        from app.core.db import SessionLocal
        from app.db.models import Asset, PluginInstance, PluginPackage
        from app.domain.plugins.tools import invoke

        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

        plugin_dir = tmp_path / "pan"
        plugin_dir.mkdir()
        (plugin_dir / "main.py").write_text(
            _tw.dedent(
                """
                import json, os, sys
                sys.stdin.read()
                out = os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"]
                with open(os.path.join(out, "pulled.txt"), "w") as f:
                    f.write("从网盘拉下来的字节")
                print(json.dumps({"ok": True, "output": {"artifact": {"path": "pulled.txt"}, "quota": "9GB"}}))
                """
            ),
            encoding="utf-8",
        )
        manifest = {
            "id": "pan-demo",
            "name": "网盘演示",
            "version": "0.1.0",
            "runtime": {"kind": "process", "entry": "main.py"},
            "tools": {"declare": [{"name": "pull", "description": "拉一个文件"}], "expose": "all"},
        }
        (plugin_dir / "mosael.plugin.json").write_text(_json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        with SessionLocal() as db:
            package = PluginPackage(
                id="pan-demo", name="网盘演示", version="0.1.0", manifest={**manifest, "_path": str(plugin_dir)}
            )
            db.add(package)
            db.flush()
            instance = PluginInstance(
                package_id=package.id, name="我的网盘", enabled=True, owner_user_id=""
            )
            db.add(instance)
            db.commit()

            invocation = invoke(db, instance.id, "pull", {}, workspace_id=ws)
            assert invocation.status == "succeeded", invocation.error
            output = invocation.output
            assert "artifact" not in output, "暂存路径漏给了下游 —— 它在返回那一刻就已经失效"
            assert output["quota"] == "9GB", "顺带把别的输出弄丢了"

            asset = db.get(Asset, output["asset_id"])
            assert asset is not None and asset.workspace_id == ws
            assert asset.name == "pulled.txt" and asset.source == "plugin"
