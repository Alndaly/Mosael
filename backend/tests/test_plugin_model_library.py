"""模型库(ADR 0034):认领 `model_library` 的连接,宿主替它列模型、取预览图、解析链接、下载。

钉住的是**框架**,不是 ComfyUI(那个在 test_comfyui_plugin_model_library.py):

- 目录类能力:认领它的工具不进工具表,能力词表里叫得出名字;
- 列出来的是插件报的那一份,宿主规整字段(坏条目丢掉),预览图地址不交给界面 —— 界面拿宿主的地址;
- 预览图宿主按插件给的地址取回、记进磁盘缓存(第二次不再去取),没有的回 404;卡片和列表要的是缩略图(由原图缩一次、
  记在原图旁边),详情页拿到的还是原图;
- 下载是一个后台任务:进度经流式协议报进任务,取消经取消文件传到插件,下完让这个连接的目录重新拉一遍;
- 文件名带路径分隔符的、不是 http(s) 的链接,宿主当场拒绝,不交给插件。
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginPackage
from app.domain.plugins import runtime
from tests.util import fresh_client, wait_status

PACKAGE_ID = "test.models"
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe\x07\x00"

PLUGIN = r'''
import json, os, sys, time
from pathlib import Path

request = json.loads(sys.stdin.read())
payload = request["input"]
data = Path(os.environ["MOSAEL_PLUGIN_DATA_DIR"])
data.mkdir(parents=True, exist_ok=True)
port = os.environ["SERVER"]


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


op = payload.get("op")
with (data / "ops.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps(payload, ensure_ascii=False) + "\n")
if op == "models":
    emit({"ok": True, "output": {"models": [{"id": "flow.json", "label": "flow", "kind": "image"}]}})
elif op == "library":
    emit({"ok": True, "output": {
        "folders": [{"name": "checkpoints", "count": 1}, {"name": "loras", "count": 2}, {"name": "vae", "count": 0}],
        "models": [
            {"folder": "checkpoints", "name": "sdxl_base.safetensors", "size": 6938041004, "modified": 1700000000.5,
             "family": "SDXL", "family_source": "metadata", "used_by": [{"id": "wf.json", "label": "人像"}],
             "preview": f"http://127.0.0.1:{port}/preview/a"},
            {"folder": "loras", "name": "sub\\style.safetensors", "size": 228456516, "modified": 1700000001,
             "family": "Illustrious", "family_source": "filename", "triggers": ["1girl", "style"],
             "triggers_source": "tags", "title": "Style", "preview": "preview/missing"},
            {"folder": "loras", "name": "plain.safetensors", "size": None},
            {"folder": "", "name": "no-folder.safetensors"},
            {"name": "no-folder-either"},
            "not a dict",
        ],
        "missing": [{"folder": "vae", "name": "ae.safetensors",
                     "url": "https://huggingface.co/x/y/resolve/main/ae.safetensors",
                     "workflows": [{"id": "wf.json", "label": "人像"}]},
                    {"folder": "vae", "name": "bad", "url": "file:///etc/passwd"}],
        "download": {"route": "manager", "note": "经 ComfyUI-Manager 下载"},
        "preview_headers": {"Authorization": "Bearer secret-for-previews"},
        "preview_base": f"http://127.0.0.1:{port}/",
    }})
elif op == "detail":
    emit({"ok": True, "output": {"folder": payload["folder"], "name": payload["name"],
                                 "metadata": {"ss_base_model_version": "sdxl_base_v1-0", "modelspec.title": "Style"},
                                 "tags": [{"tag": "1girl", "count": 40}]}})
elif op == "resolve":
    if "nope" in payload["url"]:
        emit({"ok": False, "error": "这个链接认不出是哪个模型"})
    else:
        emit({"ok": True, "output": {"source": "huggingface", "url": payload["url"], "filename": "tiny.safetensors",
                                     "size": 4900000, "folder": "", "exists": False, "uses_token": True}})
elif op == "download":
    cancel = Path(os.environ["MOSAEL_PLUGIN_CANCEL_FILE"])
    emit({"event": "progress", "progress": 0.25, "message": "已下载 1.2 MB / 4.9 MB"})
    if payload["filename"] == "slow.safetensors":
        while not cancel.exists():
            time.sleep(0.05)
        (data / "cancelled").write_text("yes")
        emit({"ok": False, "error": "已取消"})
        sys.exit(0)
    emit({"event": "progress", "progress": 0.75, "message": "已下载 3.7 MB / 4.9 MB"})
    emit({"ok": True, "output": {"folder": payload["folder"], "name": payload["filename"], "size": 4900000,
                                 "route": "local"}})
else:
    emit({"ok": False, "error": f"unknown op {op}"})
'''


def _manifest(path: Path) -> dict[str, Any]:
    return {
        "id": PACKAGE_ID,
        "name": "测试模型库",
        "version": "1.0.0",
        "manifest_version": 1,
        "runtime": {"kind": "process", "entry": "main.py"},
        "provides": ["generation", "model_library"],
        "permissions": ["network:test"],
        "instance": {
            "multiple": True,
            "name_template": "测试模型库 · {SERVER}",
            "config": [{"key": "SERVER", "label": "服务器", "type": "string", "required": True}],
        },
        "tools": {
            "declare": [
                {"name": "host", "provides": ["generation", "model_library"], "timeout_seconds": 60,
                 "input_schema": {"type": "object"}},
                {"name": "ping", "description": "普通工具", "input_schema": {"type": "object"}},
            ]
        },
        "_path": str(path),
    }


class _Previews:
    """本机一个真的 HTTP 服务,替插件那一头的「预览图地址」:`/preview/a` 有图,别的 404;记下每次请求和带的头。"""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        #: 接下来几次请求回 503(那台机器一时忙不过来)。
        self.busy = 0
        #: `/preview/a` 回的那张图。
        self.body, self.kind = WEBP, "image/webp"
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — http.server 的约定
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization")})
                if outer.busy > 0:
                    outer.busy -= 1
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/preview/a":
                    self.send_response(200)
                    self.send_header("Content-Type", outer.kind)
                    self.send_header("Content-Length", str(len(outer.body)))
                    self.end_headers()
                    self.wfile.write(outer.body)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(autouse=True)
def _direct(monkeypatch):
    """开发机的 shell 里常挂着代理,本机那台假服务器要直连。"""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)


@pytest.fixture
def library(tmp_path: Path):
    previews = _Previews()
    shutil.rmtree(runtime.data_dir_for(PACKAGE_ID), ignore_errors=True)
    client = fresh_client()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "main.py").write_text(PLUGIN, encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE_ID, name="测试模型库", version="1.0.0", manifest=_manifest(plugin)))
        db.commit()
    created = client.post(f"/api/plugins/{PACKAGE_ID}/instances", json={"config": {"SERVER": str(previews.port)}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    assert client.patch(f"/api/plugins/instances/{instance_id}/permissions",
                        json={"grants": {"network:test": True}}).status_code == 200
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    yield client, instance_id, previews
    previews.close()
    shutil.rmtree(runtime.data_dir_for(PACKAGE_ID), ignore_errors=True)


def _ops() -> list[dict[str, Any]]:
    log = runtime.data_dir_for(PACKAGE_ID) / "ops.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "模型"}).json()["id"]


def test_模型库是目录类能力_认领它的工具不进工具表(library) -> None:
    client, instance_id, _ = library
    from app.db.models import PluginInstance
    from app.domain.plugins import tools

    with SessionLocal() as db:
        by_name = {tool["name"]: tool for tool in tools.all_tools(db, db.get(PluginInstance, instance_id))}
        assert by_name["host"]["internal"] is True, "回答「有哪些模型文件」的工具不是一次能交给智能体的调用"
        assert by_name["ping"]["internal"] is False
        assert "host" not in {tool["name"] for tool in tools.exposed(db, None)}
    terms = {one["name"]: one for one in client.get("/api/plugins/capabilities").json()}
    assert terms["model_library"]["label"] and terms["model_library"]["label"] != "model_library"


def test_列出插件报的模型_宿主规整字段_预览图换成宿主的地址(library) -> None:
    client, instance_id, previews = library
    response = client.get(f"/api/plugins/instances/{instance_id}/model-library")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(one["name"], one["count"]) for one in body["folders"]] == [("checkpoints", 1), ("loras", 2), ("vae", 0)]
    names = [(one["folder"], one["name"]) for one in body["models"]]
    assert names == [("checkpoints", "sdxl_base.safetensors"), ("loras", "sub\\style.safetensors"),
                     ("loras", "plain.safetensors")], "没有目录或名字的条目丢掉,不让界面上出现一张点不开的卡"
    first, second, third = body["models"]
    assert first["family"] == "SDXL" and first["family_source"] == "metadata"
    assert first["used_by"] == [{"id": "wf.json", "label": "人像"}]
    assert first["has_preview"] is True and third["has_preview"] is False
    assert second["triggers"] == ["1girl", "style"] and second["triggers_source"] == "tags"
    assert third["size"] is None and third["triggers"] == [] and third["family"] == ""
    text = response.text
    assert f"127.0.0.1:{previews.port}" not in text, "插件那一头的地址不交给界面:界面拿宿主的预览地址"
    assert "secret-for-previews" not in text, "取预览图用的凭据不能出现在给界面的回答里"
    assert body["download"] == {"route": "manager", "note": "经 ComfyUI-Manager 下载"}
    assert body["missing"] == [{"folder": "vae", "name": "ae.safetensors",
                                "url": "https://huggingface.co/x/y/resolve/main/ae.safetensors",
                                "workflows": [{"id": "wf.json", "label": "人像"}]}], "不是 http(s) 的声明地址不列"
    assert body["downloads"] == []


def test_预览图_宿主按插件给的地址取回_记进磁盘缓存_没有的回404(library) -> None:
    client, instance_id, previews = library
    assert client.get(f"/api/plugins/instances/{instance_id}/model-library").status_code == 200
    url = f"/api/plugins/instances/{instance_id}/model-library/preview"
    hit = client.get(url, params={"folder": "checkpoints", "name": "sdxl_base.safetensors"})
    assert hit.status_code == 200, hit.text
    assert hit.content == WEBP and hit.headers["content-type"] == "image/webp"
    assert previews.requests == [{"path": "/preview/a", "auth": "Bearer secret-for-previews"}], "带着插件给的头去取"
    again = client.get(url, params={"folder": "checkpoints", "name": "sdxl_base.safetensors"})
    assert again.status_code == 200 and again.content == WEBP
    assert len(previews.requests) == 1, "第二次从磁盘缓存给,不再去那台服务器取"
    missing = client.get(url, params={"folder": "loras", "name": "sub\\style.safetensors"})
    assert missing.status_code == 404
    client.get(url, params={"folder": "loras", "name": "sub\\style.safetensors"})
    assert len(previews.requests) == 2, "没有预览图的也记一笔,不每次都去问"
    assert previews.requests[1]["path"] == "/preview/missing", "相对地址按 preview_base 补全"
    assert client.get(url, params={"folder": "loras", "name": "plain.safetensors"}).status_code == 404
    assert client.get(url, params={"folder": "loras", "name": "nobody.safetensors"}).status_code == 404


def test_重启之后没列过也拿得到预览图(library) -> None:
    """宿主记着的地址只在内存里;重启后界面直接要预览图,宿主先替它列一遍。"""
    client, instance_id, _ = library
    from app.domain import model_library

    model_library.forget()
    hit = client.get(f"/api/plugins/instances/{instance_id}/model-library/preview",
                     params={"folder": "checkpoints", "name": "sdxl_base.safetensors"})
    assert hit.status_code == 200 and hit.content == WEBP


def test_重启后一屏预览图同时到_只替它列一遍(library) -> None:
    """模型库一打开就是几十张卡同时要预览图;宿主记着的地址没了(重启)时,不能每张图各让插件列一遍目录。"""
    client, instance_id, _ = library
    from concurrent.futures import ThreadPoolExecutor

    from app.db.models import PluginInstance
    from app.domain import model_library

    model_library.forget()

    def fetch(_index: int):
        with SessionLocal() as db:
            source = model_library.preview_source(db, db.get(PluginInstance, instance_id), "checkpoints",
                                                  "sdxl_base.safetensors")
            return source.original() if source else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, range(8)))
    assert all(result and result[0] == WEBP for result in results)
    assert sum(1 for one in _ops() if one["op"] == "library") == 1


def test_同一张图同时被要好几次_只去那台服务器取一次(library) -> None:
    """整套测试跑满时这里偶尔有一张拿不到:八个请求各自去取同一张图,那台机器一时接不过来,没取到的还被记成「没有图」。"""
    client, instance_id, previews = library
    from concurrent.futures import ThreadPoolExecutor

    from app.db.models import PluginInstance
    from app.domain import model_library

    assert client.get(f"/api/plugins/instances/{instance_id}/model-library").status_code == 200

    def fetch(_index: int):
        with SessionLocal() as db:
            source = model_library.preview_source(db, db.get(PluginInstance, instance_id), "checkpoints",
                                                  "sdxl_base.safetensors")
            return source.original() if source else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, range(8)))
    assert all(result and result[0] == WEBP for result in results)
    assert [one["path"] for one in previews.requests] == ["/preview/a"], "同一张图只取一次,其余等它落盘再读"


def test_那台机器一时忙不过来_不当成没有预览图(library) -> None:
    """503、连接断了是「这次没取到」,不是「这个模型没有预览图」:记成没有的话,这张卡要显示好一阵占位。"""
    client, instance_id, previews = library
    assert client.get(f"/api/plugins/instances/{instance_id}/model-library").status_code == 200
    url = f"/api/plugins/instances/{instance_id}/model-library/preview"
    previews.busy = 1
    first = client.get(url, params={"folder": "checkpoints", "name": "sdxl_base.safetensors"})
    assert first.status_code == 404
    again = client.get(url, params={"folder": "checkpoints", "name": "sdxl_base.safetensors"})
    assert again.status_code == 200 and again.content == WEBP, "下一次照常去取"


def _portrait_png() -> bytes:
    """一张真尺寸的预览图:1024×1536 的 PNG,左上角一块透明。"""
    import io

    from PIL import Image

    image = Image.new("RGBA", (1024, 1536), (200, 80, 40, 255))
    image.paste((0, 0, 0, 0), (0, 0, 256, 256))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_缩略图_宿主缩小一次记在原图旁边_详情拿到的还是原图(library) -> None:
    """卡片、列表一屏几十张,每张都解一张 1024×1536 的原图,滚动和悬停都卡:网格要的是缩略图(长边 512 的 WebP,
    透明照留),第一次要时由原图缩一次、记在原图旁边;详情页的大图还是原图,两者只去那台服务器取一次。"""
    import io

    from PIL import Image

    from app.core.config import settings

    client, instance_id, previews = library
    previews.body, previews.kind = _portrait_png(), "image/png"
    assert client.get(f"/api/plugins/instances/{instance_id}/model-library").status_code == 200
    params = {"folder": "checkpoints", "name": "sdxl_base.safetensors"}
    base = f"/api/plugins/instances/{instance_id}/model-library"

    small = client.get(f"{base}/thumbnail", params=params)
    assert small.status_code == 200, small.text
    assert small.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(small.content)) as image:
        assert image.size == (341, 512), "长边缩到 512,等比"
        assert image.mode == "RGBA" and image.getpixel((10, 10))[3] == 0, "透明的地方还是透明"
        assert image.getpixel((300, 400))[3] == 255
    cached = list((settings.data_dir / "model-previews" / instance_id).iterdir())
    assert sorted(path.name.split(".", 1)[-1] for path in cached if "." in path.name) == ["thumbnail.webp", "type"]
    assert len(cached) == 3, "原图、类型、缩略图三个文件记在一起"

    again = client.get(f"{base}/thumbnail", params=params)
    assert again.content == small.content
    full = client.get(f"{base}/preview", params=params)
    assert full.status_code == 200 and full.headers["content-type"] == "image/png"
    assert full.content == previews.body, "详情页的大图是原图,一个字节不差"
    assert len(previews.requests) == 1, "缩略图从磁盘给;原图在缩的时候已经落盘,详情不再去那台服务器取"

    missing = client.get(f"{base}/thumbnail", params={"folder": "loras", "name": "sub\\style.safetensors"})
    assert missing.status_code == 404
    client.get(f"{base}/thumbnail", params={"folder": "loras", "name": "sub\\style.safetensors"})
    assert len(previews.requests) == 2, "没有预览图的记一笔,缩略图也不每次都去问"


def test_排到去取时人已经走了_不取也不记成没有(library) -> None:
    """一路滚过去几百张卡,每张都发过一个缩略图请求,浏览器把滚出去的那些掐掉了:宿主排到去那台服务器取原图时先问一句
    人还在不在,不在就不取 —— 挨个去取的话,眼前这几张要排在它们后面等上几十秒。也不记成「没有预览图」:下次照常取。"""
    client, instance_id, previews = library
    from app.db.models import PluginInstance
    from app.domain import model_library

    assert client.get(f"/api/plugins/instances/{instance_id}/model-library").status_code == 200
    with SessionLocal() as db:
        source = model_library.preview_source(db, db.get(PluginInstance, instance_id), "checkpoints", "sdxl_base.safetensors")
    assert source is not None
    assert source.thumbnail(lambda: False) is None
    assert previews.requests == [], "人走了,不去那台服务器取"
    back = source.thumbnail()
    assert back is not None and back[1] == "image/webp"
    assert len(previews.requests) == 1


def test_排队等那台服务器的请求_不攥着数据库连接(library) -> None:
    """第一次打开模型库,一屏的缩略图请求同时到(滚一下又是一屏):它们排队等取图名额、等那台服务器的时候,数据库连接
    已经交还了 —— 此前每个都攥着一条排着,连接池(5 + 10)空了,详情、任务列表这些请求要等满 30 秒才报错。"""
    client, instance_id, previews = library
    import asyncio

    import httpx

    from app.core.db import engine
    from app.domain import model_library
    from app.main import app

    previews.body, previews.kind = _portrait_png(), "image/png"
    assert client.get(f"/api/plugins/instances/{instance_id}/model-library").status_code == 200
    slots = model_library._remote_slots.setdefault(instance_id, threading.BoundedSemaphore(model_library.REMOTE_FETCHES))
    for _ in range(model_library.REMOTE_FETCHES):
        slots.acquire()  # 那台服务器正忙:名额都占着

    async def scenario() -> tuple[int, list[httpx.Response]]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=dict(client.headers)) as http:
            url = f"/api/plugins/instances/{instance_id}/model-library/thumbnail"
            params = {"folder": "checkpoints", "name": "sdxl_base.safetensors"}
            held = engine.pool.checkedout()
            pending = asyncio.gather(*(http.get(url, params=params) for _ in range(12)))
            try:
                await asyncio.sleep(0.8)
                queued = engine.pool.checkedout() - held
            finally:
                for _ in range(model_library.REMOTE_FETCHES):
                    slots.release()
            return queued, await pending

    queued, responses = asyncio.run(scenario())
    assert queued <= 0, f"排着队的十二个请求一条连接都不该占,占了 {queued} 条"
    assert [one.status_code for one in responses] == [200] * 12
    assert all(one.headers["content-type"] == "image/webp" for one in responses)
    assert len(previews.requests) == 1


def test_缩略图_原图已经取过就直接缩_不再去取(library) -> None:
    """升级之前缓存里只有原图:要缩略图时就地从那份缩,不重新去那台服务器取。"""
    client, instance_id, previews = library
    previews.body, previews.kind = _portrait_png(), "image/png"
    assert client.get(f"/api/plugins/instances/{instance_id}/model-library").status_code == 200
    params = {"folder": "checkpoints", "name": "sdxl_base.safetensors"}
    base = f"/api/plugins/instances/{instance_id}/model-library"
    assert client.get(f"{base}/preview", params=params).status_code == 200
    small = client.get(f"{base}/thumbnail", params=params)
    assert small.status_code == 200 and small.headers["content-type"] == "image/webp"
    assert len(small.content) < len(previews.body)
    assert len(previews.requests) == 1


def test_详情_原样交回插件读到的元数据(library) -> None:
    client, instance_id, _ = library
    response = client.get(f"/api/plugins/instances/{instance_id}/model-library/detail",
                          params={"folder": "loras", "name": "sub\\style.safetensors"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["ss_base_model_version"] == "sdxl_base_v1-0"
    assert body["tags"] == [{"tag": "1girl", "count": 40}]
    assert _ops()[-1] == {"op": "detail", "folder": "loras", "name": "sub\\style.safetensors"}


def test_解析链接_插件认不出的原话报给人看(library) -> None:
    client, instance_id, _ = library
    url = f"/api/plugins/instances/{instance_id}/model-library/resolve"
    ok = client.post(url, json={"url": "https://huggingface.co/a/b/blob/main/tiny.safetensors"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["filename"] == "tiny.safetensors" and ok.json()["size"] == 4900000
    assert ok.json()["uses_token"] is True, "下载会不会带上那个站的令牌,照插件说的交给界面"
    bad = client.post(url, json={"url": "https://example.com/nope"})
    assert bad.status_code == 422 and "认不出" in bad.json()["detail"]
    local = client.post(url, json={"url": "file:///etc/passwd"})
    assert local.status_code == 422, "不是 http(s) 的链接宿主当场拒绝"
    assert all(one.get("url") != "file:///etc/passwd" for one in _ops())


def test_下载是一个后台任务_报进度_下完让连接的目录重新拉一遍(library) -> None:
    client, instance_id, _ = library
    workspace = _workspace(client)
    models_before = sum(1 for one in _ops() if one["op"] == "models")
    response = client.post(f"/api/plugins/instances/{instance_id}/model-library/downloads", json={
        "workspace_id": workspace, "url": "https://huggingface.co/a/b/resolve/main/tiny.safetensors",
        "folder": "vae_approx", "filename": "mosael-test-tiny.safetensors",
    })
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["kind"] == "model_download"
    assert wait_status(client, job["id"]) == "succeeded"
    done = client.get(f"/api/jobs/{job['id']}").json()
    assert done["result"] == {"folder": "vae_approx", "name": "mosael-test-tiny.safetensors", "size": 4900000,
                              "route": "local"}
    sent = next(one for one in _ops() if one["op"] == "download")
    assert sent == {"op": "download", "url": "https://huggingface.co/a/b/resolve/main/tiny.safetensors",
                    "folder": "vae_approx", "filename": "mosael-test-tiny.safetensors"}
    assert sum(1 for one in _ops() if one["op"] == "models") > models_before, "下完要让生成表单的下拉马上有它"
    listed = client.get(f"/api/plugins/instances/{instance_id}/model-library").json()
    assert [(one["id"], one["status"], one["payload"]["filename"]) for one in listed["downloads"]] == [
        (job["id"], "succeeded", "mosael-test-tiny.safetensors")]


def test_下载_取消经取消文件传到插件(library) -> None:
    client, instance_id, _ = library
    workspace = _workspace(client)
    job = client.post(f"/api/plugins/instances/{instance_id}/model-library/downloads", json={
        "workspace_id": workspace, "url": "https://huggingface.co/a/b/resolve/main/slow.safetensors",
        "folder": "loras", "filename": "slow.safetensors",
    }).json()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = client.get(f"/api/jobs/{job['id']}").json()
        if current["progress"] and current["progress"] >= 0.25:
            break
        time.sleep(0.05)
    assert "1.2 MB" in current["message"], "插件报的进度那句话进任务"
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    marker = runtime.data_dir_for(PACKAGE_ID) / "cancelled"
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), "插件没收到取消 —— 那边的下载就停不下来"


@pytest.mark.parametrize("filename", ["../evil.safetensors", "sub/evil.safetensors", "sub\\evil.safetensors", "", ".."])
def test_下载_文件名带路径的宿主当场拒绝(library, filename: str) -> None:
    client, instance_id, _ = library
    response = client.post(f"/api/plugins/instances/{instance_id}/model-library/downloads", json={
        "workspace_id": _workspace(client), "url": "https://huggingface.co/a/b/resolve/main/x.safetensors",
        "folder": "loras", "filename": filename,
    })
    assert response.status_code == 422, response.text
    assert not any(one["op"] == "download" for one in _ops())


def test_不提供模型库的连接_说清楚(library, tmp_path: Path) -> None:
    client, _, _ = library
    plugin = tmp_path / "plain"
    plugin.mkdir()
    (plugin / "main.py").write_text("print('{}')", encoding="utf-8")
    manifest = _manifest(plugin) | {"id": "test.plain", "provides": []}
    manifest["tools"] = {"declare": [{"name": "ping", "input_schema": {"type": "object"}}]}
    with SessionLocal() as db:
        db.add(PluginPackage(id="test.plain", name="普通插件", version="1.0.0", manifest=manifest))
        db.commit()
    instance_id = client.post("/api/plugins/test.plain/instances", json={"config": {"SERVER": "x"}}).json()["id"]
    response = client.get(f"/api/plugins/instances/{instance_id}/model-library")
    assert response.status_code == 422
    assert "模型库" in response.json()["detail"]
