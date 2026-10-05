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
from tests.fake_comfyui import (
    INPAINT_MUTED_FIRST_PASS_API,
    INPAINT_NODE_INFO,
    MINIMAX_T2V_API,
    PNG,
    TWO_PASS_HAND_DEPTH,
    TWO_SAVES_API,
    UPSCALE_API,
    VIDEO_NODE_INFO,
    FakeComfyUI,
    fixture_workflow,
    minimax_h3_ui,
)

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


def test_刚装好还没存过工作流_照样列出内置文生图(comfy) -> None:
    """workflows 目录还不存在时 ComfyUI 对列目录回 404:那是「一张都没有」,不是连接坏了。"""
    comfy.state.workflows = {}
    assert [one["id"] for one in _models(comfy.url)] == ["builtin:txt2img"]
    fingerprint = runtime.execute_tool(PLUGIN, ENTRY, TOOL, {"op": "fingerprint"}, {"SERVER_URL": comfy.url}, timeout=60)
    assert fingerprint.output["fingerprint"]


def test_workflows目录里的隐藏文件不是工作流(comfy) -> None:
    """老版本前端在 workflows/ 下放一份 .index.json(收藏、排序):它不是一张图,不该列成一个「转不过来」的模型。"""
    comfy.state.workflows[".index.json"] = {"favorites": ["portrait.json"]}
    listed = runtime.execute_tool(PLUGIN, ENTRY, "list_workflows", {}, {"SERVER_URL": comfy.url}, timeout=60).output
    assert ".index.json" not in {one["id"] for one in listed["workflows"]}


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


def test_文件名里有引号也传得上去(comfy, tmp_path: Path) -> None:
    """multipart 的 Content-Disposition 里 filename 用引号括着:名字里的引号不剔掉,头就断了。"""
    reference = tmp_path / 'cat "v2".png'
    reference.write_bytes(PNG)
    _generate(comfy.url, tmp_path, {"model": "portrait.json",
                                    "inputs": [{"role": "reference_image", "path": str(reference)}]})
    [(uploaded_name, uploaded_bytes)] = comfy.state.uploads
    assert uploaded_bytes == PNG and uploaded_name.endswith("cat _v2_.png")


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
    assert "采样 5/20 · 第 2/9 个节点" in messages, "说的是界面上的节点名字(用户起的「采样」)、第几步、第几个节点"
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


def test_没有认得的采样器的视频图_提示词照样写进去(comfy, tmp_path: Path) -> None:
    """用户在视频格选 MiniMax 的视频工作流,面板说「这个模型不收提示词」。API 节点的提示词是它自己的 `prompt_text`;
    本地 MiniMax H3 的提示词在子图里的 MiniMaxH3ImageToVideo 上 —— 目录说可以写,写了就写进那一格。"""
    comfy.state.object_info.update(json.loads(json.dumps(VIDEO_NODE_INFO)))
    comfy.state.workflows["video/minimax.json"] = MINIMAX_T2V_API
    comfy.state.workflows["video_minimax_h3_t2v.json"] = minimax_h3_ui()
    models = {one["id"]: one for one in _models(comfy.url)}
    assert models["video/minimax.json"]["prompt"] == "optional"
    assert models["video_minimax_h3_t2v.json"]["prompt"] == "optional"
    assert models["video_minimax_h3_t2v.json"]["kind"] == "video"

    comfy.state.outputs = {"90": {"images": [{"filename": "goldfish.mp4", "subfolder": "video", "type": "output"}]}}
    output, _, _ = _generate(comfy.url, tmp_path, {"model": "video/minimax.json", "kind": "video", "prompt": "一条金鱼"})
    assert comfy.posted("/prompt")[0]["prompt"]["1"]["inputs"]["prompt_text"] == "一条金鱼"
    assert output["usage"] == {"videos": 1}

    comfy.state.outputs = {"92": {"images": [{"filename": "h3.mp4", "subfolder": "video", "type": "output"}]}}
    output, _, _ = _generate(comfy.url, tmp_path, {"model": "video_minimax_h3_t2v.json", "kind": "video",
                                                   "prompt": "一条金鱼"})
    assert comfy.posted("/prompt")[1]["prompt"]["105:104"]["inputs"]["prompt"] == "一条金鱼"
    assert len(output["outputs"]) == 1, "CreateVideo 合成、SaveVideo 存下来:交回一段"


