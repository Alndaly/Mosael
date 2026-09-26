"""ComfyUI 插件真的跑起来:经宿主的插件运行时起进程,对着一台假的 ComfyUI(tests/fake_comfyui)。

钉住的是插件那一侧的协议与行为(见 docs/PLUGIN_MANIFEST「替宿主做生成」):

- `op: models` 列出内置文生图、粘贴的 API 模板、保存的每张工作流,坏模板也列(选中时说清哪里坏);
- `op: generate`:参考图先 `/upload/image` 再接到 LoadImage 上;参数表里动过的值写回对应节点;
  提交后立刻交回回执;进度来自 WebSocket(连不上就轮询);产出取回到 MOSAEL_PLUGIN_OUTPUT_DIR;
- 取消只停**这一个**任务(在跑的 interrupt,不碰队列里别人的);重启后带着回执接着等,不再提交;
- 失败说人话:连不上报地址、校验不过报哪个节点、执行失败报 ComfyUI 自己的原因。
"""

from __future__ import annotations

import base64
import json
import socket
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from tests.fake_comfyui import PNG, FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
TOOL = "comfyui_generation"


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        yield server


def _models(url: str, **env: str) -> list[dict[str, Any]]:
    result = runtime.execute_tool(PLUGIN, ENTRY, TOOL, {"op": "models"}, {"SERVER_URL": url, **env}, timeout=60)
    return result.output["models"]


class _Hooks:
    def __init__(self, cancel_after_task: bool = False) -> None:
        self.progress: list[tuple[float, str]] = []
        self.tasks: list[dict[str, Any]] = []
        self.cancel_after_task = cancel_after_task

    def build(self) -> runtime.StreamHooks:
        return runtime.StreamHooks(
            on_progress=lambda fraction, message: self.progress.append((fraction, message)),
            on_task=self.tasks.append,
            is_cancelled=lambda: self.cancel_after_task and bool(self.tasks),
        )


def _generate(url: str, tmp_path: Path, payload: dict[str, Any], hooks: _Hooks | None = None, **env: str):
    scratch = tmp_path / "out"
    scratch.mkdir(exist_ok=True)
    hooks = hooks or _Hooks()
    request = {"op": "generate", "kind": "image", "prompt": "海边的柴犬", "negative_prompt": "", "parameters": {},
               "inputs": [], "resume": None, **payload}
    result = runtime.stream_tool(PLUGIN, ENTRY, TOOL, request, {"SERVER_URL": url, **env},
                                 hooks=hooks.build(), scratch_dir=scratch, timeout=60)
    return result.output, hooks, scratch


def _png(tmp_path: Path) -> Path:
    path = tmp_path / "参考.png"
    path.write_bytes(PNG)
    return path


# --- 目录 ---------------------------------------------------------------------


