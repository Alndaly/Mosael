"""pip 镜像是**本机引擎**的设置,不是声音克隆的。

它历史上存在 tts_config 里(克隆先有了它),于是在设置页里只出现在克隆表单中 —— 而转写和
人声分离装依赖时读的是同一份。想给转写换镜像的人得去「声音克隆」里找。

搬出来之后最容易踩的坑是**丢值**:克隆表单不再发这个字段,而它若默认成 "",每保存一次克隆
设置,镜像就被悄悄重置回官方 PyPI —— 下一次装转写依赖在国内网络上直接超时,离原因很远。
"""

from __future__ import annotations

from tests.util import fresh_client


def _clone_body(**extra):
    return {"engine": "f5-tts", "python_path": "", "fish_repo_dir": "", "fish_model_dir": "", **extra}


def test_安装源有自己的一对接口() -> None:
    client = fresh_client()
    assert client.put("/api/settings/install-source", json={"pip_index": "tsinghua"}).status_code == 200
    assert client.get("/api/settings/install-source").json()["pip_index"] == "tsinghua"


def test_保存克隆设置不会把镜像冲掉() -> None:
    """克隆表单不再发 pip_index —— 这时它必须原样留着,而不是被默认值 "" 覆盖。"""
    client = fresh_client()
    client.put("/api/settings/install-source", json={"pip_index": "aliyun"})

    saved = client.put("/api/settings/tts", json=_clone_body())
    assert saved.status_code == 200, saved.text
    assert client.get("/api/settings/install-source").json()["pip_index"] == "aliyun"


def test_改安装源不碰克隆那几项() -> None:
    client = fresh_client()
    client.put("/api/settings/tts", json=_clone_body(engine="fish-speech", python_path="/tmp/py"))

    client.put("/api/settings/install-source", json={"pip_index": "tencent", "model_source": "modelscope"})
    tts = client.get("/api/settings/tts").json()
    assert tts["engine"] == "fish-speech" and tts["python_path"] == "/tmp/py"


def test_模型下载源也归安装源_保存克隆设置不会把它冲掉() -> None:
    """模型下载源(体检 UM-16):本机识别(NSFW)、Mosael 起的本机 ComfyUI 下模型读的也是它,此前却藏在「声音克隆」里、
    跟着克隆表单一起存 —— 想给 NSFW 换源的人想不到去那儿,改了克隆的源也不知道连带改了别的。"""
    from app.ai.runtime import config as runtime_config
    from app.api.schemas import TtsConfigUpdate

    assert "source" not in TtsConfigUpdate.model_fields
    client = fresh_client()
    install = client.get("/api/settings/install-source").json()
    assert install["model_source"] == "hf-mirror" and install["model_sources"] == ["hf-mirror", "hf", "modelscope"]

    assert client.put("/api/settings/install-source", json={"model_source": "hf"}).status_code == 200
    assert runtime_config.get().hf_endpoint == "https://huggingface.co", "NSFW、本机 ComfyUI 拿到的端点跟着换"
    assert client.put("/api/settings/tts", json={**_clone_body(), "source": "hf-mirror"}).status_code == 200
    assert client.get("/api/settings/install-source").json()["model_source"] == "hf", "克隆表单冲不掉它"
    assert client.put("/api/settings/install-source", json={"model_source": "nope"}).status_code == 422


def test_克隆接口压根不收_pip_index() -> None:
    """不是"收了也不写",是**没有这个字段** —— 否则迟早有人以为它还归这里管。"""
    from app.api.schemas import TtsConfigUpdate

    assert "pip_index" not in TtsConfigUpdate.model_fields


def test_转写和分离装依赖读的就是这一份() -> None:
    """判据不是"界面上挪了位置",而是三个引擎确实共用它 —— 否则挪出来就是个错的说法。"""
    import inspect

    from app.ai.runtime import asr_models, separation_models

    for module in (asr_models, separation_models):
        assert "pip_index_url" in inspect.getsource(module.ensure_engine_runtime if module is asr_models else module.ensure_runtime)
