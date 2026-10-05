"""ComfyUI 插件「按文件名找下载地址」(工作台「缺失项」里工作流没写地址的模型,见 tools/model_search)。

对着**录下来的真回答**(fixtures/comfyui/model_search.json:2026-10 从 huggingface.co / modelscope.cn / civitai.com
录的,剪到解析要读的那几项,按插件问的地址存)。钉住的是:

- 同名的在前,近似的(别的精度、别的扩展名、名字里含着)永远不标 `exact`;给了目录,放在那个目录下的靠前;
- 每个候选的链接都是 `resolve` 认得、并且**正好解析到这个文件**的 —— 用 sources 自己的解析过一遍(Civitai 用录下来的
  版本接口);Civitai 一个版本里钉不住的文件(同类里不排第一、又不是主文件)不列;
- 一个站超时、限流、拒绝只进 `failed`,别的站照常交回;
- 搜过的记在插件持久目录里一会儿(插件每次调用是新进程),失败的不记。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib import parse

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
RECORDED: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "comfyui" / "model_search.json").read_text(encoding="utf-8"))["answers"]
DREAMSHAPER_5 = 43888


@pytest.fixture
def modules(monkeypatch):
    names = {path.stem for path in TOOLS.glob("*.py")}
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    monkeypatch.delenv("MOSAEL_PLUGIN_DATA_DIR", raising=False)
    try:
        import model_search
        import sources

        yield model_search, sources
    finally:
        sys.path.remove(str(TOOLS))
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


class _Sites:
    """替 sources 的出网口:按地址回录下来的真回答,没录的回 404。`broken` 里的域名(或完整地址)按给定的方式坏掉:
    一个状态码、`unreachable`(连不上,sources.open_url 报的那种)、`timeout`(读到一半超时)。记下每次请求。"""

    def __init__(self, broken: dict[str, int | str] | None = None) -> None:
        self.broken = broken or {}
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30):
        from lines import ComfyError
        from sources import Answer

        self.calls.append((method, url, dict(headers or {})))
        trouble = self.broken.get(url, self.broken.get(parse.urlsplit(url).hostname or ""))
        if trouble == "unreachable":
            raise ComfyError(f"{parse.urlsplit(url).hostname}: [Errno 61] Connection refused")
        if trouble == "timeout":
            raise TimeoutError("The read operation timed out")
        if isinstance(trouble, int):
            return Answer(trouble, {}, b"", url)
        if url not in RECORDED:
            return Answer(404, {}, b'{"error": "not recorded"}', url)
        return Answer(200, {"content-type": "application/json"}, json.dumps(RECORDED[url]).encode(), url)

    def asked(self, host: str) -> list[str]:
        return [url for _, url, _ in self.calls if parse.urlsplit(url).hostname == host]


def _search(model_search, filename: str, folder: str = "", locale: str = "zh") -> dict[str, Any]:
    return model_search.search({"filename": filename, "folder": folder}, None, locale)


# --- 排序 -------------------------------------------------------------------------

def test_同名的在前_近似的永远不标同名(modules, monkeypatch) -> None:
    model_search, sources = modules
    sites = _Sites()
    monkeypatch.setattr(sources, "fetch", sites)

    out = _search(model_search, "flux1-dev-fp8.safetensors")
    found = out["candidates"]
    assert out["filename"] == "flux1-dev-fp8.safetensors" and out["failed"] == []
    flags = [one["exact"] for one in found]
    assert flags[0] is True and flags == sorted(flags, reverse=True), f"同名的必须全在近似的前面:{flags}"
    assert all(one["filename"].lower() == "flux1-dev-fp8.safetensors" for one in found if one["exact"])
    assert all(one["filename"].lower() != "flux1-dev-fp8.safetensors" for one in found if not one["exact"]), \
        "近似的永远不标同名"
    first = found[0]
    assert (first["source"], first["repo"], first["size"]) == ("huggingface", "Comfy-Org/flux1-dev", 17246524772)
    assert first["url"] == "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors"
    assert first["page"] == "https://huggingface.co/Comfy-Org/flux1-dev/blob/main/flux1-dev-fp8.safetensors"
    assert first["base_model"] == "", "Comfy-Org 的仓库标了好几个底模,说不准是哪个文件的,不写"
    assert ("modelscope", "livehouse/flux1-dev-fp8", True) in [(one["source"], one["repo"], one["exact"]) for one in found]
    assert ("flux1-dev.safetensors", False) in [(one["filename"], one["exact"]) for one in found], "别的精度也列出来"
    assert not any("search=" in url for url in sites.asked("huggingface.co")), \
        "Comfy-Org 的仓库里已经有同名的:HuggingFace 不再按词搜"


def test_给了目录_放在那个目录下的靠前_不给就按站(modules, monkeypatch) -> None:
    model_search, sources = modules
    monkeypatch.setattr(sources, "fetch", _Sites())

    plain = [(one["source"], one["exact"]) for one in _search(model_search, "dreamshaper_8.safetensors")["candidates"]]
    assert plain[0] == ("huggingface", True), "同名的先按站:HuggingFace、ModelScope、Civitai"
    in_folder = _search(model_search, "dreamshaper_8.safetensors", "checkpoints")["candidates"]
    assert (in_folder[0]["source"], in_folder[0]["exact"]) == ("civitai", True), \
        "Civitai 的模型类型是 Checkpoint,放进 checkpoints;HuggingFace 上的文件在仓库根上,看不出目录"
    assert in_folder[0]["url"] == "https://civitai.com/api/download/models/128713"
    assert (in_folder[0]["title"], in_folder[0]["base_model"], in_folder[0]["size"]) == (
        "DreamShaper · 8", "SD 1.5", 2132625894)
    assert in_folder[0]["page"] == "https://civitai.com/models/4384?modelVersionId=128713"


def test_近似的里_同一个站按大小(modules, monkeypatch) -> None:
    model_search, sources = modules
    monkeypatch.setattr(sources, "fetch", _Sites())

    found = _search(model_search, "dreamshaper_8.safetensors")["candidates"]
    assert len(found) <= model_search.MAX_CANDIDATES
    assert max(sum(1 for one in found if one["source"] == site) for site in model_search.SITES) <= model_search.PER_SITE
    for site in model_search.SITES:
        sizes = [one["size"] for one in found if one["source"] == site and not one["exact"]]
        known = [size for size in sizes if size is not None]
        assert known == sorted(known) and sizes == known + [None] * (len(sizes) - len(known)), (site, sizes)


def test_要找的词_完整文件名_stem_去掉精度后缀(modules) -> None:
    model_search, _ = modules
    target = model_search._Target("wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors")
    assert target.queries == ["wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "wan2.2_i2v_high_noise_14B_fp8_scaled",
                              "wan2.2_i2v_high_noise_14B"]
    assert model_search._Target("flux1-dev-Q4_K_M.gguf").queries[-1] == "flux1-dev"
    assert model_search._Target("4x-UltraSharp.pth").queries == ["4x-UltraSharp.pth", "4x-UltraSharp"]
    assert model_search._Target("realisticVisionV60B1_v51VAE.safetensors").words == "realistic Vision V60B1", \
        "Civitai 按模型名里的词搜:第一段按驼峰拆开"
    tier = model_search._Target("Flux1-Dev-fp8.safetensors").tier
    assert tier("split_files/x/flux1-dev-FP8.safetensors") == 0, "同名不分大小写,只比最后一段"
    assert tier("flux1-dev-fp8.ckpt") == 1 and tier("flux1-dev.safetensors") == 1 and tier("flux1-dev-bf16.gguf") == 1
    assert tier("flux1-dev-kontext_fp8_scaled.safetensors") == 2
    assert tier("flux1-dev-fp8.md") is None and tier("README.md") is None and tier("flux1-schnell.safetensors") is None


def test_HuggingFace的底模_只有仓库里只有一个模型文件时才写(modules) -> None:
    model_search, _ = modules
    tags = ["lora", "base_model:black-forest-labs/FLUX.1-dev", "base_model:adapter:black-forest-labs/FLUX.1-dev"]
    assert model_search._hf_base(tags, ["README.md", "style.safetensors"]) == "black-forest-labs/FLUX.1-dev"
    assert model_search._hf_base(tags, ["a.safetensors", "b-fp8.safetensors"]) == "", \
        "一个仓库装好几个模型:标签说不准是哪个文件的"
    assert model_search._hf_base(["base_model:a/b", "base_model:c/d"], ["x.safetensors"]) == ""


def test_文件名带目录前缀_只搜最后一段(modules, monkeypatch) -> None:
    model_search, sources = modules
    sites = _Sites()
    monkeypatch.setattr(sources, "fetch", sites)

    out = _search(model_search, "SD1.5\\dreamshaper_8.safetensors")
    assert out["filename"] == "dreamshaper_8.safetensors"
    assert out["candidates"][0]["exact"] is True
    assert not any("SD1.5" in parse.unquote(url) for _, url, _ in sites.calls)


def test_文件名是空的_说清楚(modules) -> None:
    model_search, _ = modules
    from lines import ComfyError

    with pytest.raises(ComfyError, match="文件名是空的"):
        _search(model_search, "  ")


def test_经插件入口分派(modules, monkeypatch) -> None:
    _, sources = modules
    monkeypatch.setattr(sources, "fetch", _Sites())
    import main

    out = main._generation({"op": "search_sources", "filename": "sd_xl_base_1.0.safetensors"}, None, "zh")
    assert [(one["source"], one["repo"]) for one in out["candidates"] if one["exact"]] == [
        ("huggingface", "sd-research/stable-diffusion-xl-base-1.0"), ("modelscope", "muse/sd_xl_base_1.0"),
        ("modelscope", "ckpt/sd_xl_base_1.0")]


# --- 候选的链接 resolve 认得,正好是这个文件 ----------------------------------------

def _civitai_version_files(model_search) -> list[dict[str, Any]]:
    """搜索接口里 DreamShaper 5 那个版本的文件(四个,都是 Model 类型:fp16 的 .ckpt、fp16 的 .safetensors(主文件)、
    fp32 的 .ckpt、fp32 的 .safetensors)。"""
    for url, answer in RECORDED.items():
        if url.startswith("https://civitai.com/api/v1/models?"):
            for model in model_search._civitai_models(answer):
                for version in model["versions"]:
                    if version["id"] == DREAMSHAPER_5:
                        return version["files"]
    raise AssertionError("录下来的回答里没有 DreamShaper 5")


def test_Civitai_钉得住的链接_resolve正好解析到那个文件_钉不住的不列(modules, monkeypatch) -> None:
    model_search, sources = modules
    monkeypatch.setattr(sources, "fetch", _Sites())
    files = _civitai_version_files(model_search)
    #: 版本接口的文件和搜索接口的同一个顺序(名字不一样:版本接口在名字后面带文件号),下载链接带 fileId
    version = RECORDED[f"https://civitai.com/api/v1/model-versions/{DREAMSHAPER_5}"]["files"]
    assert [one["type"] for one in version] == [one["type"] for one in files]

    pinned = {index: model_search._civitai_pinned(DREAMSHAPER_5, files, index) for index in range(len(files))}
    assert pinned == {0: f"https://civitai.com/api/download/models/{DREAMSHAPER_5}?type=Model",
                      1: f"https://civitai.com/api/download/models/{DREAMSHAPER_5}", 2: "", 3: ""}
    for index, url in pinned.items():
        if url:
            link = sources.link_for(url, "zh", set())
            assert link.url == version[index]["downloadUrl"], f"{files[index]['name']} 的链接 resolve 解析成了别的文件"
            assert link.size == files[index]["size"]
    # 钉不住的那两个:拿它们自己的下载链接去 resolve,解析出来的是同类里排第一的那个 —— 所以不列
    for index in (2, 3):
        link = sources.link_for(f"https://civitai.com/api/download/models/{DREAMSHAPER_5}?type=Model", "zh", set())
        assert link.url != version[index]["downloadUrl"]

    out = _search(model_search, "dreamshaper_5BakedVae_full_fp32.safetensors")
    names = [(one["filename"], one["exact"], one["url"]) for one in out["candidates"]]
    assert names == [
        ("dreamshaper_5BakedVae_full_fp16.safetensors", False, f"https://civitai.com/api/download/models/{DREAMSHAPER_5}"),
        ("dreamshaper_5BakedVae_full_fp16.ckpt", False, f"https://civitai.com/api/download/models/{DREAMSHAPER_5}?type=Model"),
    ], "同名的那份(fp32)钉不住,不列;列出来的近似候选点了正好是它自己"


def test_HuggingFace的候选链接_resolve认得_不用联网就换得出直链(modules, monkeypatch) -> None:
    model_search, sources = modules
    monkeypatch.setattr(sources, "fetch", _Sites())
    found = _search(model_search, "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "diffusion_models")["candidates"]
    first = found[0]
    path = "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
    assert (first["source"], first["exact"], first["size"]) == ("huggingface", True, 14294742832)
    assert first["url"] == f"https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/{path}"
    assert sources._HF_FILE.match(parse.urlsplit(first["url"]).path)
    assert sources.direct_url(first["url"], "zh", set()) == first["url"]

    def head(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30):
        assert (method, url) == ("HEAD", first["url"]), "resolve 只问一下文件头,不下载"
        return sources.Answer(302, {"x-linked-size": "14294742832", "location": "https://cdn/x"}, b"", url)

    monkeypatch.setattr(sources, "fetch", head)
    link = sources.link_for(first["url"], "zh", {"diffusion_models", "vae"})
    assert (link.url, link.filename, link.size, link.folder) == (
        first["url"], first["filename"], 14294742832, "diffusion_models")


def test_ModelScope的候选链接_resolve认得_解析到同一个文件(modules, monkeypatch) -> None:
    model_search, sources = modules
    monkeypatch.setattr(sources, "fetch", _Sites())
    found = [one for one in _search(model_search, "sd_xl_base_1.0.safetensors")["candidates"] if one["source"] == "modelscope"]
    first = found[0]
    assert first["url"] == "https://modelscope.cn/models/muse/sd_xl_base_1.0/resolve/master/sd_xl_base_1.0.safetensors"
    assert first["page"] == "https://modelscope.cn/models/muse/sd_xl_base_1.0/file/view/master/sd_xl_base_1.0.safetensors"
    target = sources._ms_link(first["url"], "zh")
    assert (target.site, target.repo, target.revision, target.path) == (
        "modelscope.cn", "muse/sd_xl_base_1.0", "master", "sd_xl_base_1.0.safetensors")

    listing = RECORDED[model_search._ms_files_url("muse/sd_xl_base_1.0")]["Data"]["Files"]

    def site(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30):
        parts = parse.urlsplit(url)
        query = dict(parse.parse_qsl(parts.query))
        if parts.path == "/api/v1/models/muse/sd_xl_base_1.0":
            body = {"Code": 200, "Success": True, "Data": {"Name": "sd_xl_base_1.0", "Revision": "master"}}
        elif parts.path == "/api/v1/models/muse/sd_xl_base_1.0/repo/files" and query.get("Revision") == "master":
            root = query.get("Root", "")
            body = {"Code": 200, "Success": True, "Data": {"Files": [
                one for one in listing if one["Path"].rpartition("/")[0] == root]}}
        else:
            return sources.Answer(404, {}, b"{}", url)
        return sources.Answer(200, {"content-type": "application/json"}, json.dumps(body).encode(), url)

    monkeypatch.setattr(sources, "fetch", site)
    link = sources.link_for(first["url"], "zh", set())
    assert (link.url, link.filename, link.size) == (first["url"], first["filename"], first["size"])


# --- 一个站出了问题 ------------------------------------------------------------------

@pytest.mark.parametrize(("trouble", "said"), [
    (429, "请求太频繁"), (403, "拒绝了这次搜索"), (500, "HTTP 500"), ("unreachable", "连不上或超时"), ("timeout", "连不上或超时"),
])
def test_一个站出了问题_只进failed_别的站照常(modules, monkeypatch, trouble, said) -> None:
    model_search, sources = modules
    sites = _Sites({"civitai.com": trouble})
    monkeypatch.setattr(sources, "fetch", sites)

    out = _search(model_search, "dreamshaper_8.safetensors")
    assert [one["source"] for one in out["failed"]] == ["civitai"]
    message = out["failed"][0]["message"]
    assert "Civitai" in message and said in message
    assert "Errno" not in message and "civitai.com" not in message, "给人看的一句,不是原始报错"
    assert {one["source"] for one in out["candidates"] if one["exact"]} == {"huggingface", "modelscope"}
    assert len(sites.asked("civitai.com")) == 1, "搜索请求出了错就不再问这个站"


def test_出问题的那句_按读的人的语言(modules, monkeypatch) -> None:
    model_search, sources = modules
    monkeypatch.setattr(sources, "fetch", _Sites({"modelscope.cn": 429}))
    out = _search(model_search, "dreamshaper_8.safetensors", locale="en")
    assert out["failed"] == [{"source": "modelscope", "message": "ModelScope is rate-limiting searches; try again later"}]


def test_Comfy_Org的清单拉不到_HuggingFace照样按词搜(modules, monkeypatch) -> None:
    model_search, sources = modules
    monkeypatch.setattr(sources, "fetch", _Sites({model_search.HF_CATALOG: 502}))
    out = _search(model_search, "sd_xl_base_1.0.safetensors")
    assert out["failed"] == []
    assert out["candidates"][0]["repo"] == "sd-research/stable-diffusion-xl-base-1.0"


def test_文件大小问不到_候选照样交_不算这个站失败(modules, monkeypatch) -> None:
    model_search, sources = modules
    blobs = "https://huggingface.co/api/models/Comfy-Org/flux1-dev?blobs=true&expand%5B%5D=siblings"
    monkeypatch.setattr(sources, "fetch", _Sites({blobs: 500}))
    out = _search(model_search, "flux1-dev-fp8.safetensors")
    assert out["failed"] == []
    assert (out["candidates"][0]["repo"], out["candidates"][0]["size"]) == ("Comfy-Org/flux1-dev", None)


def test_不带令牌(modules, monkeypatch) -> None:
    model_search, sources = modules
    sites = _Sites()
    monkeypatch.setattr(sources, "fetch", sites)
    for key in ("HUGGINGFACE_TOKEN", "CIVITAI_TOKEN", "MODELSCOPE_TOKEN"):
        monkeypatch.setenv(key, "secret")
    _search(model_search, "dreamshaper_8.safetensors")
    assert sites.calls and all("Authorization" not in headers and "Cookie" not in headers for _, _, headers in sites.calls), \
        "公开的搜索接口不用登录:令牌能不发就不发"


# --- 记一会儿 -----------------------------------------------------------------------

def test_搜过的记在插件持久目录里_过期了重新问_失败的不记(modules, monkeypatch, tmp_path) -> None:
    model_search, sources = modules
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path))
    first = _Sites({"civitai.com": 429})
    monkeypatch.setattr(sources, "fetch", first)
    before = _search(model_search, "dreamshaper_8.safetensors")
    assert first.calls and (tmp_path / model_search.CACHE_FILE).is_file()

    again = _Sites()
    monkeypatch.setattr(sources, "fetch", again)
    after = _search(model_search, "dreamshaper_8.safetensors")
    assert [url for _, url, _ in again.calls if "civitai.com" not in url] == [], "记着的不再去问"
    assert again.asked("civitai.com"), "上次失败的没记,这次重新问"
    assert [one for one in after["candidates"] if one["source"] != "civitai"] == \
        [one for one in before["candidates"] if one["source"] != "civitai"]

    saved = json.loads((tmp_path / model_search.CACHE_FILE).read_text(encoding="utf-8"))
    for entry in saved["entries"].values():
        entry["until"] = 0
    (tmp_path / model_search.CACHE_FILE).write_text(json.dumps(saved), encoding="utf-8")
    expired = _Sites()
    monkeypatch.setattr(sources, "fetch", expired)
    _search(model_search, "dreamshaper_8.safetensors")
    assert expired.asked("huggingface.co") and expired.asked("modelscope.cn"), "过期了重新问"


def test_没有持久目录就不记(modules, monkeypatch) -> None:
    model_search, sources = modules
    sites = _Sites()
    monkeypatch.setattr(sources, "fetch", sites)
    _search(model_search, "sd_xl_base_1.0.safetensors")
    asked = len(sites.calls)
    _search(model_search, "sd_xl_base_1.0.safetensors")
    assert len(sites.calls) == 2 * asked


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
