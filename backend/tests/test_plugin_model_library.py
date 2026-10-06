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
             "preview": f"http://127.0.0.1:{port}/preview/a",
             **({"preview_file": "raw%2Fsdxl_base.png"} if (data / "lossless").exists() else {}),
             "nsfw_signals": [{"source": "metadata", "nsfw": True, "tags": ["nude"], "words": []},
                              {"source": "local", "nsfw": True}, {"source": "civitai"}, "junk"]},
            {"folder": "loras", "name": "sub\\style.safetensors", "size": 228456516, "modified": 1700000001,
             "family": "Illustrious", "family_source": "filename", "triggers": ["1girl", "style"],
             "triggers_source": "tags", "title": "Style", "preview": "preview/missing",
             "nsfw_signals": [{"source": "civitai", "nsfw": False}],
             "source": {"page": "https://civitai.com/models/1?modelVersionId=2", "site": "civitai",
                        "how": (data / "how").read_text() if (data / "how").exists() else "sha256"},
             # 作者排在最前的那张分级高,后面那张最低
             "remote_previews": [] if (data / "no-remote").exists() else [
                 {"url": f"http://127.0.0.1:{port}/elsewhere/clip.mp4", "kind": "video", "site": "civitai", "level": 1, "nsfw": False}
             ] if (data / "remote-video").exists() else [
                 {"url": f"http://127.0.0.1:{port}/elsewhere/spicy", "kind": "image", "site": "civitai", "level": 8, "nsfw": True},
                 {"url": f"http://127.0.0.1:{port}/elsewhere/safe", "kind": "image", "site": "civitai", "level": 1, "nsfw": False},
                 {"url": "file:///etc/passwd", "kind": "image", "site": "civitai", "level": 1}]},
            {"folder": "loras", "name": "plain.safetensors", "size": None,
             **({"sidecars": ["plain.mp4"]} if (data / "video-sidecar").exists() else {})},
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
        "sidecar_base": f"http://127.0.0.1:{port}/sidecar/",
        "preview_tools": {"lookup": "sha256", "save": not (data / "no-save").exists(),
                          "save_note": "缺 ComfyUI-Custom-Scripts" if (data / "no-save").exists() else ""},
    }})
elif op == "lookup":
    found = payload["name"] != "plain.safetensors" or (data / "plain-found").exists()
    match = (data / "lookup-match").read_text() if (data / "lookup-match").exists() else "sha256"
    page = "https://civitai.com/models/9?modelVersionId=10"
    emit({"ok": True, "output": {"match": match if found else "none", "page": page if found else "", "note": "",
                                 **({"source": {"page": page, "site": "civitai", "how": match}} if found else {}),
                                 "remote_previews": [{"url": f"http://127.0.0.1:{port}/elsewhere/safe", "kind": "image",
                                                      "site": "civitai", "level": 1, "nsfw": False}] if found else []}})
elif op == "save_preview":
    (data / "saved.bin").write_bytes(Path(payload["path"]).read_bytes())
    (data / "saved-name").write_text(Path(payload["path"]).name)
    emit({"ok": True, "output": {"folder": payload["folder"], "name": payload["name"], "saved": "loras/style.png"}})
elif op == "node_folders":
    emit({"ok": True, "output": {"folders": ["checkpoints" if one["input"] == "ckpt_name" else
                                             "../etc" if one["input"] == "evil" else "" for one in payload["nodes"]]}})
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
elif op == "search_sources":
    if payload["filename"] == "boom.safetensors":
        emit({"ok": False, "error": "三个站都搜不了"})
    else:
        emit({"ok": True, "output": {"filename": payload["filename"], "candidates": [
            {"source": "huggingface", "repo": "Comfy-Org/flux1-dev", "title": "Comfy-Org/flux1-dev",
             "filename": "flux1-dev-fp8.safetensors", "size": 17246524772, "base_model": "", "exact": True,
             "url": "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors",
             "page": "https://huggingface.co/Comfy-Org/flux1-dev/blob/main/flux1-dev-fp8.safetensors"},
            {"source": "civitai", "repo": "DreamShaper", "title": "DreamShaper · 8", "filename": "dreamshaper_8.safetensors",
             "url": "https://civitai.com/api/download/models/128713", "page": "file:///etc/passwd", "size": 2132625894.0,
             "base_model": "SD 1.5", "exact": False},
            {"source": "civitai", "filename": "local.safetensors", "url": "file:///etc/passwd"},
            {"source": "civitai", "filename": "", "url": "https://civitai.com/api/download/models/1"},
            "not a dict",
        ], "failed": [{"source": "modelscope", "message": "ModelScope 连不上或超时了"}, {"source": "civitai"}]}})
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


