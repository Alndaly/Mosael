"""百度网盘插件:把网盘里的素材拉进素材库。

**它是 artifact 通道的第一个使用者**,也是那条通道存在的理由:`pan_import` 不自己下载,
只换到 dlink 就交给宿主。进度、取消、重试、大小上限、失败隔离,宿主的任务机制里全都有,
而插件这一侧只有一次 60 秒的 stdio 调用 —— 自己下一个 2GB 的文件必然超时。

**这些用例覆盖不到真实的百度接口**(没有凭据可用)。它们钉的是:请求参数拼对了、errno
翻成了人话、dlink 连同那组必需的请求头一起交了出去。真实接口的形状按开放平台文档写,
第一次接上真号时要重新核一遍。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "baidu-pan"
ENTRY = PLUGIN / "tools" / "main.py"

#: 把 urlopen 换掉,记下请求、回一份预设响应。插进 main.py 前面执行。
STUB = """
import json, sys, urllib.request
_CALLS = []
class _Resp:
    def __init__(self, body): self._body = body
    def read(self): return json.dumps(self._body).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False
_RESPONSES = json.loads({responses!r})
def _fake(request, timeout=None):
    _CALLS.append({{"url": request.full_url, "headers": dict(request.headers)}})
    return _Resp(_RESPONSES.pop(0))
