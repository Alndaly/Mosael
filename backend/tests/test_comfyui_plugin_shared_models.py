"""共用的模型文件夹(ADR 0041 拍板 5)的插件那一半(tools/shared_models):

- **认两种样子**:ComfyUI 的 models(选 ComfyUI 目录本身也认得)—— 子目录同名对上,`clip` / `unet` / `t2i_adapter` 照 ComfyUI 自己
  的对照并过去;A1111 / Forge(选 webui 目录或它的 models)—— 照 extra_model_paths.yaml.example 的那张表;它自己的模型文件夹、
  不存在的、认不出的都说清楚;
- **配置写在宿主给的目录里**,不写进那个 ComfyUI 目录;是 ComfyUI 读得懂的 YAML(其实是 JSON),路径绝对、不用 base_path;
  起的时候加 `--extra-model-paths-config`,一处都没有就不加、删掉上一份;
- **只读**:模型库下载的新文件落在它自己的那一处(共用的排在前面也一样;那个目录只在共用的那几处有就不走本机这条路);
  共用文件夹里的模型不往旁边写预览图、不按哈希找(pysssss 会写 `.sha256`);
- `service_model_folders`:在跑的那台 ComfyUI 加载了哪几处、每处几个模型。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from app.domain.plugins.runtime import PluginRuntimeError
from tests import test_comfyui_plugin_model_library as base
from tests.test_comfyui_plugin_model_library import _call, _download, _same_machine

comfy, data_dir, files, modules, _no_proxy = base.comfy, base.data_dir, base.files, base.modules, base._no_proxy
TOOLS = base.TOOLS
SHARED_ENV = "MOSAEL_LOCAL_SERVICE_SHARED"


@pytest.fixture
def shared(monkeypatch):
    """本进程里载入插件的 shared_models、service(和它们依赖的几个),测完换回去。"""
    names = ("shared_models", "service", "model_files", "comfy_http", "lines", "pinned")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import service
        import shared_models

        yield shared_models, service
    finally:
        sys.path.remove(str(TOOLS))
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _dirs(root: Path, *names: str) -> Path:
    for name in names:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _comfy_install(root: Path) -> Path:
    """一份 ComfyUI 目录的样子(认目录要 main.py 和 comfy/)。"""
    (root / "comfy").mkdir(parents=True)
    (root / "main.py").write_text("", encoding="utf-8")
    _dirs(root / "models", "checkpoints", "loras")
    return root


# ---- 认样子 --------------------------------------------------------------------------


def test_认_ComfyUI_的_models_子目录同名对上_老名字并过去(shared, tmp_path: Path) -> None:
    shared_models, _service = shared
    other = _dirs(tmp_path / "Other" / "ComfyUI" / "models", "checkpoints", "loras", "clip", "unet", "t2i_adapter", "controlnet",
                  "sams", ".cache")
    for pick in (other, other.parent):  # 选 models 本身,或者选 ComfyUI 目录
        found = shared_models.inspect(str(pick), "zh")
        assert found.problem is None and found.layout == "comfyui"
        assert sorted(found.folders) == ["checkpoints", "controlnet", "diffusion_models", "loras", "sams", "text_encoders"]
        assert found.folders["text_encoders"] == [str(other / "clip")], "clip 是 text_encoders 的老名字"
        assert found.folders["controlnet"] == [str(other / "controlnet"), str(other / "t2i_adapter")]
        assert ".cache" not in found.folders, "隐藏目录不算"


def test_认_A1111_Forge_选_webui_或它的_models_都行(shared, tmp_path: Path) -> None:
    shared_models, _service = shared
    webui = tmp_path / "stable-diffusion-webui"
    _dirs(webui / "models", "Stable-diffusion", "Lora", "LyCORIS", "VAE", "ESRGAN", "text_encoder")
    _dirs(webui, "embeddings")
    for pick in (webui, webui / "models"):
        found = shared_models.inspect(str(pick), "zh")
        assert found.problem is None and found.layout == "a1111"
        assert found.folders == {
            "checkpoints": [str(webui / "models" / "Stable-diffusion")],
            "configs": [str(webui / "models" / "Stable-diffusion")],
            "vae": [str(webui / "models" / "VAE")],
            "loras": [str(webui / "models" / "Lora"), str(webui / "models" / "LyCORIS")],
            "upscale_models": [str(webui / "models" / "ESRGAN")],
            "embeddings": [str(webui / "embeddings")],
            "text_encoders": [str(webui / "models" / "text_encoder")],
        }, "没有的子目录不写;embeddings 在 webui 那一层"


def test_认不出的_不存在的_相对路径_它自己的模型文件夹_都说清楚(shared, tmp_path: Path) -> None:
    shared_models, _service = shared
    install = _comfy_install(tmp_path / "ComfyUI")
    (tmp_path / "photos").mkdir()
    cases = {
        str(tmp_path / "photos"): "认不出这是模型文件夹",
        str(tmp_path / "nope"): "没有这个文件夹",
        "models": "完整的路径",
        str(install / "models"): "它自己的模型文件夹",
        str(install): "它自己的模型文件夹",  # 包着它
    }
    for raw, said in cases.items():
        found = shared_models.inspect(raw, "zh", own_models=install / "models")
        assert found.problem is not None and said in found.problem["zh"], raw


# ---- 配置、起的参数 ----------------------------------------------------------------------


def test_配置是_ComfyUI_读得懂的_YAML_路径绝对_几处用换行连(shared, tmp_path: Path) -> None:
    shared_models, _service = shared
    weird = _dirs(tmp_path / "有 空格 和 $HOME 的 models", "checkpoints", "loras")
    webui = _dirs(tmp_path / "webui" / "models", "Stable-diffusion", "Lora", "LyCORIS").parent
    found = [shared_models.inspect(str(weird), "zh"), shared_models.inspect(str(webui), "zh"),
             shared_models.inspect(str(tmp_path / "nope"), "zh")]
    written = shared_models.write_config(str(tmp_path / "config"), found)
    assert written == tmp_path / "config" / "extra_model_paths.yaml"
    parsed = yaml.safe_load(written.read_text(encoding="utf-8"))
    assert parsed == {
        "mosael_shared_1": {"checkpoints": str(weird / "checkpoints"), "loras": str(weird / "loras")},
        "mosael_shared_2": {"checkpoints": str(webui / "models" / "Stable-diffusion"),
                            "configs": str(webui / "models" / "Stable-diffusion"),
                            "loras": f"{webui / 'models' / 'Lora'}\n{webui / 'models' / 'LyCORIS'}"},
    }, "认不出的那一处不写;不用 base_path(ComfyUI 会对它 expandvars,$HOME 会被改掉)"
    assert shared_models.write_config(str(tmp_path / "config"), [found[2]]) is None
    assert not written.exists(), "一处能用的都没有:删掉上一份"


@pytest.mark.parametrize("windows", [False, True])
def test_起的时候加_extra_model_paths_config_配置写在宿主给的目录_不写进_ComfyUI_目录(shared, tmp_path: Path,
                                                                                windows: bool) -> None:
    shared_models, service = shared
    install = _comfy_install(tmp_path / "ComfyUI")
    venv = install / "venv" / ("Scripts" if windows else "bin")
    venv.mkdir(parents=True)
    (venv / ("python.exe" if windows else "python")).write_bytes(b"")
    other = _dirs(tmp_path / "Other" / "models", "checkpoints")
    config_dir = tmp_path / "data" / "local-services" / "c1"
    before = sorted(str(one) for one in install.rglob("*"))
    told = service.launch({"directory": str(install), "port": 8189, "shared_models": [str(other), str(tmp_path / "gone")],
                           "config_dir": str(config_dir)}, "zh", windows=windows, has_manager=lambda *_: False)
    config = config_dir / "extra_model_paths.yaml"
    assert told["argv"][-2:] == ["--extra-model-paths-config", str(config)]
    assert json.loads(config.read_text(encoding="utf-8").split("\n", 1)[1]) == {
        "mosael_shared_1": {"checkpoints": str(other / "checkpoints")}}, "不在了的那一处跳过,不挡着起"
    assert sorted(str(one) for one in install.rglob("*")) == before, "不改你的安装"
    again = service.launch({"directory": str(install), "port": 8189, "shared_models": [], "config_dir": str(config_dir)},
                           "zh", windows=windows, has_manager=lambda *_: False)
    assert "--extra-model-paths-config" not in again["argv"] and not config.exists()


def test_在不在共用的那几处_A1111_选的是_models_时_embeddings_也算(shared, tmp_path: Path, monkeypatch) -> None:
    shared_models, _service = shared
    webui = tmp_path / "webui"
    _dirs(webui / "models", "Stable-diffusion")
    _dirs(webui, "embeddings")
    monkeypatch.setenv(SHARED_ENV, json.dumps([str(webui / "models")]))
    assert shared_models.in_shared(webui / "embeddings" / "x.pt")
    assert shared_models.in_shared(webui / "models" / "Stable-diffusion" / "a.safetensors")
    assert not shared_models.in_shared(tmp_path / "ComfyUI" / "models" / "checkpoints" / "a.safetensors")
    monkeypatch.delenv(SHARED_ENV)
    assert shared_models.shared_roots() == []


# ---- 只读:下载、预览图、按哈希找 ----------------------------------------------------------


def _with_shared(server, root: Path, shared_root: Path) -> None:
    """共用的那一处排在每个目录的**前面**(人家的 yaml 用了 is_default 也是这样):下载照样不进去。文件都报在第 0 处 —— 共用的那一处。"""
    for folder in list(server.state.folder_paths):
        (shared_root / folder).mkdir(parents=True, exist_ok=True)
        server.state.folder_paths[folder] = [str(shared_root / folder), *server.state.folder_paths[folder]]
        for name in server.state.model_folders[folder]:
            source = root / folder / name.replace("\\", "/")
            target = shared_root / folder / name.replace("\\", "/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())


def test_下载落在它自己的那一处_共用的不进(comfy, data_dir, tmp_path, files) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    shared_root = tmp_path / "Other" / "models"
    _with_shared(comfy, root, shared_root)
    site = files({"/tiny.safetensors": b"\x00" * 1000})
    out, _progress = _download(comfy, {"url": f"{site.url}/tiny.safetensors", "folder": "vae", "filename": "new.safetensors"},
                               data_dir, tmp_path, MOSAEL_LOCAL_SERVICE_SHARED=json.dumps([str(shared_root)]))
    assert out["route"] == "local"
    assert (root / "vae" / "new.safetensors").is_file()
    assert not list((shared_root / "vae").iterdir()), "共用的文件夹一个字节都不写(连 .mosael-part 都没有)"


def test_那个模型目录只在共用的那几处有_不走本机这条路(comfy, data_dir, tmp_path, files) -> None:
    _same_machine(comfy, tmp_path / "models")
    shared_root = tmp_path / "Other" / "models"
    (shared_root / "vae").mkdir(parents=True)
    comfy.state.folder_paths["vae"] = [str(shared_root / "vae")]
    site = files({"/tiny.safetensors": b"\x00" * 10})
    with pytest.raises(PluginRuntimeError, match="ComfyUI-Manager"):
        _download(comfy, {"url": f"{site.url}/tiny.safetensors", "folder": "vae", "filename": "new.safetensors"},
                  data_dir, tmp_path, MOSAEL_LOCAL_SERVICE_SHARED=json.dumps([str(shared_root)]))
    assert not list((shared_root / "vae").iterdir())


def test_共用文件夹里的模型_不写回预览图(comfy, data_dir, tmp_path) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    shared_root = tmp_path / "Other" / "models"
    _with_shared(comfy, root, shared_root)
    image = tmp_path / "preview.png"
    image.write_bytes(b"\x89PNG fake")
    env = {"MOSAEL_LOCAL_SERVICE_SHARED": json.dumps([str(shared_root)])}
    with pytest.raises(PluginRuntimeError, match="共用的模型文件夹"):
        _call(comfy, {"op": "save_preview", "folder": "loras", "name": "detail.safetensors", "path": str(image)}, data_dir,
              **env)
    assert not comfy.state.saved_previews and not comfy.state.uploads, "连 temp 都不传"
    # 不在共用那几处的(报在第 1 处:它自己的那一处)照常存
    comfy.state.model_path_index["loras/detail.safetensors"] = 1
    out = _call(comfy, {"op": "save_preview", "folder": "loras", "name": "detail.safetensors", "path": str(image)}, data_dir,
                **env)
    assert out["saved"] == "loras/detail.png"


def test_共用文件夹里的模型_不按哈希找_按文件名和大小找(modules, comfy, tmp_path, monkeypatch, data_dir) -> None:
    _library, sources = modules
    import lookup
    from comfy_http import Comfy

    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(data_dir))
    root = _same_machine(comfy, tmp_path / "models")
    shared_root = tmp_path / "Other" / "models"
    _with_shared(comfy, root, shared_root)
    monkeypatch.setenv(SHARED_ENV, json.dumps([str(shared_root)]))
    web = base._Web({("GET", "https://civitai.com/api/v1/models?query=sd_xl_base&limit=20"): (200, {}, b'{"items": []}')})
    monkeypatch.setattr(sources, "fetch", web)
    out = lookup.lookup({"folder": "checkpoints", "name": "sd_xl_base.safetensors"}, Comfy(comfy.url), "zh")
    assert out["match"] == "none"
    assert comfy.state.hashed == [], "按哈希找时 pysssss 会在模型旁边写 .sha256:共用的不让它算"
    assert web.calls and all("by-hash" not in url for _method, url, _headers in web.calls), "按文件名和大小去 Civitai 找"
    monkeypatch.delenv(SHARED_ENV)
    lookup.lookup({"folder": "checkpoints", "name": "v1-5.ckpt"}, Comfy(comfy.url), "zh")
    assert comfy.state.hashed == ["checkpoints/v1-5.ckpt"], "没共用的照常按哈希找"


# ---- service_model_folders:在跑的那台加载了哪几处、每处几个 ---------------------------------------


def test_在跑的那台加载了哪几处_每处几个模型(comfy, data_dir, tmp_path) -> None:
    root = _same_machine(comfy, tmp_path / "models")
    shared_root = tmp_path / "Other" / "models"
    _with_shared(comfy, root, shared_root)
    comfy.state.model_path_index["loras/detail.safetensors"] = 1  # 这一个在它自己那一处
    waiting = _dirs(tmp_path / "Third" / "models", "checkpoints")  # 刚加的:那台还没加载
    install = _comfy_install(tmp_path / "ComfyUI")
    out = _call(comfy, {"op": "service_model_folders", "directory": str(install),
                        "shared_models": [str(shared_root), str(waiting), str(tmp_path / "gone")]}, data_dir)
    assert out["running"] is True
    first, second, third = out["folders"]
    total = sum(len(names) for folder, names in comfy.state.model_folders.items() if folder not in ("configs", "custom_nodes"))
    assert (first["ok"], first["loaded"], first["models"]) == (True, True, total - 1)
    assert first["layout"] == {"zh": "ComfyUI 的模型文件夹", "en": "ComfyUI models folder"}
    assert (second["ok"], second["loaded"], second["models"]) == (True, False, 0), "要重启才加载"
    assert third["ok"] is False and "没有这个文件夹" in third["problem"]["zh"]


def test_没在跑_只认样子(data_dir, tmp_path) -> None:
    from app.domain.plugins import runtime

    other = _dirs(tmp_path / "Other" / "models", "checkpoints")
    out = runtime.execute_tool(base.PLUGIN, base.ENTRY, "comfyui_generation",
                               {"op": "service_model_folders", "directory": "", "shared_models": [str(other)]},
                               {"SERVER_URL": "http://127.0.0.1:9"}, data_dir=data_dir, timeout=60).output
    assert out["running"] is False
    assert out["folders"][0]["ok"] is True and out["folders"][0]["loaded"] is None and out["folders"][0]["models"] is None
