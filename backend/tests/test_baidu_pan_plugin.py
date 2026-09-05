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
    raw = request.data or b""
    try:
        body = raw.decode("utf-8", "replace")[:400]
    except Exception:
        body = ""
    _CALLS.append({{"url": request.full_url, "headers": dict(request.headers), "body": body}})
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
        env={
            "PATH": "/usr/bin:/bin",
            "BAIDU_PAN_ACCESS_TOKEN": "T",
            "BAIDU_PAN_APP_KEY": "K",
            "BAIDU_PAN_SECRET_KEY": "S",
            "BAIDU_PAN_REFRESH_TOKEN": "R",
            **(env or {}),
        },
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

    def test_没给路径就从根目录列起(self) -> None:
        """这里**曾经**有个「起始目录」配置项,只在这一行起作用。

        它既不限制智能体去别的目录(照样能传 path),也不省事 —— 不指定路径时,列根目录和列
        某个子目录,下一步都要继续往里翻。名字听起来像一道边界,实际只是个默认值,却占着设置页
        一整行去解释一件它没做的事。删了;要真把智能体圈在某个目录里,得让**所有**路径操作受限。
        """
        out, calls = run("pan_list", {}, [LIST_OK])
        assert out["output"]["path"] == "/"
        assert "dir=%2F" in calls[0]["url"]

    def test_limit_夹在上限内(self) -> None:
        _, calls = run("pan_list", {"limit": 99999}, [LIST_OK])
        assert "limit=1000" in calls[0]["url"]

    def test_对方不照办时也只返回那么多条(self) -> None:
        """**这条才是 limit 的意义所在。**

        原来只断言「limit 拼进了 URL」—— 验证的是我们问了,不是我们兑现了。而百度这个接口
        恰好收下 limit 却不照办:实测 limit=2 和 limit=10 都回了根目录全部 57 条,于是几十条
        目录直接进了模型的上下文,而这正是这个参数当初被加进来要防的事。

        声明了就得做到。对调用方来说,"我们问了、对方没听"和没有这个参数完全一样。
        """
        many = {"errno": 0, "list": [
            {"fs_id": i, "server_filename": f"f{i}", "path": f"/f{i}", "isdir": 0, "size": 1}
            for i in range(57)
        ]}
        out, calls = run("pan_list", {"limit": 2}, [many])
        assert "limit=2" in calls[0]["url"], "照样要问 —— 哪天它生效就能少传一大段回来"
        assert len(out["output"]["entries"]) == 2

    def test_对方给得比要的少就照给(self) -> None:
        """兜底是**截断**,不是补齐 —— 目录里只有 3 个文件时不该硬凑出 10 条。"""
        few = {"errno": 0, "list": [
            {"fs_id": i, "server_filename": f"f{i}", "path": f"/f{i}", "isdir": 0, "size": 1}
            for i in range(3)
        ]}
        out, _ = run("pan_list", {"limit": 10}, [few])
        assert len(out["output"]["entries"]) == 3


class Test搜索:
    def test_带上递归(self) -> None:
        """不递归的话,只搜当前一层 —— 而用它的场景恰恰是「不知道在哪一层」。"""
        _, calls = run("pan_search", {"keyword": "海边"}, [LIST_OK])
        assert "recursion=1" in calls[0]["url"]

    def test_搜索也自己保证条数(self) -> None:
        """搜索天然会命中一大片(实测一个词回了 50 条),而这些条目直接进模型的上下文 ——
        一次没约束的搜索能顶掉半个对话的可用篇幅。"""
        many = {"errno": 0, "list": [
            {"fs_id": i, "server_filename": f"f{i}", "path": f"/f{i}", "isdir": 0, "size": 1}
            for i in range(50)
        ]}
        out, calls = run("pan_search", {"keyword": "demo", "limit": 3}, [many])
        assert len(out["output"]["entries"]) == 3
        # 不往请求里塞:百度的 search 没有这个参数,凭空发一个只会让人以为是它在起作用。
        assert "limit=" not in calls[0]["url"]

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
        [(-9, "不存在"), (31034, "限流"), (99999, "errno=99999")],
    )
    def test_百度用_errno_表达失败_HTTP_永远是_200(self, errno: int, expect: str) -> None:
        """光报一个数字等于让用户去搜,而这几个的处置方式完全不同:换 token / 换文件 / 等一会儿。"""
        out, _ = run("pan_list", {}, [{"errno": errno}])
        assert out["ok"] is False and expect in out["error"]

    def test_什么都没配时直接说(self) -> None:
        out, _ = run(
            "pan_list",
            {},
            [],
            env={"BAIDU_PAN_ACCESS_TOKEN": "", "BAIDU_PAN_APP_KEY": "", "BAIDU_PAN_SECRET_KEY": "", "BAIDU_PAN_REFRESH_TOKEN": ""},
        )
        assert out["ok"] is False and "AppKey" in out["error"]

    def test_不认识的工具名(self) -> None:
        out, _ = run("nope", {}, [])
        assert out["ok"] is False and "unknown tool" in out["error"]