def test_目录列出内置文生图_API模板和每张保存的工作流(comfy) -> None:
    template = json.dumps({"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}},
                           "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["1", 0]}}})
    models = {one["id"]: one for one in _models(comfy.url, API_WORKFLOW=template)}
    assert list(models) == ["builtin:txt2img", "api-workflow", "portrait.json", "video/wan.json"]
    assert models["builtin:txt2img"]["label"] == {"zh": "内置文生图", "en": "Built-in text-to-image"}
    assert models["builtin:txt2img"]["parameters"]["size"]["default"] == "1024x1024"
    assert models["builtin:txt2img"]["parameters"]["4.ckpt_name"]["default"] == "sd_xl_base.safetensors"
    assert models["portrait.json"]["label"] == "portrait" and models["portrait.json"]["kind"] == "image"
    assert models["portrait.json"]["inputs"] == [{"role": "reference_image", "max": 1}]
    assert models["video/wan.json"]["kind"] == "video"


def test_坏模板也列出来_选中时再说清楚哪里坏(comfy, tmp_path: Path) -> None:
    models = {one["id"]: one for one in _models(comfy.url, API_WORKFLOW="not json")}
    assert models["api-workflow"]["kind"] == "image"
    with pytest.raises(runtime.PluginRuntimeError, match="导出"):
        _generate(comfy.url, tmp_path, {"model": "api-workflow"}, API_WORKFLOW="not json")


def test_没有checkpoint就不列内置文生图(comfy) -> None:
    comfy.state.object_info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [[]]
    assert "builtin:txt2img" not in {one["id"] for one in _models(comfy.url)}


# --- 一次生成 ---------------------------------------------------------------------


def test_一次生成_参考图传上去接到LoadImage上_产出取回(comfy, tmp_path: Path) -> None:
    reference = _png(tmp_path)
    output, hooks, scratch = _generate(comfy.url, tmp_path, {
        "model": "portrait.json",
        "parameters": {"seed": 7, "size": "1024x1024", "3.steps": 30, "negative_prompt": "ignored-by-host-key"},
        "negative_prompt": "模糊",
        "inputs": [{"role": "reference_image", "path": str(reference)}],
    })
    [(uploaded_name, uploaded_bytes)] = comfy.state.uploads
    assert uploaded_bytes == PNG and uploaded_name.endswith("参考.png")
    [submitted] = comfy.posted("/prompt")
    prompt = submitted["prompt"]
    assert prompt["10"]["inputs"]["image"] == f"mosael/{uploaded_name}", "参考图接到 LoadImage 上"
    assert prompt["6"]["inputs"]["text"] == "海边的柴犬" and prompt["7"]["inputs"]["text"] == "模糊"
    assert prompt["3"]["inputs"]["seed"] == 7 and prompt["3"]["inputs"]["steps"] == 30
    assert (prompt["5"]["inputs"]["width"], prompt["5"]["inputs"]["height"]) == (1024, 1024)
    assert "11" not in prompt, "Note 不进 prompt"
    # 提交之后立刻交回回执 —— 宿主落库,重启后带着它来接着等
    assert hooks.tasks == [{"prompt_id": "p1", "client_id": submitted["client_id"]}]
    assert hooks.progress and all(0 <= fraction <= 0.95 for fraction, _ in hooks.progress)
    [produced] = output["outputs"]
    assert (scratch / produced["path"]).read_bytes() == PNG
    assert output["usage"] == {"images": 1}, "预览图(temp)不算产出"


def test_目录里说清每张图要不要写提示词(comfy) -> None:
    template = json.dumps({"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}},
                           "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["1", 0]}}})
    models = {one["id"]: one for one in _models(comfy.url, API_WORKFLOW=template)}
    assert models["builtin:txt2img"]["prompt"] == "required", "内置文生图的提示词是占位符,没有默认"
    assert models["portrait.json"]["prompt"] == "optional", "存着「a cat」:不写就用它"


def test_可以不写提示词的图_空着就用它自己存的那句(comfy, tmp_path: Path) -> None:
    """宿主发来的空提示词是「没写」,不是「清成空串」—— 否则一张存好提示词的图拿一句空话去跑。"""
    _generate(comfy.url, tmp_path, {"model": "portrait.json", "prompt": ""})
    prompt = comfy.posted("/prompt")[0]["prompt"]
    assert prompt["6"]["inputs"]["text"] == "a cat"


def test_反向提示词空着_用它自己存的那句(comfy, tmp_path: Path) -> None:
    """用户没写反向提示词时宿主发来空串:那是「没写」,不该把工作流里存着的「blurry」清掉。"""
    _generate(comfy.url, tmp_path, {"model": "portrait.json", "negative_prompt": ""})
    prompt = comfy.posted("/prompt")[0]["prompt"]
    assert prompt["7"]["inputs"]["text"] == "blurry"


def test_音频图_模式是文生音频_用量记成几段音频(comfy, tmp_path: Path) -> None:
    comfy.state.workflows["music.json"] = {
        "1": {"class_type": "EmptyAceStepLatentAudio", "inputs": {"seconds": 30, "batch_size": 1}},
        "2": {"class_type": "SaveAudio", "inputs": {"audio": ["1", 0], "filename_prefix": "audio/ComfyUI"}},
    }
    comfy.state.outputs = {"2": {"audio": [{"filename": "ComfyUI_00001_.flac", "subfolder": "audio", "type": "output"}]}}
    models = {one["id"]: one for one in _models(comfy.url)}
    assert models["music.json"]["kind"] == "audio" and models["music.json"]["modes"] == ["text-to-audio"]
    output, _, _ = _generate(comfy.url, tmp_path, {"model": "music.json", "kind": "audio", "prompt": ""})
    assert output["usage"] == {"audios": 1}, "宿主按 audios 计量,不是 images"


def test_进度来自WebSocket(comfy, tmp_path: Path) -> None:
    comfy.state.websocket = True
    _, hooks, _ = _generate(comfy.url, tmp_path, {"model": "portrait.json"})
    messages = [message for _, message in hooks.progress]
    assert "采样 5/20 · 第 2/8 个节点" in messages, "说的是界面上的节点名字(用户起的「采样」)、第几步、第几个节点"
    fractions = [fraction for fraction, _ in hooks.progress]
    assert fractions == sorted(fractions), "进度只往前走"


def test_WebSocket中途被重置_退回轮询照样取回(comfy, tmp_path: Path) -> None:
    """进度是锦上添花:WebSocket 断了(连接被重置、读超时)不能让这次生成失败。"""
    comfy.state.websocket = True
    comfy.state.websocket_reset = True
    output, _, _ = _generate(comfy.url, tmp_path, {"model": "portrait.json"})
    assert len(output["outputs"]) == 1


def test_视频图取回的是合成的视频_首帧接到start_image(comfy, tmp_path: Path) -> None:
    comfy.state.outcome = "video"
    output, _, scratch = _generate(comfy.url, tmp_path, {
        "model": "video/wan.json", "kind": "video",
        "inputs": [{"role": "first_frame", "path": str(_png(tmp_path))}],
    })
    prompt = comfy.posted("/prompt")[0]["prompt"]
    assert prompt["12"]["inputs"]["image"].startswith("mosael/")
    assert prompt["20"]["inputs"]["width"] == 832, "没选尺寸就用这张图自己的"
    [produced] = output["outputs"]
    assert produced["path"].endswith(".mp4") and (scratch / produced["path"]).read_bytes() == b"mp4-bytes"
    assert output["usage"] == {"videos": 1}


def test_取消只停这一个任务(comfy, tmp_path: Path) -> None:
    comfy.state.outcome = "never"
    comfy.state.pending = ["someone-else"]
    with pytest.raises(runtime.PluginCancelled):
        _generate(comfy.url, tmp_path, {"model": "portrait.json"}, _Hooks(cancel_after_task=True))
    assert comfy.posted("/interrupt") == [{"prompt_id": "p1"}], "在跑的是我的:interrupt 它"
    assert comfy.posted("/queue") == [], "队列里是别人的任务,不碰"


def test_重启后带着回执接着等_不再提交(comfy, tmp_path: Path) -> None:
    comfy.state.history["p9"] = {
        "status": {"status_str": "success", "completed": True},
        "outputs": {"9": {"images": [{"filename": "done.png", "subfolder": "", "type": "output"}]}},
    }
    output, hooks, _ = _generate(comfy.url, tmp_path, {"model": "portrait.json", "resume": {"prompt_id": "p9"}})
    assert comfy.posted("/prompt") == [], "接着等的那一次不能再提交 —— 那会再跑一遍"
    assert hooks.tasks == []
    assert len(output["outputs"]) == 1


# --- 失败说人话 -----------------------------------------------------------------------


def _unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_要登录的ComfyUI_按访问凭据带上Authorization头_WebSocket也带(comfy, tmp_path: Path) -> None:
    comfy.state.authorization = "Bearer s3cret"
    comfy.state.websocket = True
    with pytest.raises(runtime.PluginRuntimeError, match="401"):
        _models(comfy.url)
    assert "portrait.json" in {one["id"] for one in _models(comfy.url, ACCESS_TOKEN="s3cret")}
    _, hooks, _ = _generate(comfy.url, tmp_path, {"model": "portrait.json"}, ACCESS_TOKEN="s3cret")
    assert any("5/20" in message for _, message in hooks.progress), "WebSocket 握手也带着凭据,进度照样来"
    comfy.state.authorization = "Basic " + base64.b64encode(b"me:pa:ss").decode()
    assert _models(comfy.url, ACCESS_TOKEN="me:pa:ss"), "用户名:密码 按 Basic 发"


def test_地址里写了用户名密码_说清楚填到访问凭据(comfy) -> None:
    with pytest.raises(runtime.PluginRuntimeError, match="访问凭据"):
        _models(comfy.url.replace("http://", "http://me:pw@"))


def test_连不上说出地址(tmp_path: Path) -> None:
    url = f"http://127.0.0.1:{_unused_port()}"
    with pytest.raises(runtime.PluginRuntimeError, match=url.split("//")[1]):
        _models(url)


def test_校验不过说出是哪个节点(comfy, tmp_path: Path) -> None:
    comfy.state.reject = {"error": {"message": "Prompt outputs failed validation"},
                          "node_errors": {"4": {"errors": [{"message": "Value not in list"}]}}}
    with pytest.raises(runtime.PluginRuntimeError, match="#4 Value not in list"):
        _generate(comfy.url, tmp_path, {"model": "portrait.json"})


def test_校验错误很长时照样逐条说出是哪个节点(comfy, tmp_path: Path) -> None:
    """「Value not in list」的 details 带着整张可选值列表(几百个 checkpoint):回包动辄几 KB。
    只读前 400 字再去解析 JSON,解析失败就把半截 JSON 原样甩给用户。"""
    options = [f"model_{index:03d}.safetensors" for index in range(300)]
    comfy.state.reject = {
        "error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation"},
        "node_errors": {"4": {"class_type": "CheckpointLoaderSimple", "errors": [{
            "type": "value_not_in_list", "message": "Value not in list",
            "details": f"ckpt_name: 'gone.safetensors' not in {options}"}]}},
    }
    with pytest.raises(runtime.PluginRuntimeError, match="#4 Value not in list: ckpt_name: 'gone.safetensors'") as caught:
        _generate(comfy.url, tmp_path, {"model": "portrait.json"})
    assert len(str(caught.value)) < 1200, "给人看的那句不带几 KB 的可选值列表"


def test_执行失败带出ComfyUI自己的原因(comfy, tmp_path: Path) -> None:
    comfy.state.outcome = "error"
    with pytest.raises(runtime.PluginRuntimeError, match="CUDA out of memory"):
        _generate(comfy.url, tmp_path, {"model": "portrait.json"})


def test_在ComfyUI里被中断了就说被中断_不说执行失败(comfy, tmp_path: Path) -> None:
    comfy.state.outcome = "interrupted"
    with pytest.raises(runtime.PluginRuntimeError, match="被中断"):
        _generate(comfy.url, tmp_path, {"model": "portrait.json"})


def test_工作流在ComfyUI里删掉了_提示去刷新(comfy, tmp_path: Path) -> None:
    with pytest.raises(runtime.PluginRuntimeError, match="刷新模型"):
        _generate(comfy.url, tmp_path, {"model": "gone.json"})


def test_英文界面说英文(comfy, tmp_path: Path) -> None:
    """插件运行时说的话只有插件写得出;宿主告诉它读的人用哪种语言(请求体的 locale)。"""
    from app.core.i18n import get_current_locale, set_current_locale

    comfy.state.outcome = "error"
    before = get_current_locale()
    set_current_locale("en")
    try:
        with pytest.raises(runtime.PluginRuntimeError, match="ComfyUI execution failed"):
            _generate(comfy.url, tmp_path, {"model": "portrait.json"})
    finally:
        set_current_locale(before)