def _colored_png(color: tuple[int, int, int], size: tuple[int, int] = (1024, 1536)) -> bytes:
    """一张别处的示例图:纯色的大图(1024×1536,比要写回那台服务器的 512 宽大)。"""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


_VIDEO: list[bytes] = []


def _sample_video() -> bytes:
    """一段真的示例视频:1280×720、两秒、带声音(Civitai 没转好时给的原片就是这样)。生成一次,之后复用。"""
    if not _VIDEO:
        import subprocess
        import tempfile

        from app.core.config import settings

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample.mp4"
            subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=10",
                            "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", str(target)], check=True, capture_output=True)
            _VIDEO.append(target.read_bytes())
    return _VIDEO[0]


def _video_facts(content: bytes) -> dict[str, Any]:
    """一段视频的宽、高、有没有声音。"""
    import subprocess
    import tempfile

    from app.core.config import settings

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v.mp4"
        path.write_bytes(content)
        streams = json.loads(subprocess.run([settings.ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height",
                                             "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout)["streams"]
    video = next(one for one in streams if one["codec_type"] == "video")
    return {"width": video["width"], "height": video["height"], "audio": any(one["codec_type"] == "audio" for one in streams)}


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
                if self.path in ("/sidecar/plain.mp4", "/elsewhere/clip.mp4"):
                    body = _sample_video()
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/sidecar/raw%2Fsdxl_base.png":
                    body = _colored_png((20, 160, 80), (384, 480))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path in ("/elsewhere/safe", "/elsewhere/spicy"):
                    body = _colored_png((20, 160, 80) if self.path.endswith("safe") else (200, 30, 30))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
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


def _no_elsewhere() -> None:
    """这一回插件不交别处(Civitai)的示例图:测「那台服务器上没有预览图」本身。"""
    data = runtime.data_dir_for(PACKAGE_ID)
    data.mkdir(parents=True, exist_ok=True)
    (data / "no-remote").write_text("1")


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
    _no_elsewhere()
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
    _no_elsewhere()
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
    cached = [path for path in (settings.data_dir / "model-previews" / instance_id).iterdir()
              if path.name != "server-previews.json"]
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
    from app.main import app

    previews.body, previews.kind = _portrait_png(), "image/png"
    assert client.get(f"/api/plugins/instances/{instance_id}/model-library").status_code == 200
    from app.domain import model_previews

    slots = model_previews._slots.setdefault(f"server:{instance_id}", threading.BoundedSemaphore(model_previews.SERVER_FETCHES))
    for _ in range(model_previews.SERVER_FETCHES):
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
                for _ in range(model_previews.SERVER_FETCHES):
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


def test_按文件名找下载地址_插件交回候选_宿主规整(library) -> None:
    """工作台「缺失项」里工作流没写地址的模型:插件去模型站上搜,宿主只规整 —— 没有 http(s) 地址或文件名的候选丢掉,
    页面地址不是 http(s) 的当没给,没说原因的失败不交;插件说的错原话报给人看。"""
    client, instance_id, _ = library
    url = f"/api/plugins/instances/{instance_id}/model-library/search"
    ok = client.post(url, json={"filename": "flux1-dev-fp8.safetensors", "folder": "checkpoints"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["filename"] == "flux1-dev-fp8.safetensors"
    assert [(one["source"], one["filename"], one["exact"]) for one in body["candidates"]] == [
        ("huggingface", "flux1-dev-fp8.safetensors", True), ("civitai", "dreamshaper_8.safetensors", False)]
    first, second = body["candidates"]
    assert first["url"] == "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors"
    assert (first["repo"], first["size"], first["page"]) == (
        "Comfy-Org/flux1-dev", 17246524772, "https://huggingface.co/Comfy-Org/flux1-dev/blob/main/flux1-dev-fp8.safetensors")
    assert (second["title"], second["size"], second["base_model"], second["page"]) == (
        "DreamShaper · 8", 2132625894, "SD 1.5", ""), "不是 http(s) 的页面地址当没给"
    assert body["failed"] == [{"source": "modelscope", "message": "ModelScope 连不上或超时了"}]
    assert _ops()[-1] == {"op": "search_sources", "filename": "flux1-dev-fp8.safetensors", "folder": "checkpoints"}
    bad = client.post(url, json={"filename": "boom.safetensors"})
    assert bad.status_code == 422 and "搜不了" in bad.json()["detail"]
    assert client.post(url, json={"filename": ""}).status_code == 422, "空文件名宿主当场拒绝"
    assert client.post(url, json={"filename": "x" * 301}).status_code == 422


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
    search = client.post(f"/api/plugins/instances/{instance_id}/model-library/search", json={"filename": "x.safetensors"})
    assert search.status_code == 422 and "模型库" in search.json()["detail"]


def test_工作台_选中节点那一格是哪个模型目录_插件给的不像目录名就当不是(library) -> None:
    client, instance_id, _ = library
    response = client.post(f"/api/plugins/instances/{instance_id}/model-library/node-folders", json={"nodes": [
        {"class_type": "CheckpointLoaderSimple", "input": "ckpt_name"}, {"class_type": "KSampler", "input": "steps"},
        {"class_type": "X", "input": "evil"}]})
    assert response.status_code == 200, response.text
    assert response.json() == {"folders": ["checkpoints", "", ""]}
    sent = [op for op in _ops() if op["op"] == "node_folders"][-1]
    assert sent["nodes"][0] == {"class_type": "CheckpointLoaderSimple", "input": "ckpt_name"}
    too_many = client.post(f"/api/plugins/instances/{instance_id}/model-library/node-folders",
                           json={"nodes": [{"class_type": "X", "input": "y"}] * 65})
    assert too_many.status_code == 422


# --- NSFW:几种依据合成一个判断(ADR 0038 §9) -----------------------------------

def test_NSFW判断_手动标记压过自动的_没标时任一种说是就算是() -> None:
    from app.domain.model_library import nsfw_verdict

    metadata = {"source": "metadata", "nsfw": True, "tags": ["nude"]}
    civitai_no = {"source": "civitai", "nsfw": False}
    civitai_yes = {"source": "civitai", "nsfw": True, "level": 8}
    assert nsfw_verdict(None, []) == {"flagged": False, "manual": None, "reasons": []}, "没有依据就不算"
    assert nsfw_verdict(None, [civitai_no])["flagged"] is False
    assert nsfw_verdict(None, [civitai_no, metadata])["flagged"] is True, "任一种说是就算是:宁可多藏一张"
    assert [one["source"] for one in nsfw_verdict(None, [metadata, civitai_yes])["reasons"]] == ["civitai", "metadata"], \
        "依据按 Civitai、本机识别、元数据的顺序列"
    overruled = nsfw_verdict(False, [metadata, civitai_yes])
    assert overruled["flagged"] is False and overruled["manual"] is False, "手动标了「不是」:自动判错了能改"
    assert len(overruled["reasons"]) == 2, "自动的依据照样交,悬停看得到"
    assert nsfw_verdict(True, [civitai_no])["flagged"] is True, "手动也能标成「是」"


def test_列出时带上NSFW判断_插件交的依据规整过(library) -> None:
    client, instance_id, _ = library
    models = client.get(f"/api/plugins/instances/{instance_id}/model-library").json()["models"]
    first, second, third = models
    assert first["nsfw"] == {"flagged": True, "manual": None, "reasons": [
        {"source": "metadata", "nsfw": True, "tags": ["nude"], "words": [], "level": None, "score": None}]}, \
        "插件说不出本机识别那一条(那是宿主的);缺 nsfw 的、不是对象的丢掉"
    assert second["nsfw"]["flagged"] is False and second["nsfw"]["reasons"][0]["source"] == "civitai"
    assert third["nsfw"] == {"flagged": False, "manual": None, "reasons": []}


def test_手动标NSFW_压过自动的_去掉标记回到自动_按正斜杠记(library) -> None:
    client, instance_id, _ = library
    url = f"/api/plugins/instances/{instance_id}/model-library"
    client.get(url)
    # 自动说是 → 手动标成不是
    answer = client.put(f"{url}/nsfw", json={"folder": "checkpoints", "name": "sdxl_base.safetensors", "nsfw": False})
    assert answer.status_code == 200, answer.text
    assert answer.json()["flagged"] is False and answer.json()["manual"] is False
    assert [one["source"] for one in answer.json()["reasons"]] == ["metadata"], "自动的依据照样带着"
    # Windows 的反斜杠和正斜杠是同一个文件
    marked = client.put(f"{url}/nsfw", json={"folder": "loras", "name": "sub/style.safetensors", "nsfw": True}).json()
    assert marked == {"flagged": True, "manual": True,
                      "reasons": [{"source": "civitai", "nsfw": False, "tags": [], "words": [], "level": None, "score": None}]}
    listed = {one["name"]: one["nsfw"] for one in client.get(url).json()["models"]}
    assert listed["sdxl_base.safetensors"]["manual"] is False and listed["sdxl_base.safetensors"]["flagged"] is False
    assert listed["sub\\style.safetensors"]["manual"] is True, "插件报的是反斜杠,标记按正斜杠记,对得上"
    cleared = client.put(f"{url}/nsfw", json={"folder": "checkpoints", "name": "sdxl_base.safetensors", "nsfw": None}).json()
    assert cleared["manual"] is None and cleared["flagged"] is True, "去掉标记:回到自动判断"
    assert {op.get("op") for op in _ops()} <= {"library", "models", "tools", "fingerprint"}, \
        "标记只记在 Mosael 这边,不让插件改那台服务器"


def test_手动标记按连接分_连接删了跟着删(library) -> None:
    client, instance_id, previews = library
    from sqlalchemy import select

    from app.db.models import ModelFileMark

    url = f"/api/plugins/instances/{instance_id}/model-library"
    client.get(url)
    assert client.put(f"{url}/nsfw", json={"folder": "loras", "name": "plain.safetensors", "nsfw": True}).status_code == 200
    other = client.post(f"/api/plugins/{PACKAGE_ID}/instances", json={"config": {"SERVER": str(previews.port)}}).json()["id"]
    assert client.patch(f"/api/plugins/instances/{other}/permissions",
                        json={"grants": {"network:test": True}}).status_code == 200
    assert client.patch(f"/api/plugins/instances/{other}", json={"enabled": True}).status_code == 200
    elsewhere = {one["name"]: one["nsfw"]
                 for one in client.get(f"/api/plugins/instances/{other}/model-library").json()["models"]}
    assert elsewhere["plain.safetensors"]["manual"] is None, "另一个连接(可能指着另一台服务器)不沾这个标记"
    assert client.delete(f"/api/plugins/instances/{instance_id}").status_code == 204
    with SessionLocal() as db:
        assert not db.scalars(select(ModelFileMark).where(ModelFileMark.instance_id == instance_id)).all()


# --- 别处的示例图(Civitai):那台服务器上没有预览图时用它,存回去(ADR 0038 §9) ------------

def _origin(client, instance_id: str, name: str, pick: str = "safest") -> dict:
    body = client.get(f"/api/plugins/instances/{instance_id}/model-library", params={"pick": pick}).json()
    return next(one for one in body["models"] if one["name"] == name)


def _pixel(content: bytes) -> tuple[int, ...]:
    import io

    from PIL import Image

    with Image.open(io.BytesIO(content)) as image:
        return image.convert("RGB").getpixel((5, 5))


def test_那台服务器上没有预览图_用别处的示例图_缺省挑分级最低的_不带那台服务器的头(library) -> None:
    client, instance_id, previews = library
    first = _origin(client, instance_id, "sub\\style.safetensors")
    assert first["has_preview"] is True
    assert first["preview_origin"] == "", "那台服务器上有没有还没问过:说不准"
    assert first["source"] == {"page": "https://civitai.com/models/1?modelVersionId=2", "site": "civitai", "how": "sha256"}
    thumb = client.get(f"/api/plugins/instances/{instance_id}/model-library/thumbnail",
                       params={"folder": "loras", "name": "sub\\style.safetensors"})
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    assert _pixel(thumb.content)[1] > 100, "缺省挑分级最低的那张(绿的)"
    asked = [one for one in previews.requests if one["path"].startswith("/elsewhere/")]
    assert asked == [{"path": "/elsewhere/safe", "auth": None}], "别处的不带那台服务器的访问凭据"
    assert [one["path"] for one in previews.requests if one["path"] == "/preview/missing"], "先问过那台服务器"

    after = _origin(client, instance_id, "sub\\style.safetensors")
    assert after["preview_origin"] == "civitai", "那台服务器说没有:显示的是 Civitai 的那张"
    assert [(one["source"], one["nsfw"], one["level"]) for one in after["nsfw"]["reasons"]] == [("civitai", False, 1)], \
        "显示的是这张示例图:它自己的分级就是依据"


def test_NSFW照常时挑作者排在最前的那张_判断跟着那张图(library) -> None:
    client, instance_id, _ = library
    params = {"folder": "loras", "name": "sub\\style.safetensors", "pick": "cover"}
    thumb = client.get(f"/api/plugins/instances/{instance_id}/model-library/thumbnail", params=params)
    assert thumb.status_code == 200 and _pixel(thumb.content)[0] > 150, "作者排在最前的那张(红的)"
    cover = _origin(client, instance_id, "sub\\style.safetensors", pick="cover")
    assert cover["preview_origin"] == "civitai"
    assert cover["nsfw"]["flagged"] is True and cover["nsfw"]["reasons"][0]["level"] == 8
    assert _origin(client, instance_id, "sub\\style.safetensors")["nsfw"]["flagged"] is False


def test_存为预览图_取别处那张_缩到512宽的PNG_交插件写回_之后重新去问那台服务器(library) -> None:
    import io

    from PIL import Image

    from app.domain import model_previews

    client, instance_id, _ = library
    base = f"/api/plugins/instances/{instance_id}/model-library"
    client.get(f"{base}/thumbnail", params={"folder": "loras", "name": "sub\\style.safetensors"})
    saved = client.post(f"{base}/save-preview", json={"folder": "loras", "name": "sub\\style.safetensors"})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"folder": "loras", "name": "sub\\style.safetensors", "saved": "loras/style.png"}
    data = runtime.data_dir_for(PACKAGE_ID)
    assert (data / "saved-name").read_text() == "preview.png"
    with Image.open(io.BytesIO((data / "saved.bin").read_bytes())) as image:
        assert image.format == "PNG" and image.size == (512, 768), "缩到 512 宽,等比"
        assert image.convert("RGB").getpixel((5, 5))[1] > 100
    assert model_previews.server_status(instance_id, "loras", "sub\\style.safetensors") == "found", "写回了:那台服务器上的取代别处的"
    assert model_previews.server_kind(instance_id, "loras", "sub\\style.safetensors") == "image"
    save_ops = [one for one in _ops() if one["op"] == "save_preview"]
    assert len(save_ops) == 1 and save_ops[0]["folder"] == "loras"
    again = client.post(f"{base}/save-preview", json={"folder": "loras", "name": "sub\\style.safetensors"})
    assert again.status_code == 422, "那台服务器上已经有了:写回那条路会覆盖同名的,不写"
    assert len([one for one in _ops() if one["op"] == "save_preview"]) == 1


def test_存为预览图_按文件名对上的要确认_那台服务器上已经有的不写_写不回的说缺什么(library) -> None:
    client, instance_id, _ = library
    base = f"/api/plugins/instances/{instance_id}/model-library"
    data = runtime.data_dir_for(PACKAGE_ID)
    (data / "how").write_text("filename")
    client.get(base)
    unconfirmed = client.post(f"{base}/save-preview", json={"folder": "loras", "name": "sub\\style.safetensors"})
    assert unconfirmed.status_code == 422 and "确认" in unconfirmed.json()["detail"]
    confirmed = client.post(f"{base}/save-preview", json={"folder": "loras", "name": "sub\\style.safetensors",
                                                          "confirmed": True})
    assert confirmed.status_code == 200, confirmed.text
    # 那台服务器上有预览图的(sdxl_base 有):没有别处的示例图可存
    assert client.post(f"{base}/save-preview", json={"folder": "checkpoints", "name": "sdxl_base.safetensors"}).status_code == 422
    (data / "no-save").write_text("1")
    (data / "how").unlink()
    client.get(base)
    refused = client.post(f"{base}/save-preview", json={"folder": "loras", "name": "sub\\style.safetensors"})
    assert refused.status_code == 422 and "ComfyUI-Custom-Scripts" in refused.json()["detail"]
    assert client.get(base).json()["preview_tools"] == {"lookup": "sha256", "save": False, "save_note": "缺 ComfyUI-Custom-Scripts"}


def test_在Civitai上找是一个后台任务_补图时那台服务器上有预览图的跳过_找到的存回(library) -> None:
    client, instance_id, _ = library
    workspace = _workspace(client)
    base = f"/api/plugins/instances/{instance_id}/model-library"
    client.get(base)
    started = client.post(f"{base}/lookups", json={"workspace_id": workspace, "save": True})
    assert started.status_code == 200, started.text
    assert started.json()["kind"] == "model_previews"
    assert wait_status(client, started.json()["id"]) == "succeeded"
    result = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]
    assert result["had_preview"] == 1, "sdxl_base 那台服务器上有预览图:不找、不写"
    assert (result["looked"], result["matched"], result["saved"]) == (2, 1, 1), "plain 在 Civitai 上没有;style 找到、存回"
    looked = sorted(one["name"] for one in _ops() if one["op"] == "lookup")
    assert looked == ["plain.safetensors", "sub\\style.safetensors"]
    assert all(one["refresh"] is False for one in _ops() if one["op"] == "lookup"), "补图不重查查过的"

    single = client.post(f"{base}/lookups", json={"workspace_id": workspace, "files": [{"folder": "loras", "name": "plain.safetensors"}],
                                                  "refresh": True})
    assert wait_status(client, single.json()["id"]) == "succeeded"
    assert client.get(f"/api/jobs/{single.json()['id']}").json()["result"]["saved"] == 0, "只找不存"
    assert [one["refresh"] for one in _ops() if one["op"] == "lookup"][-1] is True
    unknown = client.post(f"{base}/lookups", json={"workspace_id": workspace, "files": [{"folder": "loras", "name": "nobody"}]})
    assert unknown.status_code == 422, "列表里没有的文件不找"


def test_只找不存_对上的当场记进宿主的列表_任务交回那一条现在的样子_不必整份重列(library) -> None:
    """维护者:「在 Civitai 上找」成功之后,详情里的「原链接」和 Civitai 那张示例图要过好一阵才出来。此前任务做完把宿主
    记着的整份列表扔掉(只找不存时也不记下找到的),界面拿到「做完了」再整份重列 —— 几百个模型的服务器上要好几秒,
    这期间取预览图还得先替它列一遍。现在对上的当场记进去,任务交回这一条现在的样子(`found`),预览图不重列就取得到。"""
    client, instance_id, _ = library
    base = f"/api/plugins/instances/{instance_id}/model-library"
    plain = next(one for one in client.get(base).json()["models"] if one["name"] == "plain.safetensors")
    assert (plain["has_preview"], plain["source"]) == (False, None), "前提:那台服务器上没有预览图,也不知道出处"
    _flag("plain-found")
    listed = sum(1 for one in _ops() if one["op"] == "library")
    started = client.post(f"{base}/lookups", json={"workspace_id": _workspace(client),
                                                   "files": [{"folder": "loras", "name": "plain.safetensors"}]})
    assert wait_status(client, started.json()["id"]) == "succeeded"
    lookup = client.get(f"{base}/lookups/{started.json()['id']}")
    assert lookup.status_code == 200, lookup.text
    found = lookup.json()["result"]["found"]
    assert found == [{
        "folder": "loras", "name": "plain.safetensors", "match": "sha256",
        "source": {"page": "https://civitai.com/models/9?modelVersionId=10", "site": "civitai", "how": "sha256"},
        "has_preview": True, "preview_origin": "civitai", "preview_kind": "image",
        "nsfw": {"flagged": False, "manual": None,
                 "reasons": [{"source": "civitai", "nsfw": False, "tags": [], "words": [], "level": 1, "score": None}]},
    }]
    shown = client.get(f"{base}/preview", params={"folder": "loras", "name": "plain.safetensors"})
    assert shown.status_code == 200 and _pixel(shown.content)[:3] == (20, 160, 80), "Civitai 那张(分级最低的)当场取得到"
    assert sum(1 for one in _ops() if one["op"] == "library") == listed, "找完、取图都不必让插件整份重列"
    other = client.get(f"/api/plugins/instances/{instance_id}/model-library/lookups/nope")
    assert other.status_code == 422


def test_补图时按文件名对上的不替你存_列出来等你确认(library) -> None:
    client, instance_id, _ = library
    _flag("lookup-match")
    (runtime.data_dir_for(PACKAGE_ID) / "lookup-match").write_text("filename")
    base = f"/api/plugins/instances/{instance_id}/model-library"
    client.get(base)
    started = client.post(f"{base}/lookups", json={"workspace_id": _workspace(client), "save": True})
    assert wait_status(client, started.json()["id"]) == "succeeded"
    result = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]
    assert (result["matched"], result["saved"]) == (1, 0)
    assert result["confirm"] == [{"folder": "loras", "name": "sub\\style.safetensors"}]
    assert not [one for one in _ops() if one["op"] == "save_preview"], "按文件名猜的可能是同名的别的模型:不写到那台服务器上"


def test_挑哪张示例图_有图就在图里挑_要最稳妥的挑分级最低的_照常就要作者排在前的() -> None:
    from app.domain.model_previews import Elsewhere, pick

    clip = Elsewhere("https://x/clip.mp4", "video", "civitai", 1, False)
    spicy = Elsewhere("https://x/spicy.jpg", "image", "civitai", 8, True)
    mild = Elsewhere("https://x/mild.jpg", "image", "civitai", 2, False)
    unknown = Elsewhere("https://x/unknown.jpg", "image", "civitai", 0, False)
    assert pick([clip, spicy, mild], "safest") == mild, "有图就不用视频,哪怕视频分级更低"
    assert pick([clip, spicy, mild], "cover") == spicy
    assert pick([unknown, mild], "safest") == mild, "说不出分级的不当成最稳妥"
    assert pick([clip], "safest") == clip, "示例只有视频才用视频"
    assert pick([], "safest") is None


# --- 预览视频 --------------------------------------------------------------------------

def _flag(name: str) -> None:
    data = runtime.data_dir_for(PACKAGE_ID)
    data.mkdir(parents=True, exist_ok=True)
    (data / name).write_text("1")


def test_模型旁边的预览视频_转成512宽静音的一段_卡片是第一帧_详情播视频(library) -> None:
    client, instance_id, previews = library
    _flag("video-sidecar")
    base = f"/api/plugins/instances/{instance_id}/model-library"
    assert _origin(client, instance_id, "plain.safetensors")["has_preview"] is True
    params = {"folder": "loras", "name": "plain.safetensors"}
    thumb = client.get(f"{base}/thumbnail", params=params)
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp", "卡片上是第一帧"
    import io

    from PIL import Image

    with Image.open(io.BytesIO(thumb.content)) as frame:
        assert frame.size == (512, 288)
    video = client.get(f"{base}/preview", params=params)
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    assert _video_facts(video.content) == {"width": 512, "height": 288, "audio": False}, "缓存的是 512 宽、静音的那一段"
    assert [one["path"] for one in previews.requests if one["path"].startswith("/sidecar/")] == ["/sidecar/plain.mp4"], \
        "取过一次就从缓存给"
    listed = _origin(client, instance_id, "plain.safetensors")
    assert (listed["preview_origin"], listed["preview_kind"]) == ("server", "video")


def test_示例只有视频的_用视频当预览_存回的是视频本身(library) -> None:
    client, instance_id, _ = library
    _flag("remote-video")
    base = f"/api/plugins/instances/{instance_id}/model-library"
    name = "sub\\style.safetensors"
    assert client.get(f"{base}/thumbnail", params={"folder": "loras", "name": name}).headers["content-type"] == "image/webp"
    listed = _origin(client, instance_id, name)
    assert (listed["preview_origin"], listed["preview_kind"]) == ("civitai", "video")
    saved = client.post(f"{base}/save-preview", json={"folder": "loras", "name": name})
    assert saved.status_code == 200, saved.text
    data = runtime.data_dir_for(PACKAGE_ID)
    assert (data / "saved-name").read_text() == "preview.mp4", "维护者:不要用帧,直接用视频当预览"
    assert _video_facts((data / "saved.bin").read_bytes())["width"] == 512
    from app.domain import model_previews

    assert model_previews.server_kind(instance_id, "loras", name) == "video", "存回的是视频:列表马上标成那台服务器上的视频"


# --- 本机识别(第四种依据) ----------------------------------------------------------------

@pytest.fixture
def local_classifier(monkeypatch):
    """本机识别的权重「下好了」,识别换成看颜色:偏红的算 NSFW。"""
    import hashlib

    from PIL import Image

    from app.ai.runtime import nsfw_models
    from app.domain import model_nsfw_local

    def reset() -> None:
        model_nsfw_local.forget()
        shutil.rmtree(nsfw_models.root(), ignore_errors=True)

    reset()
    nsfw_models.weights_path().parent.mkdir(parents=True, exist_ok=True)
    nsfw_models.weights_path().write_bytes(b"weights")
    seen: list[str] = []

    def probability(image: Image.Image) -> float:
        seen.append(hashlib.sha1(image.convert("RGB").tobytes()).hexdigest())
        if image.width < 8:
            raise OSError("too small to tell")
        red, green, _blue = image.convert("RGB").getpixel((4, 4))
        return 0.91 if red > 150 and green < 100 else 0.06

    monkeypatch.setattr(model_nsfw_local, "_probability", probability)
    yield seen
    reset()


def _local(model: dict) -> list[dict]:
    return [one for one in model["nsfw"]["reasons"] if one["source"] == "local"]


def test_本机识别_看显示着的那张的缩略图_列的时候不等_下次列出就有(library, local_classifier) -> None:
    from app.domain import model_nsfw_local

    client, instance_id, _ = library
    base = f"/api/plugins/instances/{instance_id}/model-library"
    style = "sub\\style.safetensors"
    assert not _local(_origin(client, instance_id, style)), "还没有缩略图:没有这条依据"
    # 卡片露面:缩略图缩出来就排进队(显示的是 Civitai 那张分级最低的 —— 绿的)
    client.get(f"{base}/thumbnail", params={"folder": "loras", "name": style})
    assert model_nsfw_local.wait_idle()
    listed = _origin(client, instance_id, style)
    assert [(one["nsfw"], one["score"]) for one in _local(listed)] == [(False, 0.06)]
    assert listed["nsfw"]["flagged"] is False

    # 照常要作者排在前的那张(红的):看的是显示着的那张,不是别的
    client.get(f"{base}/thumbnail", params={"folder": "loras", "name": style, "pick": "cover"})
    assert model_nsfw_local.wait_idle()
    cover = _origin(client, instance_id, style, pick="cover")
    assert [(one["nsfw"], one["score"]) for one in _local(cover)] == [(True, 0.91)]
    assert cover["nsfw"]["flagged"] is True
    assert [one["source"] for one in cover["nsfw"]["reasons"]] == ["civitai", "local"], "依据按来源排"

    # 手动标记压过本机识别
    client.put(f"{base}/nsfw", json={"folder": "loras", "name": style, "nsfw": False})
    marked = _origin(client, instance_id, style, pick="cover")
    assert marked["nsfw"]["flagged"] is False and _local(marked), "标了不是:听手动的,依据照样列着"
    assert sorted(local_classifier) == sorted(set(local_classifier)), "同一张图只识别一次"


def test_本机识别_认不出的不说话_那台服务器上的预览图也看(library, local_classifier) -> None:
    from app.domain import model_nsfw_local

    client, instance_id, _ = library
    base = f"/api/plugins/instances/{instance_id}/model-library"
    # sdxl_base 那台服务器上的预览图是 1×1 的 WebP:识别不出 —— 不说是,也不当成「安全」
    client.get(f"{base}/thumbnail", params={"folder": "checkpoints", "name": "sdxl_base.safetensors"})
    assert model_nsfw_local.wait_idle()
    assert local_classifier, "那台服务器上的那张缩出来也排进去"
    assert not _local(_origin(client, instance_id, "sdxl_base.safetensors"))


def test_本机识别_那台服务器上的预览图看原文件_不看ComfyUI现转的有损WebP(library, local_classifier) -> None:
    """沙盒实测:Big Buck Bunny 的兔脸特写,原 PNG 0.47、ComfyUI 预览接口现转的 WebP 0.69、再缩一次的缩略图 0.78 ——
    判成了 NSFW。插件报了原文件(ComfyUI-Custom-Scripts 原样交出)时看原文件。这里用颜色替分数:预览接口那张偏红,
    原文件是绿的。"""
    from app.domain import model_nsfw_local

    client, instance_id, previews = library
    previews.body, previews.kind = _colored_png((200, 30, 30), (384, 480)), "image/png"
    base = f"/api/plugins/instances/{instance_id}/model-library"
    sdxl = {"folder": "checkpoints", "name": "sdxl_base.safetensors"}

    # 没报原文件:只能看预览接口那一张(红的)
    client.get(base)
    client.get(f"{base}/thumbnail", params=sdxl)
    assert model_nsfw_local.wait_idle()
    assert [(one["nsfw"], one["score"]) for one in _local(_origin(client, instance_id, sdxl["name"]))] == [(True, 0.91)]

    # 报了原文件:看它(绿的)。卡片第一次露面时就排进队(缓存清掉,列的时候还没有那张)
    from app.domain import model_library

    model_nsfw_local.forget()
    model_nsfw_local.scores_path().unlink()
    model_library.drop_cache(instance_id)
    _flag("lossless")
    assert not _local(_origin(client, instance_id, sdxl["name"])), "还没取回来:没有这条依据"
    client.get(f"{base}/thumbnail", params=sdxl)
    assert model_nsfw_local.wait_idle()
    assert [(one["nsfw"], one["score"]) for one in _local(_origin(client, instance_id, sdxl["name"]))] == [(False, 0.06)]

    # 那张已经在缓存里、结果没了(换了模型版本):列的时候排进队,同样看原文件
    model_nsfw_local.forget()
    model_nsfw_local.scores_path().unlink()
    client.get(base)
    assert model_nsfw_local.wait_idle()
    listed = _origin(client, instance_id, sdxl["name"])
    assert [(one["nsfw"], one["score"]) for one in _local(listed)] == [(False, 0.06)]
    raw = [one for one in previews.requests if one["path"] == "/sidecar/raw%2Fsdxl_base.png"]
    assert raw and all(one["auth"] == "Bearer secret-for-previews" for one in raw), "原文件在那台服务器上:带它的头"
    shown = client.get(f"{base}/preview", params=sdxl)
    assert _pixel(shown.content)[:3] == (200, 30, 30), "显示的照旧是预览接口那一张"