def test_尺寸不限于推荐的几档_每边按8的倍数取整(comfy, tmp_path: Path) -> None:
    """用户拍板:768x1024 这种要能直接用;不是 8 的倍数的按 8 取整(四舍五入),和工作流工具的宽高同一个规矩。"""
    for size in ("768x1024", "770x1021", "500 x 1001"):
        _generate(comfy.url, tmp_path, {"model": "portrait.json", "parameters": {"size": size}})
    sizes = [(one["prompt"]["5"]["inputs"]["width"], one["prompt"]["5"]["inputs"]["height"])
             for one in comfy.posted("/prompt")]
    assert sizes == [(768, 1024), (768, 1024), (504, 1000)]


def test_没接到能跑的输出上的节点_目录里不算_提交时也不带(comfy, tmp_path: Path) -> None:
    """局部重绘那张图静音了第一遍文生图:目录不再给它假的尺寸 / 张数、不说一次交回两份;提交的图里也没有那几个
    悬空的节点。给的图接到真正出图那一路的 LoadImage 上。"""
    comfy.state.object_info.update(json.loads(json.dumps(INPAINT_NODE_INFO)))
    comfy.state.workflows["inpainting.json"] = INPAINT_MUTED_FIRST_PASS_API
    model = next(one for one in _models(comfy.url) if one["id"] == "inpainting.json")
    assert "size" not in model["parameters"], "悬空的画布不是「尺寸」"
    assert model["outputs_per_run"] == 1

    comfy.state.outputs = {"16": {"images": [{"filename": "ComfyUI_temp_00001_.png", "subfolder": "", "type": "temp"}]}}
    output, _, _ = _generate(comfy.url, tmp_path, {"model": "inpainting.json", "parameters": {"num_images": 2},
                                                   "inputs": [{"role": "reference_image", "path": str(_png(tmp_path))}]})
    for submitted in (one["prompt"] for one in comfy.posted("/prompt")):
        assert not {"6", "8", "10", "11"} & set(submitted)
        assert submitted["21"]["inputs"]["image"].startswith("mosael/")
    assert len(output["outputs"]) == 2, "张数靠循环提交两次(见下面那几条),不是写进悬空节点的 batch_size"


def _inpaint(comfy) -> None:
    comfy.state.object_info.update(json.loads(json.dumps(INPAINT_NODE_INFO)))
    comfy.state.workflows["inpainting.json"] = INPAINT_MUTED_FIRST_PASS_API
    comfy.state.outputs = {"16": {"images": [{"filename": "ComfyUI_temp_00001_.png", "subfolder": "", "type": "temp"}]}}


def _submitted_seeds(comfy) -> list[int]:
    return [one["prompt"]["13"]["inputs"]["seed"] for one in comfy.posted("/prompt")]


def test_没有画布的图出N张_循环提交N次_每次换一个种子(comfy, tmp_path: Path) -> None:
    """用户拍板:局部重绘这类没有自己画布的图,张数照常生效 —— 插件循环提交 N 次。给了种子就从它开始依次 +1,
    没给就每次随机;每张用的种子跟着产出交回(宿主记进生成记录),图只传一次。"""
    _inpaint(comfy)
    model = next(one for one in _models(comfy.url) if one["id"] == "inpainting.json")
    assert model["parameters"]["num_images"] == {"type": "integer", "minimum": 1, "maximum": 4, "default": 1}
    assert model["max_outputs"] == 4
    image = {"role": "reference_image", "path": str(_png(tmp_path))}

    output, hooks, _ = _generate(comfy.url, tmp_path, {"model": "inpainting.json", "inputs": [image],
                                                       "parameters": {"num_images": 3, "seed": 100}})
    assert _submitted_seeds(comfy) == [100, 101, 102]
    assert len(comfy.state.uploads) == 1, "图只传一次,三次提交都接它"
    assert [one["parameters"] for one in output["outputs"]] == [{"seed": 100}, {"seed": 101}, {"seed": 102}]
    assert output["usage"] == {"images": 3} and output["raw"]["prompt_ids"] == ["p1", "p2", "p3"]
    assert "note" not in output
    assert [task["prompt_id"] for task in hooks.tasks] == ["p1", "p2", "p3"]
    assert any("第 2/3 张" in message for _, message in hooks.progress)

    _generate(comfy.url, tmp_path, {"model": "inpainting.json", "inputs": [image], "parameters": {"num_images": 2}})
    unseeded = _submitted_seeds(comfy)[3:]
    assert len(unseeded) == 2 and unseeded[0] != unseeded[1], "没给种子:每次随机"


