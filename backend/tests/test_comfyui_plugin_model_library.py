"""ComfyUI 插件的模型库(ADR 0034):对着一台假的 ComfyUI(tests/fake_comfyui)。

框架那一侧(宿主列表、预览缓存、下载任务)钉在 test_plugin_model_library.py;这里钉的是插件自己:

- 列出:每个目录的每个文件(大小、改动时间、预览地址),推断的底模家族(先元数据、再权重结构、再文件名,凭的是什么写明;细则在 test_comfyui_plugin_base_models.py)、
  触发词(作者写的,或训练标签里最多的几个)、哪几张工作流在用;
- 工作流缺的模型:声明了下载地址、节点真在用、这台服务器上又没有的才列,只认 HuggingFace / Civitai / ModelScope;
- 逐个读的元数据记在持久目录里,第二次只读目录;
- 链接解析:HuggingFace 文件、Civitai 页面、ModelScope 的文件与模型页、别的直链;
- 下载按优先级走:Manager → 同一台机器直接写 → 说清楚能做的那一步。不覆盖已有文件,取消时只删自己的半截文件,
  空间不够就不下;Manager 被安全策略拒绝时说人话、记下来,能走本机就走本机;令牌只发给它自己那个站。
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import parse

import pytest

from app.domain.plugins import runtime
from app.domain.plugins.runtime import PluginRuntimeError
from tests.fake_comfyui import FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
TOOLS = PLUGIN / "tools"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "workflows",
            "tooling", "library", "sources", "install", "families", "weights", "model_files", "civitai", "nsfw",
            "provenance", "lookup", "previews")

TAGS = json.dumps({"10_style": {"1girl": 40, "solo": 35, "smile": 12, "outdoors": 3}, "5_extra": {"1girl": 5, "hat": 9}})

#: 一张声明了模型下载地址的工作流(ComfyUI 官方模板的写法:节点 properties.models)。
DECLARING_UI: dict[str, Any] = {
    "id": "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d",
    "nodes": [
        {"id": 1, "type": "VAELoader", "widgets_values": ["ae.safetensors"], "inputs": [],
         "properties": {"models": [{"name": "ae.safetensors", "directory": "vae",
                                    "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors"}]}},
        {"id": 2, "type": "CheckpointLoaderSimple", "widgets_values": ["mine.safetensors"], "inputs": [],
         # 节点改选了别的文件:声明过期了,不算缺
         "properties": {"models": [{"name": "v1-5-pruned-emaonly-fp16.safetensors", "directory": "checkpoints",
                                    "url": "https://huggingface.co/Comfy-Org/sd15/resolve/main/v1-5-pruned-emaonly-fp16.safetensors"}]}},
        {"id": 3, "type": "LoraLoader", "widgets_values": ["detail.safetensors", 1.0, 1.0], "inputs": [],
         # 已经有了的不算缺
         "properties": {"models": [{"name": "detail.safetensors", "directory": "loras",
                                    "url": "https://huggingface.co/x/y/resolve/main/detail.safetensors"}]}},
        {"id": 4, "type": "UNETLoader", "widgets_values": ["sketchy.safetensors", "default"], "inputs": [],
         # 不是可信站点的地址:不给一键下载
         "properties": {"models": [{"name": "sketchy.safetensors", "directory": "diffusion_models",
                                    "url": "https://example.com/sketchy.safetensors"}]}},
    ],
    "links": [],
}


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        state = server.state
        state.model_folders = {
            "checkpoints": ["sd_xl_base.safetensors", "v1-5.ckpt", "AWPainting_IL.safetensors"],
            "loras": ["detail.safetensors", "sub\\anima_style.safetensors", "chars\\noob_char.safetensors"],
            "vae": [],
            "upscale_models": ["4x-UltraSharp.pth"],
            "custom_nodes": [],
            "configs": ["v1-inference.yaml"],
        }
        state.model_sizes = {"checkpoints/sd_xl_base.safetensors": 6938041004, "loras/detail.safetensors": 228456516}
        state.model_metadata = {
            "checkpoints/sd_xl_base.safetensors": {"modelspec.architecture": "stable-diffusion-xl-v1-base",
                                                  "modelspec.title": "SDXL base"},
            "checkpoints/AWPainting_IL.safetensors": {},
            "loras/detail.safetensors": {"ss_base_model_version": "sdxl_base_v1-0",
                                         "ss_sd_model_name": "illustriousXL_v01.safetensors",
                                         "modelspec.architecture": "stable-diffusion-xl-v1-base/lora",
                                         "ss_tag_frequency": TAGS, "ss_output_name": "detail_tweaker",
                                         "modelspec.thumbnail": "data:image/png;base64," + "A" * 5000},
            # kohya 不认识的底模:architecture 照默认写成 SD1,base 才是真的
            "loras/sub\\anima_style.safetensors": {"modelspec.architecture": "stable-diffusion-v1/lora",
                                                   "ss_base_model_version": "anima",
                                                   "modelspec.trigger_phrase": "anima style, flat color"},
        }
        state.model_previews = {"loras/detail.safetensors"}
        state.workflows["declaring.json"] = DECLARING_UI
        yield server


@pytest.fixture
def data_dir(tmp_path: Path):
    path = tmp_path / "plugin-data"
    path.mkdir()
    return path


def _env(url: str, **extra: str) -> dict[str, str]:
    return {"SERVER_URL": url, **extra}


def _call(server: FakeComfyUI, payload: dict[str, Any], data_dir: Path, **env: str) -> dict[str, Any]:
    return runtime.execute_tool(PLUGIN, ENTRY, "comfyui_generation", payload, _env(server.url, **env),
                                data_dir=data_dir, timeout=60).output


class _Progress:
    def __init__(self, cancel_after: float | None = None) -> None:
        self.events: list[tuple[float, str]] = []
        self.cancel_after = cancel_after

    def hooks(self) -> runtime.StreamHooks:
        return runtime.StreamHooks(
            on_progress=lambda fraction, message: self.events.append((fraction, message)),
            on_task=lambda _task: None,
            is_cancelled=lambda: self.cancel_after is not None and any(f >= self.cancel_after for f, _ in self.events),
        )


def _download(server: FakeComfyUI, payload: dict[str, Any], data_dir: Path, tmp_path: Path,
              progress: _Progress | None = None, **env: str) -> tuple[dict[str, Any], _Progress]:
    progress = progress or _Progress()
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    result = runtime.stream_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "download", **payload},
                                 _env(server.url, **env), hooks=progress.hooks(), scratch_dir=scratch,
                                 data_dir=data_dir, timeout=60)
    return result.output, progress


class _Files:
    """本机一个真的 HTTP 服务,替「模型文件所在的站」:按路径给字节,可以要求带某个 Authorization 头,
    也可以谎报一个巨大的长度(测剩余空间)。记下每次请求带的头。"""

    def __init__(self, files: dict[str, bytes], *, slow: bool = False, claim_size: int | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, head_only: bool) -> None:
                outer.requests.append({"method": self.command, "path": self.path,
                                       "auth": self.headers.get("Authorization")})
                body = files.get(self.path.split("?")[0])
                if body is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(claim_size or len(body)))
                self.send_header("Content-Disposition", 'attachment; filename="from-header.safetensors"')
                self.end_headers()
                if head_only:
                    return
                for start in range(0, len(body), 4096):
                    self.wfile.write(body[start:start + 4096])
                    self.wfile.flush()
                    if slow:
                        time.sleep(0.05)

            def do_GET(self) -> None:  # noqa: N802
                try:
                    self._send(False)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_HEAD(self) -> None:  # noqa: N802
                self._send(True)

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def files():
    servers: list[_Files] = []

    def make(content: dict[str, bytes], **options: Any) -> _Files:
        server = _Files(content, **options)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


def _same_machine(server: FakeComfyUI, root: Path) -> Path:
    """让假 ComfyUI 的模型目录真的在这台机器上(和它报的文件一致):Mosael 和 ComfyUI 在同一台机器的那种情形。"""
    for folder, names in server.state.model_folders.items():
        directory = root / folder
        directory.mkdir(parents=True, exist_ok=True)
        for name in names:
            target = directory / name.replace("\\", "/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * server.state.model_sizes.get(f"{folder}/{name}", 1000)
                               if server.state.model_sizes.get(f"{folder}/{name}", 1000) < 10_000_000 else b"x")
        server.state.folder_paths[folder] = [str(directory)]
    # 大文件不真写那么大:把报的大小改成写下的那么大(同一台机器的判定会比大小)
    for key in list(server.state.model_sizes):
        folder, name = key.split("/", 1)
        server.state.model_sizes[key] = (root / folder / name.replace("\\", "/")).stat().st_size
    return root


@pytest.fixture
def modules():
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import library
        import sources

        yield library, sources
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


# --- 列出 -------------------------------------------------------------------

def test_列出全部模型文件_带大小_预览地址_家族_触发词(comfy, data_dir) -> None:
    out = _call(comfy, {"op": "library"}, data_dir)
    folders = {one["name"]: one["count"] for one in out["folders"]}
    assert folders == {"checkpoints": 3, "loras": 3, "vae": 0, "upscale_models": 1}, "custom_nodes / configs 不是模型目录"
    by_key = {(one["folder"], one["name"]): one for one in out["models"]}
    assert len(by_key) == 7
    sdxl = by_key[("checkpoints", "sd_xl_base.safetensors")]
    assert sdxl["size"] == 6938041004 and sdxl["modified"] == 1700000000.0
    assert (sdxl["family"], sdxl["family_source"]) == ("SDXL", "metadata")
    assert sdxl["title"] == "SDXL base"
    assert out["preview_base"] == f"{comfy.url}/experiment/models/preview/"
    assert sdxl["preview"] == "checkpoints/0/sd_xl_base.safetensors"
    assert by_key[("loras", "sub\\anima_style.safetensors")]["preview"] == "loras/0/sub%5Canima_style.safetensors"
    detail = by_key[("loras", "detail.safetensors")]
    assert (detail["family"], detail["family_source"]) == ("Illustrious", "metadata"), "SDXL 上训练的,底模名说是 Illustrious"
    assert (detail["triggers"], detail["triggers_source"]) == (["1girl", "solo", "smile", "hat", "outdoors"], "tags")
    anima = by_key[("loras", "sub\\anima_style.safetensors")]
    assert (anima["family"], anima["family_source"]) == ("Anima", "metadata"), "看 ss_base_model_version,不往 SD1 上靠"
    assert (anima["triggers"], anima["triggers_source"]) == (["anima style", "flat color"], "metadata")
    painting = by_key[("checkpoints", "AWPainting_IL.safetensors")]
    assert (painting["family"], painting["family_source"]) == ("Illustrious", "filename")
    noob = by_key[("loras", "chars\\noob_char.safetensors")]
    assert (noob["family"], noob["family_source"]) == ("NoobAI", "filename"), "子目录名也算"
    upscaler = by_key[("upscale_models", "4x-UltraSharp.pth")]
    assert (upscaler.get("family", ""), upscaler["family_source"]) == ("", "not_applicable"), "放大模型不讲底模"
    assert by_key[("checkpoints", "v1-5.ckpt")].get("family") == "SD 1.5"


def test_哪几张工作流在用(comfy, data_dir) -> None:
    out = _call(comfy, {"op": "library"}, data_dir)
    by_key = {(one["folder"], one["name"]): one for one in out["models"]}
    assert by_key[("checkpoints", "sd_xl_base.safetensors")]["used_by"] == [{"id": "portrait.json", "label": "portrait"}]
    assert by_key[("loras", "detail.safetensors")]["used_by"] == [{"id": "declaring.json", "label": "declaring"}]
    assert by_key[("checkpoints", "v1-5.ckpt")]["used_by"] == [{"id": "video/wan.json", "label": "video/wan"}], \
        "API 格式存的图也扫"
    assert not by_key[("upscale_models", "4x-UltraSharp.pth")].get("used_by")


def test_工作流声明了地址_节点真在用_这台没有的才算缺_只认可信站点(comfy, data_dir) -> None:
    out = _call(comfy, {"op": "library"}, data_dir)
    assert out["missing"] == [{
        "folder": "vae", "name": "ae.safetensors",
        "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors",
        "workflows": [{"id": "declaring.json", "label": "declaring"}],
    }]


def test_元数据记在持久目录_第二次只读目录(comfy, data_dir) -> None:
    _call(comfy, {"op": "library"}, data_dir)
    first = sum(1 for method, path, _ in comfy.state.calls if path.startswith("/view_metadata/"))
    assert first == 5, "只有 safetensors 才问元数据"
    comfy.state.calls.clear()
    again = _call(comfy, {"op": "library"}, data_dir)
    assert not [path for _, path, _ in comfy.state.calls if path.startswith("/view_metadata/")]
    assert {(one["folder"], one["name"]): one.get("family") for one in again["models"]}[("loras", "detail.safetensors")] \
        == "Illustrious"
    # 文件变了(大小不一样):重新读这一个
    comfy.state.model_sizes["loras/detail.safetensors"] = 1
    comfy.state.calls.clear()
    _call(comfy, {"op": "library"}, data_dir)
    assert [query["filename"] for _, path, query in comfy.state.calls if path.startswith("/view_metadata/")] == \
        [["detail.safetensors"]]


def test_详情_全部元数据_训练标签按次数_内嵌的图不交(comfy, data_dir) -> None:
    out = _call(comfy, {"op": "detail", "folder": "loras", "name": "detail.safetensors"}, data_dir)
    assert out["metadata"]["ss_output_name"] == "detail_tweaker"
    assert "ss_tag_frequency" not in out["metadata"], "训练标签单独交成 tags"
    assert "modelspec.thumbnail" not in out["metadata"], "内嵌的图不是给人读的元数据"
    assert out["tags"][:3] == [{"tag": "1girl", "count": 45}, {"tag": "solo", "count": 35}, {"tag": "smile", "count": 12}]
    empty = _call(comfy, {"op": "detail", "folder": "upscale_models", "name": "4x-UltraSharp.pth"}, data_dir)
    assert empty["metadata"] == {} and empty["tags"] == []
    assert empty["note"], "没有元数据要说为什么(不是 safetensors)"


def test_老版本没有模型库接口_退回只列名字(comfy, data_dir) -> None:
    comfy.state.experiment_models = False
    out = _call(comfy, {"op": "library"}, data_dir)
    names = {(one["folder"], one["name"]) for one in out["models"]}
    assert ("checkpoints", "sd_xl_base.safetensors") in names
    assert all("preview" not in one for one in out["models"])


# --- 下载走哪条路 -------------------------------------------------------------

def test_没有Manager也不在同一台机器_说清楚能做的那一步(comfy, data_dir) -> None:
    out = _call(comfy, {"op": "library"}, data_dir)
    assert out["download"]["route"] == "none"
    assert "ComfyUI-Manager" in out["download"]["note"]


def test_有Manager就走Manager(comfy, data_dir) -> None:
    comfy.state.manager = "V4.2.1"
    out = _call(comfy, {"op": "library"}, data_dir)
    assert out["download"]["route"] == "manager"


def test_同一台机器_本机那条路(comfy, data_dir, tmp_path) -> None:
    _same_machine(comfy, tmp_path / "models")
    out = _call(comfy, {"op": "library"}, data_dir)
    assert out["download"]["route"] == "local"


def test_路径恰好也存在但文件对不上_不算同一台机器(comfy, data_dir, tmp_path) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    for file in (root / "checkpoints").iterdir():
        file.unlink()
    (root / "loras" / "detail.safetensors").unlink()
    out = _call(comfy, {"op": "library"}, data_dir)
    assert out["download"]["route"] == "none"


def test_本机那条路_直接写进模型目录_不留半截文件(comfy, data_dir, tmp_path, files) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    body = b"\x00" * 200_000
    site = files({"/tiny.safetensors": body})
    out, progress = _download(comfy, {"url": f"{site.url}/tiny.safetensors", "folder": "vae",
                                      "filename": "mosael-test-tiny.safetensors"}, data_dir, tmp_path)
    assert out == {"folder": "vae", "name": "mosael-test-tiny.safetensors", "size": 200_000, "route": "local", "page": ""}
    assert (root / "vae" / "mosael-test-tiny.safetensors").read_bytes() == body
    assert not list((root / "vae").glob("*.mosael-part"))
    assert progress.events and progress.events[-1][0] == pytest.approx(1.0)
    assert "KB" in progress.events[-1][1] or "MB" in progress.events[-1][1]


def test_本机那条路_同名文件不覆盖(comfy, data_dir, tmp_path, files) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    before = (root / "loras" / "detail.safetensors").read_bytes()
    site = files({"/detail.safetensors": b"new"})
    with pytest.raises(PluginRuntimeError, match="同名"):
        _download(comfy, {"url": f"{site.url}/detail.safetensors", "folder": "loras", "filename": "detail.safetensors"},
                  data_dir, tmp_path)
    assert (root / "loras" / "detail.safetensors").read_bytes() == before
    assert not site.requests, "同名的连下都不下"


def test_本机那条路_取消时删掉自己的半截文件(comfy, data_dir, tmp_path, files) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    site = files({"/big.safetensors": b"\x01" * 2_000_000}, slow=True)
    with pytest.raises(PluginRuntimeError):
        _download(comfy, {"url": f"{site.url}/big.safetensors", "folder": "loras", "filename": "big.safetensors"},
                  data_dir, tmp_path, progress=_Progress(cancel_after=0.01))
    assert not (root / "loras" / "big.safetensors").exists()
    assert not list((root / "loras").glob("*.mosael-part")), "半截文件是自己的,取消时删掉"
    assert (root / "loras" / "detail.safetensors").exists(), "别的文件一个不动"


def test_本机那条路_空间不够就不下(comfy, data_dir, tmp_path, files) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    site = files({"/huge.safetensors": b"x"}, claim_size=10 ** 16)
    with pytest.raises(PluginRuntimeError, match="空间"):
        _download(comfy, {"url": f"{site.url}/huge.safetensors", "folder": "loras", "filename": "huge.safetensors"},
                  data_dir, tmp_path)
    assert not list((root / "loras").glob("huge*"))


def test_令牌只发给它自己那个站(comfy, data_dir, tmp_path, files) -> None:
    _same_machine(comfy, tmp_path / "models")
    site = files({"/tiny.safetensors": b"abc"})
    _download(comfy, {"url": f"{site.url}/tiny.safetensors", "folder": "vae", "filename": "t.safetensors"},
              data_dir, tmp_path, HUGGINGFACE_TOKEN="hf_secret", CIVITAI_TOKEN="civ_secret", MODELSCOPE_TOKEN="ms_secret")
    assert all(request["auth"] is None for request in site.requests), \
        "HuggingFace / Civitai / ModelScope 的令牌不发给别的站"


def test_Manager那条路_提交装模型_等到下完(comfy, data_dir, tmp_path) -> None:
    comfy.state.manager = "V4.2.1"
    out, progress = _download(comfy, {"url": "https://huggingface.co/a/b/resolve/main/tiny.safetensors",
                                      "folder": "vae", "filename": "mosael-test-tiny.safetensors"},
                              data_dir, tmp_path)
    assert out["route"] == "manager" and out["name"] == "mosael-test-tiny.safetensors"
    submitted = comfy.posted("/v2/manager/queue/install_model")
    assert len(submitted) == 1
    task = submitted[0]
    assert (task["save_path"], task["filename"], task["url"]) == (
        "vae", "mosael-test-tiny.safetensors", "https://huggingface.co/a/b/resolve/main/tiny.safetensors")
    assert task["client_id"] and task["ui_id"].startswith("mosael-")
    assert comfy.posted("/v2/manager/queue/start")
    assert any("Manager" in message for _, message in progress.events)


def test_Manager那条路_同名文件不提交(comfy, data_dir, tmp_path) -> None:
    comfy.state.manager = "V4.2.1"
    with pytest.raises(PluginRuntimeError, match="同名"):
        _download(comfy, {"url": "https://huggingface.co/a/b/resolve/main/detail.safetensors", "folder": "loras",
                          "filename": "detail.safetensors"}, data_dir, tmp_path)
    assert not comfy.posted("/v2/manager/queue/install_model")


def test_Manager被安全策略拒绝_说人话和下一步(comfy, data_dir, tmp_path) -> None:
    comfy.state.manager = "V4.2.1"
    comfy.state.manager_outcome = "policy"
    with pytest.raises(PluginRuntimeError) as caught:
        _download(comfy, {"url": "https://huggingface.co/a/b/resolve/main/tiny.safetensors", "folder": "vae",
                          "filename": "mosael-test-tiny.safetensors"}, data_dir, tmp_path)
    message = str(caught.value)
    assert "network_mode" in message and "personal_cloud" in message and "config.ini" in message
    assert "https://huggingface.co/a/b/resolve/main/tiny.safetensors" in message, "给出直链,手动放也行"
    # 记下了:模型库在下载前就提醒
    out = _call(comfy, {"op": "library"}, data_dir)
    assert out["download"]["route"] == "manager" and "personal_cloud" in out["download"]["note"]


def test_Manager被拒绝_日志缓冲满了也找得到原因(comfy, data_dir, tmp_path) -> None:
    """ComfyUI 的日志只留最近 300 行:满了之后行数不变,按行数切会一行都切不到(实测踩过)—— 按时间认。"""
    comfy.state.manager = "V4.2.1"
    comfy.state.manager_outcome = "policy"
    comfy.state.log_entries = [{"t": f"2026-01-01T00:00:{index % 60:02d}.{index:06d}", "m": "old line\n"}
                               for index in range(300)]
    with pytest.raises(PluginRuntimeError, match="personal_cloud"):
        _download(comfy, {"url": "https://huggingface.co/a/b/resolve/main/tiny.safetensors", "folder": "vae",
                          "filename": "mosael-test-tiny.safetensors"}, data_dir, tmp_path)


def test_Manager被拒绝_同一台机器就改走本机(comfy, data_dir, tmp_path, files) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    comfy.state.manager = "V4.2.1"
    comfy.state.manager_outcome = "policy"
    site = files({"/tiny.safetensors": b"abc"})
    out, _ = _download(comfy, {"url": f"{site.url}/tiny.safetensors", "folder": "vae", "filename": "a.safetensors"},
                       data_dir, tmp_path)
    assert out["route"] == "local" and (root / "vae" / "a.safetensors").read_bytes() == b"abc"
    assert len(comfy.posted("/v2/manager/queue/install_model")) == 1
    # 第二次:记着被拒过、本机走得通,就不再去碰 Manager
    _download(comfy, {"url": f"{site.url}/tiny.safetensors", "folder": "vae", "filename": "b.safetensors"},
              data_dir, tmp_path)
    assert len(comfy.posted("/v2/manager/queue/install_model")) == 1
    assert (comfy.posted("/v2/manager/queue/install_model")[0]["filename"]) == "a.safetensors"


def test_Manager下载失败_原因从日志里找出来(comfy, data_dir, tmp_path) -> None:
    comfy.state.manager = "V4.2.1"
    comfy.state.manager_outcome = "error"
    with pytest.raises(PluginRuntimeError, match="404"):
        _download(comfy, {"url": "https://huggingface.co/a/b/resolve/main/gone.safetensors", "folder": "vae",
                          "filename": "gone.safetensors"}, data_dir, tmp_path)


def test_下载到这台服务器没有的目录_说清楚(comfy, data_dir, tmp_path) -> None:
    comfy.state.manager = "V4.2.1"
    with pytest.raises(PluginRuntimeError, match="没有.*目录"):
        _download(comfy, {"url": "https://huggingface.co/a/b/resolve/main/t.safetensors", "folder": "no_such_folder",
                          "filename": "t.safetensors"}, data_dir, tmp_path)


# --- 底模家族的规矩 ---------------------------------------------------------

@pytest.mark.parametrize(("folder", "name", "meta", "expected"), [
    ("loras", "x.safetensors", {"ss_base_model_version": "sd_v1"}, ("SD 1.5", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "sd_v2"}, ("SD 2", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "sd_1.5"}, ("SD 1.5", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "minimax_h3"}, ("MiniMax H3", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "flux1"}, ("Flux", "metadata")),
    ("loras", "x.safetensors", {"modelspec.architecture": "flux-1-dev/lora"}, ("Flux", "metadata")),
    ("loras", "x.safetensors", {"modelspec.architecture": "Krea-2/lora", "ss_base_model_version": "krea2"},
     ("Krea 2", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "mystery_v9"}, ("mystery_v9", "metadata")),
    ("loras", "pony_style.safetensors", {"ss_base_model_version": "sdxl_base_v1-0"}, ("Pony", "filename")),
    ("checkpoints", "Illustrious XL - v1.0_v1.0.safetensors", {}, ("Illustrious", "filename")),
    ("checkpoints", "AnythingXL_xl.safetensors", {}, ("SDXL", "filename")),
    ("diffusion_models", "wan2.2_t2v_high_noise_14B_fp8.safetensors", {}, ("Wan 2.2", "filename")),
    ("diffusion_models", "wan2.1_i2v_480p_14B.safetensors", {}, ("Wan 2.1", "filename")),
    ("diffusion_models", "z_image_turbo_bf16.safetensors", {}, ("Z-Image", "filename")),
    ("diffusion_models", "qwen_image_edit_fp8.safetensors", {}, ("Qwen-Image", "filename")),
    ("diffusion_models", "flux1-kontext-dev.safetensors", {}, ("Flux Kontext", "filename")),
    ("text_encoders", "qwen3vl_4b_fp8_scaled.safetensors", {}, ("", "not_applicable")),
    ("upscale_models", "4x-UltraSharp.pth", {}, ("", "not_applicable")),
])
def test_底模家族_先元数据再文件名_认不出不猜(modules, folder, name, meta, expected) -> None:
    library, _ = modules
    assert library.family_of(folder, name, meta) == expected


# --- 链接解析 ---------------------------------------------------------------

class _Web:
    """替 sources 的那一个出网口:按 (方法, 地址) 回预先写好的答案,记下每次带的头。"""

    def __init__(self, answers: dict[tuple[str, str], tuple[int, dict[str, str], bytes]],
                 needs_auth: set[str] | None = None) -> None:
        self.answers = answers
        #: 这些地址不带 Authorization 就回 401(要登录才看得到的模型)
        self.needs_auth = needs_auth or set()
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30):
        from sources import Answer

        self.calls.append((method, url, dict(headers or {})))
        if url in self.needs_auth and not (headers or {}).get("Authorization"):
            return Answer(status=401, headers={}, body=b"", url=url)
        status, answer_headers, body = self.answers.get((method, url), (404, {}, b""))
        return Answer(status=status, headers={k.lower(): v for k, v in answer_headers.items()}, body=body, url=url)


def test_解析HuggingFace文件链接_换成直链_大小_按路径里的目录名建议(modules, comfy, monkeypatch) -> None:
    library, sources = modules
    direct = "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors"
    web = _Web({("HEAD", direct): (302, {"X-Linked-Size": "335304388", "Location": "https://cdn/x"}, b"")})
    monkeypatch.setattr(sources, "fetch", web)
    from comfy_http import Comfy

    out = sources.resolve({"url": direct.replace("/resolve/", "/blob/")}, Comfy(comfy.url), "zh")
    assert out["source"] == "huggingface" and out["url"] == direct
    assert out["filename"] == "ae.safetensors" and out["size"] == 335304388
    assert out["folder"] == "vae", "官方仓库按 ComfyUI 的目录名放文件:路径里有这一段就建议它"
    assert out["exists"] is False


def test_解析HuggingFace_要同意条款的仓库_说清楚(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    url = "https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors"
    monkeypatch.setattr(sources, "fetch", _Web({("HEAD", url): (401, {"X-Error-Code": "GatedRepo"}, b"")}))
    from comfy_http import Comfy

    with pytest.raises(Exception, match="令牌"):
        sources.resolve({"url": url}, Comfy(comfy.url), "zh")


def test_解析Civitai页面_版本接口给文件_类型定目录_底模定家族(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    version = {
        "id": 222, "name": "v2.0", "modelId": 111, "baseModel": "Illustrious", "trainedWords": ["chibi", "sd style"],
        "model": {"name": "Chibi Style", "type": "LORA"},
        "files": [{"name": "chibi_training.zip", "type": "Training Data", "sizeKB": 10.0,
                   "downloadUrl": "https://civitai.com/api/download/models/222?type=Training%20Data"},
                  {"name": "chibi_v2.safetensors", "type": "Model", "primary": True, "sizeKB": 148000.5,
                   "downloadUrl": "https://civitai.com/api/download/models/222"}],
    }
    web = _Web({("GET", "https://civitai.com/api/v1/model-versions/222"): (200, {}, json.dumps(version).encode())})
    monkeypatch.setattr(sources, "fetch", web)
    monkeypatch.setenv("CIVITAI_TOKEN", "civ_secret")
    from comfy_http import Comfy

    out = sources.resolve({"url": "https://civitai.com/models/111/chibi-style?modelVersionId=222"}, Comfy(comfy.url), "zh")
    assert out["source"] == "civitai"
    assert out["url"] == "https://civitai.com/api/download/models/222"
    assert (out["filename"], out["size"], out["folder"]) == ("chibi_v2.safetensors", int(148000.5 * 1024), "loras")
    assert (out["family"], out["triggers"]) == ("Illustrious", ["chibi", "sd style"])
    assert out["title"] == "Chibi Style · v2.0"
    assert "civ_secret" not in json.dumps(out), "令牌不进结果"
    assert "Authorization" not in web.calls[0][2], "公开的模型信息不用令牌就看得到:令牌能不带就不带"
    assert out["uses_token"] is True, "下载时会带上 Civitai 令牌(界面据此提醒经 Manager 下载时它会留在那台机器上)"


def test_解析Civitai_链接能点名版本里的哪个文件_按编号或格式精度(modules, comfy, monkeypatch) -> None:
    """一个版本常有几个文件(fp16 / fp8、SafeTensor / PickleTensor):链接带 `fileId` 就是那一个,带 Civitai 下载链接上的
    `format` / `size` / `fp` 就按它们挑;都没带是主文件。点名的编号不在这个版本里,说出来,不悄悄换成主文件。"""
    _, sources = modules
    version = {
        "id": 333, "name": "v1", "modelId": 30, "baseModel": "Flux.1 D", "model": {"name": "F", "type": "Checkpoint"},
        "files": [
            {"id": 9001, "name": "f_fp16.safetensors", "type": "Model", "primary": True, "sizeKB": 2.0,
             "metadata": {"format": "SafeTensor", "size": "full", "fp": "fp16"},
             "downloadUrl": "https://civitai.com/api/download/models/333"},
            {"id": 9002, "name": "f_fp8.safetensors", "type": "Model", "sizeKB": 1.0,
             "metadata": {"format": "SafeTensor", "size": "pruned", "fp": "fp8"},
             "downloadUrl": "https://civitai.com/api/download/models/333?type=Model&format=SafeTensor&size=pruned&fp=fp8"},
        ],
    }
    monkeypatch.setattr(sources, "fetch", _Web({("GET", "https://civitai.com/api/v1/model-versions/333"):
                                                (200, {}, json.dumps(version).encode())}))
    from comfy_http import Comfy

    def resolved(url: str) -> str:
        return sources.resolve({"url": url}, Comfy(comfy.url), "zh")["filename"]

    page = "https://civitai.com/models/30?modelVersionId=333"
    assert resolved(page) == "f_fp16.safetensors", "没点名:主文件"
    assert resolved(f"{page}&fileId=9002") == "f_fp8.safetensors"
    assert resolved("https://civitai.com/api/download/models/333?type=Model&format=SafeTensor&fp=fp8") == "f_fp8.safetensors"
    assert resolved(f"{page}&fp=bf16") == "f_fp16.safetensors", "格式精度对不上的:和 Civitai 一样给主文件"
    with pytest.raises(Exception, match="9003"):
        resolved(f"{page}&fileId=9003")
    assert sources.direct_url(f"{page}&fileId=9002", "zh", set()).endswith("fp=fp8"), "下载用的是那个文件自己的直链"


@pytest.mark.parametrize("host", ["civitai.red", "www.civitai.red", "civitai.green"])
def test_Civitai的别的域名也认_统一走civitai_com的接口(modules, comfy, monkeypatch, host) -> None:
    """用户贴了 https://civitai.red/models/1318945/one-obsession,解析报「这个链接回了 HTTP 403」:插件只认 civitai.com,
    别的域名被当成文件直链,拿插件的 User-Agent 去敲网页,被 Civitai 的防护挡了回来。它们是同一个站,接口一样。"""
    _, sources = modules
    version = {
        "id": 222, "name": "v2.0", "modelId": 111, "baseModel": "Illustrious", "trainedWords": [],
        "model": {"name": "Chibi Style", "type": "LORA"},
        "files": [{"name": "chibi_v2.safetensors", "type": "Model", "primary": True, "sizeKB": 1.0,
                   "downloadUrl": "https://civitai.com/api/download/models/222"}],
    }
    web = _Web({("GET", "https://civitai.com/api/v1/model-versions/222"): (200, {}, json.dumps(version).encode())})
    monkeypatch.setattr(sources, "fetch", web)
    monkeypatch.setenv("CIVITAI_TOKEN", "civ_secret")
    from comfy_http import Comfy

    out = sources.resolve({"url": f"https://{host}/models/111/chibi-style?modelVersionId=222"}, Comfy(comfy.url), "zh")
    assert (out["source"], out["url"], out["filename"]) == ("civitai", "https://civitai.com/api/download/models/222", "chibi_v2.safetensors")
    assert [call[1] for call in web.calls] == ["https://civitai.com/api/v1/model-versions/222"], "只问 civitai.com 的接口"
    # 贴的是别的域名上的下载链接:换成 civitai.com 再下,令牌也只交给 civitai.com
    assert sources.direct_url(f"https://{host}/api/download/models/222", "zh", set()) == "https://civitai.com/api/download/models/222"
    assert sources.token_for(f"https://{host}/api/download/models/222") == ""
    assert sources.token_for("https://civitai.com/api/download/models/222") == "civ_secret"


def test_解析Civitai_要登录才看得到的模型_再带上令牌问一次(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    version = {"id": 9, "name": "v1", "modelId": 8, "baseModel": "Pony", "model": {"name": "P", "type": "LORA"},
               "files": [{"name": "p.safetensors", "type": "Model", "primary": True, "sizeKB": 1,
                          "downloadUrl": "https://civitai.com/api/download/models/9"}]}
    url = "https://civitai.com/api/v1/model-versions/9"
    web = _Web({("GET", url): (200, {}, json.dumps(version).encode())}, needs_auth={url})
    monkeypatch.setattr(sources, "fetch", web)
    monkeypatch.setenv("CIVITAI_TOKEN", "civ_secret")
    from comfy_http import Comfy

    out = sources.resolve({"url": "https://civitai.com/api/download/models/9"}, Comfy(comfy.url), "zh")
    assert out["filename"] == "p.safetensors"
    assert [call[2].get("Authorization") for call in web.calls] == [None, "Bearer civ_secret"]


def test_没填令牌_解析结果说下载不带令牌(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    version = {"id": 7, "name": "v1", "modelId": 6, "baseModel": "SDXL 1.0", "model": {"name": "S", "type": "LORA"},
               "files": [{"name": "s.safetensors", "type": "Model", "primary": True, "sizeKB": 1,
                          "downloadUrl": "https://civitai.com/api/download/models/7"}]}
    monkeypatch.setattr(sources, "fetch", _Web({("GET", "https://civitai.com/api/v1/model-versions/7"):
                                                (200, {}, json.dumps(version).encode())}))
    monkeypatch.delenv("CIVITAI_TOKEN", raising=False)
    from comfy_http import Comfy

    out = sources.resolve({"url": "https://civitai.com/api/download/models/7"}, Comfy(comfy.url), "zh")
    assert out["uses_token"] is False


def test_解析Civitai_同名文件已在_说出来(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    version = {"id": 5, "name": "v1", "modelId": 4, "baseModel": "SDXL 1.0", "model": {"name": "D", "type": "LORA"},
               "files": [{"name": "detail.safetensors", "type": "Model", "primary": True, "sizeKB": 1,
                          "downloadUrl": "https://civitai.com/api/download/models/5"}]}
    monkeypatch.setattr(sources, "fetch", _Web({("GET", "https://civitai.com/api/v1/model-versions/5"):
                                                (200, {}, json.dumps(version).encode())}))
    from comfy_http import Comfy

    out = sources.resolve({"url": "https://civitai.com/api/download/models/5"}, Comfy(comfy.url), "zh")
    assert out["exists"] is True
    assert out["family"] == "SDXL"


def test_解析别的直链_文件名取下载头里的(modules, comfy, files) -> None:
    _, sources = modules
    site = files({"/download/123": b"abc"})
    from comfy_http import Comfy

    out = sources.resolve({"url": f"{site.url}/download/123"}, Comfy(comfy.url), "zh")
    assert (out["source"], out["filename"], out["size"], out["folder"]) == ("direct", "from-header.safetensors", 3, "")
    assert [request["method"] for request in site.requests] == ["HEAD"], "解析只问头,不下整个文件"


def test_解析认不出的HuggingFace页面_说该复制哪个地址(modules, comfy) -> None:
    _, sources = modules
    from comfy_http import Comfy

    with pytest.raises(Exception, match="Files"):
        sources.resolve({"url": "https://huggingface.co/Comfy-Org/z_image_turbo"}, Comfy(comfy.url), "zh")


# --- ModelScope(魔搭)--------------------------------------------------------

def _ms_file(path: str, size: int = 1000) -> dict[str, Any]:
    return {"Path": path, "Name": path.split("/")[-1], "Size": size, "Sha256": "ab" * 32, "Type": "blob"}


#: AIGC 专区里的一个 LoRA(字段照 2026-10 真站点的接口):一个模型文件,类型 LoRA,底模 SDXL 上的 Illustrious。
MS_LORA = {
    "info": {"Name": "chibi-style", "ChineseName": "Q 版画风", "Revision": "master", "AigcType": "LoRA",
             "VisionFoundation": "SD_XL", "BaseModel": ["ModelE/Illustrious-XL"], "TriggerWords": ["chibi", ""]},
    "files": [_ms_file(".gitattributes", 2143), _ms_file("README.md", 2928), _ms_file("configuration.json", 108),
              _ms_file("chibi_v2.safetensors", 228456516)],
}
#: 一个普通仓库(不在 AIGC 专区):ComfyUI 官方的拆分仓库在魔搭上的镜像,按 ComfyUI 的目录名放文件。
MS_SPLIT = {
    "info": {"Name": "Qwen-Image_ComfyUI", "ChineseName": "", "Revision": "master", "AigcType": "", "VisionFoundation": "",
             "BaseModel": []},
    "files": [{"Path": "split_files", "Name": "split_files", "Size": 0, "Type": "tree"},
              {"Path": "split_files/vae", "Name": "vae", "Size": 0, "Type": "tree"},
              _ms_file("README.md"), _ms_file("split_files/vae/qwen_image_vae.safetensors", 253806246),
              _ms_file("split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors", 20430635136),
              _ms_file("split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", 9384670680)],
}


class _ModelScope:
    """替 sources 的出网口扮 ModelScope:模型信息(`/api/v1/models/{仓库}`)、文件列表(`…/repo/files`,认 Revision、
    Root、Recursive)。真站点的样子:没有的仓库、没有的分支回 404;`locked` 里的仓库不带对的令牌就回给定的状态码
    (私有的回 404,要授权的回 401 / 403)。站点按域名分:modelscope.cn 和 modelscope.ai 各是各的。记下每次请求。"""

    def __init__(self, repos: dict[str, dict[str, Any]], *, site: str = "modelscope.cn",
                 locked: dict[str, int] | None = None, token: str = "ms_secret") -> None:
        self.repos, self.site, self.locked, self.token = repos, site, locked or {}, token
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30):
        self.calls.append((method, url, dict(headers or {})))
        parts = parse.urlsplit(url)
        found = re.match(r"^/api/v1/models/([^/]+/[^/]+?)(/repo/files)?$", parse.unquote(parts.path))
        repo = found.group(1) if found and parts.hostname == self.site else ""
        if repo not in self.repos:
            return self._answer(404, {"Code": 10010205001, "Message": "获取模型信息失败,信息:record not found", "Success": False})
        if repo in self.locked and (headers or {}).get("Authorization") != f"Bearer {self.token}":
            return self._answer(self.locked[repo], {"Code": self.locked[repo], "Message": "denied", "Success": False})
        if not found.group(2):
            return self._answer(200, {"Code": 200, "Data": self.repos[repo]["info"], "Success": True})
        query = {key: values[0] for key, values in parse.parse_qs(parts.query).items()}
        if query.get("Revision", "master") != "master":
            return self._answer(404, {"Code": 10990101004, "Message": "获取模型目录树失败", "Success": False})
        root = query.get("Root", "").strip("/")
        recursive = query.get("Recursive", "true").lower() == "true"

        def under(path: str) -> bool:
            rest = path[len(root) + 1:] if root else path
            return (not root or path.startswith(root + "/")) and (recursive or "/" not in rest)

        files = [one for one in self.repos[repo]["files"] if under(one["Path"])]
        return self._answer(200, {"Code": 200, "Data": {"Files": files or None}, "Success": True})

    def _answer(self, status: int, body: dict[str, Any]):
        from sources import Answer

        return Answer(status=status, headers={"content-type": "application/json"},
                      body=json.dumps(body, ensure_ascii=False).encode(), url="")


def test_解析ModelScope文件页_AIGC类型定目录_底模定家族_交回resolve直链(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    site = _ModelScope({"someone/chibi-style": MS_LORA})
    monkeypatch.setattr(sources, "fetch", site)
    monkeypatch.setenv("MODELSCOPE_TOKEN", "ms_secret")
    from comfy_http import Comfy

    out = sources.resolve({"url": "https://modelscope.cn/models/someone/chibi-style/file/view/master/chibi_v2.safetensors?status=1"},
                          Comfy(comfy.url), "zh")
    assert out["source"] == "modelscope"
    assert out["url"] == "https://modelscope.cn/models/someone/chibi-style/resolve/master/chibi_v2.safetensors"
    assert (out["filename"], out["size"], out["folder"]) == ("chibi_v2.safetensors", 228456516, "loras"), "AIGC 类型 LoRA → loras"
    assert out["family"] == "Illustrious", "登记的底模类型是 SDXL,底模仓库名说是 Illustrious"
    assert (out["triggers"], out["title"]) == (["chibi"], "Q 版画风")
    assert out["page"] == "https://modelscope.cn/models/someone/chibi-style/file/view/master/chibi_v2.safetensors"
    assert "ms_secret" not in json.dumps(out), "令牌不进结果"
    assert all("Authorization" not in headers and "Cookie" not in headers for _, _, headers in site.calls), \
        "公开的模型不用令牌就看得到:令牌能不带就不带"
    assert out["uses_token"] is True, "下载时会带上 ModelScope 令牌(经 Manager 时带不过去,界面据此提醒)"
    english = sources.resolve({"url": "https://modelscope.cn/models/someone/chibi-style/file/view/master/chibi_v2.safetensors"},
                              Comfy(comfy.url), "en")
    assert english["title"] == "chibi-style", "英文界面用仓库名"


@pytest.mark.parametrize("url", [
    "https://modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/resolve/master/split_files/vae/qwen_image_vae.safetensors",
    "https://modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/file/view/master/split_files%2Fvae%2Fqwen_image_vae.safetensors?status=2",
    "https://modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/file/view/master/split_files/vae/qwen_image_vae.safetensors",
    "https://www.modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/file/view/master/split_files/vae/qwen_image_vae.safetensors",
    "https://modelscope.cn/api/v1/models/Comfy-Org/Qwen-Image_ComfyUI/repo?Revision=master&FilePath=split_files%2Fvae%2Fqwen_image_vae.safetensors",
    # 目录页:里面只有一个模型文件,就是它
    "https://modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/tree/master/split_files/vae",
])
def test_解析ModelScope各种文件链接_不在AIGC专区的按路径里的目录名建议(modules, comfy, monkeypatch, url) -> None:
    _, sources = modules
    monkeypatch.setattr(sources, "fetch", _ModelScope({"Comfy-Org/Qwen-Image_ComfyUI": MS_SPLIT}))
    from comfy_http import Comfy

    out = sources.resolve({"url": url}, Comfy(comfy.url), "zh")
    assert out["url"] == \
        "https://modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/resolve/master/split_files/vae/qwen_image_vae.safetensors"
    assert (out["filename"], out["size"], out["folder"], out["family"]) == ("qwen_image_vae.safetensors", 253806246, "vae", "")


@pytest.mark.parametrize("page", ["", "/", "/summary", "/files"])
def test_解析ModelScope模型页_只有一个模型文件就是它(modules, comfy, monkeypatch, page) -> None:
    _, sources = modules
    monkeypatch.setattr(sources, "fetch", _ModelScope({"someone/chibi-style": MS_LORA}))
    from comfy_http import Comfy

    out = sources.resolve({"url": f"https://modelscope.cn/models/someone/chibi-style{page}"}, Comfy(comfy.url), "zh")
    assert (out["filename"], out["folder"]) == ("chibi_v2.safetensors", "loras")
    assert out["url"] == "https://modelscope.cn/models/someone/chibi-style/resolve/master/chibi_v2.safetensors"


def test_解析ModelScope模型页_好几个模型文件_列出候选请贴具体文件(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    monkeypatch.setattr(sources, "fetch", _ModelScope({"Comfy-Org/Qwen-Image_ComfyUI": MS_SPLIT}))
    from comfy_http import Comfy

    with pytest.raises(Exception) as caught:
        sources.resolve({"url": "https://modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/files"}, Comfy(comfy.url), "zh")
    message = str(caught.value)
    assert "3 个模型文件" in message
    assert "split_files/vae/qwen_image_vae.safetensors" in message and "qwen_2.5_vl_7b_fp8_scaled.safetensors" in message
    assert "README.md" not in message, "只列模型文件"
    assert "文件" in message and "地址" in message, "说该贴哪个地址"


def test_解析ModelScope模型页_一个模型文件都没有_说清楚(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    empty = {"info": MS_SPLIT["info"], "files": [_ms_file("README.md"), _ms_file("configuration.json")]}
    monkeypatch.setattr(sources, "fetch", _ModelScope({"a/b": empty}))
    from comfy_http import Comfy

    with pytest.raises(Exception, match="没有模型文件"):
        sources.resolve({"url": "https://modelscope.cn/models/a/b"}, Comfy(comfy.url), "zh")


@pytest.mark.parametrize(("kind", "folder"), [("Checkpoint", "checkpoints"), ("LoRA", "loras"), ("VAE", "vae"),
                                               ("", "")])
def test_ModelScope的AIGC类型定目录(modules, comfy, monkeypatch, kind, folder) -> None:
    _, sources = modules
    repo = {"info": {**MS_LORA["info"], "AigcType": kind}, "files": [_ms_file("x.safetensors")]}
    monkeypatch.setattr(sources, "fetch", _ModelScope({"a/b": repo}))
    from comfy_http import Comfy

    out = sources.resolve({"url": "https://modelscope.cn/models/a/b/resolve/master/x.safetensors"}, Comfy(comfy.url), "zh")
    assert out["folder"] == folder
    assert bool(out["family"]) is bool(kind), "底模家族只看 AIGC 专区登记的;普通仓库不猜"


@pytest.mark.parametrize(("vision", "bases", "expected"), [
    ("SD_XL", [], "SDXL"),
    ("SD_XL", ["ModelE/Illustrious-XL"], "Illustrious"),
    ("SD_XL", ["LaxharLAB/NoobAI-XL@epsilon1.1"], "NoobAI"),
    ("SD_XL", ["Liudef/XB_PONY"], "Pony"),
    ("SD_1_5", ["MusePublic/majicMIX_realistic"], "SD 1.5"),
    ("SD_2_1", [], "SD 2"),
    ("SD_3", [], "SD 3"),
    ("FLUX_1", ["black-forest-labs/FLUX.1-dev"], "Flux"),
    ("FLUX_2", ["black-forest-labs/FLUX.2-dev"], "Flux.2"),
    ("QWEN_IMAGE_20_B", ["Qwen/Qwen-Image"], "Qwen-Image"),
    ("Z_IMAGE_TURBO", ["Tongyi-MAI/Z-Image-Turbo@master"], "Z-Image"),
    ("WAN_VIDEO_2_2_I2V_A_14_B", ["Wan-AI/Wan2.2-I2V-A14B"], "Wan 2.2"),
    ("WAN_VIDEO_2_1_T2V_14_B", [], "Wan 2.1"),
    ("MINIMAX_H3", ["MiniMax/MiniMax-H3"], "MiniMax H3"),
    ("LTX_VIDEO", [], "LTX-Video"),
    # 没登记类型(或 UNKNOWN):看底模仓库名
    ("", ["AI-ModelScope/stable-diffusion-xl-base-1.0"], "SDXL"),
    ("UNKNOWN", ["MusePublic/489_ckpt_FLUX_1@2172"], "Flux"),
    # 表里没有的:底模仓库名原样交出(没有就类型原样),不往认得的家族上靠
    ("KREA_2", ["krea/Krea-2-Turbo"], "Krea 2"),
    ("", ["someone/Mystery-Diffusion-9"], "Mystery-Diffusion-9"),
    ("IDEOGRAM_4", [], "IDEOGRAM_4"),
    ("", ["undefined", ""], ""),
    ("", [], ""),
])
def test_ModelScope登记的底模_接同一张家族表(modules, vision, bases, expected) -> None:
    from families import family_from_modelscope

    assert family_from_modelscope(vision, bases) == expected


def test_ModelScope登记成SDXL的_自己的仓库名和文件名也能细分(modules) -> None:
    """真站点上的 ModelE/Illustrious-XL:Checkpoint,类型 SD_XL,底模写的是 SDXL base —— 它本身就是 Illustrious。"""
    from families import family_from_modelscope

    assert family_from_modelscope("SD_XL", ["stabilityai/stable-diffusion-xl-base-1.0"],
                                  ("Illustrious-XL", "Illustrious-XL-v0.1.safetensors")) == "Illustrious"
    assert family_from_modelscope("SD_XL", ["stabilityai/stable-diffusion-xl-base-1.0"], ("my-style", "x.safetensors")) == "SDXL"
    assert family_from_modelscope("FLUX_1", [], ("pony-on-flux", "x.safetensors")) == "Flux", "只在认出是 SDXL 之后细分"


def test_解析ModelScope_私有模型_不带令牌回404_带上令牌再问一次(modules, comfy, monkeypatch) -> None:
    """ModelScope 对看不到的私有模型回 404(官方 SDK 也这么说:不存在,或者是要登录的私有仓库)。"""
    _, sources = modules
    site = _ModelScope({"me/private": MS_LORA}, locked={"me/private": 404})
    monkeypatch.setattr(sources, "fetch", site)
    monkeypatch.setenv("MODELSCOPE_TOKEN", "ms_secret")
    from comfy_http import Comfy

    out = sources.resolve({"url": "https://modelscope.cn/models/me/private/resolve/master/chibi_v2.safetensors"},
                          Comfy(comfy.url), "zh")
    assert out["filename"] == "chibi_v2.safetensors"
    assert [headers.get("Authorization") for _, _, headers in site.calls] == [None, "Bearer ms_secret", "Bearer ms_secret"], \
        "先不带;模型信息带了令牌才看得到,文件列表直接带"
    assert all(headers.get("Cookie") == "m_session_id=ms_secret" for _, _, headers in site.calls[1:]), \
        "老接口和下载认会话 cookie(官方 SDK 两样都带)"
    assert "ms_secret" not in json.dumps(out)


@pytest.mark.parametrize(("status", "token", "said"), [
    (404, "", "令牌"), (404, "ms_wrong", "没有这个模型"),
    (401, "", "填"), (403, "", "填"), (403, "ms_wrong", "没有权限"),
])
def test_解析ModelScope_被拒或没有_说清楚(modules, comfy, monkeypatch, status, token, said) -> None:
    """`ms_wrong` 是看不到这个模型的令牌(别人的,或另一个站的)。"""
    _, sources = modules
    site = _ModelScope({"me/private": MS_LORA}, locked={"me/private": status})
    monkeypatch.setattr(sources, "fetch", site)
    if token:
        monkeypatch.setenv("MODELSCOPE_TOKEN", token)
    else:
        monkeypatch.delenv("MODELSCOPE_TOKEN", raising=False)
    from comfy_http import Comfy

    with pytest.raises(Exception) as caught:
        sources.resolve({"url": "https://modelscope.cn/models/me/private"}, Comfy(comfy.url), "zh")
    message = str(caught.value)
    assert said in message and "ModelScope" in message
    assert not token or token not in message, "令牌不进报错"
    assert len(site.calls) == (2 if token else 1), "填了令牌才再问一次"


def test_解析ModelScope_没有的文件_没有的分支_说清楚(modules, comfy, monkeypatch) -> None:
    _, sources = modules
    monkeypatch.setattr(sources, "fetch", _ModelScope({"someone/chibi-style": MS_LORA}))
    from comfy_http import Comfy

    with pytest.raises(Exception, match="没有这个文件"):
        sources.resolve({"url": "https://modelscope.cn/models/someone/chibi-style/resolve/master/nope.safetensors"},
                        Comfy(comfy.url), "zh")
    with pytest.raises(Exception, match="v9"):
        sources.resolve({"url": "https://modelscope.cn/models/someone/chibi-style/resolve/v9/chibi_v2.safetensors"},
                        Comfy(comfy.url), "zh")


def test_ModelScope国际站_是另一个站_各认各的(modules, comfy, monkeypatch) -> None:
    """modelscope.ai 和 modelscope.cn 接口一样,但模型库和账号各是各的(.cn 上的模型 .ai 上不一定有):
    只把 www. 换掉,不互相改写。"""
    _, sources = modules
    site = _ModelScope({"someone/chibi-style": MS_LORA}, site="modelscope.ai")
    monkeypatch.setattr(sources, "fetch", site)
    from comfy_http import Comfy

    out = sources.resolve({"url": "https://www.modelscope.ai/models/someone/chibi-style"}, Comfy(comfy.url), "zh")
    assert out["url"] == "https://modelscope.ai/models/someone/chibi-style/resolve/master/chibi_v2.safetensors"
    assert {sources._host(url) for _, url, _ in site.calls} == {"modelscope.ai"}  # noqa: SLF001
    assert sources.canonical_url("https://www.modelscope.cn/models/a/b") == "https://modelscope.cn/models/a/b"
    assert sources.canonical_url("https://modelscope.ai/models/a/b") == "https://modelscope.ai/models/a/b"


def test_ModelScope令牌_只发给ModelScope自己的站(modules, monkeypatch) -> None:
    _, sources = modules
    monkeypatch.setenv("MODELSCOPE_TOKEN", "ms_secret")
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_secret")
    for url in ("https://modelscope.cn/models/a/b/resolve/master/x.safetensors",
                "https://modelscope.ai/models/a/b/resolve/master/x.safetensors"):
        assert sources.auth_for(url) == {"Authorization": "Bearer ms_secret", "Cookie": "m_session_id=ms_secret"}
    # 下载跳到的 CDN(签好名的地址)、别名域名、别的站都不带
    for url in ("https://cdn-lfs-cn-1.modelscope.cn/prod/lfs-objects/48/52/x?auth_key=1",
                "https://www.modelscope.cn/models/a/b/resolve/master/x.safetensors",
                "https://modelscope.cn.evil.example/models/a/b", "https://example.com/x.safetensors"):
        assert sources.auth_for(url) == {}, url
    assert sources.auth_for("https://huggingface.co/a/b/resolve/main/x.safetensors") == {"Authorization": "Bearer hf_secret"}


def test_下载时ModelScope的页面链接换成resolve直链_不用联网(modules, monkeypatch) -> None:
    _, sources = modules

    def offline(*_args: Any, **_kwargs: Any):
        raise AssertionError("文件链接换直链不该联网")

    monkeypatch.setattr(sources, "fetch", offline)
    assert sources.direct_url("https://www.modelscope.cn/models/a/b/file/view/master/sub%2Fx.safetensors", "zh", set()) == \
        "https://modelscope.cn/models/a/b/resolve/master/sub/x.safetensors"
    assert sources.direct_url("https://modelscope.cn/api/v1/models/a/b/repo?Revision=v1&FilePath=x.gguf", "zh", set()) == \
        "https://modelscope.cn/models/a/b/resolve/v1/x.gguf"


def test_Manager那条路_ModelScope的令牌带不过去_不拼进地址(comfy, data_dir, tmp_path) -> None:
    comfy.state.manager = "V4.2.1"
    out, _ = _download(comfy, {"url": "https://modelscope.cn/models/a/b/file/view/master/tiny.safetensors",
                               "folder": "vae", "filename": "mosael-test-tiny.safetensors"},
                       data_dir, tmp_path, MODELSCOPE_TOKEN="ms_secret")
    assert out["route"] == "manager"
    task = comfy.posted("/v2/manager/queue/install_model")[0]
    assert task["url"] == "https://modelscope.cn/models/a/b/resolve/master/tiny.safetensors"
    assert "ms_secret" not in json.dumps(comfy.posted("/v2/manager/queue/install_model")), \
        "Manager 不收请求头,ModelScope 的令牌又没有放进地址的用法:不拼进去"


def test_工作流声明的ModelScope地址也算可信来源_先换成规范域名(comfy, data_dir) -> None:
    comfy.state.workflows["ms.json"] = {
        "id": "ms", "links": [],
        "nodes": [{"id": 1, "type": "VAELoader", "widgets_values": ["qwen_image_vae.safetensors"], "inputs": [],
                   "properties": {"models": [{
                       "name": "qwen_image_vae.safetensors", "directory": "vae",
                       "url": "https://www.modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/resolve/master/"
                              "split_files/vae/qwen_image_vae.safetensors"}]}}],
    }
    out = _call(comfy, {"op": "library"}, data_dir)
    found = next(one for one in out["missing"] if one["name"] == "qwen_image_vae.safetensors")
    assert found["url"] == \
        "https://modelscope.cn/models/Comfy-Org/Qwen-Image_ComfyUI/resolve/master/split_files/vae/qwen_image_vae.safetensors"


def test_插件的持久目录里没有令牌(comfy, data_dir, tmp_path) -> None:
    comfy.state.manager = "V4.2.1"
    comfy.state.manager_outcome = "policy"
    with pytest.raises(PluginRuntimeError):
        _download(comfy, {"url": "https://civitai.com/api/download/models/5", "folder": "loras",
                          "filename": "x.safetensors"}, data_dir, tmp_path, CIVITAI_TOKEN="civ_secret")
    for file in data_dir.rglob("*"):
        if file.is_file():
            assert "civ_secret" not in file.read_text(encoding="utf-8", errors="replace")


def test_连不上时_第一行只说该做什么_地址和原文在下一行(modules) -> None:
    """界面把报错的第一行当正文,其余收进「详情」(docs/PLUGIN_MANIFEST.md):用户先读到的是该做什么,不是 errno。"""
    from comfy_http import Comfy
    from lines import ComfyError

    with socket.socket() as sock:  # 一个没人在听的端口
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    for locale, first in (("zh", "连不上这台 ComfyUI,确认它在运行、地址填对"),
                          ("en", "Can't reach this ComfyUI. Make sure it is running and the URL is right")):
        with pytest.raises(ComfyError) as caught:
            Comfy(f"http://127.0.0.1:{port}", locale).get("/system_stats")
        head, *rest = str(caught.value).split("\n")
        assert head == first
        assert rest and f"http://127.0.0.1:{port}" in rest[0], "地址和原文在下一行,排查的人展开还看得到"


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)