class Test清单和实现对得上:
    def test_声明的工具都实现了(self) -> None:
        """声明即接口 —— 声明了没实现的话,用户在插件页勾得上,一调就是「unknown tool」。"""
        manifest = json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))
        declared = {t["name"] for t in manifest["tools"]["declare"]}
        source = ENTRY.read_text(encoding="utf-8")
        implemented = set(json.loads(json.dumps(sorted(declared))))  # 名字集合
        for name in implemented:
            assert f"def {name}(" in source, f"清单声明了 {name} 但没实现"
        assert "TOOLS = {" in source

    def test_清单能被宿主解析(self) -> None:
        from app.domain.plugins.manifest import parse

        raw = json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))
        manifest = parse(raw, str(PLUGIN))
        assert manifest.runtime.kind == "process"
        assert manifest.runtime.entry == "tools/main.py"
        assert {t["name"] for t in manifest.declared_tools} == {"pan_list", "pan_search", "pan_import", "pan_upload"}

    def test_只读的那两个标了只读(self) -> None:
        """标错的话,列目录这种纯查询也会被当成会改东西的工具,子智能体就用不了它。"""
        manifest = json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))
        by_name = {t["name"]: t for t in manifest["tools"]["declare"]}
        assert by_name["pan_list"]["read_only"] is True
        assert by_name["pan_search"]["read_only"] is True
        assert by_name["pan_import"].get("read_only") is not True, "导入会往素材库里加东西,不是只读"
        assert by_name["pan_upload"].get("read_only") is not True, "上传会往网盘里写东西,不是只读"


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


class Test自动续期:
    """access_token 三十天到期。用户只填一次 refresh_token,之后由插件自己续。

    这条路以前不存在 —— 插件是无状态的,续出来的新令牌没地方放,于是只能让用户三十天
    回来粘一次。现在响应里多了个 `state` 槽(见 domain/plugins/state)。
    """

    def test_撞上过期就续一次并重试(self) -> None:
        out, calls = run(
            "pan_list",
            {},
            [{"errno": 111}, {"access_token": "NEW", "refresh_token": "R"}, LIST_OK],
        )
        assert out["ok"], out.get("error")
        assert len(calls) == 3, "没有续期重试"
        assert "oauth/2.0/token" in calls[1]["url"]
        assert "access_token=NEW" in calls[2]["url"], "重试还在用那个已经过期的令牌"

    def test_续出来的令牌交回去记住(self) -> None:
        """不交回去的话,下一次调用又是「过期 → 续 → 重试」,每次都白跑一趟。"""
        out, _ = run("pan_list", {}, [{"errno": 111}, {"access_token": "NEW", "refresh_token": "R"}, LIST_OK])
        assert out["state"]["BAIDU_PAN_ACCESS_TOKEN"] == "NEW"

    def test_轮换出来的_refresh_token_也要记(self) -> None:
        """百度换 token 时会连 refresh_token 一起轮换。只存 access_token 的话,三十天后
        拿着一个已经作废的 refresh_token 去换,得到的是一个查不出原因的失败。"""
        out, _ = run("pan_list", {}, [{"errno": 111}, {"access_token": "NEW", "refresh_token": "R2"}, LIST_OK])
        assert out["state"]["BAIDU_PAN_REFRESH_TOKEN"] == "R2"

    def test_没轮换就不写那一项(self) -> None:
        """原样写回去不算错,但每次调用都重写一遍数据库是白费的。"""
        out, _ = run("pan_list", {}, [{"errno": 111}, {"access_token": "NEW", "refresh_token": "R"}, LIST_OK])
        assert "BAIDU_PAN_REFRESH_TOKEN" not in out["state"]

    def test_没续期时不带_state(self) -> None:
        """一切正常的调用不该顺手重写一遍凭据。"""
        out, _ = run("pan_list", {}, [LIST_OK])
        assert "state" not in out

    def test_一个令牌都没有时直接去换(self) -> None:
        """第一次用:用户只填了 refresh_token,access_token 那栏留空。"""
        out, calls = run(
            "pan_list",
            {},
            [{"access_token": "FIRST", "refresh_token": "R"}, LIST_OK],
            env={"BAIDU_PAN_ACCESS_TOKEN": ""},
        )
        assert out["ok"], out.get("error")
        assert "oauth/2.0/token" in calls[0]["url"]
        assert "access_token=FIRST" in calls[1]["url"]

    def test_只重试一次(self) -> None:
        """续完还是过期,说明问题不在有效期上(AppKey 不对、应用被停用)。
        再试就是拿同一个错误刷接口。"""
        out, calls = run(
            "pan_list",
            {},
            [{"errno": 111}, {"access_token": "NEW", "refresh_token": "R"}, {"errno": 111}],
        )
        assert out["ok"] is False and "回设置里检查" in out["error"]
        assert len(calls) == 3, "重试了不止一次"

    def test_refresh_token_作废时说得明白(self) -> None:
        out, _ = run(
            "pan_list",
            {},
            [{"errno": 111}, {"error": "invalid_grant", "error_description": "refresh token 已过期"}],
        )
        assert out["ok"] is False and "重新走一次授权" in out["error"]

    def test_导入那条路也会续期(self) -> None:
        """续期在 _call 里,不是在某个工具里 —— 三个工具都该受益。"""
        out, calls = run(
            "pan_import",
            {"fs_id": "111"},
            [{"errno": 111}, {"access_token": "NEW", "refresh_token": "R"}, META_OK],
        )
        assert out["ok"], out.get("error")
        # 交给宿主的下载地址要用**续过的**那个,不是过期的那个
        assert "access_token=NEW" in out["output"]["artifact"]["url"]