def test_循环里一次失败_出来的照样交回_说明成功了几张和原因(comfy, tmp_path: Path) -> None:
    _inpaint(comfy)
    comfy.state.outcomes = ["success", "error", "success"]
    comfy.state.error_message = "CUDA out of memory"
    output, _, _ = _generate(comfy.url, tmp_path, {"model": "inpainting.json", "parameters": {"num_images": 3, "seed": 7},
                                                   "inputs": [{"role": "reference_image", "path": str(_png(tmp_path))}]})
    assert [one["parameters"]["seed"] for one in output["outputs"]] == [7, 9], "第 2 张失败,第 1、3 张照样交回"
    assert "3 张里出了 2 张" in output["note"] and "第 2 张" in output["note"] and "CUDA out of memory" in output["note"]


def test_循环里一张都没出来_照旧报失败(comfy, tmp_path: Path) -> None:
    _inpaint(comfy)
    comfy.state.outcomes = ["error", "error"]
    with pytest.raises(runtime.PluginRuntimeError, match="CUDA out of memory"):
        _generate(comfy.url, tmp_path, {"model": "inpainting.json", "parameters": {"num_images": 2},
                                        "inputs": [{"role": "reference_image", "path": str(_png(tmp_path))}]})


def test_循环中途取消_剩下的不再提交_在跑的那个中断(comfy, tmp_path: Path) -> None:
    _inpaint(comfy)
    comfy.state.outcome = "never"
    with pytest.raises(runtime.PluginCancelled):
        _generate(comfy.url, tmp_path, {"model": "inpainting.json", "parameters": {"num_images": 3},
                                        "inputs": [{"role": "reference_image", "path": str(_png(tmp_path))}]},
                  _Hooks(cancel_after_task=True))
    assert len(comfy.posted("/prompt")) == 1, "剩下的两次不再提交"
    assert comfy.posted("/interrupt") == [{"prompt_id": "p1"}], "在跑的那个在 ComfyUI 上中断"


def test_循环到一半后端重启_接着等那一次再把剩下的跑完(comfy, tmp_path: Path) -> None:
    """回执里记着这是第几次、前面几次的任务号和种子:重启后接着等在跑的那一次,不重复提交它,剩下的照常提交。"""
    _inpaint(comfy)
    done = {"status": {"status_str": "success", "completed": True},
            "outputs": {"16": {"images": [{"filename": "done.png", "subfolder": "", "type": "temp"}]}}}
    comfy.state.history.update({"p8": done, "p9": json.loads(json.dumps(done))})
    receipt = {"prompt_id": "p9", "repeat": {"count": 3, "index": 1, "done": ["p8"], "seeds": [50, 51]}}
    output, _, _ = _generate(comfy.url, tmp_path, {"model": "inpainting.json", "parameters": {"num_images": 3, "seed": 50},
                                                   "inputs": [{"role": "reference_image", "path": str(_png(tmp_path))}],
                                                   "resume": receipt})
    assert _submitted_seeds(comfy) == [52], "只提交还没跑的第 3 次"
    assert [one["parameters"]["seed"] for one in output["outputs"]] == [50, 51, 52]


