"""ComfyUI 插件的模型库(ADR 0034):对着一台假的 ComfyUI(tests/fake_comfyui)。

框架那一侧(宿主列表、预览缓存、下载任务)钉在 test_plugin_model_library.py;这里钉的是插件自己:

- 列出:每个目录的每个文件(大小、改动时间、预览地址),推断的底模家族(先元数据、再文件名,凭的是什么写明)、
  触发词(作者写的,或训练标签里最多的几个)、哪几张工作流在用;
- 工作流缺的模型:声明了下载地址、节点真在用、这台服务器上又没有的才列,只认 HuggingFace / Civitai;
- 逐个读的元数据记在持久目录里,第二次只读目录;
- 链接解析:HuggingFace 文件、Civitai 页面、别的直链;
- 下载按优先级走:Manager → 同一台机器直接写 → 说清楚能做的那一步。不覆盖已有文件,取消时只删自己的半截文件,
  空间不够就不下;Manager 被安全策略拒绝时说人话、记下来,能走本机就走本机;令牌只发给它自己那个站。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from app.domain.plugins.runtime import PluginRuntimeError
from tests.fake_comfyui import FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
TOOLS = PLUGIN / "tools"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "workflows",
            "tooling", "library", "sources", "install")

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
    assert (anima["family"], anima["family_source"]) == ("anima", "metadata"), "表里没有的值原样显示,不往 SD1 上靠"
    assert (anima["triggers"], anima["triggers_source"]) == (["anima style", "flat color"], "metadata")
    painting = by_key[("checkpoints", "AWPainting_IL.safetensors")]
    assert (painting["family"], painting["family_source"]) == ("Illustrious", "filename")
    noob = by_key[("loras", "chars\\noob_char.safetensors")]
    assert (noob["family"], noob["family_source"]) == ("NoobAI", "filename"), "子目录名也算"
    assert by_key[("upscale_models", "4x-UltraSharp.pth")].get("family", "") == "", "认不出就空着,不猜"
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
    assert out == {"folder": "vae", "name": "mosael-test-tiny.safetensors", "size": 200_000, "route": "local"}
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
              data_dir, tmp_path, HUGGINGFACE_TOKEN="hf_secret", CIVITAI_TOKEN="civ_secret")
    assert all(request["auth"] is None for request in site.requests), "HuggingFace / Civitai 的令牌不发给别的站"


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
     ("krea2", "metadata")),
    ("loras", "pony_style.safetensors", {"ss_base_model_version": "sdxl_base_v1-0"}, ("Pony", "filename")),
    ("checkpoints", "Illustrious XL - v1.0_v1.0.safetensors", {}, ("Illustrious", "filename")),
    ("checkpoints", "AnythingXL_xl.safetensors", {}, ("SDXL", "filename")),
    ("diffusion_models", "wan2.2_t2v_high_noise_14B_fp8.safetensors", {}, ("Wan 2.2", "filename")),
    ("diffusion_models", "wan2.1_i2v_480p_14B.safetensors", {}, ("Wan 2.1", "filename")),
    ("diffusion_models", "z_image_turbo_bf16.safetensors", {}, ("Z-Image", "filename")),
    ("diffusion_models", "qwen_image_edit_fp8.safetensors", {}, ("Qwen-Image", "filename")),
    ("diffusion_models", "flux1-kontext-dev.safetensors", {}, ("Flux Kontext", "filename")),
    ("text_encoders", "qwen3vl_4b_fp8_scaled.safetensors", {}, ("", "")),
    ("upscale_models", "4x-UltraSharp.pth", {}, ("", "")),
])
def test_底模家族_先元数据再文件名_认不出不猜(modules, folder, name, meta, expected) -> None:
    library, _ = modules
    assert library.family_of(folder, name, meta) == expected


# --- 链接解析 ---------------------------------------------------------------

class _Web:
    """替 sources 的那一个出网口:按 (方法, 地址) 回预先写好的答案,记下每次带的头。"""

    def __init__(self, answers: dict[tuple[str, str], tuple[int, dict[str, str], bytes]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30):
        from sources import Answer

        self.calls.append((method, url, dict(headers or {})))
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
    assert web.calls[0][2].get("Authorization") == "Bearer civ_secret", "Civitai 的接口带它自己的令牌"


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


def test_插件的持久目录里没有令牌(comfy, data_dir, tmp_path) -> None:
    comfy.state.manager = "V4.2.1"
    comfy.state.manager_outcome = "policy"
    with pytest.raises(PluginRuntimeError):
        _download(comfy, {"url": "https://civitai.com/api/download/models/5", "folder": "loras",
                          "filename": "x.safetensors"}, data_dir, tmp_path, CIVITAI_TOKEN="civ_secret")
    for file in data_dir.rglob("*"):
        if file.is_file():
            assert "civ_secret" not in file.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)

