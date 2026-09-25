"""ComfyUI 插件的**工具**:经宿主的插件运行时起进程,对着一台假的 ComfyUI(tests/fake_comfyui)。

生成那一路钉在 test_comfyui_plugin_run.py;这里钉的是给智能体和工作流的那一组(见 mosael.plugin.json):

- `list_workflows`:每张工作流能喂什么(哪个参数喂哪个节点)、能调什么、交出什么、在做什么;
- `run_workflow`:素材按顺序接到读素材的节点上,任意节点的值能改,**全部**产出取回(每个保存节点的
  每个文件 + 显示文字的节点说的话),进度一行一个,取消只停这一个任务,`wait: false` 只提交;
- `import_outputs`:按任务号或最近几次把历史产出取回;
- `server_status` / `list_models`:显卡、队列、模型文件(老版本没有 `/models` 时看加载节点的下拉);
- `interrupt` / `clear_queue` / `free_memory`:只动该动的那一个。

以及生成那一路的两处新东西:一次几张(`num_images` → batch_size,几张全交回),模型清单的指纹。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from tests.fake_comfyui import PNG, UPSCALE_API, FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        server.state.workflows["upscale.json"] = UPSCALE_API
        yield server


def _call(url: str, tool: str, payload: dict[str, Any] | None = None, tmp_path: Path | None = None) -> dict[str, Any]:
    return runtime.execute_tool(PLUGIN, ENTRY, tool, payload or {}, {"SERVER_URL": url}, scratch_dir=tmp_path,
                                timeout=60).output


class _Hooks:
    def __init__(self, cancel: bool = False) -> None:
        self.progress: list[tuple[float, str]] = []
        self.tasks: list[dict[str, Any]] = []
        self.cancel = cancel

    def build(self) -> runtime.StreamHooks:
        return runtime.StreamHooks(
            on_progress=lambda fraction, message: self.progress.append((fraction, message)),
            on_task=self.tasks.append,
            is_cancelled=lambda: self.cancel and bool(self.tasks),
        )


def _stream(url: str, tool: str, payload: dict[str, Any], tmp_path: Path, hooks: _Hooks | None = None):
    scratch = tmp_path / "out"
    scratch.mkdir(exist_ok=True)
    hooks = hooks or _Hooks()
    result = runtime.stream_tool(PLUGIN, ENTRY, tool, payload, {"SERVER_URL": url}, hooks=hooks.build(),
                                 scratch_dir=scratch, timeout=60)
    return result.output, hooks, scratch


def _png(tmp_path: Path, name: str = "图.png") -> Path:
    path = tmp_path / name
    path.write_bytes(PNG)
    return path


# --- list_workflows --------------------------------------------------------------


def test_列出工作流_说清楚哪个参数喂哪个节点(comfy) -> None:
    listed = {one["id"]: one for one in _call(comfy.url, "list_workflows")["workflows"]}
    assert set(listed) == {"builtin:txt2img", "portrait.json", "upscale.json", "video/wan.json"}
    upscale = listed["upscale.json"]
    assert upscale["features"] == ["upscale"] and upscale["prompt"] is False
    assert upscale["inputs"] == [{"node": "1", "title": "LoadImage", "class_type": "LoadImage", "media": "image",
                                  "role": "reference_image", "argument": "image"}]
    assert [(one["node"], one["media"]) for one in upscale["outputs"]] == [("4", "image"), ("5", "image")]
    [model_param] = upscale["parameters"]
    assert model_param == {"key": "2.model_name", "title": "放大模型", "type": "string", "default": "4x-UltraSharp.pth",
                           "options": ["4x-UltraSharp.pth", "RealESRGAN_x2.pth"]}
    portrait = listed["portrait.json"]
    assert portrait["prompt"] and portrait["negative_prompt"] and portrait["size"] == "832x1216"
    assert "prompt" in portrait["features"]


def test_转不过来的工作流也列出来_带着原因(comfy) -> None:
    comfy.state.workflows["broken.json"] = {"nodes": "not a list"}
    listed = {one["id"]: one for one in _call(comfy.url, "list_workflows")["workflows"]}
    assert listed["broken.json"]["error"], "静默消失比标着「转换失败」更让人摸不着头脑"


def test_按名字筛(comfy) -> None:
    listed = _call(comfy.url, "list_workflows", {"query": "UPSC"})["workflows"]
    assert [one["id"] for one in listed] == ["upscale.json"]


# --- run_workflow ----------------------------------------------------------------


def test_跑一张放大工作流_图接上去_全部产出取回(comfy, tmp_path: Path) -> None:
    comfy.state.outputs = {
        "4": {"images": [{"filename": "up_00001_.png", "subfolder": "", "type": "output"},
                         {"filename": "up_00002_.png", "subfolder": "", "type": "output"}]},
        "5": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]},
        "9": {"text": ["done: 2 images"]},
    }
    output, hooks, scratch = _stream(comfy.url, "run_workflow", {
        "workflow": "upscale.json", "image": str(_png(tmp_path)), "values": {"2.model_name": "RealESRGAN_x2.pth"},
    }, tmp_path)
    [(uploaded, content)] = comfy.state.uploads
    assert content == PNG
    prompt = comfy.posted("/prompt")[0]["prompt"]
    assert prompt["1"]["inputs"]["image"] == f"mosael/{uploaded}"
    assert prompt["2"]["inputs"]["model_name"] == "RealESRGAN_x2.pth", "values 改的是那个节点上的那一格"
    assert prompt["4"]["inputs"]["filename_prefix"] == "up", "没给的都用工作流自己的"
    assert [one["filename"] for one in output["artifacts"]] == ["up_00001_.png", "up_00002_.png"], "预览不算(有保存节点时)"
    assert all((scratch / one["path"]).read_bytes() == PNG for one in output["artifacts"])
    assert [one["node"] for one in output["artifacts"]] == ["4", "4"]
    assert output["texts"] == ["done: 2 images"]
    assert output["counts"] == {"image": 2} and output["prompt_id"] == "p1" and output["status"] == "succeeded"
    assert {one["node"]: len(one["files"]) for one in output["outputs"]} == {"4": 2, "9": 0}
    assert hooks.tasks and hooks.tasks[0]["prompt_id"] == "p1"


def test_没有保存节点时_预览就是产出(comfy, tmp_path: Path) -> None:
    comfy.state.outputs = {"5": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]}}
    output, _, _ = _stream(comfy.url, "run_workflow", {"workflow": "upscale.json"}, tmp_path)
    assert [one["filename"] for one in output["artifacts"]] == ["preview.png"]


def test_按标题改值_提示词和种子没给就用工作流自己的(comfy, tmp_path: Path) -> None:
    _stream(comfy.url, "run_workflow", {"workflow": "portrait.json", "values": {"采样.steps": 9}}, tmp_path)
    prompt = comfy.posted("/prompt")[0]["prompt"]
    assert prompt["3"]["inputs"]["steps"] == 9
    assert prompt["6"]["inputs"]["text"] == "a cat" and prompt["7"]["inputs"]["text"] == "blurry"
    assert prompt["3"]["inputs"]["seed"] == 42, "跑一张存好的工作流:种子没给就用它存着的,可复现"


def test_对不上的值和多给的图说清楚(comfy, tmp_path: Path) -> None:
    with pytest.raises(runtime.PluginRuntimeError, match="nope.steps"):
        _stream(comfy.url, "run_workflow", {"workflow": "portrait.json", "values": {"nope.steps": 1}}, tmp_path)
    with pytest.raises(runtime.PluginRuntimeError, match="只有 1 个读图的节点"):
        _stream(comfy.url, "run_workflow", {"workflow": "upscale.json", "image": str(_png(tmp_path)),
                                            "images": [str(_png(tmp_path, "b.png"))]}, tmp_path)
    with pytest.raises(runtime.PluginRuntimeError, match="没有读视频的节点"):
        _stream(comfy.url, "run_workflow", {"workflow": "upscale.json", "video": str(_png(tmp_path))}, tmp_path)
    assert comfy.posted("/prompt") == [], "对不上就不提交"


def test_蒙版接到LoadImage的alpha那一路(comfy, tmp_path: Path) -> None:
    comfy.state.workflows["inpaint.json"] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}},
        "2": {"class_type": "VAEEncodeForInpaint", "inputs": {"pixels": ["1", 0], "mask": ["1", 1]}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "p"}},
    }
    _stream(comfy.url, "run_workflow", {"workflow": "inpaint.json", "image": str(_png(tmp_path)),
                                        "mask": str(_png(tmp_path, "mask.png"))}, tmp_path)
    prompt = comfy.posted("/prompt")[0]["prompt"]
    mask_node = prompt["2"]["inputs"]["mask"][0]
    assert prompt[mask_node]["class_type"] == "LoadImageMask"
    assert prompt[mask_node]["inputs"]["image"].endswith("mask.png")
    assert len(comfy.state.uploads) == 2


def test_只提交不等_之后用import_outputs取回(comfy, tmp_path: Path) -> None:
    comfy.state.outcome = "never"
    output, _, _ = _stream(comfy.url, "run_workflow", {"workflow": "upscale.json", "wait": False}, tmp_path)
    assert output["status"] == "queued" and output["prompt_id"] == "p1" and "artifacts" not in output
    waiting, _, _ = _stream(comfy.url, "import_outputs", {"prompt_id": "p1"}, tmp_path)
    assert waiting["status"] == "running" and "artifacts" not in waiting
    comfy.state.running.clear()
    comfy.state.history["p1"] = {"status": {"status_str": "success", "completed": True},
                                 "outputs": {"4": {"images": [{"filename": "late.png", "type": "output"}]}}}
    done, _, _ = _stream(comfy.url, "import_outputs", {"prompt_id": "p1"}, tmp_path)
    assert [one["filename"] for one in done["artifacts"]] == ["late.png"]


def test_运行中取消只停这一个任务(comfy, tmp_path: Path) -> None:
    comfy.state.outcome = "never"
    comfy.state.pending = ["someone-else"]
    with pytest.raises(runtime.PluginCancelled):
        _stream(comfy.url, "run_workflow", {"workflow": "upscale.json"}, tmp_path, _Hooks(cancel=True))
    assert comfy.posted("/interrupt") == [{"prompt_id": "p1"}]
    assert comfy.posted("/queue") == []


def test_进度里有节点名和步数(comfy, tmp_path: Path) -> None:
    comfy.state.websocket = True
    _, hooks, _ = _stream(comfy.url, "run_workflow", {"workflow": "portrait.json"}, tmp_path)
    assert any("5/20" in message for _, message in hooks.progress), hooks.progress


# --- import_outputs ----------------------------------------------------------------


def test_取最近几次的产出(comfy, tmp_path: Path) -> None:
    for index in (1, 2, 3):
        comfy.state.history[f"h{index}"] = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"9": {"images": [{"filename": f"h{index}.png", "type": "output"}]}},
        }
    output, _, _ = _stream(comfy.url, "import_outputs", {"last": 2}, tmp_path)
    assert [one["filename"] for one in output["artifacts"]] == ["h2.png", "h3.png"]
    assert output["prompt_ids"] == ["h2", "h3"]


def test_不认识的任务号说清楚(comfy, tmp_path: Path) -> None:
    with pytest.raises(runtime.PluginRuntimeError, match="找不到任务 nope"):
        _stream(comfy.url, "import_outputs", {"prompt_id": "nope"}, tmp_path)


# --- 服务器 ----------------------------------------------------------------------


def test_服务器状态(comfy) -> None:
    comfy.state.running = ["r1"]
    comfy.state.pending = ["q1", "q2"]
    status = _call(comfy.url, "server_status")
    assert status["comfyui_version"] == "0.3.60"
    assert status["devices"][0]["vram_total_gb"] == 24.0 and status["devices"][0]["vram_free_gb"] == 20.0
    assert status["queue"] == {"running": 1, "pending": 2, "running_ids": ["r1"], "pending_ids": ["q1", "q2"]}
    assert "在跑 1 个,排队 2 个" in status["summary"]


def test_模型文件_有models接口就用它_没有就看加载节点(comfy) -> None:
    listed = _call(comfy.url, "list_models")
    assert listed["source"] == "models"
    assert listed["folders"]["loras"] == ["detail.safetensors"]
    assert "custom_nodes" not in listed["folders"], "不是模型的目录不列"
    assert _call(comfy.url, "list_models", {"folder": "checkpoints"})["folders"] == {
        "checkpoints": ["sd_xl_base.safetensors", "v1-5.ckpt"]}
    comfy.state.models_api = False
    old = _call(comfy.url, "list_models")
    assert old["source"] == "object_info"
    assert old["folders"]["upscale_models"] == ["4x-UltraSharp.pth", "RealESRGAN_x2.pth"]


def test_中断_给了任务号只停那一个(comfy) -> None:
    comfy.state.running = ["mine"]
    comfy.state.pending = ["queued-one"]
    assert _call(comfy.url, "interrupt", {"prompt_id": "queued-one"})["was"] == "pending"
    assert comfy.posted("/queue") == [{"delete": ["queued-one"]}] and comfy.posted("/interrupt") == []
    assert _call(comfy.url, "interrupt", {"prompt_id": "mine"})["was"] == "running"
    assert comfy.posted("/interrupt") == [{"prompt_id": "mine"}]
    assert _call(comfy.url, "interrupt", {"prompt_id": "ghost"})["interrupted"] is False


def test_清空队列_释放显存(comfy) -> None:
    comfy.state.pending = ["a", "b"]
    assert _call(comfy.url, "clear_queue")["cleared"] == 2
    assert comfy.posted("/queue") == [{"clear": True}]
    freed = _call(comfy.url, "free_memory", {"unload_models": False})
    assert freed["unloaded_models"] is False
    assert comfy.posted("/free") == [{"unload_models": False, "free_memory": True}]


# --- 生成那一路的新东西 -----------------------------------------------------------------


def test_一次几张_全部交回(comfy, tmp_path: Path) -> None:
    comfy.state.outputs = {"9": {"images": [{"filename": f"b{i}.png", "type": "output"} for i in range(3)]}}
    scratch = tmp_path / "gen"
    scratch.mkdir()
    result = runtime.stream_tool(
        PLUGIN, ENTRY, "comfyui_generation",
        {"op": "generate", "model": "portrait.json", "kind": "image", "prompt": "p", "negative_prompt": "",
         "parameters": {"num_images": 3}, "inputs": [], "resume": None},
        {"SERVER_URL": comfy.url}, hooks=_Hooks().build(), scratch_dir=scratch, timeout=60,
    )
    assert comfy.posted("/prompt")[0]["prompt"]["5"]["inputs"]["batch_size"] == 3
    assert len(result.output["outputs"]) == 3 and result.output["usage"] == {"images": 3}


def test_模型清单的指纹_工作流变了它就变(comfy) -> None:
    first = _call(comfy.url, "comfyui_generation", {"op": "models"})
    assert first["fingerprint"] and len(first["models"]) == 4
    same = _call(comfy.url, "comfyui_generation", {"op": "fingerprint"})["fingerprint"]
    assert same == first["fingerprint"]
    comfy.state.workflows["new.json"] = UPSCALE_API
    assert _call(comfy.url, "comfyui_generation", {"op": "fingerprint"})["fingerprint"] != same
    before = [call for call in comfy.state.calls if call[1] == "/object_info"]
    _call(comfy.url, "comfyui_generation", {"op": "fingerprint"})
    after = [call for call in comfy.state.calls if call[1] == "/object_info"]
    assert before == after, "问指纹不拉 object_info、不拉任何一张图"
    assert not [call for call in comfy.state.calls[-6:] if call[1].startswith("/api/userdata/")]


def test_清单里的工具与实现对得上() -> None:
    """清单里声明的每个工具都有实现,流式的那几个在清单里标了 `stream`(宿主据此走流式协议)。"""
    import sys

    manifest = json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))
    declared = {tool["name"]: tool for tool in manifest["tools"]["declare"]}
    sys.path.insert(0, str(PLUGIN / "tools"))
    saved = {name: sys.modules.pop(name) for name in ("main", "run", "graph", "models", "labels", "server",
                                                        "workflows", "lines", "ws", "comfy_http") if name in sys.modules}
    try:
        import main as plugin_main

        implemented = set(plugin_main._PLAIN) | set(plugin_main._STREAMING) | {"comfyui_generation"}
        streaming = set(plugin_main._STREAMING)
    finally:
        sys.path.remove(str(PLUGIN / "tools"))
        for name in ("main", "run", "graph", "models", "labels", "server", "workflows", "lines", "ws", "comfy_http"):
            sys.modules.pop(name, None)
        sys.modules.update(saved)
    assert set(declared) == implemented
    assert {name for name, tool in declared.items() if tool.get("stream")} == streaming
    assert {name for name, tool in declared.items() if tool.get("read_only")} == {
        "list_workflows", "server_status", "list_models"}, "会动服务器或素材库的不标只读"