UPLOAD_PRE = {"errno": 0, "uploadid": "U1"}
UPLOAD_CHUNK = {"md5": "x"}
UPLOAD_CREATE = {"errno": 0, "fs_id": 777, "path": "/我的资源/成片.mp4"}


class Test上传:
    """素材库 → 网盘。百度的上传协议本身就是三步,不是我们绕远。"""

    def _run(self, tmp_path, payload: dict, responses: list, size: int = 100):
        local = tmp_path / "成片.mp4"
        local.write_bytes(b"x" * size)
        return run("pan_upload", {**payload, "asset_id": str(local)}, responses)

    def test_三步都走(self, tmp_path) -> None:
        """少一步都不行:只传不 create 的话,文件在网盘上根本不存在,而 superfile2 全返回成功。"""
        out, calls = self._run(tmp_path, {"path": "/我的资源/成片.mp4"},
                               [UPLOAD_PRE, UPLOAD_CHUNK, UPLOAD_CREATE])
        assert out["ok"], out.get("error")
        assert "method=precreate" in calls[0]["url"]
        assert "superfile2" in calls[1]["url"]
        assert "method=create" in calls[2]["url"]
        assert out["output"]["fs_id"] == "777"

    def test_秒传时一个字节都不传(self, tmp_path) -> None:
        """百度认得这些分片就直接给 return_type=2 —— 再传一遍是纯浪费。"""
        out, calls = self._run(
            tmp_path, {"path": "/x.mp4"},
            [{"errno": 0, "return_type": 2, "info": {"fs_id": 999, "path": "/x.mp4"}}],
        )
        assert out["ok"] and out["output"]["rapid"] is True
        assert len(calls) == 1, "秒传还传了分片"

    def test_大文件按_4MB_分片(self, tmp_path) -> None:
        """分片大小是百度规定的,不是可调参数 —— 换个数字 precreate 报的 md5 清单就对不上。"""
        out, calls = self._run(
            tmp_path, {"path": "/big.mp4"},
            [UPLOAD_PRE, UPLOAD_CHUNK, UPLOAD_CHUNK, UPLOAD_CHUNK, UPLOAD_CREATE],
            size=9 * 1024 * 1024,  # 9MB → 3 片
        )
        assert out["ok"], out.get("error")
        chunks = [c for c in calls if "superfile2" in c["url"]]
        assert len(chunks) == 3
        assert [int(c["url"].split("partseq=")[1].split("&")[0]) for c in chunks] == [0, 1, 2]

    def test_默认不覆盖(self, tmp_path) -> None:
        """传错一次就把人家网盘上的东西冲掉,这个代价比多一个副本大得多。"""
        _, calls = self._run(tmp_path, {"path": "/x.mp4"}, [UPLOAD_PRE, UPLOAD_CHUNK, UPLOAD_CREATE])
        assert "rtype=1" in calls[0]["body"], "默认成了覆盖"

    def test_明确要求才覆盖(self, tmp_path) -> None:
        _, calls = self._run(tmp_path, {"path": "/x.mp4", "overwrite": True},
                             [UPLOAD_PRE, UPLOAD_CHUNK, UPLOAD_CREATE])
        assert "rtype=3" in calls[0]["body"]

    def test_路径要含文件名(self, tmp_path) -> None:
        out, _ = self._run(tmp_path, {"path": "/我的资源/"}, [])
        assert out["ok"] is False and "文件名" in out["error"]

    def test_空文件挡住(self, tmp_path) -> None:
        out, _ = self._run(tmp_path, {"path": "/x.mp4"}, [], size=0)
        assert out["ok"] is False and "空的" in out["error"]

    def test_插件拿到的是路径而不是_id(self) -> None:
        """`asset_id` 在清单里标了 format:asset,宿主交过来的已经是本地路径
        (见 tests/test_plugin_inputs)。插件这一侧不知道素材库存在。"""
        manifest = json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))
        upload = next(t for t in manifest["tools"]["declare"] if t["name"] == "pan_upload")
        assert upload["input_schema"]["properties"]["asset_id"]["format"] == "asset"
        source = ENTRY.read_text(encoding="utf-8")
        assert "os.path.isfile(local)" in source, "没把它当路径用"