def test_两个保存节点_一次交回两份_结果取自选一个就只交回它的(comfy, tmp_path: Path) -> None:
    """目录说一次交回几份(`outputs_per_run`),做的就是那几份:没选张数时画布一次出一张(工作流里存着 2 张也是),
    两个保存节点各一张;「结果取自」选了「高清」,只交回它那一张,原图那个保存节点不跑。"""
    comfy.state.workflows["two.json"] = TWO_SAVES_API
    comfy.state.outputs = {"9": {"images": [{"filename": "base_00001_.png", "subfolder": "", "type": "output"}]},
                           "12": {"images": [{"filename": "hd_00001_.png", "subfolder": "", "type": "output"}]}}
    model = next(one for one in _models(comfy.url) if one["id"] == "two.json")
    assert model["outputs_per_run"] == 2 and model["parameters"]["output_node"]["enum"] == ["all", "9", "12"]

    output, _, _ = _generate(comfy.url, tmp_path, {"model": "two.json"})
    submitted = comfy.posted("/prompt")[0]["prompt"]
    assert submitted["5"]["inputs"]["batch_size"] == 1, "没选张数:一次一张,和目录里张数的缺省一致"
    assert {"9", "12"} <= set(submitted)
    assert len(output["outputs"]) == 2 and output["usage"] == {"images": 2}

    output, _, _ = _generate(comfy.url, tmp_path, {"model": "two.json",
                                                   "parameters": {"output_node": "12", "num_images": 2}})
    submitted = comfy.posted("/prompt")[1]["prompt"]
    assert "9" not in submitted and submitted["5"]["inputs"]["batch_size"] == 2
    assert output["usage"] == {"images": 1}
    viewed = [query["filename"] for method, path, query in comfy.state.calls if method == "GET" and path == "/view"]
    assert viewed[-1:] == [["hd_00001_.png"]], viewed


def test_两遍出图只接了预览_缺省只交回最终结果_全部照旧三张(comfy, tmp_path: Path) -> None:
    """维护者的「古风女孩1」(脱敏夹具):第一遍、从它算出来的手部深度图、第二遍各接一个预览。目录说一次一张,
    没选「结果取自」(宿主只发动过的参数)时提交的图里摘掉中间一步的两个预览、只交回第二遍那张;选「全部」照旧三张。"""
    ui, info = fixture_workflow(TWO_PASS_HAND_DEPTH)
    comfy.state.object_info.update(info)
    comfy.state.workflows["古风女孩1.json"] = ui
    comfy.state.outputs = {node: {"images": [{"filename": f"ComfyUI_temp_{node}_00001_.png", "subfolder": "",
                                              "type": "temp"}]} for node in ("8", "17", "18")}
    model = next(one for one in _models(comfy.url) if one["id"] == "古风女孩1.json")
    assert model["outputs_per_run"] == 1 and model["parameters"]["output_node"]["default"] == "final"

    output, _, _ = _generate(comfy.url, tmp_path, {"model": "古风女孩1.json"})
    submitted = comfy.posted("/prompt")[0]["prompt"]
    assert "17" in submitted and not {"8", "18"} & set(submitted), "中间一步的预览不跑"
    assert {"6", "10", "11", "14", "16"} <= set(submitted)
    assert submitted["7"]["inputs"]["batch_size"] == 1
    assert len(output["outputs"]) == 1 and output["usage"] == {"images": 1}
    viewed = [query["filename"] for method, path, query in comfy.state.calls if method == "GET" and path == "/view"]
    assert viewed == [["ComfyUI_temp_17_00001_.png"]]

    output, _, _ = _generate(comfy.url, tmp_path, {"model": "古风女孩1.json", "parameters": {"output_node": "all"}})
    assert {"8", "17", "18"} <= set(comfy.posted("/prompt")[1]["prompt"])
    assert len(output["outputs"]) == 3 and output["usage"] == {"images": 3}


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


def test_一部分输出校验不过_ComfyUI照样排上_说出原因并把它撤掉(comfy, tmp_path: Path) -> None:
    """实测用户的「beautiful girl」:checkpoint 不在那台机器上,依赖它的三个输出校验不过;另一个只预览参考图骨架的
    PreviewImage 不依赖它,校验过了。ComfyUI 回 200、照样排上,只跑那一个预览 —— 此前插件不看回包里的 node_errors,
    这次生成「成功」,交回来的是一张姿态骨架图。现在说出哪个节点什么不对,把排上的那个任务撤掉。"""
    comfy.state.node_errors = {"4": {"class_type": "CheckpointLoaderSimple", "dependent_outputs": ["9"], "errors": [{
        "type": "value_not_in_list", "message": "Value not in list",
        "details": "ckpt_name: 'gone.safetensors' not in ['sd_xl_base.safetensors']"}]}}
    with pytest.raises(runtime.PluginRuntimeError, match="#4 Value not in list: ckpt_name: 'gone.safetensors'"):
        _generate(comfy.url, tmp_path, {"model": "portrait.json"})
    assert comfy.posted("/queue") == [{"delete": ["p1"]}], "排上的那个任务撤掉,不让它在 ComfyUI 上跑一个没人要的结果"