urllib.request.urlopen = _fake
import atexit
atexit.register(lambda: sys.stderr.write("CALLS=" + json.dumps(_CALLS, ensure_ascii=False)))
"""


def run(tool: str, payload: dict, responses: list, env: dict | None = None) -> tuple[dict, list]:
    """跑一次插件,返回 (响应, 它发出去的请求)。"""
    script = STUB.format(responses=json.dumps(responses)) + "\n" + ENTRY.read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps({"tool": tool, "input": payload}),
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "BAIDU_PAN_ACCESS_TOKEN": "T", **(env or {})},
    )
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stderr.split("CALLS=", 1)[1]) if "CALLS=" in result.stderr else []
    return json.loads(result.stdout), calls


LIST_OK = {
    "errno": 0,
    "list": [
        {"fs_id": 111, "server_filename": "a.mp4", "path": "/素材/a.mp4", "isdir": 0, "size": 2048},
        {"fs_id": 222, "server_filename": "旧片", "path": "/素材/旧片", "isdir": 1, "size": 0},
    ],
}


class Test列目录:
    def test_只留调用方要用的字段(self) -> None:
        """原样透传的话,模型要在几十个字段里找 fs_id。"""
        out, _ = run("pan_list", {"path": "/素材"}, [LIST_OK])
        assert out["ok"]
        assert out["output"]["entries"][0] == {
            "fs_id": "111",
            "name": "a.mp4",
            "path": "/素材/a.mp4",
            "is_dir": False,
            "size": 2048,
        }

    def test_目录标出来(self) -> None:
        """不标的话,模型会拿一个目录的 fs_id 去 import,而失败要等到换 dlink 那一步。"""
        out, _ = run("pan_list", {"path": "/素材"}, [LIST_OK])
        assert out["output"]["entries"][1]["is_dir"] is True

    def test_没给路径时用配置里的起始目录(self) -> None:
        out, calls = run("pan_list", {}, [LIST_OK], env={"BAIDU_PAN_ROOT": "/我的资源"})
        assert "dir=%2F%E6%88%91%E7%9A%84%E8%B5%84%E6%BA%90" in calls[0]["url"]
        assert out["output"]["path"] == "/我的资源"

    def test_起始目录也没配就是根(self) -> None:
        out, _ = run("pan_list", {}, [LIST_OK])
        assert out["output"]["path"] == "/"

    def test_limit_夹在上限内(self) -> None:
        _, calls = run("pan_list", {"limit": 99999}, [LIST_OK])
        assert "limit=1000" in calls[0]["url"]


class Test搜索:
    def test_带上递归(self) -> None:
        """不递归的话,只搜当前一层 —— 而用它的场景恰恰是「不知道在哪一层」。"""
        _, calls = run("pan_search", {"keyword": "海边"}, [LIST_OK])
        assert "recursion=1" in calls[0]["url"]

    def test_关键词不能为空(self) -> None:
        out, _ = run("pan_search", {"keyword": "  "}, [])
        assert out["ok"] is False and "keyword" in out["error"]


META_OK = {
    "errno": 0,
    "list": [{"fs_id": 111, "server_filename": "a.mp4", "size": 2048, "dlink": "https://d.pcs.baidu.com/f?x=1"}],
}


class Test导入:
    def test_交出_dlink_而不是自己下(self) -> None:
        """插件这一侧只有一次 60 秒的 stdio 调用,自己下一个 2GB 的文件必然超时;
        就算不超时,用户也看不到进度,按取消也停不下来。"""
        out, _ = run("pan_import", {"fs_id": "111"}, [META_OK])
        artifact = out["output"]["artifact"]
        assert artifact["url"].startswith("https://d.pcs.baidu.com/f?x=1")
        assert "path" not in artifact, "自己下了文件 —— 那正是这条通道要避免的"

    def test_access_token_拼在_url_上(self) -> None:
        """dlink 不带 token 是 403,而百度不会告诉你缺的是哪一样。"""
        out, _ = run("pan_import", {"fs_id": "111"}, [META_OK])
        assert "access_token=T" in out["output"]["artifact"]["url"]

    def test_必需的_UA_一起交出去(self) -> None:
        """请求头是凭据的一部分,不是可选装饰 —— 交了 url 不交头,宿主一样下不动。"""
        out, _ = run("pan_import", {"fs_id": "111"}, [META_OK])
        assert out["output"]["artifact"]["headers"]["User-Agent"] == "pan.baidu.com"

    def test_文件名带过去(self) -> None:
        """不带的话素材库里会出现一排叫 download 的东西。"""
        out, _ = run("pan_import", {"fs_id": "111"}, [META_OK])
        assert out["output"]["artifact"]["filename"] == "a.mp4"

    def test_要单独一次_filemetas_才有_dlink(self) -> None:
        """列表接口不给 dlink —— 它是有时效的临时地址,列一次目录签一百个出来没有意义。"""
        _, calls = run("pan_import", {"fs_id": "111"}, [META_OK])
        assert "/multimedia" in calls[0]["url"] and "dlink=1" in calls[0]["url"]

    def test_目录或无权限时说得明白(self) -> None:
        out, _ = run("pan_import", {"fs_id": "222"}, [{"errno": 0, "list": [{"fs_id": 222, "dlink": ""}]}])
        assert out["ok"] is False and "下载地址" in out["error"]

    def test_找不到那个文件(self) -> None:
        out, _ = run("pan_import", {"fs_id": "999"}, [{"errno": 0, "list": []}])
        assert out["ok"] is False and "找不到" in out["error"]


class Test错误翻成人话:
    @pytest.mark.parametrize(
        "errno,expect",
        [(-6, "过期"), (111, "过期"), (-9, "不存在"), (31034, "限流"), (99999, "errno=99999")],
    )
    def test_百度用_errno_表达失败_HTTP_永远是_200(self, errno: int, expect: str) -> None:
        """光报一个数字等于让用户去搜,而这几个的处置方式完全不同:换 token / 换文件 / 等一会儿。"""
        out, _ = run("pan_list", {}, [{"errno": errno}])
        assert out["ok"] is False and expect in out["error"]

    def test_没配_token_直接说(self) -> None:
        out, _ = run("pan_list", {}, [], env={"BAIDU_PAN_ACCESS_TOKEN": ""})
        assert out["ok"] is False and "access_token" in out["error"]

    def test_不认识的工具名(self) -> None:
        out, _ = run("nope", {}, [])
        assert out["ok"] is False and "unknown tool" in out["error"]


class Test清单和实现对得上:
    def test_声明的工具都实现了(self) -> None:
        """声明即接口 —— 声明了没实现的话,用户在插件页勾得上,一调就是「unknown tool」。"""
        manifest = json.loads((PLUGIN / "open-studio.plugin.json").read_text(encoding="utf-8"))
        declared = {t["name"] for t in manifest["tools"]["declare"]}
        source = ENTRY.read_text(encoding="utf-8")
        implemented = set(json.loads(json.dumps(sorted(declared))))  # 名字集合
        for name in implemented:
            assert f"def {name}(" in source, f"清单声明了 {name} 但没实现"
        assert "TOOLS = {" in source

    def test_清单能被宿主解析(self) -> None:
        from app.domain.plugins.manifest import parse

        raw = json.loads((PLUGIN / "open-studio.plugin.json").read_text(encoding="utf-8"))
        manifest = parse(raw, str(PLUGIN))
        assert manifest.runtime.kind == "process"
        assert manifest.runtime.entry == "tools/main.py"
        assert {t["name"] for t in manifest.declared_tools} == {"pan_list", "pan_search", "pan_import"}

    def test_只读的那两个标了只读(self) -> None:
        """标错的话,列目录这种纯查询也会被当成会改东西的工具,子智能体就用不了它。"""
        manifest = json.loads((PLUGIN / "open-studio.plugin.json").read_text(encoding="utf-8"))
        by_name = {t["name"]: t for t in manifest["tools"]["declare"]}
        assert by_name["pan_list"]["read_only"] is True
        assert by_name["pan_search"]["read_only"] is True
        assert by_name["pan_import"].get("read_only") is not True, "导入会往素材库里加东西,不是只读"


class Test和_artifact_通道合得上:
    def test_交出的形状宿主收得下(self, tmp_path, monkeypatch) -> None:
        """两边分开测都绿,不等于接缝对得上。

        这条把插件真的跑一遍,拿它吐出来的那份 artifact 原样喂给宿主的收口函数 —— 字段名
        错一个、请求头漏一层,这里就会红,而上面那些用例还是绿的。
        """
        from app.core.db import SessionLocal
        from app.domain.plugins import artifacts
        from app.domain.plugins.tools import _collect_artifact
        from tests.util import fresh_client

        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

        # 1. 插件跑一次,拿到它交出的东西
        out, _ = run("pan_import", {"fs_id": "111"}, [META_OK])
        plugin_output = out["output"]

        # 2. 宿主按那份 artifact 去下。这里把网络那一层换掉 —— 要验的是「字段对不对得上」,
        #    不是百度的服务器在不在。
        seen: dict = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_bytes(self):
                yield b"\x00\x00\x00\x18ftypmp42"

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

        with SessionLocal() as db:
            collected = _collect_artifact(
                db, plugin_output, scratch, workspace_id=ws, project_id=None, fallback_name="pan_import"
            )
            db.commit()

        # 3. 该到的都到了
        assert seen["headers"] == {"User-Agent": "pan.baidu.com"}, "必需的 UA 没传到下载那一步"
        assert "access_token=T" in seen["url"], "token 没传到下载那一步"
        assert collected["asset_name"] == "a.mp4"
        assert collected["asset_id"]
        assert "artifact" not in collected
        assert collected["fs_id"] == "111", "插件的其它输出被顺手丢了"
