"""ComfyUI 插件的「模型信息」(ADR 0038 §9):NSFW 的依据、来源。对着一台假的 ComfyUI(tests/fake_comfyui)。

宿主那一侧(合成判断、手动标记、预览缓存)钉在 test_plugin_model_library.py;这里钉插件自己:

- **元数据推断**:训练标签里成人标签占到训练图的一成才算(偶然一两张不算),文件名和标题里的词(驼峰拆开)也算;
  什么都没有的模型**不交**元数据这一条(它说不出「安全」);
- **经 Mosael 下载时记下来源**:HuggingFace / Civitai / ModelScope 的那一页,Civitai 的连着版本信息(NSFW 标记);
  贴的是别的直链只记站点,不记页;文件换了(大小对不上)记录就不算数;
- 列出时把 Civitai 的标记交成一条依据;
- **在 Civitai 上找**:装了 ComfyUI-Custom-Scripts 时让那台机器算 SHA256、按哈希对版本(精确);没有算哈希的路时按
  「Civitai 记的原始文件名 + 大小」找,恰好一个版本才认(标 `filename`,存回前要确认),几个都像就不认;找到的记进来源,
  第二次直接交记录;
- **出处**:下载时记的页、Civitai 对上的版本页;文件元数据里只认明说来源的键、指着一个模型页的,作者主页、文章不算;
- **底模**:权重只看得出 SDXL / Wan 时,Civitai 登记的底模细分到那一支(凭的写 `civitai`);
- **示例图**交给宿主当预览图挑:512 宽的那一份、分级、算不算 NSFW;
- **存为预览图**走 pysssss 自己那条路:传进 temp,再 `/pysssss/save`;没有那条路说缺什么。

Civitai 的回答形状照 2026-10-06 真站点的接口(tests/fixtures/civitai/,模型名、文件名换成了中性的)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests import test_comfyui_plugin_model_library as base
from tests.test_comfyui_plugin_model_library import _Web, _call, _download, _same_machine

#: 夹具借模型库那一份(假 ComfyUI、插件的持久目录、出网的假站点、按需载入的插件模块)
comfy, data_dir, files, modules, _no_proxy = base.comfy, base.data_dir, base.files, base.modules, base._no_proxy

#: 真站点回的一个版本(删掉了用不上的字段,名字换成中性的)。
CIVITAI_VERSION = {
    "id": 2107735, "modelId": 1862320, "name": "v1.0", "nsfwLevel": 7, "baseModel": "Wan Video 2.2 T2V-A14B",
    "trainedWords": ["cartoon style"],
    "model": {"name": "Cartoon Style", "type": "LORA", "nsfw": False, "poi": False},
    "files": [{"id": 1, "sizeKB": 299655.71875, "name": "cartoon_low.safetensors", "type": "Model", "primary": True,
               "hashes": {"AutoV2": "72663446FD", "SHA256": "72663446FD0AF94B2769435243EE1867842198E0AEEB0D526B638351B05874C6"},
               "downloadUrl": "https://civitai.com/api/download/models/2107735"}],
    "images": [
        {"url": "https://image.civitai.com/key/uuid-a/original=true/93890742.mp4", "nsfwLevel": 1, "width": 1920,
         "height": 1440, "type": "video"},
        {"url": "https://image.civitai.com/key/uuid-b/original=true/93903557.mp4", "nsfwLevel": 4, "width": 1920,
         "height": 1440, "type": "video"},
        {"url": "https://elsewhere.example/x.jpeg", "nsfwLevel": 1, "width": 512, "height": 512, "type": "image"},
        {"url": "https://image.civitai.com/key/uuid-c/original=true/1.jpeg", "nsfwLevel": 32, "type": "image"},
    ],
}


def _seed_provenance(server, data_dir: Path, files: dict) -> None:
    """插件持久目录里先放好一份来源记录(经 Mosael 下载时会写的那种)。"""
    digest = hashlib.sha1(server.url.encode()).hexdigest()[:12]
    (data_dir / f"provenance-{digest}.json").write_text(json.dumps({"version": 1, "files": files}), encoding="utf-8")


def _by_key(out: dict) -> dict:
    return {(one["folder"], one["name"]): one for one in out["models"]}


# --- 元数据推断 -----------------------------------------------------------------

def test_训练标签里成人标签占到一成才算_名字里的词也算(comfy, data_dir) -> None:
    state = comfy.state
    state.model_folders["loras"] += ["explicit_style.safetensors", "mostly_safe.safetensors", "BlowjobComicPart2.safetensors",
                                     "NippleSizeSlider.safetensors", "Analog_Film.safetensors"]
    state.model_metadata["loras/explicit_style.safetensors"] = {"ss_tag_frequency": json.dumps(
        {"10_x": {"style trigger": 40, "1girl": 38, "nude": 30, "Nipples": 12, "pussy": 3, "smile": 10}})}
    # 40 张里只有 2 张带 nude:不到一成,不算
    state.model_metadata["loras/mostly_safe.safetensors"] = {"ss_tag_frequency": json.dumps(
        {"10_x": {"style trigger": 40, "1girl": 38, "nude": 2, "smile": 10}})}
    by_key = _by_key(_call(comfy, {"op": "library"}, data_dir))

    explicit = by_key[("loras", "explicit_style.safetensors")]["nsfw_signals"]
    assert explicit == [{"source": "metadata", "nsfw": True, "tags": ["nude", "nipples"]}], \
        "按比重排;pussy 只占 7.5% 不到一成,不算;大小写、下划线统一"
    assert "nsfw_signals" not in by_key[("loras", "mostly_safe.safetensors")], "偶然一两张不算,也不说「安全」"
    assert by_key[("loras", "BlowjobComicPart2.safetensors")]["nsfw_signals"] == \
        [{"source": "metadata", "nsfw": True, "words": ["blowjob"]}], "驼峰拆开认文件名"
    assert by_key[("loras", "NippleSizeSlider.safetensors")]["nsfw_signals"][0]["words"] == ["nipple"]
    assert "nsfw_signals" not in by_key[("loras", "Analog_Film.safetensors")], "整词比:Analog 不是 anal"
    assert "nsfw_signals" not in by_key[("loras", "detail.safetensors")], "1girl、solo 不是成人标签"


def test_标题里的词也算(comfy, data_dir) -> None:
    comfy.state.model_folders["loras"].append("ok_name.safetensors")
    comfy.state.model_metadata["loras/ok_name.safetensors"] = {"modelspec.title": "Lewd Poses Pack"}
    signal = _by_key(_call(comfy, {"op": "library"}, data_dir))[("loras", "ok_name.safetensors")]["nsfw_signals"]
    assert signal == [{"source": "metadata", "nsfw": True, "words": ["lewd"]}]


# --- 来源记录 -------------------------------------------------------------------

def test_来源记录里的Civitai标记交成一条依据_文件换了就不算数(comfy, data_dir) -> None:
    from_civitai = {"model_id": 1862320, "version_id": 2107735, "page": "https://civitai.com/models/1862320?modelVersionId=2107735",
                    "nsfw": True, "base_model": "Wan Video 2.2 T2V-A14B", "images": []}
    _seed_provenance(comfy, data_dir, {
        "loras/detail.safetensors": {"how": "download", "site": "civitai", "page": from_civitai["page"],
                                     "civitai": from_civitai, "size": 228456516},
        # 大小对不上:同名的文件换过了
        "checkpoints/sd_xl_base.safetensors": {"how": "download", "site": "civitai", "civitai": from_civitai, "size": 1},
    })
    by_key = _by_key(_call(comfy, {"op": "library"}, data_dir))
    assert by_key[("loras", "detail.safetensors")]["nsfw_signals"] == [{"source": "civitai", "nsfw": True}]
    assert "nsfw_signals" not in by_key[("checkpoints", "sd_xl_base.safetensors")], "文件换了:那条记录说的不是它"


def test_下载时记下来源_贴的是直链只记站点(comfy, data_dir, files, tmp_path) -> None:
    _same_machine(comfy, tmp_path / "models")
    site = files({"/tiny.safetensors": b"x" * 2000})
    out, _ = _download(comfy, {"url": f"{site.url}/tiny.safetensors", "folder": "vae", "filename": "tiny.safetensors"},
                       data_dir, tmp_path)
    assert out["page"] == "", "下载地址不是介绍页"
    record = json.loads(next(data_dir.glob("provenance-*.json")).read_text(encoding="utf-8"))
    assert record["version"] == 1
    entry = record["files"]["vae/tiny.safetensors"]
    assert (entry["how"], entry["site"], entry["size"]) == ("download", "direct", 2000)
    assert "page" not in entry


def test_来源页_HuggingFace_ModelScope不联网_Civitai问一次版本(modules, monkeypatch) -> None:
    _library, sources = modules
    web = _Web({("GET", "https://civitai.com/api/v1/model-versions/2107735"): (200, {}, json.dumps(CIVITAI_VERSION).encode())})
    monkeypatch.setattr(sources, "fetch", web)
    assert sources.provenance_of("https://huggingface.co/Comfy-Org/z/resolve/main/split_files/vae/ae.safetensors", "zh") == \
        {"site": "huggingface", "page": "https://huggingface.co/Comfy-Org/z/blob/main/split_files/vae/ae.safetensors"}
    assert sources.provenance_of("https://www.modelscope.cn/models/A/B/resolve/master/sub/x.safetensors", "zh") == \
        {"site": "modelscope", "page": "https://modelscope.cn/models/A/B/file/view/master/sub/x.safetensors"}
    assert not web.calls, "HuggingFace、ModelScope 的页从链接本身就看得出"
    found = sources.provenance_of("https://civitai.red/api/download/models/2107735", "zh")
    assert found["site"] == "civitai" and found["page"] == "https://civitai.com/models/1862320?modelVersionId=2107735"
    info = found["civitai"]
    assert (info["model_id"], info["version_id"], info["base_model"], info["nsfw"]) == \
        (1862320, 2107735, "Wan Video 2.2 T2V-A14B", False)
    assert [(one["kind"], one["level"]) for one in info["images"]] == [("video", 1), ("video", 4)], \
        "只收 Civitai 图床上的;站方屏蔽的(32)不收"
    assert info["files"][0]["sha256"] == "72663446fd0af94b2769435243ee1867842198e0aeeb0d526b638351b05874c6"
    assert [call[1] for call in web.calls] == ["https://civitai.com/api/v1/model-versions/2107735"]
    ua = web.calls[0][2].get("User-Agent")
    assert ua is None, "UA 由 sources.open_url 统一加(见 USER_AGENT),不在这里各写各的"
    assert sources.USER_AGENT.startswith("Mozilla/5.0"), "Civitai 对 Python 自己的 UA 回 403"


def test_问Civitai失败不挡住下载_只记站点(modules, monkeypatch) -> None:
    _library, sources = modules
    from lines import ComfyError

    def broken(*_args, **_kwargs):
        raise ComfyError("civitai.com: timed out")

    monkeypatch.setattr(sources, "fetch", broken)
    assert sources.provenance_of("https://civitai.com/api/download/models/5", "zh") == {"site": "civitai"}


# --- 在 Civitai 上找 -------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "civitai"
BY_HASH = json.loads((FIXTURES / "version_by_hash.json").read_text(encoding="utf-8"))
SEARCH = json.loads((FIXTURES / "search_by_name.json").read_text(encoding="utf-8"))


@pytest.fixture
def plugin_env(monkeypatch, data_dir):
    """在本进程里调插件的函数:持久目录指到这次的临时目录。"""
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(data_dir))
    return data_dir


def test_按哈希找_那台机器算SHA256_对上版本_记进来源_第二次直接交记录(modules, comfy, plugin_env, monkeypatch) -> None:
    _library, sources = modules
    import lookup
    from comfy_http import Comfy

    digest = BY_HASH["files"][0]["hashes"]["SHA256"].lower()
    comfy.state.model_hashes["checkpoints/AWPainting_IL.safetensors"] = digest
    web = _Web({("GET", f"https://civitai.com/api/v1/model-versions/by-hash/{digest.upper()}"):
                (200, {}, json.dumps(BY_HASH).encode())})
    monkeypatch.setattr(sources, "fetch", web)
    out = lookup.lookup({"folder": "checkpoints", "name": "AWPainting_IL.safetensors"}, Comfy(comfy.url), "zh")
    assert out["match"] == "sha256" and out["sha256"] == digest
    assert out["page"] == "https://civitai.com/models/795765?modelVersionId=889818"
    assert out["civitai"]["base_model"] == "Illustrious"
    assert comfy.state.hashed == ["checkpoints/AWPainting_IL.safetensors"]
    previews = out["remote_previews"]
    assert previews and all(one["kind"] == "image" and one["site"] == "civitai" for one in previews)
    assert previews[0]["url"].endswith("/width=512/31462610.jpeg"), "512 宽的那一份,不要原图"
    assert previews[0]["nsfw"] is False and previews[0]["level"] == 1

    again = lookup.lookup({"folder": "checkpoints", "name": "AWPainting_IL.safetensors"}, Comfy(comfy.url), "zh")
    assert again["match"] == "sha256"
    assert comfy.state.hashed == ["checkpoints/AWPainting_IL.safetensors"], "查过的不再让那台机器算一遍"
    assert len(web.calls) == 1
    lookup.lookup({"folder": "checkpoints", "name": "AWPainting_IL.safetensors", "refresh": True}, Comfy(comfy.url), "zh")
    assert len(comfy.state.hashed) == 2, "用户点了「在 Civitai 上找」:重查"


def test_Civitai上没有这个文件_也记一笔_不再让那台机器算哈希(modules, comfy, plugin_env, monkeypatch) -> None:
    _library, sources = modules
    import lookup
    from comfy_http import Comfy

    monkeypatch.setattr(sources, "fetch", _Web({}))  # by-hash 一律 404
    out = lookup.lookup({"folder": "checkpoints", "name": "sd_xl_base.safetensors"}, Comfy(comfy.url), "zh")
    assert out["match"] == "none" and "civitai" not in out and out["note"]
    lookup.lookup({"folder": "checkpoints", "name": "sd_xl_base.safetensors"}, Comfy(comfy.url), "zh")
    assert comfy.state.hashed == ["checkpoints/sd_xl_base.safetensors"]


def test_没有算哈希的路_按文件名和大小找_恰好一个才认_几个都像不认(modules, comfy, plugin_env, monkeypatch) -> None:
    _library, sources = modules
    import lookup
    from comfy_http import Comfy

    comfy.state.pysssss_scripts = ("betterCombos.js",)  # 没有 modelInfo.js:算不了哈希
    state = comfy.state
    state.model_folders["loras"] += ["example_style_low.safetensors", "diffusers_lora.safetensors", "other.safetensors"]
    state.model_sizes["loras/example_style_low.safetensors"] = round(299655.71875 * 1024)
    state.model_sizes["loras/diffusers_lora.safetensors"] = round(149854.140625 * 1024)
    state.model_sizes["loras/other.safetensors"] = 5
    # 同名、大小差得远(另一个目录里的一份):不认
    state.model_folders["checkpoints"] += ["example_style_low.safetensors"]
    state.model_sizes["checkpoints/example_style_low.safetensors"] = round(299655.71875 * 1024) + 4096
    twice = json.loads(json.dumps(SEARCH))
    other = json.loads(json.dumps(twice["items"][1]))
    other["id"], other["modelVersions"][0]["id"] = 99, 990001  # 同名同大小的另一个模型的另一个版本
    twice["items"].append(other)
    answers = {
        "example_style_low": SEARCH, "diffusers_lora": twice, "other": SEARCH,
    }
    web = _Web({("GET", f"https://civitai.com/api/v1/models?query={stem}&limit=20"): (200, {}, json.dumps(body).encode())
                for stem, body in answers.items()})
    monkeypatch.setattr(sources, "fetch", web)
    found = lookup.lookup({"folder": "loras", "name": "example_style_low.safetensors"}, Comfy(comfy.url), "zh")
    assert found["match"] == "filename" and found["civitai"]["version_id"] == 2107735
    assert found["note"], "按文件名对上的:存回之前要确认"
    assert not comfy.state.hashed
    ambiguous = lookup.lookup({"folder": "loras", "name": "diffusers_lora.safetensors"}, Comfy(comfy.url), "zh")
    assert ambiguous["match"] == "none" and "2" in ambiguous["note"], "两个版本都像:不猜"
    unknown = lookup.lookup({"folder": "loras", "name": "other.safetensors"}, Comfy(comfy.url), "zh")
    assert unknown["match"] == "none"
    wrong_size = lookup.lookup({"folder": "checkpoints", "name": "example_style_low.safetensors"}, Comfy(comfy.url), "zh")
    assert wrong_size["match"] == "none", "名字一样、大小差了 4 KB:不是同一个文件"


def test_列出时带出处_示例图_Civitai细分的底模_写回预览图的路(comfy, data_dir) -> None:
    info = {"model_id": 795765, "version_id": 889818, "page": "https://civitai.com/models/795765?modelVersionId=889818",
            "base_model": "Illustrious", "nsfw": False,
            "images": [{"url": "https://image.civitai.com/k/a/original=true/1.jpeg", "preview": "https://image.civitai.com/k/a/width=512/1.jpeg",
                        "kind": "image", "level": 8},
                       {"url": "https://image.civitai.com/k/b/original=true/2.jpeg", "preview": "https://image.civitai.com/k/b/width=512/2.jpeg",
                        "kind": "image", "level": 1},
                       {"url": "https://image.civitai.com/k/c/original=true/3.mp4", "preview": "https://image.civitai.com/k/c/transcode=true,width=512/3.mp4",
                        "kind": "video", "level": 1}]}
    comfy.state.model_metadata["checkpoints/AWPainting_IL.safetensors"] = {"modelspec.architecture": "stable-diffusion-xl-v1-base"}
    _seed_provenance(comfy, data_dir, {
        "checkpoints/AWPainting_IL.safetensors": {"how": "sha256", "site": "civitai", "page": info["page"], "civitai": info,
                                                  "checked": 1, "size": 1000},
        "vae/never.safetensors": {"how": "download", "site": "huggingface", "page": "https://huggingface.co/x/y/blob/main/a"},
    })
    comfy.state.model_metadata["loras/detail.safetensors"]["Civitai url"] = "https://civitai.com/user/someone"
    comfy.state.model_metadata["loras/sub\\anima_style.safetensors"]["modelspec.url"] = "https://huggingface.co/acme/anima-style"
    out = _call(comfy, {"op": "library"}, data_dir)
    by_key = _by_key(out)
    painting = by_key[("checkpoints", "AWPainting_IL.safetensors")]
    assert painting["source"] == {"page": info["page"], "site": "civitai", "how": "sha256"}
    assert (painting["family"], painting["family_source"]) == ("Illustrious", "civitai"), "元数据只说 SDXL:Civitai 细分"
    assert [(one["url"], one["level"], one["nsfw"]) for one in painting["remote_previews"]] == [
        ("https://image.civitai.com/k/a/width=512/1.jpeg", 8, True),
        ("https://image.civitai.com/k/b/width=512/2.jpeg", 1, False)], "视频在第四刀"
    assert "source" not in by_key[("loras", "detail.safetensors")], "作者主页不是这个模型的页:不写"
    assert by_key[("loras", "sub\\anima_style.safetensors")]["source"] == \
        {"page": "https://huggingface.co/acme/anima-style", "site": "huggingface", "how": "metadata"}
    assert out["preview_tools"] == {"lookup": "sha256", "save": True, "save_note": ""}


def test_Civitai的底模只细分不改架构() -> None:
    import sys

    sys.path.insert(0, str(base.TOOLS))
    try:
        from families import refined_by_civitai
    finally:
        sys.path.remove(str(base.TOOLS))
    assert refined_by_civitai("SDXL", "weights", "Illustrious") == ("Illustrious", "civitai")
    assert refined_by_civitai("Wan", "weights", "Wan Video 2.2 I2V-A14B") == ("Wan 2.2", "civitai")
    assert refined_by_civitai("Flux", "metadata", "Illustrious") == ("Flux", "metadata"), "架构对不上:信元数据 / 权重"
    assert refined_by_civitai("Pony", "metadata", "Illustrious") == ("Pony", "metadata"), "已经认出一支的不改"
    assert refined_by_civitai("", "", "SDXL 1.0") == ("SDXL", "civitai"), "认不出时用 Civitai 的"
    assert refined_by_civitai("SDXL", "filename", "Pony") == ("Pony", "civitai")
    assert refined_by_civitai("", "not_applicable", "SDXL 1.0") == ("", "not_applicable")
    assert refined_by_civitai("SDXL", "weights", "Other") == ("SDXL", "weights"), "「Other」等于没说"


# --- 存为预览图 ------------------------------------------------------------------------

def test_存为预览图_传进temp_再经pysssss拷到模型旁边(comfy, data_dir, tmp_path) -> None:
    image = tmp_path / "preview.png"
    image.write_bytes(b"\x89PNG fake")
    out = _call(comfy, {"op": "save_preview", "folder": "loras", "name": "detail.safetensors", "path": str(image)}, data_dir)
    assert (out["folder"], out["name"], out["saved"]) == ("loras", "detail.safetensors", "loras/detail.png")
    fields = comfy.state.upload_fields[-1]
    assert (fields["type"], fields["subfolder"]) == ("temp", "mosael-previews"), "先进 temp,不进 input"
    saved = comfy.posted("/pysssss/save/loras%2Fdetail.safetensors")  # 「目录/文件」是一整段,斜杠编码成 %2F
    assert saved and saved[0]["type"] == "temp" and saved[0]["filename"].endswith(".png")
    assert comfy.state.saved_previews["loras/detail.safetensors"] == (".png", b"\x89PNG fake")


def test_没有写回的路_说缺什么_不去试(comfy, data_dir, tmp_path) -> None:
    from app.domain.plugins.runtime import PluginRuntimeError

    comfy.state.pysssss_scripts = ("modelInfo.js",)
    image = tmp_path / "preview.png"
    image.write_bytes(b"x")
    with pytest.raises(PluginRuntimeError, match="ComfyUI-Custom-Scripts"):
        _call(comfy, {"op": "save_preview", "folder": "loras", "name": "detail.safetensors", "path": str(image)}, data_dir)
    assert not comfy.state.uploads, "没有那条路就不往 temp 里传"
    listed = _call(comfy, {"op": "library"}, data_dir)
    assert listed["preview_tools"]["save"] is False and "ComfyUI-Custom-Scripts" in listed["preview_tools"]["save_note"]


# --- 预览视频 --------------------------------------------------------------------------

def test_模型旁边的预览视频_按名字直接读_带方括号的图也是(comfy, data_dir) -> None:
    comfy.state.model_folders["loras"].append("Style [v2].safetensors")
    out = _call(comfy, {"op": "library"}, data_dir)
    assert out["sidecar_base"] == f"{comfy.url}/pysssss/view/"
    by_key = _by_key(out)
    assert by_key[("loras", "detail.safetensors")]["sidecars"] == ["loras%2Fdetail.mp4", "loras%2Fdetail.webm"]
    brackets = by_key[("loras", "Style [v2].safetensors")]["sidecars"]
    assert brackets[:2] == ["loras%2FStyle%20%5Bv2%5D.png", "loras%2FStyle%20%5Bv2%5D.jpg"], \
        "ComfyUI 的预览接口按通配符找,[ ] 让它找不到:那几张图按名字直接读,排在视频前面"
    assert brackets[-2:] == ["loras%2FStyle%20%5Bv2%5D.mp4", "loras%2FStyle%20%5Bv2%5D.webm"]


def test_没有pysssss就不列旁边的文件(comfy, data_dir) -> None:
    comfy.state.pysssss_scripts = ("modelInfo.js",)
    out = _call(comfy, {"op": "library"}, data_dir)
    assert "sidecar_base" not in out
    assert all("sidecars" not in one for one in out["models"])


def test_示例只有视频的_交512宽的转码视频_有图就只交图(modules) -> None:
    import civitai

    only_video = civitai.essentials(CIVITAI_VERSION)
    previews = civitai.remote_previews(only_video)
    assert [(one["kind"], one["level"], one["nsfw"]) for one in previews] == [("video", 1, False), ("video", 4, True)]
    assert previews[0]["url"] == "https://image.civitai.com/key/uuid-a/transcode=true,width=512/93890742.mp4"
    with_images = civitai.essentials(BY_HASH)
    assert {one["kind"] for one in civitai.remote_previews(with_images)} == {"image"}


def test_存回的是视频本身_写成模型名点mp4(comfy, data_dir, tmp_path) -> None:
    video = tmp_path / "preview.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake")
    out = _call(comfy, {"op": "save_preview", "folder": "loras", "name": "detail.safetensors", "path": str(video)}, data_dir)
    assert out["saved"] == "loras/detail.mp4", "维护者:不要用帧,直接用视频当预览"
    assert comfy.state.saved_previews["loras/detail.safetensors"][0] == ".mp4"
    assert len(comfy.state.uploads) == 1, "只写视频,不另截一帧"