def test_缺节点缺模型文件_提交之前一次说全_说人话(comfy, tmp_path: Path) -> None:
    """用户的 krea2 那张缺五个自定义节点,ComfyUI 每次只回第一个(「Node 'TTResolutionSelector' not found. The custom node
    may not be installed.」),装好一个才知道下一个;缺模型文件时回一句英文的「Value not in list」或执行到一半才说
    「Model in folder 'checkpoints' with filename … not found」。插件手里有 object_info:提交之前就看得出缺什么,一次说全,
    什么都不排上。"""
    comfy.state.workflows["missing.json"] = {
        **UPSCALE_API,
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4xNomosWebPhoto_RealPLKSR.pth"}},
        "7": {"class_type": "CR Prompt Text", "inputs": {"prompt": "田园"}},
        "8": {"class_type": "TTResolutionSelector", "inputs": {"resolution": "1920x1080"}},
    }
    with pytest.raises(runtime.PluginRuntimeError) as caught:
        _generate(comfy.url, tmp_path, {"model": "missing.json", "inputs": [{"role": "reference_image",
                                                                             "path": str(_png(tmp_path))}]})
    said = str(caught.value)
    assert "没装" in said and "CR Prompt Text" in said and "TTResolutionSelector" in said
    assert "4xNomosWebPhoto_RealPLKSR.pth" in said and "模型文件" in said
    assert not comfy.posted("/prompt") and not comfy.posted("/upload/image"), "缺东西的图不提交、不传素材"


def test_执行到一半才发现缺模型文件_也说人话(comfy, tmp_path: Path) -> None:
    """有的加载节点(带子目录的 checkpoint 名)校验时不拦,执行到它才说找不到文件 —— DaSiWa WAN 2.2 就是这样。"""
    comfy.state.outcome = "error"
    comfy.state.error_node = "CheckpointLoaderSimple"
    comfy.state.error_message = ("Model in folder 'checkpoints' with filename "
                                 "'Wan/22/Wan2_2-I2V-High-LS-DaSiWa-TastySin-fp8-v81.safetensors' not found.")
    with pytest.raises(runtime.PluginRuntimeError) as caught:
        _generate(comfy.url, tmp_path, {"model": "portrait.json"})
    said = str(caught.value)
    assert "没有模型文件" in said and "Wan/22/Wan2_2-I2V-High-LS-DaSiWa-TastySin-fp8-v81.safetensors" in said
    assert "checkpoints" in said and "not found" not in said


def test_执行失败带出ComfyUI自己的原因(comfy, tmp_path: Path) -> None:
    comfy.state.outcome = "error"
    with pytest.raises(runtime.PluginRuntimeError, match="CUDA out of memory"):
        _generate(comfy.url, tmp_path, {"model": "portrait.json"})


_NO_CLIP = ("ERROR: clip input is invalid: None\n\nIf the clip is from a checkpoint loader node your checkpoint "
            "does not contain a valid clip or text encoder model.")


@pytest.mark.parametrize("websocket", [False, True], ids=["轮询", "WebSocket"])
def test_模型文件里没有文本编码器_点名是哪个文件并说怎么办(comfy, tmp_path: Path, websocket: bool) -> None:
    """用户在「模型」里挑了一个 Anima / Flux 这类不带文本编码器的 checkpoint:ComfyUI 的原话是一段英文,读完也
    不知道是哪个文件、该换成什么。WebSocket 推来的失败和轮询历史读到的失败说同一句。"""
    comfy.state.websocket = websocket
    comfy.state.outcome = "error"
    comfy.state.error_node = "CLIPTextEncode"
    comfy.state.error_message = _NO_CLIP
    with pytest.raises(runtime.PluginRuntimeError) as caught:
        _generate(comfy.url, tmp_path, {"model": "portrait.json"})
    said = str(caught.value)
    assert "「sd_xl_base.safetensors」里没有文本编码器" in said
    assert "换一个完整的 checkpoint" in said
    assert "clip input is invalid" not in said


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
